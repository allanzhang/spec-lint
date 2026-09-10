# spec-lint

> PRD / Spec 的质量门禁——"需求文档的单元测试"。只评审，不代写、不改写、不评分。

生成式 AI 让"写一份漂亮的需求文档"成本趋近于零，瓶颈从生产转移到了判断。spec-lint 补的是验证侧：像 ESLint 一样输出**带规则 ID、严重度、行号证据**的质疑清单——不评价方向对错，只保证决策依据显形、可度量、自洽。

**它是一个 Skill，不是一个 CLI。** 入口就是在 agent 里说话。

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

### 离线安装（不联网、不用 git）

从 [Releases](https://github.com/allanzhang/spec-lint/releases) 下载 `spec-lint-1.6.0.zip`
或 `spec-lint-1.6.0.tar.gz`，解压后把 `spec-lint/` 整个目录放进你的技能目录：

```bash
unzip spec-lint-1.6.0.zip -d /tmp/sl
cp -R /tmp/sl/spec-lint ~/.dsh/skills/spec-lint     # 换成你的宿主目录

# 可选：验证包完整、工具能跑
python3 ~/.dsh/skills/spec-lint/scripts/selftest.py
```

下载文件旁有 `SHA256SUMS`，校验：

```bash
shasum -a 256 -c SHA256SUMS
```

重开 agent 生效。`scripts/` 下的工具只依赖 `python3` 标准库（可选，见下）。

## 用法：跟 agent 说话就行

| 你想干什么 | 就这么说 |
|---|---|
| 评审一份已有需求 | **"用 spec-lint 评审这份 PRD"**（粘贴文本、给文件路径或链接都行） |
| 判断能不能进研发 | **"用 spec-lint 给个门禁判定"** |
| 起草中反复打磨 | **"用 spec-lint 复评，看上一轮的问题解决了没"** |
| 需求还只是想法 | **"帮我列出这份需求开工前必须回答的问题"** |

## 输出长什么样

评审的产物是**一张表**（每条 finding 带编号、原话、以及下一轮该问什么），报告是这张表的人读视图：

```markdown
# Spec 评审报告：智能推送中心 PRD
## 摘要
- 🔴 5 项必须回答 · 🟡 8 项建议补充 · 🔵 3 项表述问题
- 结论：当前不具备进入研发评审的条件。卡点：成功指标不可度量、范围自相矛盾、存在 TBD。

## 🔴 Blocker
### [B1] 目标与指标全是模糊词，无法判断成败
- **位置**：目标（第 7 行附近）
- **原文**：「显著提升新用户的上手效率，让首周体验更流畅」
- **问题**："显著/流畅"无度量主体，上线后无法判断目标达成没有。
- **请回答**：对应的指标、基线值、目标值、采集方式各是什么？
- **指纹**：`B1:e1c977c7e3`
```

表里对应的那一条：

```json
{
  "rule_id": "B1",
  "severity": "blocker",
  "line": 7,
  "evidence": "显著提升新用户的上手效率，让首周体验更流畅",
  "question": "这个词对应的具体指标是什么？当前值和目标值是多少？",
  "fingerprint": "B1:e1c977c7e3",
  "status": "open"
}
```

`question` 是下一轮要问的；`fingerprint` 是**跨轮次对得上的把手**（只依赖规则 ID + 证据文本，行号漂移不影响）。这两样是它比一段报告值钱的地方——见下面的闭环。

## 两种用法

### A. 单独用：评估一份已有需求

把文档交给 agent 说"评审这份"。产出报告 + findings 表。调研/可行性文档会自动改用「决策就绪度」标准，不套验收类规则。

### B. 接入 pipeline：从零开发一个项目

```
① brainstorming（发散：意图/假设/边界/取舍）      ← 上游，负责"问"
② 成文 Spec / proposal
③ spec-lint 出表：编号 + 原话 + 下一轮该问什么     ← 本技能，负责"查"
④ 表里的问题变回上游要问的 → 修订 → 复评
   收敛信号：本轮「新出现」为 0
⑤ 过门 → 写计划 → 执行
```

- 需求还没成文时，让它先印「开工前必答清单」——内容来自规则库里每条规则的「请回答」，交给上游去问。**提问的节奏归上游，spec-lint 只保证该问的没漏。**
- **收敛信号是「新出现」为 0，不是「还有没有问题」**——问题永远挑得出来，永远能挑。
- 过门条件：无未解决的 blocker（显式豁免的算已解决）。

## 规则

- **8 组 33 条**：完整性 A / 可度量性 B / 歧义自洽 C / 证据 D / 上线就绪 F / 决策归集 G / 调研决策就绪度 H，附体裁分流（PRD 按可验收性，调研按决策就绪度）。
- 两条检查线：**机械/候选**（A5 占位、C7 和/或命中即结论；B1/C3/C6/G1 只给候选，须结合上下文确认；C2 列数字行供交叉核对）+ **语义判断**（其余 26 条，多为枚举完整性类，不主动过一遍就必然漏）。
- **规则唯一事实源是 `references/rules.md`**。`references/rules.json` 是它的机器可读生成物（含每条规则的严重度、适用体裁、「该问什么」），由 `scripts/build_rules.py` 生成，改完 rules.md 要重跑，回归会校验两者同步。

## 误报怎么处理

不要"报个 ID 就全局退役"——一个人的误报不该让所有用户丢一条规则。用项目级 `.spec-lint.json`（模板见 `references/config-example.json`）：

```json
{
  "genre": "prd",
  "rules": { "C6": "nit", "F4": "off" },
  "waivers": [
    { "fingerprint": "B1:e1c977c7e3",
      "reason": "该指标在附录 B 已给出基线与目标值",
      "owner": "allan",
      "expires": "2026-12-31" }
  ]
}
```

- `rules`：按规则 ID 覆盖严重度或关闭，只影响本项目；
- `waivers`：单条豁免，**必须写理由、责任人和有效期**，过期自动失效并提示；
- 豁免按 `fingerprint` 匹配，所以文档编辑导致行号变化不会让豁免失效。

## 自进化

每份报告末尾征求裁决（误报 / 漏报 / 级别），写入 `references/calibration.jsonl`（机器可读，一行一条）与 `references/calibration.md`（叙述性教训）。规则改动跑 `scripts/selftest.py` 回归、经确认后才发版。

规则体检按早就写好、但以前没人真的在算的生命周期阈值自动判定：

| 信号 | 阈值 | 含义 |
|---|---|---|
| 可升 blocker | 命中 ≥3 份不同文档 | 规则被反复证实有效 |
| 降级候选 | **未修的**连续误报 ≥2 次 | 规则在伤人 |
| 重构候选 | 同一规则累计修复 ≥3 次 | 排除表在膨胀，该重写规则体而不是继续堆补丁 |
| 待删除评审 | ≥10 份文档零命中 | 只增不减是衰败信号 |

注意区分「误报」和「已修」：一条误报后面写着"已生效 vX"就是修好了，不该算失职——那是排除表又加了一条。

## 内部工具（可选）

`scripts/` 是给 agent 用的加速器和给维护者用的工具，**不是用户入口**。有 shell + python3 时，agent 可以用它们把机械层做确定：

| 命令 | 用途 |
|---|---|
| `spec_lint.py scan <文档> --genre prd --out findings.json` | 出表（机械+候选，含指纹与「该问什么」）；`--semantic` 合并模型判断并强制核对证据 |
| `spec_lint.py questions --genre prd [--json]` | 印开工前必答清单 |
| `spec_lint.py round --prev A --current B` | 复评两轮差异 |
| `spec_lint.py stats` | 规则体检 |
| `build_rules.py` / `selftest.py` | 生成规则表 / 回归测试 |

## 与 spec-kit / OpenSpec 的关系

串联，不冲突：spec-kit / OpenSpec 是"写 spec → plan → tasks → 代码"的开发流水线；spec-lint 是不依附任何流水线的独立质量门禁。

### 接入 OpenSpec 流水线（把 spec-lint 设为提案门禁）

OpenSpec v1.6+ 通过 `openspec instructions <artifact> --change <name>` 向模型注入每条 artifact 的规则。把 spec-lint 门禁写进 `openspec/config.yaml` 的 `rules:`，模型在 propose 阶段就必须先过门禁：

```yaml
rules:
  proposal:
    - "质量门禁：proposal 生成后必须用本机已安装的 spec-lint 技能评审，按 PRD 可验收性标准。产出 findings 表并给出门禁判定；无未解决 blocker（或全部被作者显式驳回并记录）才允许生成 tasks / 进入实施。"
  design:
    - "质量门禁：design 生成后必须用本机已安装的 spec-lint 技能评审，按工程规格可验收性标准。无未解决 blocker 才允许进入实施。"
```

已实测：`openspec instructions proposal --change <name> --json` 的 `rules` 字段会携带上述门禁文本，作为模型的硬约束。

## 仓库结构

```
spec-lint/
├── SKILL.md                    # 技能入口（agent 读这个就能干活）：铁律、输出契约、流程、四个模式
├── references/
│   ├── rules.md                # 规则库（唯一事实源，人写）
│   ├── rules.json              # 规则表（生成物，机器读）
│   ├── calibration.md          # 校准日志与规则生命周期（叙述）
│   ├── calibration.jsonl       # 裁决账（机器可读）
│   ├── config-example.json     # 项目配置模板（规则开关 + 豁免）
│   └── report-format.md        # 报告格式（报告是表的人读视图）
├── scripts/                    # 内部工具（可选加速器 + 维护者工具）
│   ├── check_mechanical.py     # 确定性机械检查（输出带行号 JSON）
│   ├── build_rules.py          # rules.md → rules.json
│   ├── spec_lint.py            # scan / questions / round / stats
│   └── selftest.py             # 回归测试（语料 + 工具链）
└── tests/
```

## 许可

MIT
