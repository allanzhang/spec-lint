# spec-lint

> PRD / Spec 的质量门禁——"需求文档的单元测试"。只评审，不代写、不改写、不评分。

生成式 AI 让"写一份漂亮的需求文档"成本趋近于零，瓶颈从生产转移到了判断。spec-lint 补的是验证侧：像 ESLint 一样输出**带规则 ID、严重度、行号证据**的质疑清单——不评价方向对错，只保证决策依据显形、可度量、自洽。

它输出的是一张**能接得上的表**，不是一段报告：每条问题都带规则 ID、稳定指纹和「下一轮该问什么」。所以查出来的问题能直接变回上游要问的问题，评审工具和提问工具才形成闭环。

## 安装

```bash
git clone https://github.com/allanzhang/spec-lint
```

把 `spec-lint/` 放进你所用的宿主技能目录（任何支持 `SKILL.md` 约定的 agent 都可以）：

| 宿主 | 技能目录 |
|---|---|
| Codex | `~/.codex/skills/` |
| Claude Code | `~/.claude/skills/` |
| DeepSeek Harness | `$DSH_HOME/skills/`（默认 `~/.dsh/skills/`） |

只依赖 `python3` 标准库，不需要安装任何包。重开 agent 生效。

## 使用

### 一、评审已有文档

对 agent 说"用 spec-lint 评审这份文档"，或直接跑工具：

```bash
python3 scripts/spec_lint.py scan 你的文档.md --genre prd --out findings.json
```

`--genre prd`（产品/工程需求文档，按可验收性）或 `--genre research`（调研/可行性文档，按决策就绪度）决定跑哪些规则。

```
文档：doc.md   体裁：prd   轮次：1
🔴 7 · 🟡 2 · 🔵 0   （未解决 9，已豁免 0，需人工确认 0）
门禁：不通过（7 项 blocker 未解决）
  🔴 [B1] 第 7 行 「显著」- 显著提升新用户的上手效率，让首周体验更流畅；
  🔴 [A5] 第 31 行 「TBD」- 营销推送支持人群圈选，圈选规则 TBD；
```

表里每条 finding 长这样：

```json
{
  "rule_id": "B1",
  "severity": "blocker",
  "line": 7,
  "evidence": "- 显著提升新用户的上手效率，让首周体验更流畅；",
  "question": "这个词对应的具体指标是什么？当前值和目标值是多少？",
  "fingerprint": "B1:e1c977c7e3",
  "status": "open"
}
```

`question` 是下一轮要问的，`fingerprint` 是跨轮次对得上的把手（只依赖规则 ID + 证据文本，**行号漂移不影响**）。

### 二、文档还没写：印提问清单

```bash
python3 scripts/spec_lint.py questions --genre prd             # 人读的必答清单
python3 scripts/spec_lint.py questions --genre research --json  # 交给上游提问工具
```

把规则库里每条规则的「请回答」印成开工前的必答清单。**提问由上游（brainstorming 一类）执行**，spec-lint 只保证该问的没漏。

### 三、循环：查 → 改 → 再查

```bash
# 第 1 轮
python3 scripts/spec_lint.py scan 文档.md --genre prd --out r1.json
# 作者按表里的 question 逐条修订文档后，第 2 轮
python3 scripts/spec_lint.py scan 文档.md --genre prd --round 2 --out r2.json
python3 scripts/spec_lint.py round --prev r1.json --current r2.json
```

```
复评第 2 轮
  已解决  3
  仍存在  6
  新出现  0   ← 收敛信号
收敛：是（本轮无新问题）
门禁：不通过（4 项 blocker 未解决）
```

**收敛信号是「新出现」为 0，不是「还有没有问题」**——问题永远挑得出来，永远能挑。只问"还有没有问题"，循环永远停不下来。

### 四、门禁进 CI

```bash
python3 scripts/spec_lint.py scan 文档.md --genre prd --fail-on blocker
```

退出码 1 = 不通过。`--fail-on warning` / `--fail-on nit` 可收紧口径，`none` 只看报告不拦。

### 五、规则体检（自进化）

```bash
python3 scripts/spec_lint.py stats
```

```
规则    级别          命中   文档   误报   已修   漏报     未修连续
C3    warning      0    7    4    4    0        0  ← 重构候选（排除表膨胀）
B1    blocker      0    7    3    3    0        0  ← 重构候选（排除表膨胀）
G2    blocker      3    7    0    0    1        0
```

它按 `references/calibration.md` 里早就写好、但以前没人真的在算的生命周期阈值自动判定：

| 信号 | 阈值 | 含义 |
|---|---|---|
| 可升 blocker | 命中 ≥3 份不同文档 | 规则被反复证实有效 |
| 降级候选 | **未修的**连续误报 ≥2 次 | 规则在伤人 |
| 重构候选 | 同一规则累计修复 ≥3 次 | 排除表在膨胀，该重写规则体而不是继续堆补丁 |
| 待删除评审 | ≥10 份文档零命中 | 只增不减是衰败信号 |

