#!/usr/bin/env python3
"""spec-lint 工具：把评审从"一段中文报告"变成"一张能接得上的表"。

为什么需要它：评审要能和上游形成闭环——查出来的问题，直接变成下一轮要问的问题；
上一轮问过的，这一轮能对上号。中文报告做不到这件事，带编号和指纹的表可以。

子命令:
  scan <文档>             查一遍，输出 findings 表
  questions              印"开工前必须回答"的提问清单（文档还没写时用）
  round --prev --current 对比两轮：已解决 / 仍存在 / 新出现（新出现=0 即收敛）
  stats                  从裁决账算规则体检，自动触发升降级候选

约定:
  - 规则表读 references/rules.json（由 scripts/build_rules.py 从 rules.md 生成）
  - 项目配置 .spec-lint.json（可选）：体裁、规则开关、严重度覆盖、带过期的豁免
  - finding.status: open（未解决）/ answered（已回答）/ waived（显式豁免）
  - 门禁通过 = 无 open 的 blocker；循环收敛 = 本轮"新出现"为 0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_mechanical as cm  # noqa: E402

RULES_JSON = ROOT / "references" / "rules.json"
DEFAULT_LEDGER = ROOT / "references" / "calibration.jsonl"
SEVERITY_ORDER = {"blocker": 0, "warning": 1, "nit": 2}
SEVERITY_MARK = {"blocker": "🔴", "warning": "🟡", "nit": "🔵"}
CONFIG_NAME = ".spec-lint.json"

# 规则体检阈值（与 references/calibration.md 的"新规则生命周期"一致）
PROMOTE_HITS = 3      # 连续在 ≥3 份不同文档中确认有效命中 → 可升 blocker
DEMOTE_FP_RUN = 2     # 连续误报 ≥2 次且未修复 → 降级/删除候选
REFACTOR_FIXES = 3    # 同一规则累计修复 ≥3 次 → 重构候选（排除表在膨胀，该重写规则体）
DELETE_DOCS = 10      # ≥10 份文档零命中 → 待删除评审


def err(msg: str) -> "NoReturn":  # noqa: F821
    sys.exit(f"错误：{msg}")


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip("　 .,，。;；:：、")


def fingerprint(f: dict) -> str:
    """跨轮次稳定的把手：只依赖规则 ID + 证据文本，不依赖行号（行号会随编辑漂移）。"""
    raw = norm(f.get("evidence", "")) + "|" + norm(f.get("match", "") or "")
    return f"{f['rule_id']}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:10]}"


def load_rules() -> dict:
    if not RULES_JSON.exists():
        err("references/rules.json 不存在，请先运行 python3 scripts/build_rules.py")
    return json.loads(RULES_JSON.read_text(encoding="utf-8"))


def load_config(path: str | None) -> dict:
    p = Path(path) if path else Path.cwd() / CONFIG_NAME
    if not p.exists():
        return {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(f"{p} 不是合法 JSON（{e}）")
    if not isinstance(cfg, dict):
        err(f"{p} 顶层必须是对象")
    return cfg


def rule_view(rule: dict, cfg: dict) -> dict | None:
    """应用配置后的规则视图；被关闭返回 None。"""
    r = dict(rule)
    ov = (cfg.get("rules") or {}).get(r["id"])
    if isinstance(ov, str):
        if ov == "off":
            return None
        if ov not in SEVERITY_ORDER:
            err(f"配置 rules.{r['id']} = {ov!r} 无效（可选 off/blocker/warning/nit）")
        r["severity"] = ov
    return r


def active_waivers(cfg: dict) -> tuple[dict, list]:
    today = date.today().isoformat()
    by_fp: dict[str, dict] = {}
    expired: list[dict] = []
    for w in cfg.get("waivers") or []:
        fp = w.get("fingerprint")
        if not fp:
            continue
        exp = w.get("expires")
        if exp and str(exp) < today:
            expired.append(w)
            continue
        by_fp[fp] = w
    return by_fp, expired


def find_line(lines: list[str], evidence: str, hint: int | None = None) -> int | None:
    """在文档里定位证据所在行；先信 hint，再全文搜。定位不到 = 证据不成立。"""
    nev = norm(evidence)
    if not nev:
        return None
    if hint and 1 <= hint <= len(lines) and nev in norm(lines[hint - 1]):
        return hint
    for i, ln in enumerate(lines, 1):
        if nev in norm(ln):
            return i
    return None


def mechanical_findings(doc_text: str, rules_by_id: dict) -> tuple[list, dict]:
    raw = cm.scan(doc_text)
    findings, cross_check = [], {}
    for rid, rule in rules_by_id.items():
        key = rule.get("script_key")
        if not key:
            continue
        bucket = raw.get(key, [])
        if rule["detector"] == "helper":
            if bucket:
                cross_check[rid] = bucket
            continue
        for item in bucket:
            findings.append({
                "rule_id": rid,
                "line": item.get("line"),
                "evidence": item.get("text", ""),
                "match": item.get("match") or item.get("word") or "",
                "detector": rule["detector"],
                "confidence": "confirmed" if rule["detector"] == "mechanical" else "candidate",
                "source": "script",
            })
    return findings, cross_check


def load_semantic(path: str, lines: list[str], rules_by_id: dict, genre: str) -> tuple[list, list]:
    """读入模型写的语义 findings，并强制"无证据不报警"。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(f"{path} 不是合法 JSON（{e}）")
    items = data.get("findings", []) if isinstance(data, dict) else data
    need_human = data.get("need_human", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        err(f"{path} 的 findings 必须是数组")

    out, errs = [], []
    for it in items:
        rid = it.get("rule_id")
        rule = rules_by_id.get(rid)
        if rule is None:
            errs.append(f"未知规则 ID：{rid!r}")
            continue
        if genre not in rule["genres"]:
            errs.append(f"{rid} 不适用于体裁 {genre}（适用：{'/'.join(rule['genres'])}）")
            continue
        ev = (it.get("evidence") or "").strip()
        if not ev:
            errs.append(f"{rid} 缺 evidence —— 无证据不报警，拒绝上报")
            continue
        line = find_line(lines, ev, it.get("line"))
        if line is None:
            errs.append(f"{rid} 的 evidence 在文档里找不到：「{ev[:40]}」")
            continue
        sev = it.get("severity")
        if sev is not None and sev not in SEVERITY_ORDER:
            errs.append(f"{rid} 的 severity={sev!r} 无效（blocker/warning/nit）")
            continue
        status = it.get("status", "open")
        if status not in ("open", "answered", "waived"):
            errs.append(f"{rid} 的 status={status!r} 无效（open/answered/waived）")
            continue
        rec = {
            "rule_id": rid,
            "line": line,
            "section": it.get("section"),
            "evidence": ev,
            "detector": "semantic",
            "confidence": it.get("confidence", "confirmed"),
            "source": "model",
            "status": status,
        }
        if sev:
            rec["severity"] = sev
        out.append(rec)

    if errs:
        err(f"{path} 校验未通过：\n  - " + "\n  - ".join(errs))
    return out, need_human


def finalize(findings: list, doc_path: str, genre: str, rules: list, cfg: dict,
             round_no: int, cross_check: dict, need_human: list) -> dict:
    rules_by_id = {r["id"]: r for r in rules}
    kept = []
    for f in findings:
        rv = rule_view(rules_by_id[f["rule_id"]], cfg)
        if rv is None:
            continue
        f.setdefault("severity", rv["severity"])
        f["title"] = rv["title"]
        f["group"] = rv["group"]
        f["question"] = rv["question"]
        f["evidence"] = (f.get("evidence") or "").strip()
        f["fingerprint"] = fingerprint(f)
        kept.append(f)

    merged: dict[str, dict] = {}
    for f in kept:
        if f["fingerprint"] in merged:
            merged[f["fingerprint"]]["occurrences"] += 1
            continue
        f["occurrences"] = 1
        f.setdefault("status", "open")
        merged[f["fingerprint"]] = f
    findings = list(merged.values())

    waivers, expired = active_waivers(cfg)
    for f in findings:
        w = waivers.get(f["fingerprint"])
        if w:
            f["status"] = "waived"
            f["waiver"] = {k: w.get(k) for k in ("reason", "owner", "expires") if w.get(k)}

    findings.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f.get("line") or 0, f["rule_id"]))

    summary = {"blocker": 0, "warning": 0, "nit": 0, "open": 0, "answered": 0, "waived": 0,
               "open_blocker": 0}
    for f in findings:
        summary[f["severity"]] += 1
        summary[f["status"]] += 1
        if f["severity"] == "blocker" and f["status"] == "open":
            summary["open_blocker"] += 1

    rules_data = load_rules()
    return {
        "spec_lint": rules_data["version"],
        "rules_version": rules_data["version"],
        "doc": doc_path,
        "genre": genre,
        "round": round_no,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "gate": "pass" if summary["open_blocker"] == 0 else "fail",
        "findings": findings,
        "cross_check": cross_check,
        "need_human": need_human,
        "expired_waivers": expired,
    }


