# fastaget 融合架构设计：mobilerun × AutoGLM × opencode

> 本文档基于 `ARCHITECTURE_ANALYSIS.md` 的参照分析，进一步将 mobilerun、AutoGLM、opencode 三者的优点与 fastaget 当前功能做平衡融合，形成整体架构图与设计决策记录。

---

## 一、设计目标：fastaget 要解决什么

fastaget 的核心定位是**「快速、自愈的 Android 测试 Agent」**，一句话概括其设计目标：

> 让 LLM 通过原生 tool-calling 操控本地真机，以**确定性优先 + 分层兜底**的方式，把自然语言测试目标转化为可验证的设备操作结果。

从代码里可以读出几个明确的子目标：

1. **快（fast）**——名字即宣言。`phonefast.py` 用 Unix Socket 直连 daemon 把单步设备交互从 ~80ms（subprocess）压到 ~10ms；`actions.py` 的 `tap_element` 不调 phonefast 内部 `tap_element`（会重新 observe，650ms），而是从 `UIState` 查坐标后直接 `tap(x,y)`，快 60 倍。`FlowRunner` 还通过 `_sync_ctx_from_agent` 复用 agent 已 observe 的屏幕状态，省掉每 node 一次重复 observe（~500ms/node）。
2. **稳（自愈）**——四层分层防御（`retry.py` 注释明确写了 L1-L4），不让单点故障炸断整个 agent 循环。
3. **可判定**——不只是「操作完」，还要「验证对」。`SemanticJudge` + `ExpectationEvaluator` 构成独立的判定层，与执行 LLM 隔离。
4. **可声明编排**——`FlowRunner` + YAML flow case 把测试流程从「一句 goal 全自主」细化为 precondition/flow/expect/teardown 四阶段 DAG，支持分支/循环/参数替换。

---

## 二、平衡决策：取什么、舍什么

| 来源 | 优点 | 决策 | 理由 |
|------|------|------|------|
| **mobilerun** | 编号枢纽（index→坐标） | ✅ 已落地，保留 | 降坐标幻觉，快60倍 |
| **mobilerun** | 五层分层自愈 | ✅ 已重组为四层，保留 | 测试场景去掉格式校验层 |
| **mobilerun** | ToolRegistry + deps 能力声明 | 🔶 已有 Registry，**补 deps 自适应** | 跨平台/跨模式时自动裁剪工具集 |
| **mobilerun** | Manager+Executor Reasoning 双层 | 🔶 **补为可选模式** | 复杂多步场景需要规划层，快任务仍用 Direct |
| **mobilerun** | Trajectory 复盘（json/gif/截图） | ➕ **新增** | 测试场景必须可回溯可复盘 |
| **mobilerun** | 视觉坐标契约（displayBounds+scale） | ➕ **新增 VisionState** | 视觉模式需要坐标空间解耦 |
| **mobilerun** | Portal App / Stealth / PostHog | ❌ 舍弃 | 已用 phonefast 替代；测试要可重复 |
| **AutoGLM** | 纯视觉 + 相对坐标(0-999) | 🔶 **补为辅模式** | a11y 文本为主，视觉兜底无 a11y 场景 |
| **AutoGLM** | DeviceFactory 多平台抽象 | ➕ **新增执行层工厂** | 为 iOS/HarmonyOS 扩展留路，phonefast 为默认 |
| **AutoGLM** | Take_over 人机协作 | ➕ **新增 takeover 工具** | 测试遇登录/验证码时接管或跳过 |
| **AutoGLM** | 流式 + thinking/action 分离 | ❌ 舍弃 | 原生 tool-calling 已结构化，无需流式解析 |
| **AutoGLM** | 自由文本 do() 协议 | ❌ 舍弃 | 解析脆弱，tool-calling 更稳 |
| **AutoGLM** | 18条 prompt 领域规则 | 🔶 **提炼补入 prompt** | 取「加载等待/滑动查找/返回策略」等通用规则 |
| **opencode** | Route provider 抽象 | ➕ **新增模型层 Route** | 接 OpenAI 兼容端点 + 视觉模型 + 自定义模型 |
| **opencode** | 工具输出边界 bound | ➕ **新增** | 控制 LLM 上下文膨胀 |
| **opencode** | generateObject 结构化输出 | ➕ **新增** | 测试断言的结构化判定 |
| **opencode** | Effect 运行时 / durable clustering | ❌ 舍弃 | 过重，原生 async/await 够用 |

**平衡核心理念**：fastaget 仍是「结构化文本优先、编号枢纽优先、代码护栏优先、设备事实优先」，但在三个维度做扩展——**感知双模**（a11y 主 + 视觉辅）、**执行多平台**（phonefast 默认 + 工厂扩展）、**模型可插拔**（Route 抽象）。

---

## 三、融合后的整体架构图

