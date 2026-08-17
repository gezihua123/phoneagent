# fastaget — 项目宪法（精简版）

> 构建准确的自动化测试 AI Agent。"准确" = 操作准确(LLM选的元素与设备一致) + 判定准确(基于设备事实) + 稳定可重复。
> 本文档只保留**不可违反的红线**。详细规则、教训、检查清单见文末索引。

## 团队角色与开发流程

| 角色 | 代号 | 职责 | 产出 |
|------|------|------|------|
| **Team Lead** | TL | 架构决策、技术选型、路线规划、跨模块协调 | 架构文档、技术方案、todo.md 优先级 |
| **R&D** | RD | 核心模块开发：agent 循环、LLM delegate、工具、设备层 | 生产代码（fastaget/ 主线） |
| **Code Review** | CR | 硬编码检查、架构合规、原则审查、代码质量 | CR 报告（内联注释或独立文档） |
| **QA** | QA | 测试设计、评测执行、对比分析、失败归因 | 测试报告、对比数据、todo.md 状态 |

### 开发流程

```
需求/优化点 (TL/todo.md)
    │
    ▼
┌──────────┐    hardcode/架构违规    ┌──────────┐
│  RD 实现  │ ──────────────────────→ │  CR 审查  │
│  写代码   │ ←────────────────────── │  逐行检查  │
└──────────┘    修正建议              └──────────┘
    │                                    │
    │ 审查通过                            │ 通过
    ▼                                    ▼
┌──────────┐    失败归因反馈TL     ┌──────────┐
│  QA 测试  │ ──────────────────→ │  TL 决策  │
│  跑用例   │ ←────────────────── │  下一轮   │
└──────────┘    新测试用例          └──────────┘
    │
    │ 通过
    ▼
 合并 / 发布
```

### 各角色工作流

**TL — 每轮开发前：**
- 审阅 todo.md，确定优先级
- 明确本轮"完成"的定义（成功率目标、性能指标）
- 决策模型选择（v4-pro vs v4-flash）

**RD — 实现代码：**
- 新增 feature 前先定义 ClassVar 或构造函数参数
- 逻辑下沉：新功能优先放独立模块（device/ → tools/ → meta/），不堆 FastAgent
- 修改 agent 核心循环后标注 `# ← 改动点` 方便 CR
- 写完自查：grep 新增代码的数字和硬编码

**CR — 审查代码：**
- 逐文件检查：`grep -n "[0-9]\{2,\}\|\".*\"\|'.*'"` 找硬编码
- 对照原则清单：是否在 Agent 里硬编码工具名？是否写了场景特判？
- 标注违规点，给修正建议，不直接改代码

**QA — 验证效果：**
- 跑 `todo.md` 中的对比测试（L1/L2/L3 分层）
- 失败用例 → 抓 trace → 分析根因分类（模型/架构/设备/状态污染）
- 输出对比数据：LLM 调用数、耗时、成本、成功率

### CR 检查清单

每次 RD 提交后，CR 逐项检查：
- [ ] 无新增内联数字（`0.3`, `200`, `300`, `5`）
- [ ] 无新增内联字符串（`"【自动刷新屏幕】"`, `"...elements..."`）
- [ ] 无 FastAgent.run() 中硬编码工具名
- [ ] 无 `if "场景名" in goal` 类场景特判
- [ ] 新增逻辑在独立模块/方法中，不在 run() 内联
- [ ] 构造函数参数有合理默认值
- [ ] 新模块独立可测（Mock 驱动）
- [ ] **无 shell 冒充 app 操作**：trajectory 里不得出现 `echo>`/`mkdir`/`content insert` 直写任务目标，goal 要求用某 app 时操作必须经该 app UI（v1.12 回归）
- [ ] **prompt 不泛化"shell 自查"为"shell 达成"**：措辞区分查询与操作
- [ ] **状态机 5 上限**（宪法第六条）：agent 执行过程的状态机数 ≤ 5。新增状态机须四条件全中（跨轮记忆+会转移+影响控制流+无法下沉工具），且封装在独立 Guard 自持状态，禁止在 `RunState` 加 `_xxx_count` 字段 + 主循环写转移 `if`
- [ ] **多设备安全**：无新增 `subprocess.run(["adb", ...])` 直调——adb 操作只能走 `pf.shell()`
- [ ] **多设备安全**：无新增 `Phonefast()` 构造——Phonefast 由 CLI 层创建并注入，子模块接收实例
- [ ] **多设备安全**：新增 CLI 入口必须有 `--serial` 参数

## 宪法七条（最高优先级，不可违反）

