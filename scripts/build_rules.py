#!/usr/bin/env python3
"""从 references/rules.md 生成 references/rules.json。

rules.md 是唯一事实源（人写）；rules.json 是生成物（scripts/spec_lint.py 读它）。
改了 rules.md 就重跑本脚本；scripts/selftest.py 会校验两者是否同步。

用法:
  python3 scripts/build_rules.py            # 生成/更新 references/rules.json
  python3 scripts/build_rules.py --check    # 只校验是否同步（不同步退出 1）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_MD = ROOT / "references" / "rules.md"
RULES_JSON = ROOT / "references" / "rules.json"

VERSION_RE = re.compile(r"^#\s*评审规则库\s*v?([0-9][0-9.]*)")
GROUP_RE = re.compile(r"^##\s+([A-H])\.\s*(.+?)\s*$")
RULE_RE = re.compile(
    r"^###\s+([A-H]\d+)\s*"
    r"(?:(?P<sev>[\U0001F534\U0001F7E1\U0001F535](?:/[\U0001F534\U0001F7E1\U0001F535])?)\s+)?"
    r"(?P<title>.+?)"
    r"(?:\s*\[(?P<prov>[^\]]+)\])?\s*$"
)
FIELD_RES = {
    "genres": re.compile(r"^-\s*体裁：\s*(.+?)\s*$"),
    "severity_override": re.compile(r"^-\s*定级：\s*(.+?)\s*$"),
    "escalate_when": re.compile(r"^-\s*升级条件：\s*(.+?)\s*$"),
    "question": re.compile(r"^-\s*请回答：\s*(.+?)\s*$"),
}

SEV_NAME = {"\U0001F534": "blocker", "\U0001F7E1": "warning", "\U0001F535": "nit"}
GENRE_DOC = {
    "prd": "产品/工程需求文档（按可验收性评审）",
    "research": "调研/可行性/立项文档（按决策就绪度评审）",
}

# 脚本覆盖：规则 ID -> (check_mechanical.py 的桶名, 判定方式)
#   mechanical 脚本命中即最终结论
#   hybrid     脚本给候选，模型须结合上下文确认
#   helper     脚本只给交叉核对数据，本身不构成 finding
SCRIPT_SUPPORT = {
    "A5": ("A5", "mechanical"),
    "B1": ("B1", "hybrid"),
    "C2": ("C2_number_lines", "helper"),
    "C3": ("C3", "hybrid"),
    "C6": ("C6", "hybrid"),
    "C7": ("C7", "mechanical"),
    "G1": ("G1", "hybrid"),
}


def parse(md_text: str) -> dict:
    version = None
    groups: dict[str, str] = {}
    rules: list[dict] = []
    current_group = None
    current = None

    for raw in md_text.splitlines():
        line = raw.rstrip()
        if version is None:
            vm = VERSION_RE.match(line)
            if vm:
                version = vm.group(1)
        gm = GROUP_RE.match(line)
        if gm:
            current_group = gm.group(1)
            groups[current_group] = gm.group(2)
            current = None
            continue
        rm = RULE_RE.match(line)
        if rm and current_group:
            rid = rm.group(1)
            sev_raw = rm.group("sev")
            severity, escalate_to = "warning", None
            if sev_raw:
                parts = [SEV_NAME[p] for p in sev_raw.split("/") if p in SEV_NAME]
                severity = parts[0]
                if len(parts) > 1:
                    escalate_to = parts[-1]
            script = SCRIPT_SUPPORT.get(rid)
            current = {
                "id": rid,
                "group": current_group,
                "title": rm.group("title").strip(),
                "severity": severity,
                "escalate_to": escalate_to,
                "provenance": [p.strip() for p in (rm.group("prov") or "").split("/") if p.strip()],
                "genres": [],
                "question": None,
                "detector": script[1] if script else "semantic",
                "script_key": script[0] if script else None,
            }
            rules.append(current)
            continue
        if current is not None:
            for key, rx in FIELD_RES.items():
                fm = rx.match(line)
                if not fm:
                    continue
                val = fm.group(1)
                if key == "genres":
                    current["genres"] = [g.strip() for g in val.split("/") if g.strip()]
                elif key == "severity_override":
                    m2 = re.match(r"^(\w+)→(\w+)$", val)
                    if m2:
                        current["severity"] = m2.group(1)
                        current["escalate_to"] = m2.group(2)
                else:
                    current[key] = val

    errs = []
    if not version:
        errs.append("未找到版本号（形如 `# 评审规则库 v1.6.0`）")
    for r in rules:
        if not r["genres"]:
            errs.append(f"{r['id']} 缺 `- 体裁：` 行")
        if not r["question"]:
            errs.append(f"{r['id']} 缺 `- 请回答：` 行")
        for g in r["genres"]:
            if g not in GENRE_DOC:
                errs.append(f"{r['id']} 的体裁 `{g}` 未知（只支持 {'/'.join(GENRE_DOC)}）")
    if errs:
        raise SystemExit("rules.md 体检未通过：\n  - " + "\n  - ".join(errs))

    ids = [r["id"] for r in rules]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise SystemExit("规则 ID 重复：" + ", ".join(dupes))

    return {
        "version": version,
        "source": "references/rules.md",
        "generated_by": "scripts/build_rules.py",
        "severities": {"blocker": "\U0001F534", "warning": "\U0001F7E1", "nit": "\U0001F535"},
        "groups": groups,
        "genres": GENRE_DOC,
        "rules": rules,
    }


def render(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    data = parse(RULES_MD.read_text(encoding="utf-8"))
    text = render(data)
    if "--check" in sys.argv:
        if not RULES_JSON.exists():
            print("rules.json 不存在，请运行 scripts/build_rules.py")
            return 1
        if RULES_JSON.read_text(encoding="utf-8") != text:
            print("rules.json 与 rules.md 不同步，请重跑 scripts/build_rules.py")
            return 1
        print(f"rules.json 同步（{len(data['rules'])} 条规则，v{data['version']}）")
        return 0
    RULES_JSON.write_text(text, encoding="utf-8")
    counts: dict[str, int] = {}
    for r in data["rules"]:
        counts[r["detector"]] = counts.get(r["detector"], 0) + 1
    print(f"已生成 references/rules.json（v{data['version']}，{len(data['rules'])} 条规则）")
    print("判定方式：" + "，".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