```
╔═══════════════════════════════════════════════════════════════════════╗
║                         fastaget 整体架构                             ║
║         (mobilerun 自愈范式 × AutoGLM 多模多平台 × fastaget 确定性)   ║
╚═══════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────┐
│ ① 入口层  CLI                                                        │
│   devices │ observe │ run │ flow │ doctor │ ➕replay │ ➕vision      │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│ ② 编排层  FlowRunner                                                 │
│                                                                      │
│   Phase1: Precondition ──→ Phase2: Flow DAG ──→ Phase3: Expect ──→ Phase4: Teardown
│   (不满足则SKIP)            (遍历+loop+branch)   (rule/semantic/hybrid)  (无论成败)
│                                                                      │
│   node mode: guided(单步) │ autonomous(多步) │ wait(轮询不调LLM)     │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│ ③ 智能层  FastAgent                                                  │
│                                                                      │
│   ┌──────────────────┐        ┌──────────────────┐                   │
│   │  Direct (默认)    │        │  Reasoning (可选) │                   │
│   │  原生 tool-call   │        │  Manager+Executor │                   │
│   │  ReAct 单循环     │        │  Plan+Subgoal     │                   │
│   │  快任务           │        │  复杂多步场景      │                   │
│   └────────┬─────────┘        └────────┬─────────┘                   │
│            └──────────┬────────────────┘                             │
│                       │                                              │
│            ┌──────────▼───────────┐  首步 auto-observe               │
│            │   ➕ 双模感知路由     │  messages 持续累积+prompt cache  │
│            │                       │                                  │
│            │  a11y文本(主)         │  视觉截图(辅)                    │
│            │  UIProcessor格式化    │  ➕VisionState相对坐标契约       │
│            │  → index 编号枢纽     │  → 0-999归一化坐标               │
│            └──────────┬───────────┘                                  │
└───────────────────────┼─────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────────┐
│ ④ 判定层  (执行/判定隔离 — 独立 LLM 实例)                            │
│                                                                      │
│   SemanticJudge ──→ {satisfied, confidence, evidence, reasoning}     │
│        │                                                             │
│   ExpectationEvaluator: rule(0ms) → semantic(LLM) → hybrid(规则先行) │
│        │                  + wait 轮询(每秒observe重判)               │
│   ConditionEvaluator:   {screen.} → {device.} → {step.}/{var.} → {llm.judge} │
│                          规则        设备事实    上下文       语义    │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────────┐
│ ⑤ 工具层  ToolRegistry + ActionContext                               │
│                                                                      │
│   ┌─ deps 能力声明 ──→ disable_unsupported(跨平台/跨模式自动裁剪) ─┐ │
│   │                                                               │ │
│   │  observe │ tap │ tap_element │ swipe │ type │ wait           │ │
│   │  back │ home │ key │ launch │ assert │ complete              │ │
│   │  check_package │ current_app │ ➕takeover                    │ │
│   │                                                               │ │
│   │  ActionContext: 每步刷新 ui (抽取⇄操作枢纽)                  │ │
│   │  ➕ 输出边界 bound: 超限落盘只留 preview+路径                 │ │
│   └───────────────────────────────────────────────────────────────┘ │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────────┐
│ ⑥ 状态层                                                             │
│                                                                      │
│   UIState (纯数据)          │  ➕ VisionState (新)                  │
│   · parse → Element[]       │  · 相对坐标 0-999 ↔ 原生像素          │
│   · get_coords(index)       │  · coordinate_scale 反缩放            │
│     ↑ 编号枢纽              │  · displayBounds(模型空间)            │
│                              │                                       │
│   UIProcessor (加工)         │  视觉坐标契约:                        │
│   · 三层清洗: 几何→可见→语义 │  截图缩放与 tap 精度解耦             │
│   · 空间分区: 顶/中/底+缩进  │                                       │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────────┐
│ ⑦ 执行层  ➕ DeviceFactory (借鉴 AutoGLM, phonefast 为默认)          │
│                                                                      │
│   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐       │
│   │ phonefast │  │ ➕ ADB    │  │ ➕ HDC    │  │ ➕ iOS    │       │
│   │ (默认,快) │  │  Direct   │  │ HarmonyOS │  │ XCUITest  │       │
│   │ <10ms     │  │           │  │           │  │           │       │
│   │ daemon    │  │           │  │           │  │           │       │
│   └───────────┘  └───────────┘  └───────────┘  └───────────┘       │
│                                                                      │
│   设备级事实通道 (ground truth, 不依赖屏幕文本):                     │
│   shell() │ is_package_installed() │ current_activity()              │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────────┐
│ ⑧ 模型层  ➕ Route Provider (借鉴 opencode)                          │
│                                                                      │
│   ┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│   │ Anthropic    │  │ ➕ OpenAI-Compat │  │ ➕ Vision Route   │      │
│   │ HTTP Delegate│  │  Route           │  │  (autoglm/Gemini)│      │
│   │ (已有)       │  │  (任意兼容端点)  │  │  (多模态)        │      │
│   └──────────────┘  └──────────────────┘  └──────────────────┘      │
│                                                                      │
│   prompt caching (system 稳定前缀)                                   │
│   ➕ generateObject (强制 tool call 取结构化输出, 跨协议一致)        │
│   ➕ catalog + 解析分离 (运行时切模型不改 turn)                      │
└─────────────────────────────────────────────────────────────────────┘

╔═══════════════════════════════════════════════════════════════════════╗
║  横切关注点                                                           ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║  ┌─ 自愈层 (四层分层防御) ──────────────────────────────────────┐    ║
║  │ L1 设备I/O:  with_retry + _recover_device(daemon重启+observe)│    ║
║  │ L2 工具执行:  异常 → ActionResult(success=False), LLM 自愈   │    ║
║  │ L3 模型调用:  线性退避 + should_retry 跳过确定性崩溃          │    ║
║  │ L4 测试编排:  连续失败 → 注入"换思路" → ➕错误升级重规划     │    ║
║  └──────────────────────────────────────────────────────────────┘    ║
║                                                                       ║
║  ┌─ ➕ Trajectory 复盘 ─┐  ┌─ ➕ Takeover 人机协作 ──────────┐     ║
║  │ json + 截图 + ui_states│  │ 登录/验证码: 人工接管 or 跳过   │     ║
║  │ 异步落盘, 支持 replay  │  │ 多选项: Interact 询问用户       │     ║
║  └────────────────────────┘  └────────────────────────────────┘     ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

## 四、关键数据流（一次 flow run 的完整链路）

```
用户: fastaget flow run -f case.yaml
  │
  ▼
