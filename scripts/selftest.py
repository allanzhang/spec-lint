#!/usr/bin/env python3
"""spec-lint 机械检查器回归测试。

用法: python3 scripts/selftest.py
遍历 tests/cases/*.md，对照 tests/expectations/<同名>.json 断言：
- must_find[rule]：每个子串必须出现在该规则至少一条命中的 match/word/text 中；
- must_not_find[rule]：空列表 = 该规则必须零命中；非空列表 = 命中文本不得包含这些子串。
（expectations 中以 _ 开头的键为注释，忽略。）
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_mechanical as cm  # noqa: E402

CASES = ROOT / "tests" / "cases"
EXPECT = ROOT / "tests" / "expectations"


def findings_text(items):
    return " ".join(
        str(x.get("match", "")) + str(x.get("word", "")) + x.get("text", "")
        for x in items
    )


def main() -> int:
    total_fail = 0
    cases = sorted(CASES.glob("*.md"))
    for case in cases:
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

    print(f"\n{'全部通过 ✅' if total_fail == 0 else f'{total_fail} 个用例失败 ❌'}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