def print_summary(result: dict, out_path: str | None) -> None:
    s = result["summary"]
    print(f"文档：{result['doc']}   体裁：{result['genre']}   轮次：{result['round']}")
    print(f"{SEVERITY_MARK['blocker']} {s['blocker']} · {SEVERITY_MARK['warning']} {s['warning']}"
          f" · {SEVERITY_MARK['nit']} {s['nit']}   "
          f"（未解决 {s['open']}，已豁免 {s['waived']}，需人工确认 {len(result['need_human'])}）")
    verdict = "通过" if result["gate"] == "pass" else f"不通过（{s['open_blocker']} 项 blocker 未解决）"
    print(f"门禁：{verdict}")
    for f in result["findings"][:10]:
        mark = SEVERITY_MARK[f["severity"]]
        loc = f"第 {f['line']} 行" if f.get("line") else "—"
        tok = f"「{f['match']}」" if f.get("match") else ""
        print(f"  {mark} [{f['rule_id']}] {loc} {tok}{f['evidence'][:44]}")
    if len(result["findings"]) > 10:
        print(f"  …… 另有 {len(result['findings']) - 10} 条")
    if out_path:
        print(f"表已写入：{out_path}")


def cmd_scan(args) -> int:
    doc = Path(args.doc)
    if not doc.exists():
        err(f"文档不存在：{doc}")
    cfg = load_config(args.config)
    rules_data = load_rules()
    rules = rules_data["rules"]
    genre = args.genre or cfg.get("genre") or "prd"
    if genre not in rules_data["genres"]:
        err(f"未知体裁 {genre!r}（可选：{'/'.join(rules_data['genres'])}）")

    text = doc.read_text(encoding="utf-8")
    lines = text.splitlines()
    rules_by_id = {r["id"]: r for r in rules}

    findings, cross_check = mechanical_findings(text, rules_by_id)
    need_human: list = []
    if args.semantic:
        sem, need_human = load_semantic(args.semantic, lines, rules_by_id, genre)
        findings.extend(sem)
    findings = [f for f in findings if genre in rules_by_id[f["rule_id"]]["genres"]]

    result = finalize(findings, str(doc), genre, rules, cfg, args.round, cross_check, need_human)
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        print_summary(result, args.out)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0