FlowRunner.run(case)
  │
  ├─ Phase1: Precondition
  │    └─ ConditionEvaluator.eval("{device.pkg_installed:com.xxx}")
  │         └─ Phonefast.is_package_installed() ──→ pm list packages (ground truth)
  │              └─ 不满足 → SKIP（不是 FAIL）
  │
  ├─ Phase2: Flow DAG 遍历
  │    │
  │    │  ┌──────────────────────────────────────────────────┐
  │    └─▶ FastAgent.run(node.goal)                           │
  │         │                                                 │
  │         │  ① 首步 auto-observe                            │
  │         │     Phonefast.observe()                         │
  │         │       → raw_text                                │
  │         │       → UIProcessor.process()                   │
  │         │           → UIState.parse() (编号枢纽)          │
  │         │           → filter() 三层清洗                    │
  │         │           → format() 空间分区                    │
  │         │       → (辅) screenshot base64                  │
  │         │     ActionContext.refresh(ui)                   │
  │         │                                                 │
  │         │  ② ReAct 循环 (max_steps)                       │
  │         │     ┌──────────────────────────────────┐        │
  │         │     │ LLMDelegate.complete(            │        │
  │         │     │   system, messages, tools)       │        │
  │         │     │   → Route → Anthropic/OpenAI/    │        │
  │         │     │     Vision (prompt cache 命中)   │        │
  │         │     │   ← tool_calls[]                 │        │
  │         │     └──────────────┬───────────────────┘        │
  │         │                    │                            │
  │         │     for tc in tool_calls:                       │
  │         │       ToolRegistry.execute(tc.name, tc.input)   │
  │         │         └─ actions.tap_element(index=5)         │
  │         │              └─ UIState.get_coords(5) ← 编号枢纽│
  │         │              └─ Phonefast.tap(x, y)  ← <10ms    │
  │         │              └─ (失败) with_retry + _recover    │
  │         │              └─ (index过时) auto observe 重选    │
  │         │         → ActionResult(ok/fail)                 │
  │         │         → (新) 输出边界 bound                   │
  │         │       messages.append(tool_result)              │
  │         │       complete? → break                         │
  │         │     L3自愈: LLM失败 → 退避重试 / 注入错误        │
  │         │     L4自愈: 连续3步失败 → 注入"换思路"          │
  │         └──────────────────────────────────────────────────┘
  │
  │    ┌─ 分支决策 ─────────────────────────────────────┐
  │    │ ConditionEvaluator.eval_branches(branches)     │
  │    │   {screen.has_text:成功} → rule(0ms) 命中?     │
  │    │   {device.activity:com.xxx} → 设备事实         │
  │    │   {step.install.success} → 上下文               │
  │    │   {llm.judge:安装完成} → 语义兜底               │
  │    │   default → 兜底跳转                            │
  │    └─────────────────────────────────────────────────┘
  │
  ├─ Phase3: Expect (用例级)
  │    └─ ExpectationEvaluator.check_all(case.expect)
  │         └─ rule: {screen.has_text:已安装} (0ms)
  │         └─ device: {device.pkg_installed:com.xxx} (ground truth)
  │         └─ semantic: SemanticJudge.judge() (独立LLM, 不喂执行历史)
  │              └─ {satisfied, confidence, evidence}
  │         └─ hybrid: 规则先行, 不过则语义兜底
  │         └─ +wait: 每秒 observe 重判, 最多 N 秒
  │
  ├─ Phase4: Teardown (无论成败)
  │    └─ FlowRunner._execute_node(teardown_node)
  │
  └─ → FlowResult (success, path, branches_hit, expect_records, cost)
       │
       ├─ (新) Trajectory 异步落盘: json + 截图 + ui_states
       └─ FlowSuiteReport → flow_report.txt + flow_report.json