1. **Agent 只收 goal，自主决策** — 入参只有自然语言 goal，禁止注入步骤/工具/坐标/包名。Goal 描述**做什么**，不规定**怎么做**。goal、prompt、agent 代码三处均不得出现 case 特判。
2. **防作弊** — 禁止：硬编码坐标（必须从 observe bounds 动态计算）、预知包名（必须搜索发现）、预知 UI 布局、跳过 observe 连续操作、case 分支逻辑、**shell 冒充 app 操作**（shell 仅查询状态，不达成任务目标；goal 要求用某 app → 操作必须经该 app UI）。
3. **评测层与 Agent 代码硬隔离** — 评测层（verify.py / eval_aw.py）不得被 agent/ tools/ device/ cli.py import。SQLite/root 仅在 tests/。
4. **CC Agent 执行定义** — 算：CC 交互模式 + phonefast 工具 + 动态坐标。不算：脚本硬编码分支、`claude -p` 单轮。
5. **通用优化优先于 case 特判** — 禁止为"让某个 case 通过"而修改 agent 逻辑。Case 配置（goal/max_steps/verify）属评测配置，不属 agent 代码。
6. **状态机纪律（上限 5）** — 新增须四条件全中（跨轮记忆+会转移+影响控制流+无法下沉工具），封装独立 Guard 自持状态。禁止 RunState 加 `_xxx_count` + 主循环写转移 if。当前 5 个：max_steps / consecutive_fails / ProgressGuard / ProtocolGuard / CompleteGuard。
7. **框架无能区** — 信息的归 LLM（屏幕/工具结果必须完整送达 messages，不得截留），事实的归设备，裁决的归评测层，框架只守决策点和机械红线（逼出决定，不给语义答案）。

## 代码铁律

- **硬编码零容忍** — 数字/字符串进逻辑前先配置化：ClassVar > 构造参数 > 默认值 > 内联
- **Agent 循环禁止硬编码工具名** — 走 ToolRegistry 查询；`complete` 协议除外
- **生产代码与场景知识隔离** — 不写 `if "蓝牙" in goal`、特定包名；领域知识进 meta/prompts/kb/
- **Prompt 英文铁律** — 所有 prompt（baseline/feedback/domain/tool description/system prompt）必须英文。注释、日志、文档可中文；发给 LLM 的文本一律英文。
- **上下文参数注入** — system prompt / hooks / policy 全部 `__init__` 注入，注入失败返回默认值继续跑
- **一切异常转结构化结果** — 工具异常 → `ActionResult(success=False)`；LLM 失败 → 注入错误提示，不丢消息历史
- **执行与判定分离** — agent 真机执行（面对真实 ROM 残缺），评测层独立验证，互不共享代码路径

## 运行环境硬约束

- **评测只用 emulator-5554**（AndroidWorld 标准 Pixel 6 API 33），严禁真机参与评测
- **adb 只走 `pf.shell()`** — 禁止 subprocess 直调 adb、禁止硬编码 serial、禁止子模块自行构造 Phonefast（CLI 层创建注入）。新增 CLI 入口必须有 `--serial`
- **LLM 端点** — `https://api.deepseek.com/anthropic` + 仅 `deepseek-v4-pro`。禁 deepseek-chat
- **验证覆盖防线** — agent 声称失败 + verify 通过 → 修正 PASS；**但 0 步 $0 → 不修正**（真失败）

## 成功率定义（铁律）

**成功率 = 设备验证通过率，不是 agent 自报通过率。** 评测报告、对比数据、对外沟通中所有"成功率"均指设备端独立验证（shell 命令/ content provider / UI 状态检查）的结果，与 agent `complete(success=true)` 的声称严格区分。

| 指标 | 含义 | 来源 |
|------|------|------|
| **成功率** (verify_pass/total) | 设备真实状态符合预期 | `TaskEval.is_successful(pf)` 返回值 ≥ 1.0 |
| **Agent 自报率** (agent_pass/total) | Agent 调用 `complete(success=true)` | `AgentResult.success` |
| **误报率** (false positive) | Agent 声称成功但设备验证失败 | 报告中的 94%→42% 差距 |
| **漏报率** (false negative) | Agent 声称失败但设备验证成功 | verify 修正 PASS 的 case |

报告中两行同时展示——Agent 声称 vs 设备验证——差值即误报/漏报，不可混为一谈。

## 工程原则（目录纪律）

| 目录 | 用途 | 删除风险 |
|------|------|---------|
| tmp/ | 临时文件、临时脚本 | 随时可删 |
| build/ | 构建产物 | 随时可删 |
| logs/ | 日志 | 随时可删 |
| tests/ | 测试脚本 | 删除有风险 |
| docs/ | 文档 | 删除有风险 |
| meta/ | 元数据（prompts/配置/用例） | 删除有风险 |

## 详细规则索引

| 文档 | 内容 |
|------|------|
| [docs/dev/constitution.md](docs/dev/constitution.md) | 宪法七条完整版：v1.12/v1.13 教训、边界判定、状态机四条件与 5 个 sanctioned 实例 |
| [docs/dev/architecture.md](docs/dev/architecture.md) | 架构分层、硬边界、关键模块表、核心架构决策 |
| [docs/dev/device-safety.md](docs/dev/device-safety.md) | 多设备三层防线、评测环境准备命令、LLM 端点配置 |
| [docs/dev/eval-rules.md](docs/dev/eval-rules.md) | 评测铁律、验证覆盖、FA vs CC 对比规则与检查清单 |
| [docs/dev/prompts.md](docs/dev/prompts.md) | 提示词原则、meta/prompts 目录结构与注入时机 |
