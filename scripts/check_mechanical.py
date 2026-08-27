#!/usr/bin/env python3
"""Spec 评审机械检查器 v1.2：确定性扫描，输出带行号的 JSON 证据。

用法: python3 check_mechanical.py <文档路径>

v1.2 校准（来自真实 PRD 语料）：
- A5：「待确认」是业务状态名、「占位/骨架占位」是 UI 术语、<domain>/<JWT> 是
  代码示例、¥xxx 是 UI 示意——均不再报；只报真正的未定占位。
- C3：「等回款/等财务/等通知」等"等待"义不再误判为开放列举；「稍等一下/等我一下/我等一下」类，lookbehind 加「我」、lookahead 加「一下」。
- B1：「智能化平台」（产品名）、「友好提示」（固定术语）、「完善」作动词
  （从句结尾/前接"随/逐步"）不报；其余仍为候选，需模型结合上下文确认。
- G1：新增决策点标记扫描（待评审/口径待确认/待实测/审批流待定…）。

v1.4 校准（调研/可行性文档复审）：
- B1：「显著标识」是 AI 生成内容标识的法定术语，加入白名单。
- C3：法规/公文原文直接引语（成对引号内）中的"等"不报（引号掩码）；
  「不等」固定词不报。引号外的"等"仍为候选，需模型结合上下文确认。
"""
import json
import re
import sys

# A5: 未完成痕迹（不含业务状态名「待确认」、不含 UI 术语「占位」）
PLACEHOLDER_PATTERNS = [
    r"TBD", r"TODO", r"FIXME",
    r"待定(?!稿)", r"待补充", r"待明确", r"待填写", r"尚未确定",
    r"x{3,}", r"X{3,}", r"\?{3,}", r"【[^】]*】",
    r"<[一-龥][^>]{0,20}>",   # 中文尖括号占位（<待填>）；<domain>/<JWT> 不匹配
]

# B1: 模糊词候选（需模型结合上下文确认是否真的无度量主体）
VAGUE_WORDS = [
    "高效", "流畅", "显著", "大幅", "更好", "极致", "友好", "便捷",
    "智能化", "一站式", "丰富", "完善", "明显", "极大", "提升体验",
    "体验好", "满意度高", "又快又稳",
    "鲁棒", "直观", "灵活", "可靠", "可扩展", "无缝", "现代化",
    "强大", "易用", "人性化",
]

# B1 上下文白名单：词出现在这些固定搭配中时不报
VAGUE_CONTEXT_OK = {
    "智能化": re.compile(r"智能化(?:平台|系统|产品|工具|转型)"),
    "友好": re.compile(r"友好(?:提示|文案|引导|界面)|提示友好|隐私友好|环境友好|环保友好"),
    # v1.4：「显著标识」是 AI 生成内容标识的法定术语，非模糊形容词
    "显著": re.compile(r"显著标识"),
}
# 「完善」作动词（从句结尾，或前接 随/逐步/进一步/不断/持续）不报
WENSHAN_VERB = re.compile(r"(?:随|逐步|进一步|不断|持续|共同)[^。；\n]{0,12}完善|完善[。；，\s]*(?:$|[，。；）])")

# C6: 弱模态/推诿式表述（候选）
HEDGE_WORDS = [
    "尽量", "尽可能", "争取", "原则上", "视情况", "酌情",
    "最好能", "也许", "或许", "大概",
]

# C3: 开放列举（"等待"义通过负向先行/后行排除）
OPEN_ENDED_PATTERNS = [
    r"等等", r"之类", r"诸如此类", r"什么的",
    r"(?<![平和同均优劣一幂系稍不我])等(?!待|于|级|号|同|回款|财务|业务员|通知|审核|确认|发货|回复|结果|电话|上线|到账|到货|价|我|你|他|她|人[，。、；）\s]|入[口库]|一下)",
]

# G1: 决策点标记（正文里尚未拍板、应归集到待决策清单的项）
DECISION_PATTERNS = [
    r"待评审", r"口径待(?:确认|定|评审)", r"规则待确认", r"方案待定",
    r"审批流待(?:确认|定|评审)", r"待实测", r"待最终锁定",
    r"待第?\s*[0-9一二两]+\s*周实测", r"待第?\s*[0-9一二两]+\s*周(?:确认|锁定)",
]


# 引号对：成对引号内为原文直接引语，其中的"等"不算作者的开放列举
_QUOTE_PAIRS = [("“", "”"), ("‘", "’"), ("「", "」"), ("『", "』")]


def mask_quoted(line: str) -> str:
    """把成对引号内的字符替换为空格（仅用于 C3 扫描）。

    中文弯引号/直角引号严格配对；直双引号按奇偶配对；直单引号不处理
    （英文撇号会误伤）。掩码只抑制候选，引号外的"等"照常报出。
    """
    chars = list(line)
    for open_q, close_q in _QUOTE_PAIRS:
        i = 0
        while i < len(chars):
            if chars[i] == open_q:
                j = i + 1
                while j < len(chars) and chars[j] != close_q:
                    chars[j] = " "
                    j += 1
                i = j + 1
            else:
                i += 1
    inside = False
    for idx, ch in enumerate(chars):
        if ch == '"':
            inside = not inside
        elif inside:
            chars[idx] = " "
    return "".join(chars)


def scan(text: str) -> dict:
    findings = {"A5": [], "B1": [], "C3": [], "C6": [], "C7": [], "G1": [],
                "C2_number_lines": []}
    placeholder_re = re.compile("|".join(PLACEHOLDER_PATTERNS))
    open_re = re.compile("|".join(OPEN_ENDED_PATTERNS))
    decision_re = re.compile("|".join(DECISION_PATTERNS))

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        for m in placeholder_re.finditer(line):
            # ¥xxx / ￥xxx 是 UI 价格示意，不报
            if m.group(0).lower().startswith("xxx") and m.start() > 0 and line[m.start()-1] in "¥￥":
                continue
            # 「学你说：xxx」类语音复读模板，不报
            if m.group(0).lower().startswith("xxx") and "学你说" in line:
                continue
            findings["A5"].append({"line": lineno, "match": m.group(0), "text": stripped})
        for w in VAGUE_WORDS:
            if w in line:
                if w in VAGUE_CONTEXT_OK and VAGUE_CONTEXT_OK[w].search(line):
                    continue
                if w == "完善" and WENSHAN_VERB.search(line):
                    continue
                findings["B1"].append({"line": lineno, "word": w, "text": stripped})
        for m in open_re.finditer(mask_quoted(line)):
            findings["C3"].append({"line": lineno, "match": m.group(0), "text": stripped})
        for w in HEDGE_WORDS:
            if w in line:
                findings["C6"].append({"line": lineno, "word": w, "text": stripped})
        if "和/或" in line or "或/和" in line:
            findings["C7"].append({"line": lineno, "word": "和/或", "text": stripped})
        for m in decision_re.finditer(line):
            findings["G1"].append({"line": lineno, "match": m.group(0), "text": stripped})
        if re.search(r"\d", line):
            findings["C2_number_lines"].append({"line": lineno, "text": stripped})

    return findings


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python3 check_mechanical.py <文档路径>", file=sys.stderr)
        return 2
    try:
        text = open(sys.argv[1], encoding="utf-8").read()
    except OSError as e:
        print(f"无法读取文件: {e}", file=sys.stderr)
        return 1
    print(json.dumps(scan(text), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