```

---

## 五、平衡后的三层扩展说明

### 5.1 感知层：a11y 主 + 视觉辅的双模路由

```
              ┌──────────────────┐
              │  感知路由 (新)    │
              │  vision=False/True│
              └────┬────────┬────┘
                   │        │
          a11y 文本(主)    视觉截图(辅)
                   │        │
         ┌─────────▼──┐  ┌──▼──────────┐
         │ UIProcessor │  │ VisionState  │
         │ → index枢纽 │  │ → 0-999坐标  │
         │ → 三层清洗  │  │ → scale反缩放│
         │ → 空间分区  │  │ → 多模态模型 │
         └─────────────┘  └──────────────┘
```

- **默认 a11y 文本**：编号枢纽，结构化，不依赖多模态模型，快且准
- **视觉兜底**：a11y 树缺失（游戏/Canvas/Flutter）、或视觉信息更丰富时（图标识别）切换
- 借鉴 AutoGLM 相对坐标(0-999)协议 + mobilerun 视觉坐标契约（displayBounds + coordinate_scale）

### 5.2 执行层：DeviceFactory 多平台

```
              ┌──────────────────┐
              │ DeviceFactory(新)│
              │  supported 能力集 │
              └────┬─────────────┘
                   │
    ┌──────────┬───┴───┬──────────┬──────────┐
    ▼          ▼       ▼          ▼          ▼
 phonefast   ADB     HDC       iOS       (扩展)
 (默认,快)  Direct  HarmonyOS  XCUITest
 <10ms
    │
    └─→ deps 能力声明 → disable_unsupported
         iOS 无 drag → 工具集自动裁剪
         phonefast 有 observe → 编号枢纽启用
```

- phonefast 仍为默认高性能执行器
- 借鉴 AutoGLM DeviceFactory 工厂模式为多平台留路
- mobilerun 的 `supported` + `deps` → `disable_unsupported` 自动裁剪工具集，跨平台零改 prompt

### 5.3 模型层：Route Provider 可插拔

```
              ┌──────────────────┐
              │  LLMDelegate     │
              │  (抽象接口)       │
              └────┬─────────────┘
                   │
    ┌──────────────┼──────────────────┐
    ▼              ▼                  ▼
 Anthropic    OpenAI-Compat       Vision Route
 HTTP Delegate  Route             (autoglm等)
 (已有)        (新)               (新)
    │              │                  │
    └─prompt cache └─baseURL+auth    └─多模态
                   └─generateObject
                      (强制tool call
                       取结构化输出)
```

- 借鉴 opencode `Route<Body,Prepared>` 封装端点+鉴权+传输
- `openai-compatible` route + baseURL + auth 即可接任意自定义端点
- `generateObject` 跨协议取结构化输出，用于测试断言
- catalog + 解析分离：运行时切模型不改 turn

---

## 六、当前实现的七层架构（现状对照）

fastaget 的代码已经落地了清晰的分层，与融合架构的目标高度吻合：

```
① 入口层    cli.py — devices/observe/run/flow/doctor 五子命令
② 编排层    flow/runner.py — FlowRunner 声明式 DAG（precondition→flow→expect→teardown）
            flow/case.py — FlowCase/FlowNode/LoopSpec/Branch YAML 数据模型
③ 智能层    agent/fast_agent.py — FastAgent 原生 tool-calling ReAct 循环
            （首步 auto-observe，messages 持续累积，prompt caching）
④ 判定层    flow/judge.py — SemanticJudge（独立 LLM，结构化 JSON 输出）
            flow/expectation.py — rule/semantic/hybrid 三档 + wait 轮询
            flow/condition.py — {screen.xxx}/{device.xxx}/{step.xxx}/{var.xxx}/{llm.judge} 条件语法
⑤ 工具层    tools/registry.py — ToolRegistry + ActionResult + JSON Schema 定义
            tools/actions.py — 14 个标准动作（observe/tap/tap_element/swipe/type/wait/back/home/key/launch/assert/check_package/current_app/complete）
            tools/context.py — ActionContext 每步刷新 ui 枢纽
⑥ 状态层    device/uistate.py — UIState 纯数据模型（parse + get_coords 编号枢纽）
            device/uiprocessor.py — UIProcessor 加工层（三层清洗 + 空间分区格式化）
