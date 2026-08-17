# 宪法七条 — 完整版

> 根 CLAUDE.md 是压缩红线；本文档保留全部教训、边界判定与实例清单。

## 第一条：Agent 只收 goal，自主决策

Agent 入参只有自然语言 goal。禁止向 agent 注入执行步骤、工具选择、坐标、包名。
Goal 描述**做什么**，不规定**怎么做**。Agent 通过 observe→分析→选 tool→执行→验证 闭环自主推进，
自主判断何时 complete。评测 case 的 goal、prompt、agent 代码三处均不得出现 case 特判。

**fastaget 与 Claude Code 共同遵守**：对比评测时，双方同输入(只给 goal)、同工具(phonefast)、同验证(verify rules)。

## 第二条：防作弊——评测数据作废条件

以下行为导致对比数据无效：
- 硬编码坐标（`tap 540 1959`）→ 必须从 observe 元素 bounds 动态计算 (left+right)/2, (top+bottom)/2
- 预知包名（`launch com.google.android.deskclock`）→ 必须 shell(pm list packages | grep) 搜索
- 预知 UI 布局（假设 tab 顺序）→ 必须 observe 后从 UI 树中定位
- 跳过 observe 连续操作 → 每次操作后必须 observe 确认
- 在 agent 代码或 prompt 中为特定 case 写分支逻辑
- **shell 冒充 app 操作**（v1.12 发现的回归）：用 shell 直接创建/修改任务目标来冒充 app 操作。
  禁止：`echo '...' > file` 冒充"用 Markor 创建笔记"、`mkdir` 冒充"在 app 里建文件夹"、
  `content insert` 冒充"用 app 录入数据"。shell 仅用于**查询状态**（`settings get`/`ls`/
  `content query`/`dumpsys`），不得用于**达成任务目标**本身。任务要求用某 app 操作时，
  必须通过该 app 的 UI 完成（launch→observe→tap/type→observe 确认）。
  判定：goal 含"用 X app 创建/编辑/删除" → agent 的操作序列必须经 X app UI，不得用 shell 直写。
  例外：goal 明确要求 shell 操作（"用 shell 关闭 wifi"）或系统设置类（亮度/飞行模式）。

**"shell 自查"引导的边界**（防误报，v1.12 教训）：
- 允许：agent 用 shell 查询设备事实作为 assert 依据（`settings get`/`ls`/`content query`）
- 禁止：prompt 引导"用 shell 自查"泛化成"用 shell 达成"——前者是验证手段，后者是作弊捷径
- prompt 措辞必须区分"查询"与"操作"：shell 是查询工具，不是任务执行工具

## 第三条：评测层与 Agent 代码硬隔离

评测层（`verify.py`、`sqlite_verify.py`、`eval_aw.py`）不得被 agent 代码路径 import。
Agent 代码路径（`agent/`、`tools/`、`device/`、`cli.py`）零 SQLite/root 引用。
SQLite/root 仅存在于 `tests/sqlite_verify.py` 测试文件中。

## 第四条：Claude Code Agent 执行定义

以下方式**算** CC Agent 执行：
- CC 交互模式（当前会话）：给 goal，CC 用 phonefast 工具 observe→决策→执行→验证
- 每步从 observe 输出中动态解析元素 bounds 计算坐标，零硬编码

以下方式**不算** CC Agent 执行：
- Bash/Python 脚本用 `if "wifi" then svc wifi disable` 等硬编码分支替代 CC 决策
- 脚本预判 case 类型并写死执行步骤
- `claude -p` 单轮模式（不支持多轮 tool calling）

## 第五条：通用优化优先于 case 特判

Agent 代码改进必须通用：改进停滞检测、shell 容错、prompt 模式。
禁止为"让某个 case 通过"而修改 agent 逻辑。
Case 配置（goal/max_steps/initialize/verify）属于评测配置，不属于 agent 代码。

## 第六条：状态机纪律（5 个上限，需才可加）

Agent 执行过程中的**状态机总数硬上限 = 5**。状态机可以存在，但必须：
1. **分散到各自 owner**——每个状态机封装在独立 Guard 组件里自持状态，
   不集中在 `FastAgent` 主循环或 `RunState` 字段中
2. **不严格写死**——阈值是构造函数参数（有默认值），Guard 实例可整体
   注入替换或传 NullGuard 禁用；工具名集合从 registry 注入，不内联字符串
3. **需才可加**——新增状态机必须同时满足四个条件，缺一不可：
   - **跨轮记忆**：信息必须跨 LLM 调用保留，且**无法从消息历史派生**
     （能派生的就是缓存，不是状态机——直接写查询函数，不存字段）
   - **状态会转移**：有明确的"前一状态→后一状态"转移逻辑（纯缓存不算）
   - **影响控制流**：状态值改变终止/继续/反馈决策
   - **无法下沉工具**：不是工具执行副作用（副作用走 Effect-as-Data）

**当前 5 个 sanctioned 状态机（不得新增第 6 个，除非四条件全中且经 CR）：**
1. `max_steps` 循环边界（`FastAgent.run`）— while 循环必须有界，是循环契约
2. `consecutive_fails`（`RunState`）— LLM 网络间歇失败计数，触发自愈反馈
3. `ProgressGuard`（`tools/progress.py`）— 停滞/退化/连败，自持指纹窗口+计数
4. `ProtocolGuard`（`agent/guards.py`）— complete 协议催促，自持 nudge 计数
5. `CompleteGuard`（`tools/guards.py`）— complete 覆盖+assert 回退（无状态策略，
   但作为终局判定 Guard 计入配额，统一在 Guard 体系内管理）

> 反模式（禁止）：在 `RunState` 加 `_xxx_count` 字段 + 在 agent 主循环写
> `if state._xxx_count > N` 转移逻辑——这就是"集中在 agent、写死"。
> 正确做法：写一个 Guard 类自持该计数，agent 只调 `guard.check()`。

## 第七条：框架无能区——判断力的边界划分

框架设计的核心不是"让框架更聪明"，而是清醒地划定框架的无能区——
**信息的归 LLM，事实的归设备，裁决的归评测层，框架只守决策点和机械红线。**

- **信息的归 LLM**：屏幕/工具结果必须完整送达 messages，框架不得截留。
  观察数据只同步指纹不进消息 = LLM 瞎了挣扎（v1.13 确认死循环根因：
  observation_data 有数据但 LLM 只收到元素计数摘要，反复 observe 试图看到屏幕）。
- **事实的归设备**：任务是否达成以设备状态为准（observe/shell/verify），
  不以 LLM 声称或框架假设为准。
- **裁决的归评测层**：最终 PASS/FAIL 由 verify 层独立判定，agent 不知晓、不参与。
- **框架只守决策点和机械红线**：机械条件（屏幕 N 轮不变/步数/连败）只用于
  **逼出决定**（complete 或换方法二选一），不得用于给出语义答案。

> 推论 1：压力机制的前提是信息已送达——信息断供时，催促只会转化为循环。
> 推论 2：机械信号的正确形态 = 收缩可选动作空间（"禁止继续观察，二选一"），
> 不是提供语义结论（"你可能已完成"——加载中/卡死/已达成屏幕都稳定，框架无法区分）。
> 推论 3：LLM 行为异常先查信息供给链，再查反馈机制，最后才归因模型。
