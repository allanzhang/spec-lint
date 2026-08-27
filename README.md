# spec-lint

> PRD / Spec 的质量门禁——"需求文档的单元测试"。只评审，不代写、不改写、不评分。

生成式 AI 让"写一份漂亮的需求文档"成本趋近于零，瓶颈从生产转移到了判断。spec-lint 补的是验证侧：像 ESLint 一样输出**带规则 ID、严重度、行号证据**的质疑清单——不评价方向对错，只保证决策依据显形、可度量、自洽。

## 安装

```bash
git clone https://github.com/allanzhang/spec-lint
cp -R spec-lint ~/.codex/skills/spec-lint         # Codex
cp -R spec-lint ~/.claude/skills/spec-lint        # Claude Code / 其他支持 SKILL.md 约定的 agent
```

重启 agent 后生效。

## 使用

把 PRD / 调研文档丢给它，说"用 spec-lint 评审这份文档"。输入支持 `.md`/`.txt` 文件、直接粘贴文本；`.docx`/`.pdf`/`.html` 先转换为 Markdown 再评（报告注明转换损耗）。

```markdown
# Spec 评审报告：智能推送中心 PRD
## 摘要
- 🔴 5 项必须回答 · 🟡 8 项建议补充 · 🔵 3 项表述问题
- 结论：当前不具备进入研发评审的条件。卡点：成功指标不可度量、范围自相矛盾、存在 TBD。

## 🔴 Blocker
### [B1/B2] 目标与指标全是模糊词，无法判断成败
- 原文：「显著提升新用户的上手效率，让首周体验更流畅」
- 问题："显著/流畅"无度量主体，上线后无法判断目标达成没有。
- 请回答：对应的指标、基线值、目标值、采集方式各是什么？
```

要求"门禁判定"时只输出「通过 / 不通过 + 🔴 卡点清单 + 一句话结论」。完整报告格式见 `references/report-format.md`。

## 规则

- **8 组 33 条**（v1.4）：完整性 A / 可度量性 B / 歧义自洽 C / 证据 D / 上线就绪 F / 决策归集 G / 调研决策就绪度 H，附带体裁分流（PRD 按可验收性，调研按决策就绪度）。
- 两层检查：机械检查（`scripts/check_mechanical.py`，确定性扫描输出行号证据）+ 语义判定（按规则库逐条审，机械结果不替代判断）。
- **规则唯一事实源是 `references/rules.md`**（每条含判定指引、正反例、校准场景、出处）。每条规则可独立关闭——误报时报规则 ID 即可退役该条。

## 与 spec-kit / OpenSpec 的关系

串联，不冲突：spec-kit / OpenSpec 是"写 spec → plan → tasks → 代码"的开发流水线；spec-lint 是不依附任何流水线的独立质量门禁。

```
① brainstorming → ② 成文 Spec → ③ spec-lint 门禁 → ④ 修订循环至无🔴 → ⑤ 计划 → ⑥ 执行
```

- 闸门位置在 Spec 定稿与写计划之间，烂 Spec 被拦在返工发生之前；
- 「门禁判定」模式输出 通过/不通过+🔴 卡点清单，供流程编排；「循环模式」支持 评审→修订→复审 直到达标（上限 3 轮，见 SKILL.md 5.6）；
- 完整联动图见 SKILL.md「工作流位置」。

## 自进化

每份报告末尾征求裁决（误报 / 漏报 / 级别），记入 `references/calibration.md` 校准日志；规则改动跑 `scripts/selftest.py` 回归、经确认后才发版。排除表膨胀与长期零命中规则也有强制体检机制（见 calibration.md）。

## 仓库结构

```
spec-lint/
├── SKILL.md                 # 技能入口：触发条件、评审流程、铁律
├── references/
│   ├── rules.md             # 规则库（唯一事实源）
│   ├── calibration.md       # 校准日志与规则生命周期
│   └── report-format.md     # 报告格式
├── scripts/
│   ├── check_mechanical.py  # 确定性机械检查（输出带行号 JSON）
│   └── selftest.py          # 回归测试（tests/ 正反例语料）
└── tests/
```

## 许可

MIT