⑦ 执行层    device/phonefast.py — phonefast daemon Unix Socket 客户端 + adb shell 设备级事实通道
            heal/retry.py — with_retry 线性退避 + is_max_turns_error/is_device_io_error/is_llm_error 故障分类
⑧ 模型层    llm/delegate.py — LLMDelegate 抽象 + LLMResponse/ToolCall
            llm/anthropic_http_delegate.py — httpx 直连 + prompt caching + 原生 tools
```

层间解耦的关键接口是 `ActionContext`（抽取链路 observe→UIState 与操作链路 tap→phonefast 的枢纽）和 `LLMDelegate`（智能层只依赖接口，实现可换）。

---

## 七、四个项目的角色定位

| 项目 | 关系 | 借鉴内容 |
|------|------|----------|
| **phonefast** | 硬依赖执行器 | fastaget 所有设备动作的实际执行层，Unix Socket daemon <10ms 触控 |
| **mobilerun** | 设计参照 | 编号枢纽、分层自愈、ToolRegistry+ActionContext、FastAgent(Direct) 范式 |
| **opencode** | 设计参照 | Route provider 抽象、admission/execution 分离思想、工具输出边界 |
| **AutoGLM** | 设计参照 | 视觉优先 + 相对坐标(0-999)协议、设备工厂多平台、接管(takeover)机制 |

### AutoGLM 带来的新视角

AutoGLM（Open-AutoGLM-main）与前三者有本质区别——它是一个**视觉优先的端到端 phone agent**，其设计取向与 fastaget 形成鲜明对比：

1. **感知方式：纯视觉 vs 结构化文本**
   - AutoGLM：每步截图喂多模态模型（`autoglm-phone-9b`），模型直接在图像空间输出 `element=[x,y]` 相对坐标（0-1000 归一化），用 `ast.parse` 解析 `do(action="Tap", element=[x,y])` 自由文本协议。`agent.py:205` 还会 `remove_images_from_message` 省上下文。
   - fastaget：`phonefast.observe()` 返回 a11y 文本 → `UIProcessor` 三层清洗 + 空间分区格式化 → 喂结构化文本，LLM 报 `index`，工具层查坐标。**编号枢纽降坐标幻觉**，且无视觉模型依赖。

2. **动作协议：自由文本 do() vs 原生 tool-calling**
   - AutoGLM：`<think>...</think><answer>do(action="Tap", element=[x,y])</answer>`，用 `parse_action` + `ast.literal_eval` 解析（`handler.py:332-388`），`Type` 动作还特殊处理。解析脆弱性高。
   - fastaget：原生 `tool_use` 结构化块，零正则解析失败。

3. **设备抽象：DeviceFactory 多平台 vs Phonefast 单执行器**
   - AutoGLM：`device_factory.py` 用工厂模式 + 全局单例支持 ADB/HDC/iOS/XCTest 四平台。
   - fastaget：只接 phonefast 一种执行器，但额外开了 `shell()`/`is_package_installed()`/`current_activity()` 的 **adb 设备级事实通道**，从原理上规避「广告'打开'按钮被误判为已安装」的幻觉。

4. **人机协作：Take_over vs 无**
   - AutoGLM 有 `Take_over`（登录/验证码人工接管）和 `Interact`（多选项询问用户）两类人机交互动作，面向真实消费场景。
   - fastaget 面向测试，不需要人工接管，但 `complete(success=False)` 的无响应收尾策略是另一种形式的「不硬撑」。

5. **自愈深度：浅 vs 深**
   - AutoGLM 的自愈几乎全在 prompt 里（`prompts_zh.py` 18 条规则），代码层只有 `try/except` 兜底转 `finish`。
   - fastaget 有四层代码护栏 + `tap_element` 内置自动重试 + `available indices` 引导自愈。**「模型是大脑、代码是脊柱反射」** 在 fastaget 落地更彻底。

---

## 八、核心设计决策与取舍

### 8.1 已经落地的强借鉴

1. **编号枢纽机制**（mobilerun）：`UIState.get_coords(index)` + `tap_element` 直接 `tap(x,y)`，index 与 LLM 看到的元素列表完全对齐，降坐标幻觉且快 60 倍。
2. **分层自愈**（mobilerun 五层→fastaget 四层）：`with_retry` 线性退避 + `should_retry` 跳过确定性崩溃（max_turns）+ `_recover_device`（daemon 重启 + 重新 observe 校准，替代 mobilerun 的 Portal a11y 重启）。
3. **原生 tool-calling**（opencode 思想）：砍掉正则解析，`LLMResponse.tool_calls` 结构化，`stop_reason=="tool_use"` 驱动循环。
4. **执行/判定隔离**（mobilerun app_opener 分角色 + opencode 分离思想）：`SemanticJudge` 用独立 `LLMDelegate` 实例，不喂执行历史，只给「预期描述 + 当前屏幕」独立判断，输出 `satisfied/confidence/evidence` 结构化结果。
5. **设备级事实通道**（fastaget 原创）：`check_package`/`current_app`/`{device.pkg_installed}` 条件，从 `pm list packages`/`dumpsys` 取 ground truth，规避屏幕文本幻觉——这是 mobilerun 和 AutoGLM 都没有的。

### 8.2 简化借鉴

- **System Context / Context Epoch**（opencode）：未上 reconcile/replace 状态机，简化为「system prompt 加 `cache_control` 稳定前缀」（`anthropic_http_delegate.py:78-80`），多步用例越长 cache 收益越大。
- **admission/execution 分离**（opencode）：未上 durable clustering，fastaget 短任务可重跑。
- **Reasoning 双层**（mobilerun）：以 FastAgent(Direct) 为主，`FlowRunner` 的 `guided/autonomous/wait` 三模式已覆盖编排需求，未引入 Manager+Executor。

### 8.3 尚未落地（融合架构设想，代码未实现）

1. **Route provider 抽象**：当前只有 `AnthropicHTTPDelegate` 一个实现，没有 opencode 的 `Route<Body,Prepared>` 封装和 `openai-compatible` route。接自定义/OpenAI 兼容端点还需新建 delegate。
2. **工具输出边界**（opencode ToolOutputStore.bound）：`ActionResult.summary` 无长度上限，长 observe 结果可能膨胀 LLM 上下文。
3. **能力声明自适应**（mobilerun `deps`+`disable_unsupported`）：`ToolRegistry` 注释明确说「暂不启用（只接 phonefast 一种执行器）」。
4. **Trajectory 复盘**（mobilerun json/gif/截图）：`Step` 有 `cost_usd/elapsed` 但无异步 trajectory 落盘。
5. **DeviceFactory 多平台**：当前硬编码 phonefast，未抽象工厂。
6. **VisionState 视觉坐标契约**：`vision=True` 参数已预留但无独立 VisionState。
7. **takeover 工具**：无人机协作机制。

### 8.4 fastaget 相对参照项目的独有增量

- **FlowRunner 声明式编排**：mobilerun 和 AutoGLM 都是「一句 goal 全自主」，fastaget 的 `precondition→flow(DAG+loop+branch)→expect(rule/semantic/hybrid+wait)→teardown` 四阶段是测试场景特有的。
- **三级条件语法**：`{screen.has_text}`/`{device.pkg_installed}`/`{step.xxx.success}`/`{var.count>0}`/`{llm.judge:描述}` 统一了 branch.when 和 expect.check，规则→上下文→语义三级降级。
- **UIProcessor 三层清洗 + 空间分区**：独立设计，且 `UIState`（纯数据）与 `UIProcessor`（加工）职责分离。

---

## 九、设计哲学总结

fastaget 融合后的设计哲学可概括为 **「四个优先 + 三个扩展」**：

**四个优先（确定性基石，不变）**：
1. 结构化文本优先于视觉
2. 编号枢纽优先于裸坐标
3. 代码护栏优先于 prompt 规则
4. 设备事实优先于屏幕文本

**三个扩展（借鉴融合，新增）**：
1. **感知双模**：a11y 主 + 视觉辅（AutoGLM 视觉协议 + mobilerun 坐标契约）
2. **执行多平台**：phonefast 默认 + DeviceFactory 扩展（AutoGLM 工厂模式 + mobilerun 能力声明）
3. **模型可插拔**：Route 抽象 + generateObject（opencode provider 抽象）

核心不变的是 **「模型是大脑、代码是脊柱反射」**——步数上限、错误升级、坐标校验、能力裁剪、设备事实、断连终结全是不可绕过的代码护栏，围在 LLM 决策外。新增的 Trajectory 复盘和 Takeover 机制让测试场景更完整：前者让结果可回溯，后者让异常场景（登录/验证码）可处理而非硬崩。

---

## 十、下一步落地优先级

基于融合架构，fastaget 的后续实现建议按以下优先级推进：

1. **Route provider 抽象**（模型层）：`openai-compatible` route + baseURL + auth，接任意自定义端点。这是「连接自定义模型」的工程基础。
2. **工具输出边界 bound**（工具层）：`ActionResult.summary` 加聚合上限，超限落盘只留 preview+路径，控制 LLM 上下文膨胀。
3. **Trajectory 复盘**（横切）：`Step` 扩展 + 异步落盘 json/截图/ui_states，支持 `fastaget replay`。
4. **DeviceFactory 多平台**（执行层）：抽象 `DeviceDriver` 基类 + `supported` 能力集，phonefast 为默认实现。
5. **deps 能力声明自适应**（工具层）：`ToolEntry` 加 `deps`，`disable_unsupported(capabilities)` 自动裁剪工具集。
6. **VisionState 视觉坐标契约**（状态层）：`displayBounds` + `coordinate_scale`，截图缩放与 tap 精度解耦。
7. **Reasoning 双层可选**（智能层）：ManagerAgent + ExecutorAgent，复杂多步场景启用。
8. **takeover 工具**（工具层）：登录/验证码人工接管或跳过。

---

## 十一、架构合理性评价：能否实现「准确的移动端 AI 测试 Agent」

### 11.1 目标拆解：「准确」的两层含义

「准确」对测试 Agent 有两层含义，缺一不可：

| 层面 | 含义 | 衡量方式 |
|------|------|----------|
| **操作准确** | 点对元素、输对内容、走对路径 | tap 落在 GT bounds 内、前台包名匹配 |
| **判定准确** | 正确判断测试是否通过 | expect 的 passed 与人工判定一致 |

ART.md 的架构对这两层都有针对性设计，这是架构合理的根基。

### 11.2 架构对「操作准确」的支撑（强项）

**① 编号枢纽是操作准确的核心保障**。`UIState.get_coords(index)` + `tap_element` 直接 `tap(x,y)`，让 LLM 报 index 而非裸坐标。这从原理上消除了「坐标幻觉」——LLM 看到的元素列表与工具层查到的坐标完全对齐。mobilerun 验证过这条路，fastaget 已落地。

**② 设备级事实通道是 fastaget 的独特准确性增量**。`check_package`/`current_app` 从 `pm list packages`/`dumpsys` 取 ground truth，规避了「广告'打开'按钮被误判为已安装」这类屏幕文本幻觉。这是 mobilerun 和 AutoGLM 都没有的，对测试场景的「准确判定」尤其关键。

**③ UIProcessor 三层清洗 + 空间分区**降低了 LLM 的感知噪声。几何合法性（丢零面积）→ 屏幕内可见（丢屏外）→ 语义有效性（丢 id-only 纯容器），再加上顶/中/底三区 + 父子缩进，让 LLM 更容易选对元素。

**④ `tap_element` 内置自动重试 + `available indices` 引导**提供了操作准确的自愈兜底。index 过时时自动 observe 刷新重选，失败信息返回可用 index 列表让 LLM 一步自愈。

**结论**：操作准确性的架构支撑充分，已落地的部分已覆盖主要幻觉来源。

### 11.3 架构对「判定准确」的支撑（强项）

**① 执行/判定隔离是判定准确的核心**。`SemanticJudge` 用独立 `LLMDelegate` 实例，不喂执行历史，只给「预期描述 + 当前屏幕」。这避免了「学生批改自己作业」的同源偏差——执行 LLM 倾向于认为自己做对了，判定 LLM 独立判断更客观。

**② 三级条件降级让判定既快又准**。`{screen.has_text}` rule(0ms) → `{device.pkg_installed}` 设备事实 → `{llm.judge:描述}` 语义兜底。确定性规则优先，只有规则不够时才调 LLM，兼顾效率与覆盖。

**③ hybrid 判定 + wait 轮询**处理了异步操作判定的难点。规则先行快速通过，不过则语义兜底；`wait` 每秒 observe 重判最多 N 秒，适配「安装中/下载中」等异步场景。

**结论**：判定准确性的架构设计是 fastaget 相对参照项目的最大优势，四阶段 DAG + 执行判定隔离 + 三级条件是测试 Agent 特有的完整方案。

### 11.4 三个结构性缺口（需补才能完全达标）

#### 缺口 1：视觉模式缺乏坐标契约，a11y 不可用场景下准确性无保障

ART.md 第五节设想了「a11y 主 + 视觉辅」双模路由和 `VisionState`（displayBounds + coordinate_scale），但代码里 `vision=True` 只是把截图 base64 塞进 user content（`fast_agent.py:182-186`），**没有独立的 VisionState，没有坐标空间解耦**。

**问题**：当 a11y 树缺失（游戏/Canvas/Flutter）需要视觉模式时，LLM 在图像空间报的坐标与 tap 坐标空间不一致——截图可能被缩放，模型看到的 1080×2400 与 tap 需要的原生像素如果不对齐，就会点偏。mobilerun 的视觉坐标契约（displayBounds 模型空间 + bounds 原生像素 + coordinate_scale 反缩放）正是解决这个的，ART.md 也列了但未实现。

**影响**：a11y 可用的场景准确，a11y 不可用的场景准确性无保障。

**建议**：这是 ART.md 第十节优先级第 6 项，应提到更高优先级——至少在视觉模式开启时校验截图分辨率与设备分辨率一致，或实现 coordinate_scale 反缩放。

#### 缺口 2：判定层缺少「执行历史可追溯」，失败归因不够准确

当前 `FlowResult` 有 `expect_records`（判定结果）和 `step_results`（步骤结果），但 `StepResult` 只有 `node_id/success/summary/cost/elapsed`，**没有 LLM 的每轮 tool_calls、tool_results、屏幕快照**。ART.md 第十节列了 Trajectory 复盘（优先级第 3），但尚未实现。

**问题**：当 expect 判定失败时，无法回溯「LLM 当时看到了什么、做了什么、为什么选了这个元素」。这对测试 Agent 的「准确」很关键——测试失败后的归因分析依赖完整轨迹。mobilerun 有 Trajectory（json/gif/截图/ui_states），AutoGLM 也有 thinking + action 记录，fastaget 当前只有文本 summary。

**影响**：测试失败时归因困难，无法区分是「LLM 选错元素」还是「设备状态异常」还是「判定器误判」。

**建议**：`Step` 已有 `thought/action/args/result/success/elapsed/cost_usd/healed` 字段，只需扩展异步落盘 + 截图 + ui_states。这是提升「判定准确的可信度」的关键。建议把 Trajectory 复盘从第十节优先级第 3 提到第 2（先于工具输出边界），因为测试 Agent 的核心价值不只是「跑过」，更是「跑不过时能说清为什么」。

#### 缺口 3：FlowRunner 的 agent 复用导致状态污染风险，影响多 node 场景的准确性

`FlowRunner.__init__` 创建了一个复用的 `FastAgent` 实例（`runner.py:89-93`），所有 node 共享它的 `messages` 列表和 `ctx`。但 `FastAgent.run()` 每次**重建 messages**（`fast_agent.py:188-190`），所以 messages 不污染——这点是对的。

但 `self.ctx = ActionContext(phonefast=phonefast)` 在 `__init__` 里创建一次，`run()` 里不重置。如果上一个 node 的 observe 残留在 `ctx.ui` 里，下一个 node 首步 auto-observe 前如果 LLM 先调了 `tap_element`，会用到过时的 ui。实际上 `run()` 首步会 auto-observe 并 `ctx.refresh(ui)`（`fast_agent.py:169-173`），所以这个问题被首步 auto-observe 规避了——但这是隐式依赖，不是显式保证。

**影响**：当前不构成 bug，但架构上不够健壮。若未来改动首步逻辑，可能引入状态污染。

**建议**：`FastAgent.run()` 开头显式 `self.ctx = ActionContext(phonefast=self.phonefast)` 或加 `self.ctx.reset()`，让每个 goal 的上下文隔离显式化。

### 11.5 架构合理性总评

| 维度 | 评分 | 说明 |
|------|------|------|
| **分层清晰度** | ⭐⭐⭐⭐⭐ | 八层分层 + 横切关注点，职责边界清晰，接口解耦（ActionContext / LLMDelegate） |
| **操作准确性支撑** | ⭐⭐⭐⭐☆ | 编号枢纽 + 设备事实 + 自愈兜底已覆盖主要幻觉；视觉模式坐标契约缺失扣半星 |
| **判定准确性支撑** | ⭐⭐⭐⭐⭐ | 执行/判定隔离 + 三级条件 + hybrid + wait，测试场景特有且完整 |
| **自愈健壮性** | ⭐⭐⭐⭐☆ | 四层分层防御已落地；L4 错误升级重规划尚是设想（ART.md 标 ➕） |
| **可扩展性** | ⭐⭐⭐⭐☆ | Route/DeviceFactory/deps 均已规划但未实现；接口已预留（LLMDelegate 抽象） |
| **目标可达性** | ⭐⭐⭐⭐☆ | a11y 场景已可达「准确」；视觉场景和失败归因需补两个缺口 |

### 11.6 总体结论

ART.md 的架构**合理且能实现设计目标**，尤其「结构化文本优先 + 编号枢纽 + 设备事实 + 执行判定隔离」四件套对「准确」的支撑是扎实的。

三个缺口中，**缺口 1（视觉坐标契约）和缺口 2（Trajectory 复盘）建议优先补**——前者保障 a11y 不可用场景的准确性，后者保障失败归因的准确性，两者都是「准确的测试 Agent」不可缺失的环节。缺口 3 是健壮性优化，当前不阻塞。

ART.md 第十节的落地优先级排序基本合理，但建议调整为：

1. **Route provider 抽象**（模型层）— 不变，接自定义模型的基础
2. **Trajectory 复盘**（横切）— 从第 3 提到第 2，测试 Agent 核心价值是「跑不过时能说清为什么」
3. **工具输出边界 bound**（工具层）— 从第 2 降到第 3
4. **VisionState 视觉坐标契约**（状态层）— 从第 6 提到第 4，保障视觉模式准确性
5. **DeviceFactory 多平台**（执行层）— 不变
6. **deps 能力声明自适应**（工具层）— 不变
7. **Reasoning 双层可选**（智能层）— 不变
8. **takeover 工具**（工具层）— 不变
