#!/usr/bin/env python3
"""spec-lint 回归测试。

用法: python3 scripts/selftest.py

两部分：
1. 机械检查器语料回归：遍历 tests/cases/*.md，对照 tests/expectations/<同名>.json 断言。
2. 工具链回归：规则表同步/完整性、指纹鲁棒性、证据强制、评审裁定、轮次对比。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_mechanical as cm  # noqa: E402
import build_rules as br  # noqa: E402
import spec_lint as sl  # noqa: E402

CASES = ROOT / "tests" / "cases"
EXPECT = ROOT / "tests" / "expectations"
SPEC_LINT = ROOT / "scripts" / "spec_lint.py"


def findings_text(items):
    return " ".join(
        str(x.get("match", "")) + str(x.get("word", "")) + x.get("text", "")
        for x in items
    )


def run_cases() -> int:
    total_fail = 0
    for case in sorted(CASES.glob("*.md")):
        exp_path = EXPECT / (case.stem + ".json")
        if not exp_path.exists():
            print(f"SKIP  {case.name}（无 expectations 文件）")
            continue
        exp = json.loads(exp_path.read_text(encoding="utf-8"))
        result = cm.scan(case.read_text(encoding="utf-8"))
        fails = []

        for rule, needles in exp.get("must_find", {}).items():
            blob = findings_text(result.get(rule, []))
            for n in needles:
                if n not in blob:
                    fails.append(f"应命中未命中 {rule}: 「{n}」")

        for rule, needles in exp.get("must_not_find", {}).items():
            if rule.startswith("_"):
                continue
            items = result.get(rule, [])
            if needles == []:
                if items:
                    fails.append(f"{rule} 应零命中，实际 {len(items)} 条: "
                                 + "; ".join(x.get("text", "")[:40] for x in items[:3]))
            else:
                blob = findings_text(items)
                for n in needles:
                    if n in blob:
                        fails.append(f"{rule} 不应出现「{n}」")

        if fails:
            total_fail += 1
            print(f"FAIL  {case.name}")
            for f in fails:
                print(f"        - {f}")
        else:
            counts = {k: len(v) for k, v in result.items() if v}
            print(f"PASS  {case.name}  {counts}")
    return total_fail


def check_rules_sync():
    data = br.parse(br.RULES_MD.read_text(encoding="utf-8"))
    want = br.render(data)
    if not br.RULES_JSON.exists():
        return False, "rules.json 不存在"
    if br.RULES_JSON.read_text(encoding="utf-8") != want:
        return False, "rules.json 与 rules.md 不同步 —— 跑 scripts/build_rules.py"
    return True, f"rules.json 同步（{len(data['rules'])} 条规则，v{data['version']}）"


def check_rules_integrity():
    data = json.loads(br.RULES_JSON.read_text(encoding="utf-8"))
    buckets = set(cm.scan("").keys())
    problems = []
    ids = [r["id"] for r in data["rules"]]
    if len(set(ids)) != len(ids):
        problems.append("规则 ID 有重复")
    for r in data["rules"]:
        if not r.get("question"):
            problems.append(f"{r['id']} 缺 `- 请回答：`")
        if not r.get("genres"):
            problems.append(f"{r['id']} 缺 `- 体裁：`")
        for g in r.get("genres", []):
            if g not in data["genres"]:
                problems.append(f"{r['id']} 体裁 {g} 未定义")
        key = r.get("script_key")
        if key and key not in buckets:
            problems.append(f"{r['id']} 的 script_key={key} 在机械脚本里没有对应桶")
        if r["detector"] == "mechanical" and not key:
            problems.append(f"{r['id']} 标为 mechanical 但没有 script_key")
    if problems:
        return False, "规则表体检未通过：" + "；".join(problems)
    return True, f"规则表完整（{len(ids)} 条，无缺字段/无悬空 script_key）"


def check_fingerprint():
    base = {"rule_id": "B1", "evidence": "显著提升体验", "match": "显著"}
    a = sl.fingerprint(base)
    b = sl.fingerprint({"rule_id": "B1", "evidence": "显著提升体验 ", "match": " 显著"})
    c = sl.fingerprint({"rule_id": "B1", "evidence": "流畅体验", "match": "流畅"})
    if a != b:
        return False, "指纹对空白不鲁棒（同一证据不同空白应同指纹）"
    if a == c:
        return False, "不同证据生成了相同指纹"
    if not a.startswith("B1:"):
        return False, f"指纹前缀不是规则 ID：{a}"
    return True, f"指纹对空白鲁棒、对不同证据敏感（{a}）"


def _doc(tmp: Path) -> Path:
    p = tmp / "doc.md"
    p.write_text("- 显著提升新用户的上手效率，让首周体验更流畅；\n"
                 "- 显著提升新用户的上手效率，让首周体验更流畅；\n", encoding="utf-8")
    return p


def check_evidence_enforcement():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        doc = _doc(tmp)
        bad = tmp / "bad.json"
        bad.write_text(json.dumps({"findings": [
            {"rule_id": "A1", "evidence": "这句原文在文档里根本不存在"}]}, ensure_ascii=False),
            encoding="utf-8")
        r = subprocess.run([sys.executable, str(SPEC_LINT), "scan", str(doc),
                            "--genre", "prd", "--semantic", str(bad)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return False, "编造证据的语义 finding 竟然通过了"
        if "找不到" not in (r.stderr + r.stdout):
            return False, f"拒绝理由不明确：{r.stderr.strip()[:80]}"
        good = tmp / "good.json"
        good.write_text(json.dumps({"findings": [
            {"rule_id": "A1", "line": 999,
             "evidence": "- 显著提升新用户的上手效率，让首周体验更流畅；"}]}, ensure_ascii=False),
            encoding="utf-8")
        out = tmp / "out.json"
        r2 = subprocess.run([sys.executable, str(SPEC_LINT), "scan", str(doc),
                             "--genre", "prd", "--semantic", str(good), "--out", str(out)],
                            capture_output=True, text=True)
        if r2.returncode != 0:
            return False, f"合法语义 finding 被拒：{r2.stderr.strip()[:80]}"
        data = json.loads(out.read_text(encoding="utf-8"))
        a1 = [f for f in data["findings"] if f["rule_id"] == "A1"]
        if not a1 or a1[0]["line"] != 1:
            return False, f"给错行号时未按证据正确定位：{a1}"
        if not a1[0].get("question"):
            return False, "合并后没有补上「该问什么」"
    return True, "编造证据被拒；合法证据合并并自动定位行号、补问题"


def check_round():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        doc = _doc(tmp)
        prev = tmp / "prev.json"
        cur = tmp / "cur.json"
        subprocess.run([sys.executable, str(SPEC_LINT), "scan", str(doc),
                        "--genre", "prd", "--out", str(prev)], check=True,
                       capture_output=True)
        doc.write_text("- 将新用户首周留存率从 42% 提升到 55%；\n", encoding="utf-8")
        subprocess.run([sys.executable, str(SPEC_LINT), "scan", str(doc), "--genre", "prd",
                        "--round", "2", "--out", str(cur)], check=True, capture_output=True)
        r = subprocess.run([sys.executable, str(SPEC_LINT), "round", "--prev", str(prev),
                            "--current", str(cur), "--json"], capture_output=True, text=True)
        if r.returncode != 0:
            return False, f"round 执行失败：{r.stderr.strip()[:80]}"
        d = json.loads(r.stdout)
        if d["counts"]["new_open"] != 0 or not d["converged"]:
            return False, f"改用可度量表述后应无新问题并收敛，实际 {d['counts']}"
        if d["counts"]["resolved"] == 0:
            return False, "旧问题没有被判为已解决"

        # 只改措辞、违规标记仍在 → 应记为「改写后仍在」，不是「新出现」
        d2 = tmp / "doc2.md"; d2.write_text(
            "- 显著提升新用户留存与上手效率\n", encoding="utf-8")
        d3 = tmp / "doc3.md"; d3.write_text("- 显著提升新用户留存与上手效率\n", encoding="utf-8")
        subprocess.run([sys.executable, str(SPEC_LINT), "scan", str(d2), "--genre", "prd",
                        "--round", "1", "--out", str(tmp / "a.json")],
                       check=True, capture_output=True)
        d3.write_text("- 显著提升留存与上手效率（新用户）\n", encoding="utf-8")
        subprocess.run([sys.executable, str(SPEC_LINT), "scan", str(d3), "--genre", "prd",
                        "--round", "2", "--out", str(tmp / "b.json")],
                       check=True, capture_output=True)
        r3 = subprocess.run([sys.executable, str(SPEC_LINT), "round", "--prev", str(tmp / "a.json"),
                             "--current", str(tmp / "b.json"), "--json"],
                            capture_output=True, text=True)
        d4 = json.loads(r3.stdout)
        if d4["counts"]["reworded"] != 1 or d4["counts"]["new_open"] != 0:
            return False, f"改写同一违规词应记为「改写后仍在」，实际 {d4['counts']}"
    return True, "轮次对比正确识别 已解决/仍存在/改写后仍在/新出现"


def check_resolutions():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        doc = tmp / "doc.md"
        doc.write_text("- 显著提升新用户的上手效率\n", encoding="utf-8")
        sem = tmp / "sem.json"
        sem.write_text(json.dumps({"resolutions": [
            {"rule_id": "B1", "match": "显著", "status": "dismissed", "reason": "测试用驳回"},
            {"rule_id": "B1", "severity": "warning"},
        ]}, ensure_ascii=False), encoding="utf-8")
        out = tmp / "out.json"
        r = subprocess.run([sys.executable, str(SPEC_LINT), "scan", str(doc), "--genre", "prd",
                            "--semantic", str(sem), "--out", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return False, f"resolutions 执行失败：{r.stderr.strip()[:100]}"
        data = json.loads(out.read_text(encoding="utf-8"))
        b1 = [f for f in data["findings"] if f["rule_id"] == "B1"]
        if not b1:
            return False, "没找到 B1 候选"
        if data["summary"].get("dismissed") != 1:
            return False, f"驳回计数不对：{data['summary'].get('dismissed')}"
        if any(f["severity"] != "warning" for f in b1):
            return False, "降级没有作用于全部 B1 候选"
        if data["gate"] != "pass":
            return False, f"驳回 blocker 后门禁应通过，实际 {data['gate']}"
        bad = tmp / "bad.json"
        bad.write_text(json.dumps({"resolutions": [
            {"rule_id": "B1", "evidence": "文档里根本不存在的句子", "status": "dismissed"}]},
            ensure_ascii=False), encoding="utf-8")
        r2 = subprocess.run([sys.executable, str(SPEC_LINT), "scan", str(doc), "--genre", "prd",
                             "--semantic", str(bad)], capture_output=True, text=True)
        if r2.returncode == 0:
            return False, "裁定匹配不到候选时竟然静默通过"
    return True, "驳回/降级生效，空匹配会报错"


def check_round_ignores_dismissed():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        def mk(name, findings):
            (tmp / name).write_text(json.dumps(
                {"round": 1, "findings": findings,
                 "summary": {"open_blocker": 0, "open": 1}}, ensure_ascii=False),
                encoding="utf-8")

        dismissed = {"rule_id": "C3", "severity": "warning", "status": "dismissed",
                     "fingerprint": "C3:aaa", "evidence": "x", "match": "等", "line": 1}
        kept = {"rule_id": "B1", "severity": "warning", "status": "open",
                "fingerprint": "B1:bbb", "evidence": "y", "match": "丰富", "line": 2}
        mk("prev.json", [dismissed, kept])
        mk("cur.json", [kept])
        r = subprocess.run([sys.executable, str(SPEC_LINT), "round", "--prev", str(tmp / "prev.json"),
                            "--current", str(tmp / "cur.json"), "--json"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return False, f"执行失败：{r.stderr.strip()[:80]}"
        d = json.loads(r.stdout)
        if d["counts"]["resolved"] != 0:
            return False, f"已驳回项被误算成「已解决」：{d['counts']}"
        if d["counts"]["persisting"] != 1:
            return False, f"未解决项应仍存在，实际 {d['counts']}"
    return True, "已驳回项不参与轮次比对"


def check_round_duplicate_tokens():
    """同一违规词出现多处时，改写匹配必须一对一，不能复用同一条上轮候选。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        def mk(name, rows):
            findings = [{"rule_id": "B1", "severity": "warning", "status": "open",
                         "fingerprint": fp, "evidence": ev, "match": "丰富", "line": ln}
                        for fp, ev, ln in rows]
            (tmp / name).write_text(json.dumps(
                {"round": 1, "findings": findings,
                 "summary": {"open_blocker": 0, "open": len(findings)}}, ensure_ascii=False),
                encoding="utf-8")

        mk("prev.json", [("B1:aaa", "甲处丰富", 1), ("B1:bbb", "乙处丰富", 2)])
        mk("cur.json", [("B1:ccc", "丙处丰富", 5), ("B1:ddd", "丁处丰富", 6)])
        r = subprocess.run([sys.executable, str(SPEC_LINT), "round", "--prev", str(tmp / "prev.json"),
                            "--current", str(tmp / "cur.json"), "--json"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return False, f"执行失败：{r.stderr.strip()[:80]}"
        d = json.loads(r.stdout)
        if (d["counts"]["reworded"] != 2 or d["counts"]["new_open"] != 0
                or d["counts"]["resolved"] != 0):
            return False, f"多处同词时分类错乱：{d['counts']}"
    return True, "多处同词一对一配对，不重复消费上轮候选"


def run_toolchain() -> int:
    checks = [
        ("规则表同步", check_rules_sync),
        ("规则表完整性", check_rules_integrity),
        ("指纹稳定性", check_fingerprint),
        ("证据强制", check_evidence_enforcement),
        ("评审裁定", check_resolutions),
        ("轮次对比", check_round),
        ("驳回不参与比对", check_round_ignores_dismissed),
        ("多处同词配对", check_round_duplicate_tokens),
    ]
    fails = 0
    for name, fn in checks:
        try:
            ok, msg = fn()
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"异常：{type(e).__name__}: {e}"
        print(f"{'PASS' if ok else 'FAIL'}  [{name}] {msg}")
        if not ok:
            fails += 1
    return fails


def main() -> int:
    case_fails = run_cases()
    print()
    tool_fails = run_toolchain()
    total = case_fails + tool_fails
    print(f"\n{'全部通过 ✅' if total == 0 else f'{total} 项失败 ❌'}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