def cmd_questions(args) -> int:
    cfg = load_config(args.config)
    rules_data = load_rules()
    genre = args.genre or cfg.get("genre") or "prd"
    if genre not in rules_data["genres"]:
        err(f"未知体裁 {genre!r}（可选：{'/'.join(rules_data['genres'])}）")

    rules = []
    for r in rules_data["rules"]:
        if genre not in r["genres"]:
            continue
        rv = rule_view(r, cfg)
        if rv is not None:
            rules.append(rv)

    if args.json:
        print(json.dumps({
            "genre": genre,
            "genre_doc": rules_data["genres"][genre],
            "rules_version": rules_data["version"],
            "count": len(rules),
            "questions": [{"rule_id": r["id"], "severity": r["severity"], "group": r["group"],
                           "title": r["title"], "question": r["question"]} for r in rules],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"【{genre} · 开工前必须回答】{rules_data['genres'][genre]}")
    print(f"（共 {len(rules)} 项，规则库 v{rules_data['version']}）\n")
    last_group = None
    for r in sorted(rules, key=lambda x: (x["group"], x["id"])):
        if r["group"] != last_group:
            last_group = r["group"]
            print(f"— {r['group']}. {rules_data['groups'].get(r['group'], '')}")
        esc = f"（{r['severity']}→{r['escalate_to']}）" if r.get("escalate_to") else ""
        print(f"  {SEVERITY_MARK[r['severity']]} {r['id']} {r['title']}{esc}")
        print(f"      → {r['question']}")
    return 0


def cmd_round(args) -> int:
    prev = json.loads(Path(args.prev).read_text(encoding="utf-8"))
    cur = json.loads(Path(args.current).read_text(encoding="utf-8"))
    pf = {f["fingerprint"]: f for f in prev.get("findings", [])}
    cf = {f["fingerprint"]: f for f in cur.get("findings", [])}

    resolved = [pf[k] for k in pf if k not in cf]
    new = [cf[k] for k in cf if k not in pf]
    persist = [cf[k] for k in cf if k in pf]
    new_open = [f for f in new if f["status"] == "open"]
    sev_changed = [f for f in persist if f["severity"] != pf[f["fingerprint"]]["severity"]]

    s = cur.get("summary", {})
    converged = len(new_open) == 0
    gate_pass = s.get("open_blocker", 0) == 0

    if args.json:
        print(json.dumps({
            "round": cur.get("round"),
            "resolved": [f["fingerprint"] for f in resolved],
            "persisting": [f["fingerprint"] for f in persist],
            "new": [f["fingerprint"] for f in new],
            "counts": {"resolved": len(resolved), "persisting": len(persist),
                       "new": len(new), "new_open": len(new_open)},
            "converged": converged,
            "gate": "pass" if gate_pass else "fail",
            "open_blocker": s.get("open_blocker", 0),
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"复评第 {cur.get('round')} 轮")
    print(f"  已解决  {len(resolved)}")
    print(f"  仍存在  {len(persist)}")
    print(f"  新出现  {len(new_open)}" + ("   ← 收敛信号" if converged else "   ← 还在动"))
    if sev_changed:
        print(f"  级别变化 {len(sev_changed)}：" +
              "，".join(f"{f['rule_id']} {pf[f['fingerprint']]['severity']}→{f['severity']}"
                        for f in sev_changed))
    for f in new_open[:5]:
        tok = f"「{f['match']}」" if f.get("match") else ""
        print(f"    新 {SEVERITY_MARK[f['severity']]} [{f['rule_id']}] {tok}{f['evidence'][:40]}")
    for f in persist:
        if f["status"] == "open":
            tok = f"「{f['match']}」" if f.get("match") else ""
            print(f"    未解决 {SEVERITY_MARK[f['severity']]} [{f['rule_id']}] {tok}{f['evidence'][:36]}")
    print(f"\n收敛：{'是（本轮无新问题）' if converged else '否'}")
    print("门禁：" + ("通过" if gate_pass else f"不通过（{s.get('open_blocker', 0)} 项 blocker 未解决）"))
    return 0


def cmd_stats(args) -> int:
    ledger = Path(args.ledger)
    if not ledger.exists():
        err(f"裁决账不存在：{ledger}")
    reviews, verdicts = [], []
    for i, raw in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            err(f"{ledger}:{i} 不是合法 JSON（{e}）")
        t = rec.get("type")
        if t == "review":
            reviews.append(rec)
        elif t == "verdict":
            verdicts.append(rec)
        else:
            err(f"{ledger}:{i} 未知 type={t!r}（只支持 review / verdict）")

    rules_data = load_rules()
    stat: dict[str, dict] = {}
    for r in rules_data["rules"]:
        stat[r["id"]] = {"rule_id": r["id"], "severity": r["severity"], "docs": 0,
                         "hits": 0, "FP": 0, "MISS": 0, "SEV": 0, "OK": 0,
                         "fp_run": 0, "fixes": 0, "hit_docs": set()}
    for rv in reviews:
        genre = rv.get("genre")
        for rid in stat:
            rule = next(r for r in rules_data["rules"] if r["id"] == rid)
            if genre and genre in rule["genres"]:
                stat[rid]["docs"] += 1
        for rid in rv.get("findings", []):
            if rid in stat:
                stat[rid]["hits"] += 1
                stat[rid]["hit_docs"].add(rv.get("doc"))
    for v in verdicts:
        rid = v.get("rule")
        if rid not in stat:
            err(f"裁决账引用了未知规则：{rid}")
        verdict = v.get("verdict")
        if verdict not in ("FP", "MISS", "SEV", "OK"):
            err(f"裁决 {verdict!r} 无效（FP/MISS/SEV/OK）")
        stat[rid][verdict] += 1
    # 连续误报：按裁决顺序取「末尾连续且尚未修复」的 FP 段。
    # 已修的 FP（fixed 字段）不是失职信号，而是"排除表又加了一条"——那由 fixes 计数反映。
    for rid in stat:
        run = 0
        for v in verdicts:
            if v.get("rule") != rid:
                continue
            if v.get("verdict") != "FP":
                run = 0
            elif v.get("fixed"):
                stat[rid]["fixes"] += 1
                run = 0
            else:
                run += 1
        stat[rid]["fp_run"] = run

    rows = sorted(stat.values(), key=lambda x: (-x["FP"], -x["MISS"], x["rule_id"]))
    if args.json:
        for r in rows:
            r["hit_docs"] = len([d for d in r["hit_docs"] if d])
        print(json.dumps({"rules_version": rules_data["version"],
                          "reviews": len(reviews), "verdicts": len(verdicts),
                          "thresholds": {"promote_hits": PROMOTE_HITS,
                                         "demote_fp_run": DEMOTE_FP_RUN,
                                         "delete_docs": DELETE_DOCS},
                          "rules": rows}, ensure_ascii=False, indent=2))
        return 0

    print(f"规则体检（规则库 v{rules_data['version']}）")
    print(f"裁决账：{len(reviews)} 次评审记录，{len(verdicts)} 条裁决\n")
    print(f"{'规则':<6}{'级别':<9}{'命中':>5}{'文档':>5}{'误报':>5}{'已修':>5}"
          f"{'漏报':>5}{'未修连续':>9}")
    for r in rows:
        flag = ""
        if r["fp_run"] >= DEMOTE_FP_RUN:
            flag = "  ← 降级候选"
        elif r["fixes"] >= REFACTOR_FIXES:
            flag = "  ← 重构候选（排除表膨胀）"
        elif r["hits"] >= PROMOTE_HITS and r["severity"] != "blocker" and r["FP"] == 0:
            flag = "  ← 可升 blocker"
        elif r["docs"] >= DELETE_DOCS and r["hits"] == 0:
            flag = "  ← 待删除评审"
        if flag or r["FP"] or r["MISS"]:
            print(f"{r['rule_id']:<6}{r['severity']:<9}{r['hits']:>5}{r['docs']:>5}"
                  f"{r['FP']:>5}{r['fixes']:>5}{r['MISS']:>5}{r['fp_run']:>9}{flag}")
    if not reviews:
        print("（还没有 review 记录：文档覆盖数从 v1.6.0 起累积，历史无法回溯）")
    print(f"\n阈值：确认命中 ≥{PROMOTE_HITS} 份文档可升 blocker；"
          f"未修连续误报 ≥{DEMOTE_FP_RUN} 次降级；累计修复 ≥{REFACTOR_FIXES} 次重构；"
          f"≥{DELETE_DOCS} 份文档零命中待删除评审")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="spec-lint：把评审变成一张能接得上的表")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="查一遍文档，输出 findings 表")
    p.add_argument("doc")
    p.add_argument("--genre", choices=["prd", "research"])
    p.add_argument("--semantic", help="模型写的语义 findings JSON，合并进表并校验证据")
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--out", help="findings 表写到哪里（默认打印到 stdout）")
    p.add_argument("--config")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("questions", help="印开工前的提问清单")
    p.add_argument("--genre", choices=["prd", "research"])
    p.add_argument("--config")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_questions)

    p = sub.add_parser("round", help="对比两轮结果")
    p.add_argument("--prev", required=True)
    p.add_argument("--current", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_round)

    p = sub.add_parser("stats", help="规则体检")
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