注意区分「误报」和「已修」：一条误报后面写着"已生效 vX"就是修好了，不该算失职——那是排除表又加了一条，由「已修」计数反映。早期版本把两者混为一谈，会把好规则误报成坏规则。

## 闭环里的位置

```
① brainstorming（发散：意图/假设/边界/取舍）      ← 上游，负责"问"
② 成文 Spec
③ spec-lint 出表：编号 + 原话 + 下一轮该问什么     ← 本技能，负责"查"
④ 表里的问题变回上游要问的 → 修订 → 复审
   收敛信号：本轮「新出现」为 0
⑤ 过门 → 写计划 → 执行
```

- spec-lint 负责**问题的完备性**（该问的别漏）；提问的节奏、追问、一次问一个是上游的事。
- 过门条件：无未解决的 blocker（显式豁免的算已解决）。
- 完整流程见 `SKILL.md`。

## 规则

- **8 组 33 条**：完整性 A / 可度量性 B / 歧义自洽 C / 证据 D / 上线就绪 F / 决策归集 G / 调研决策就绪度 H，附带体裁分流（PRD 按可验收性，调研按决策就绪度）。
- 两条检查线：**机械**（`scripts/check_mechanical.py`，确定性命中，输出行号证据；A5/C7 命中即结论，B1/C3/C6/G1 只给候选）+ **语义**（按规则库逐条审，机械结果不替代判断）。
- **规则唯一事实源是 `references/rules.md`**。`references/rules.json` 由 `scripts/build_rules.py` 生成，含每条规则的严重度、适用体裁和「该问什么」；改了 rules.md 要重跑生成器，`selftest.py` 会校验两者同步，防漂移。

## 误报怎么处理

不要"报个 ID 就全局退役"——一个人的误报不该让所有用户丢一条规则。用项目级 `.spec-lint.json`（模板见 `references/config-example.json`）：

```json
{
  "genre": "prd",
  "rules": { "C6": "nit", "F4": "off" },
  "waivers": [
    { "fingerprint": "B1:0123456789",
      "reason": "该指标在附录 B 已给出基线与目标值",
      "owner": "allan",
      "expires": "2026-12-31" }
  ]
}
```

- `rules`：按规则 ID 覆盖严重度或关闭，只影响本项目；
- `waivers`：单条豁免，**必须写理由、责任人和有效期**，过期自动失效并提示；
- 豁免按 `fingerprint` 匹配，所以文档编辑导致行号变化不会让豁免失效。

## 与 spec-kit / OpenSpec 的关系

串联，不冲突：spec-kit / OpenSpec 是"写 spec → plan → tasks → 代码"的开发流水线；spec-lint 是不依附任何流水线的独立质量门禁。

```
① brainstorming → ② 成文 Spec → ③ spec-lint 门禁 → ④ 修订循环至无🔴 → ⑤ 计划 → ⑥ 执行
```

闸门位置在 Spec 定稿与写计划之间，烂 Spec 被拦在返工发生之前。

### 接入 OpenSpec 流水线（把 spec-lint 设为提案门禁）

OpenSpec v1.6+ 通过 `openspec instructions <artifact> --change <name>` 向模型注入每条 artifact 的规则。把 spec-lint 门禁写进 `openspec/config.yaml` 的 `rules:`，模型在 propose 阶段就必须先过门禁：

```yaml
rules:
  proposal:
    - "质量门禁：proposal 生成后必须运行本机已安装的 spec-lint 评审，按 PRD 可验收性标准（规则组 A/B/C/F/G）。无 🔴（或全部被作者显式驳回并记录）才允许生成 tasks / 进入实施。"
  design:
    - "质量门禁：design 生成后必须运行本机已安装的 spec-lint 评审，按工程规格可验收性标准（规则组 A/B/C/F/G）。无 🔴 才允许进入实施。"
```

已实测：`openspec instructions proposal --change <name> --json` 的 `rules` 字段会携带上述门禁文本，作为模型的硬约束。

## 自进化

每份报告末尾征求裁决（误报 / 漏报 / 级别），写入 `references/calibration.jsonl`（机器可读，一行一条）与 `references/calibration.md`（叙述性教训）。`spec_lint.py stats` 自动算规则体检；规则改动跑 `scripts/selftest.py` 回归、经确认后才发版。

## 仓库结构

```
spec-lint/
├── SKILL.md                    # 技能入口：触发条件、评审流程、铁律、循环模式
├── references/
│   ├── rules.md                # 规则库（唯一事实源，人写）
│   ├── rules.json              # 规则表（生成物，机器读）
│   ├── calibration.md          # 校准日志与规则生命周期（叙述）
│   ├── calibration.jsonl       # 裁决账（机器可读，stats 用它算体检）
│   ├── config-example.json     # 项目配置模板（规则开关 + 豁免）
│   └── report-format.md        # 报告格式（报告是表的人读视图）
├── scripts/
│   ├── check_mechanical.py     # 确定性机械检查（输出带行号 JSON）
│   ├── build_rules.py          # rules.md → rules.json
│   ├── spec_lint.py            # scan / questions / round / stats
│   └── selftest.py             # 回归测试（语料 + 工具链）
└── tests/
```

## 许可

MIT
