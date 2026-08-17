# fastaget 参照项目架构分析：mobilerun × opencode × Claude Code

> 本文档是 fastaget 的第一步：分析三个参照项目 mobilerun、opencode、Claude Code 的架构与产品思路，形成对 fastaget 设计的输入。结论部分明确「借鉴什么、舍弃什么」。
>
> **四者关系定位（重要）：**
> - **phonefast**：fastaget **调用的执行器**（硬依赖、执行引擎）。fastaget 不自建设备通信，所有「点屏幕/截图/取 UI/输入」都通过调用 phonefast（daemon 模式，触控 <10ms）完成。phonefast 是 fastaget 运行时真正依赖的执行层，不是「参照学习」的对象。
> - **mobilerun**：`/Users/mulei/Downloads/mobilerun` — 设计参照。LLM agent 操控手机的框架，提供「测试 agent」的设备交互与自愈**范式**（思想借鉴，实现因绑死自建 Portal App 而不能直接复用）。
> - **opencode**：`/Users/mulei/Downloads/opencode` — 设计参照。开源 AI 编码 agent runtime，提供「会话核心 + 可插拔模型 provider」的工程**范式**（思想借鉴，Effect 体系过重不搬实现）。
> - **Claude Code**：`/Users/mulei/Downloads/Claude-Code`（反混淆重建源码）— 设计参照 + 对比评测的另一方（宪法第四条）。通用编码 agent 的工业级实现，提供「单 while 循环状态机 + 流式工具执行 + 权限分级 + 自动压缩」的**成熟度参照**。在 fastaget 项目中，Claude Code 同时扮演两个角色：(1) 架构设计的参照对象；(2) `tests/cc_agent_eval.py` 中通过 `claude_agent_sdk.query()` 调用的对比评测基线。

---

## 一、mobilerun：产品思路

### 1.1 产品定位

mobilerun 是 MIT 开源的「LLM agent 操控 Android/iOS 真机/云机」框架。给 agent 提供 mobile-native 工具：检视 UI 状态（a11y 树）、理解截图、tap/swipe/type、规划多步工作流，通过 CLI（`mobilerun run`）或 Python API（`MobileAgent`）返回结果。Benchmark 自报 91.4%。

**解决的问题**：自然语言 → 跨 App 的多步移动自动化（QA 回归、重复任务、数据抽取、引导式工作流）。

**目标用户**：开发者 / 测试工程师，本地跑 agent + 自有设备。

### 1.2 框架 vs 云的产品分层

| | Framework | Cloud |
|---|---|---|
| 定位 | 本机运行 runtime，CLI/Docker/Python API，需 ADB + Portal APK | 托管设备 fleet + REST API/SDK |
| 设备 | 自有真机本地控制 | Personal / Cloud Phone(Hosted) / Physical Phone(Hosted) 三类 |
| 选型逻辑 | 要本地代码级控制 → 框架；要托管规模 → 云 | |

**对 fastaget 的启示**：fastaget 当前定位是「本机快速测试 agent」，对应 mobilerun 的 Framework 侧；Cloud/VisualRemote 设备类型暂不需要。

---

## 二、mobilerun：架构

### 2.1 七层分层

```
① 入口层    CLI(cli/main.py) + SDK(__init__.py)；config_manager 分层覆盖(CLI>文件>默认)
② 编排层    MobileAgent(agent/droid/droid_agent.py) — LlamaIndex Workflow 事件驱动
            start_handler 创建 driver/state_provider/registry/action_ctx，按 reasoning 分流
            send_user_message() 支持 runtime 注入；max_steps 限流
③ 智能层    Manager+Executor(reasoning) / FastAgent(direct) / AppStarter / StructuredOutputAgent
④ 工具层    ToolRegistry + actions.py + ActionContext
⑤ 状态层    StateProvider(provider.py) → TreeFilter → IndexedFormatter → UIState
⑥ 设备层    DeviceDriver 抽象(Android/iOS/Cloud/VisualRemote) + 装饰器(Stealth/Recording)
⑦ 通信层    Portal App(com.mobilerun.portal)：AccessibilityService+手势+IME+MediaProjection
            TCP(8080)/ContentProvider 双通道（实现在外部 mobilerun_core_local 包）
```

层间解耦靠 `MobileAgentState`(shared_state) + 清晰接口；driver 用 `supported` 能力集让 registry 自裁工具。

### 2.2 三种 Agent 模式

- **FastAgent（Direct，`fast_agent.py`）**：标准 ReAct，XML 协议 `<function_calls>`/`<function_results>`，LLM 自主循环到 `complete()` 或 max_steps。维护 `message_history` 跨轮保留 thinking。**适合简单单步/快任务。**
- **ManagerAgent（`manager_agent.py`）**：规划者，每步产出 `<plan>`+`current_subgoal`，跟踪进度，用 `<request_accomplished success=...>` 结束；`_validate_and_retry`(max_retries=3) 纠格式。
- **ExecutorAgent（`executor_agent.py`）**：拿 subgoal 输出单动作 JSON（`### Thought/### Action/### Description` 三段式）。上下文含**最近 min(5,len) 步** action 历史，prompt 指示不重复失败动作；`_EXCLUDE_TOOLS={"complete"}`（complete 对 executor 隐藏，由 Manager 路径调用）。

**关键判断**：mobilerun 的 Reasoning 双层对「快」是负担。fastaget 主打 fast，应以 FastAgent(Direct) 为主，Reasoning 仅复杂场景可选。FastAgent 的 XML 协议比 function-calling 更可控可解析。

### 2.3 工具层

- **ToolRegistry**：`register(name,fn,params,description,deps)` 存 `ToolEntry`；`deps` 是 driver 能力声明集。`disable_unsupported(capabilities)` 删掉 `deps` 不被 `driver.supported | state_provider.supported` 满足的工具（如 iOS 无 drag 自动消失）。`execute` 统一注入 `ctx`，捕获 TypeError/Exception → `ActionResult(success=False)`，并 stream `ToolExecutionEvent`。
- **ActionContext**：依赖包，含 `driver/ui(每步刷新)/shared_state/state_provider/app_opener_llm/credential_manager/streaming/macro_recorder`——抽取链路与操作链路枢纽。
- **actions.py**：标准动作统一签名 `(*, ctx: ActionContext)->ActionResult`：click/click_at/type_text/system_button/swipe/open_app/wait/complete/type_secret 等。`_convert_action_point` 三重坐标校验后 `ctx.ui.convert_point`。
- **调用链**：LLM → `registry.execute` → `actions.xxx(ctx=ctx)` → `ctx.ui.get_element_coords` → `ctx.driver.tap` → `ActionResult`。

### 2.4 状态层（抽取链路，最值得借鉴）

```
AndroidStateProvider.get_state()
  → fetch_state_with_retry(fetch=driver.get_ui_tree)
  → TreeFilter.filter
  → IndexedFormatter.format
  → UIState
```

- **过滤**：`ConciseFilter`(vision 开，min_size=5px) + `DetailedFilter`(vision 关，10% 可见度，键盘 Gboard 递归剪除，父节点保留逻辑)。
- **格式化**：`IndexedFormatter._flatten_with_index` 从 index=1 递增展平；text 回退链 text→contentDescription→resourceId→className；输出 schema `'index. className: resourceId; checkedState, text - bounds(...)'`。
- **UIState**：`get_element_coords(index)` 返回中心点 `((l+r)//2,(t+b)//2)`；`get_clear_point(index)` 避开更高 index 遮挡；`convert_point` 按 `coordinate_scale` 反缩放。

> **编号枢纽机制（强借鉴）**：IndexedFormatter 展平 + index，LLM 报 index 而非裸坐标，工具层 `get_element_coords(index)` 查中心点——大幅降坐标幻觉，抽取与操作低耦合高内聚。这是抽取层与工具层的交汇点。

> **视觉坐标契约**：displayBounds(模型空间) + bounds(原生像素) + coordinate_scale，截图缩放与 tap 精度解耦。解决「模型看到的坐标空间 ≠ tap 坐标空间」。

### 2.5 设备抽象层

`DeviceDriver` 基类（在外部 `mobilerun_core_local`）抽象 tap/swipe/input_text/press_button/start_app/get_ui_tree/screenshot，`supported` 集合 + `supported_buttons`。实现：AndroidDriver(ADB+Portal)、IOSDriver、CloudDriver(经云端 SDK)、VisualRemoteDriver(httpx HTTP，screenshot-only)。装饰器：`StealthDriver`（贝塞尔+噪声拟人化）、`RecordingDriver`（记录 mutating action），可叠加 `StealthDriver(RecordingDriver(AndroidDriver))`。

### 2.6 自愈机制（五层，强借鉴）

| 层 | 位置 | 故障 | 策略 | 关键参数 |
|---|---|---|---|---|
| L1 设备 I/O | `provider.py fetch_state_with_retry` | Portal/a11y 间歇故障 | 指数退避重试 + 物理恢复回调 | `_RETRY_DELAYS=[1,2,3,5,8,10]` 总约29s，`_MAX_RETRIES=7`，`_RECOVERY_AFTER_ATTEMPT=5` |
| L2 工具执行 | `ToolRegistry.execute` | 未知工具/参数错/通用异常 | 转 `ActionResult(success=False)` | Executor 端 JSON 解析失败→`{"action":"invalid"}`，空响应→fallback |
| L3 LLM 调用 | `inference.py acall_with_retries` | 超时/空响应/通用异常 | 重试 + 线性退避 | retries=3, timeout=500s, delay*attempt |
| L4 格式校验 | `ManagerAgent._validate_and_retry` | LLM 输出格式错 | 校验错误当 user 消息喂回 LLM 自纠 | max_retries=3 |
| L5 协调自愈 | `droid_agent.handle_executor_result` | 连续失败卡住 | 错误升级到规划层重规划，一次成功复位 | `err_to_manager_thresh=2`，注入 `<potentially_stuck>` |

**物理恢复回调 `_recover_portal`**：`settings put secure accessibility_enabled 0/1` + 重启 a11y service + toggle TCP socket + 刷新 auth token；`recovery_attempted` 保证只触发一次；`DeviceDisconnectedError` 立即上抛（设备真断不重试）；iOS 失败返回空 UIState 不崩。

> **设计精髓：模型是大脑、代码是脊柱反射**。步数上限/错误升级/格式校验/坐标越界/能力裁剪/断连终结/a11y 重启全是不可绕过的代码护栏，围在 LLM 决策外。

### 2.7 模型接入

`PROVIDER_FAMILIES`（`providers/registry.py`）：Gemini / OpenAI / Anthropic / Ollama / OpenAI Compatible(用于 OpenRouter/LM Studio/vLLM) / MiniMax / ZAI(glm-5 等，复用 OpenAI 兼容 transport)。每 family 多 variant(auth_mode)。`config_manager` 的 `llm_profiles`（manager/executor/fast_agent/app_opener/structured_output 各自 provider+model），可单 LLM 共用或分角色。**绑 LlamaIndex**（`acall_with_retries`/Workflow/ChatMessage 全依赖 `llama_index.core`）。

### 2.8 横切关注点

遥测(PostHog，硬编码默认开) / Tracing(Arize Phoenix + Langfuse，含截图追踪) / 宏录制回放(`compare_states` 阈值 0.85 轮询预状态，mismatch 可 handoff 给 agent) / MCP(stdio 连外部 server，JSON Schema→ToolRegistry) / 凭证管理(FileCredentialManager 读 YAML，`type_secret` 只记 secret_id 不记值) / Trajectory(后台异步写 json+gif+截图+ui_states) / App Cards(App 专属操作指南喂 prompt)。

### 2.9 ReAct 范式

- **FastAgent 是教科书式 ReAct**：每轮 LLM 输出 `<function_calls>`(Thought+Action) → 执行 → `<function_results>`(Observation) 追加为 user 消息 → 回 LLM。系统 prompt + device_state(注入最后一条 user msg) + screenshot(带网格) + previous_device_state(倒数第二条) + memory。
- **Reasoning 是双层 ReAct + Plan 成分**：Manager 每轮基于 Observation 修正 plan（非一成不变 Plan-and-Execute），即 "ReAct with planning"。error_flag_plan 驱动错误重规划。

---

## 三、opencode：产品思路

### 3.1 产品定位

opencode 自称 "The open source AI coding agent"，开源 AI 编码 agent runtime。区别于 Cursor（编辑器内置闭源），opencode 是独立运行的 agent runtime：CLI / TUI / 桌面 / Web / console 多端，并可嵌入式嵌入（Embedded OpenCode）作为库被其他程序内嵌调用。

**差异化定位**：不是 IDE 锁定的——是可被任何前端驱动的「会话运行时」。核心卖点是「durable conversational history + 可组合运行时上下文 + 多 provider 模型抽象」。内置 `build`（全权限）与 `plan`（只读分析）两个 agent。

**对 fastaget 的启示**：opencode 的「可嵌入 runtime + 多 provider 抽象」思想可借鉴，但多端分发与企业特性不需要。

---

## 四、opencode：架构

### 4.1 monorepo 分层

依赖方向（AGENTS.md 明确）：`Schema → Core & Protocol → Server`；`Client` 可依赖 Schema/Protocol 但绝不依赖 Core/Server；`sdk-next` 组合 Client+Core+Server。

| package | 职责 |
|---|---|
| schema | 纯数据叶子（`Schema.Struct`），无 DB/WASM，浏览器安全。provider/model/permission/location/catalog 公共记录 |
| protocol | schema 组合成 HTTP 路径/载荷/流/SSE，Session 端点构造 |
| core | 领域行为核心：会话引擎、system-context、tool registry、permission、catalog、llm 适配 |
| llm | provider 抽象与协议适配层，独立于 core |
| server | protocol group 具体化，挂载中间件，拥有 HttpApi（权威 API） |
| client | HttpApi codegen 出 Promise 客户端 + `/effect` 子导出 |
| sdk-next | Effect 原生 Embedded OpenCode，内存执行 HttpRouter |

### 4.2 会话核心（V2 Session Core，三分离）

| 组件 | 职责 | 作用域 |
|---|---|---|
| **SessionV2.prompt** | durable prompt admission：用户输入落盘为一行 `session_input`，再 advisory `SessionExecution.wake`（除非 `resume:false`） | — |
| **SessionExecution** | 进程全局、基于 Session ID；拥有进程内 Session 协调器，drain 时通过 `SessionStore`+`LocationServiceMap` 发现 placement | process-global |
| **SessionRunner** | 跑一个 drain 直到 settle；两层 while（外层 queue 推进，内层 provider-turn + tool 结算循环） | Location-scoped |

**为什么分离**：admission 是 durable 的（崩溃后可重放），execution wake 是 advisory 的（可丢失可合并）。把「用户输入持久化」与「谁来执行、何时执行」解耦，为未来 clustering 留空间。`SessionRunCoordinator` 做 per-key 串行（同 Session 串行、不同 Session 并发）+ 唤醒合并。

**关键约束**：每 provider turn 恰好一次 `llm.stream(request)`；本地工具结算后再 reload projected history 开下一个 turn，绝不桥接 legacy loop。

### 4.3 模型 provider 抽象（最值得借鉴）

三层：

- **llm 包的 Route 模型**：`Route<Body,Prepared>` 接口封装「端点 + 鉴权 + 传输 + body schema + 流式」。`AnthropicMessages.route` / `OpenAIResponses.route` / `OpenAICompatibleChat.route`。`route.with({...})` 不可变打补丁，`route.model({id})` 产出 `Model`。`Auth` 支持 value/config/optional/orElse/header/bearer 组合。统一入口 `llm.stream(request)` / `llm.generate` / `llm.generateObject`（后者强制合成 tool call 取结构化输出，跨协议一致）。
- **Catalog**：Location-scoped 的 provider/model 注册表，`provider.available()`/`model.available()`/`model.default()`，异步被 Location 插件填充过滤。
- **SessionRunnerModel**：把 Catalog 的 `ModelV2.Info` 解析成 llm 包的 `Model`。按 `api.type:aisdk` + `api.package` 选 route；`withVariant` 用 immer `produce` 叠加 variant 的 headers/body；`apiKey()` 从 credential 或 settings 取。

**自定义模型/端点**：`ConfigV2.Provider`/`ConfigV2.Model` 支持 `api:{aisdk|native,url,package,settings}`、`request.headers/body`、`variants`、`cost`、`limit`。`openai-compatible.ts` profile 覆盖任意 OpenAI 兼容端点。`promptCacheKey` 按 session id 派生喂给 providerOptions。

> **对 fastaget 的核心借鉴**：接任意自定义/OpenAI 兼容端点只需一个 `openai-compatible` route + baseURL + auth。`generateObject` 用强制合成 tool call 跨协议取结构化输出，适合「测试 agent 需要结构化判定」场景。catalog + SessionRunnerModel 分离「模型注册/可见性」与「解析到具体 route」，允许运行时切模型/provider 而不改 turn。

### 4.4 工具层

- **ToolRegistry**（Location-scoped）：`materialize(permissions?)` 返回 `{definitions, settle}`——按 permission ruleset 过滤后产出 tool definitions。`register` 用 `Effect.acquireRelease` 作用域化注册。`settle` 内置 stale/unknown 检测（`identity` 比对防工具版本漂移）。
- **工具与会话绑定**：runner 在 stream 的 `tool-call` 事件里立即 `settle`，用 `Effect.uninterruptibleMask` 包成不可中断区，再 `FiberSet.run` 异步结算；`awaitToolFibers` 等全部结算才续 turn。
- **工具输出边界**：`ToolOutputStore.bound` 对每个工具结果施加聚合上限（行数或字节），超限写 Managed Tool Output File，历史只留 bounded preview + 路径。

### 4.5 System Context（系统上下文）

- **Context Source**：`Source<A> = {key, codec, load, baseline, update, removed?}`。`SystemContext.make` 把值类型隐藏成 opaque carrier，不同类型 source 统一组合。
- **Context Epoch**：一段「baseline 不可变」区间，结束于 compaction/session 移动/不兼容转换。`SessionContextEpoch` 持久化 baseline 文本 + Snapshot，状态机 `initialize/prepare/reconcile/replace`。
- **与 prompt cache 的关系**：baseline 文本 durably 存储且跨重启逐字复用，作为 provider-cache 的稳定前缀；变更不立即推送，在下一个 Safe Provider-Turn Boundary 懒采样成 Mid-Conversation System Message，baseline 保持不变 → cache 命中率最大化。

> **对 fastaget 的借鉴**：把系统上下文建模成「独立可刷新的 typed source + codec 比对」，baseline 持久化跨重启复用 → prompt cache 稳定前缀。测试环境信息（日期、被测对象状态）可如此稳定注入。但全套 reconcile/replace 状态机对测试 agent 偏复杂，可简化为「每次 turn 重新组装 system prompt」或仅保留 baseline 持久化。

### 4.6 配置 / 权限 / 持久化

- **配置**：global config → 向上发现的 `opencode.json/jsonc` → `.opencode/` 目录，近处覆盖远处。agent 配置（model/variant/system/mode/permissions）、model/provider 配置（api/variants/cost/limit）。
- **权限模型**：`Rule = {action, resource, effect: allow|deny|ask}`，`*` 通配，`findLast` 匹配，无匹配默认 ask，deny>ask>allow。`always` 回复持久化规则。Location-scoped（按 `location.project.id` 隔离）。
- **持久化**：SQLite（SessionInputTable / SessionContextEpochTable / SessionMessageTable / PermissionSaved）。drain 是 process-local 协调，无 durable 身份、无 transcript 边界，从 durable 事实推断恢复。clustering 是未完成项。

### 4.7 代码风格与设计哲学

函数内联优先（不预先抽一次性 helper）、避免 try/catch、避免 any、避免不必要解构（用点号保上下文）、避免 else（早返回）、避免 let。import 禁 alias/star。**全项目重度用 Effect**（Layer/Context.Service/Stream/Fiber/Deferred/Schema）。价值观：主函数读作 happy path、最小变量数、确定性优先（registry 按 key 排序）、类型推断优先。

---

## 五、Claude Code：产品思路与架构

### 5.1 产品定位

Claude Code 是 Anthropic 的通用编码 agent，多端形态（CLI/TUI/桌面/SDK）共享同一套核心引擎。定位不是「移动设备自动化」也不是「多 provider 会话 runtime」，而是**单模型（Claude）+ 工具生态深度优化**的编码助手：60+ 内置工具（Bash/Read/Write/Edit/Grep/Glob/AgentTool/TodoWrite/Skill/MCP 等）、REPL 交互 + 非交互（`-p`/SDK）双模式、子 agent 编排（Task/AgentTool）。

**对 fastaget 的启示**：Claude Code 是 fastaget 在宪法第四条中「对比评测的另一方」——理解其真实执行方式，才能准确判断「CC 交互模式」与「脚本硬编码分支」的边界，避免评测数据因误解 CC 行为而作废。

### 5.2 核心 Agent 循环：单 while 状态机（`query.ts` `queryLoop`）

不同于 mobilerun 的「事件驱动 Workflow」或 opencode 的「Effect 体系」，Claude Code 的核心循环是一个**单个 `while(true)` 状态机**，每轮迭代做九件事：

```
① 消息预处理：越过 compact 边界 → 应用工具结果预算(bound) → snip → microcompact
② 拼装最终 system prompt（含动态 systemContext 追加）
③ autocompact 检测：token 超阈值 → 生成摘要 → 替换消息 → yield 摘要消息 → 用新状态 continue（不进入 API 调用）
④ 调 deps.callModel() 流式请求：边流式边解析 assistant 消息中的 tool_use 块
   - 若开启 streamingToolExecution：tool_use 块一到达就立即 addTool()，与模型输出并行执行
⑤ 流式过程中处理特殊信号：模型 fallback、withheld 错误（prompt-too-long/max-output-tokens 等）
⑥ 无 tool_use（needsFollowUp=false）→ 走"回合结束"分支：
   - prompt-too-long → collapse drain / reactive compact 恢复重试
   - max_output_tokens → 分级恢复（默认8k→64k→多轮续写，MAX_OUTPUT_TOKENS_RECOVERY_LIMIT=3）
   - stop hooks 执行（可能阻断继续或注入 blocking error）
   - token budget 检测（continue / diminishing-returns 提前停止）
   - 都通过 → return { reason: 'completed' }（唯一"正常结束"出口）
⑦ 有 tool_use → runTools()：按并发安全性分批（见 5.3），执行完拿到 toolResults
⑧ 中断检测（abortController）→ 各种清理后 return
⑨ 附件注入（队列命令/内存预取/Skill 发现）→ 检查 maxTurns → 状态机 continue 到下一轮
```

**与 fastaget/mobilerun 的本质区别**：mobilerun/fastaget 是"LLM 决策 → 执行 → 下一轮 LLM"的**递归/循环调用**；Claude Code 用**唯一一个 while 循环 + 显式 State 对象**驱动全部分支（正常继续/自动压缩重试/max_output_tokens 恢复/stop_hook 拦截/token_budget 续写），每个 continue 点都显式构造完整的 `next: State`，**没有隐式状态残留**——这是工程成熟度的体现，值得 fastaget 的 `run()` 循环借鉴其「状态显式化」思想（当前 fastaget 用散落的局部变量 `consecutive_fails`/`total_steps` 等，State 对象化能减少跨分支状态遗漏风险，参考本次审查中发现的 `_last_assert_passed` 等未定义变量问题）。

### 5.3 工具执行：并发安全分批 + 流式执行

`toolOrchestration.ts` 的 `runTools()`：

- **分批策略**：`partitionToolCalls` 把连续的 tool_use 块按 `isConcurrencySafe()` 分组——**连续的只读工具（Read/Grep/Glob 等）合并成一批并发执行**（`getMaxToolUseConcurrency()` 默认 10），非并发安全的工具（Write/Edit/Bash 等有副作用的）单独串行执行。
- **流式工具执行**（`StreamingToolExecutor`，可选特性）：不等模型把整条 assistant 消息流完，`tool_use` 块一到达就立即执行，与后续模型输出（如工具调用后的文本说明）并行——大幅降低总延迟。
- **权限分级**（`useCanUseTool.tsx`）：每个工具调用先过 `hasPermissionsToUseTool` 判定 `allow/deny/ask`。`ask` 时经过一层「自动化检查」（coordinator/swarm-worker/speculative bash classifier）尝试自动决策，都不行才真正弹出交互式权限对话框——**"能自动就不问人"**的分级降级思想。

**对 fastaget 的启示**：fastaget 当前工具全部串行执行（`for tc in llm_resp.tool_calls`），对于「多个只读 observe/check_package/current_app 类查询」场景，可借鉴按 `isConcurrencySafe` 分批并发的思想（虽然移动端操作大多有副作用，并发收益不如编码场景大，但设备事实类只读查询工具存在并发空间）。

### 5.4 自愈与恢复机制（比 mobilerun 更工业化，无独立分层，融于状态机分支）

| 故障类型 | 恢复策略 | 关键参数 |
|---|---|---|
| prompt 超长（413） | ① context-collapse drain（先尝试，代价小）→ ② reactive compact（全量摘要重试） | 各自 single-shot，`hasAttemptedReactiveCompact` 防死循环 |
| max_output_tokens 截断 | 首次：升级 max_tokens（8k→64k）重试同请求；仍不行：注入"继续，不要道歉不要复述"续写消息 | `MAX_OUTPUT_TOKENS_RECOVERY_LIMIT=3` |
| 模型不可用/降级 | streaming fallback：切换到 fallback model，丢弃 orphan 消息，重新执行完整请求 | `FallbackTriggeredError` 触发 |
| stop hook 拦截 | 注入 blocking error 消息，`stopHookActive=true` 防止无限重入 | — |
| token budget 超限 | `continue`（注入 nudge 消息续写）或 `diminishingReturns` 提前停止 | — |
| 达到 maxTurns | 硬性终止，yield `max_turns_reached` 附件 | 与 fastaget `max_steps` 同构 |

**核心差异**：mobilerun/fastaget 的自愈是"**分层防御**"（L1 设备/L2 工具/L3 模型/L4 编排，每层独立重试），Claude Code 的自愈是"**状态机分支**"（每种异常对应一个具体的 `State` 重建路径 + `continue`）。前者更模块化易扩展，后者更精确（每种故障有专属恢复策略而非通用退避重试）。fastaget 目前对「LLM 输出为空」「上下文压力」有专属处理（`_validate_llm_output`/`context_pressure`），已经在往这个方向演进。

### 5.5 消息历史管理：多级压缩而非简单截断

Claude Code 对上下文膨胀的处理比 opencode 的 baseline/prompt-cache 更精细，分四级：

1. **工具结果预算**（`applyToolResultBudget`）：单个工具结果超限→ 持久化到磁盘，历史只留 preview + 路径（对应 opencode 的 `ToolOutputStore.bound`，fastaget ART.md 规划中同名的"工具输出边界"）
2. **snip**：`snipCompactIfNeeded` 按需裁剪部分历史
3. **microcompact**：轻量级压缩（不改变整体结构，压缩局部）
4. **autocompact**：token 超阈值触发完整摘要，替换全部历史为摘要 + 附件

四级从"轻量局部"到"重量全局"依次尝试，只有前面都不够才升级到下一级——这是比 fastaget 当前 `compress_screen_observations`（单一压缩策略：早期屏幕观察→一行摘要）更细粒度的分级方案。

### 5.6 子 agent 与任务编排（AgentTool / Task）

`Task.ts` 定义了 `TaskType`（local_bash / local_agent / remote_agent / in_process_teammate / local_workflow / monitor_mcp / dream）统一任务抽象；`AgentTool` 让主 agent 可以派生子 agent（`forkSubagent`/`runAgent`/`resumeAgent`）处理子任务，子 agent 有独立的消息历史与工具集裁剪（`allowedAgentTypes`）。这对应 mobilerun 的 Manager+Executor 双层思想，但实现为「主 agent 按需动态派生」而非固定两层架构——更灵活，按需付费复杂度。

**对 fastaget 的启示**：ART.md 规划中的「Reasoning 双层可选」可参考此思想——不做固定的 Manager/Executor 分层，而是给 FastAgent 加一个可选的 `spawn_subagent` 工具，仅复杂目标需要拆解时才由主 agent 自主决定派生子任务，避免所有场景都背上双层调度的开销。

### 5.7 Claude Code 对宪法第四条的落地含义

结合 `tests/cc_agent_eval.py` 的实际调用方式，可以精确定义"CC 交互/评测模式"的技术边界：

- CC 通过 `claude_agent_sdk.query(prompt, options)` 发起，底层正是本节分析的 `queryLoop`——CC 自己决定何时调用 Bash 工具执行 `phonefast`/`adb` 命令、何时 observe、何时判定完成，**不存在外部脚本注入的决策分支**。
- `_build_prompt()` 只提供 goal + 工具列表说明 + 通用规则（宪法允许的"能力说明"，不是"步骤指令"）——符合宪法第一条。
- CC 的 tool_use 全部走 Bash 工具间接调用 `phonefast --daemon <cmd>`，本质是 mobilerun/fastaget 的「原生 tool-calling」的另一种实现（用单一 Bash 工具代理多个具体动作，而非每个动作注册一个独立 tool），这是 CC 与 fastaget 工具粒度设计的关键差异——fastaget 是`observe`/`tap_element`/`swipe` 等细粒度工具，CC 对移动端场景是粗粒度的 `Bash` 通用工具。

---

## 六、三项目对比

| 维度 | mobilerun | opencode | Claude Code |
|---|---|---|---|
| 领域 | 移动设备自动化 agent | 通用编码 agent runtime | 通用编码 agent（工业级单产品） |
| 运行时 | LlamaIndex Workflow（事件驱动） | Effect 体系（Layer/Stream/Fiber） | 单 while 循环 + 显式 State 状态机 |
| 设备交互 | 自建 Portal App（a11y+手势+IME+截图） | 无（操作文件系统/bash） | 无（Bash/Read/Write 等 60+ 工具） |
| 自愈重点 | 设备 I/O + 工具 + LLM + 格式 + 协调 五层 | durable admission + drain 恢复 + 工具结算 | 按故障类型分支恢复（413/max_tokens/fallback/hook/budget 各自专属路径） |
| 模型抽象 | provider family + llm_profiles 分角色 | Route + Catalog + SessionRunnerModel 三层 | 单模型深度优化（Claude 系列 + fallback model 兜底） |
| 上下文 | 注入 device_state/screenshot 到 user msg | System Context + Context Epoch + prompt cache | 四级压缩（工具结果预算→snip→microcompact→autocompact） |
| 工具执行 | 顺序执行 | Location-scoped registry + settle 结算 | 并发安全分批 + 流式执行 + 权限分级 |
| 持久化 | Trajectory（json/gif/截图） | SQLite durable session + inbox | Session 文件 + sidechain（子 agent 独立记录） |
| 复杂度重心 | 设备抽取链路 + 自愈护栏 | 会话核心 + 模型 provider 抽象 | 状态机健壮性 + 工具生态深度 + 上下文管理精细度 |
| 对 fastaget | 提供「测试 agent」的设备/自愈范式 | 提供「会话核心 + provider 抽象」的工程范式 | 提供「状态显式化 + 分级压缩 + 分批并发」的工程成熟度参照；同时是宪法第四条的对比评测基线 |

---

## 七、对 fastaget 的借鉴与取舍

### 7.1 强借鉴（直接复刻思想）

1. **编号枢纽机制**（mobilerun 状态层）：phonefast 的 `observe` 返回 UI 树后，用 IndexedFormatter 展平 + index，LLM 报 index 而非裸坐标，工具层按 index 查坐标。**降坐标幻觉的核心**。phonefast 已有 `tap_element <idx|txt>`，与这套机制天然契合。
2. **分层自愈 + 错误升级**（mobilerun 五层）：fastaget 重组为四层（设备 I/O / 工具执行 / 模型调用 / 测试编排），逐级兜底，连续失败升级重规划，一次成功复位。物理恢复回调需改写为 phonefast daemon 重启 + 重新 observe 校准。
3. **模型 provider 抽象**（opencode Route）：`Route<Body,Prepared>` 封装端点+鉴权+传输+流式，`openai-compatible` route + baseURL + auth 即可接任意自定义端点。`generateObject` 强制合成 tool call 取结构化输出，用于测试断言的结构化判定。catalog + 解析分离让运行时切模型不改 turn——这是「连接 Claude Code 自定义模型」的工程基础。
4. **admission/execution/runner 三分离思想**（opencode）：输入先 durable 落盘再 advisory 唤醒，崩溃不丢输入。fastaget 可取轻量版（任务队列 + 幂等），不必上全套 durable clustering。
5. **能力声明自适应**（mobilerun）：driver `supported` + tool `deps` → `disable_unsupported` 自动裁剪可见工具集，跨能力零改 prompt。
6. **ActionContext 每步刷新 ui**（mobilerun）：保证动作基于最新屏幕，抽取与操作链路的同步桥梁。
7. **工具输出边界**（opencode ToolOutputStore.bound / Claude Code applyToolResultBudget）：对工具结果施加聚合上限，超限落盘只留 preview+路径——控制 LLM 上下文膨胀。两个参照项目都独立收敛到同一个方案，说明这是测试/编码 agent 的通用刚需。
8. **状态显式化**（Claude Code `State` 对象）：把 `consecutive_fails`/`total_steps`/`_last_assert_passed` 等跨轮状态收敛成一个显式 `State` 对象，每次状态转移都重建完整对象而非零散赋值——降低「某分支忘记更新某个状态变量」的 bug 风险（本次代码审查中发现的未定义变量问题即此类风险的实例）。
9. **多级消息压缩**（Claude Code 工具结果预算→snip→microcompact→autocompact）：fastaget 当前 `compress_screen_observations` 是单一压缩策略，可参考「先轻量局部、再重量全局」的分级思路，尤其是「单个工具结果超限」与「整体历史超限」应该是两级独立触发条件。
10. **工具并发安全分批**（Claude Code `partitionToolCalls`）：连续的只读工具（如 fastaget 的 `observe`/`check_package`/`current_app`）可并发执行，有副作用的操作类工具（`tap`/`swipe`/`type`）保持串行——移动端场景收益小于编码场景，但设备事实查询类工具仍有优化空间。

### 7.2 简化借鉴（取思想减复杂度）

- **System Context / Context Epoch**：保留「typed source + baseline 持久化 → prompt cache 稳定前缀」思想，舍弃 reconcile/replace/ReplacementBlocked 全套状态机，简化为「每次 turn 重新组装 system prompt」或仅 baseline 持久化。
- **Reasoning 双层**：以 FastAgent(Direct) 为主，Reasoning 仅复杂场景可选；XML 协议优先于 function-calling（更可控可解析）。
- **SessionRunCoordinator**：取 per-key 串行 + 跨 key 并发 + 唤醒合并的并发原语思想。
- **子 agent 按需派生**（Claude Code AgentTool）：不做固定 Manager/Executor 双层，而是给 FastAgent 加一个可选的 `spawn_subagent` 工具，仅复杂目标需要拆解时才由主 agent 自主决定派生——比 mobilerun 固定双层更省资源。
- **按故障类型分支恢复**（Claude Code）：在现有四层分层自愈基础上，对「上下文压力」「LLM 输出为空」等已识别的高频故障类型，可参考 Claude Code 对每种故障给专属恢复路径的思路（fastaget 的 `_validate_llm_output`/`context_pressure` 已是此方向的雏形），而非所有故障都走同一套退避重试。

### 7.3 舍弃（不适用或过重）

- **mobilerun Portal App 强依赖**：抽取/操作/IME/截图全绑死 Portal，fastaget 用 phonefast，设备通信层整体替换，`_recover_portal` 和 driver.get_ui_tree 数据源需重写。
- **mobilerun Cloud/VisualRemote driver**：自家云服务 + 通用 HTTP 截图服务器，fastaget 本地真机不需要（VisualRemote 的 screenshot-only 思路可留作 vision_only 模式参考）。
- **mobilerun Stealth 拟人化**：贝塞尔+噪声+逐词打字引入随机性与延迟，测试 agent 要可重复/快，应默认关闭。
- **mobilerun PostHog 硬编码遥测**：需移除或自托管。
- **mobilerun open_app 依赖 LLM 选包名**：多一次 LLM 调用，fastaget 若已知包名直接 `phonefast launch` 规避。
- **opencode Effect 运行时**：学习曲线陡、运行时依赖重，fastaget 用原生 async/await + 轻量 schema 即可。只借鉴「分离思想」不搬 Effect 实现。
- **opencode 全套 durable session + clustering**：为长生命周期可中断编码会话设计，fastaget 短任务可重跑，全套过重。
- **opencode SDK Contract IR / HttpApi codegen / 多端分发 / 企业特性**：单一内嵌场景不需要。
- **Claude Code 交互式权限系统（allow/deny/ask 弹窗）**：fastaget 是自动化测试 agent，不应有人工确认环节（违反宪法「自主决策」），权限分级思想不适用，但「自动化检查优先于人工询问」的降级思路可用于「shell 命令是否需要额外确认」类场景。
- **Claude Code 60+ 工具生态与 MCP 集成**：为通用编码场景设计，fastaget 是垂直移动测试场景，工具集应保持精简（宪法「参数化优于内联」同样适用于工具数量——不为了“看起来强大”而引入与测试场景无关的工具）。
- **Claude Code 单 while 循环内内联十几个特性开关**（`feature('XXX')` 满天飞）：工程成熟度高但可读性代价大，fastaget 代码量远小于 Claude Code，应优先保持 `run()` 循环可读，不盲目堆疑似 Claude Code 的分支密度。

### 7.4 fastaget 的合成路径

> 关键：phonefast 是 fastaget **调用的执行器**（执行层硬依赖），mobilerun/opencode/Claude Code 是**设计参照**（仅借鉴思想）。

```
执行层：phonefast daemon —— fastaget 调用的执行器（硬依赖，<10ms 触控）
        所有 tap/swipe/type/screenshot/ui/observe 动作都是对 phonefast 的调用
        不自建设备通信，不依赖 mobilerun Portal App
状态层：phonefast observe 的输出 → IndexedFormatter → UIState（借鉴 mobilerun 编号枢纽思想）
工具层：ToolRegistry + actions + ActionContext（借鉴 mobilerun）+ 工具输出边界（借鉴 opencode/Claude Code）
        actions 内部调用 phonefast 完成 actual 执行
自愈层：四层分层防御（mobilerun 五层按测试场景重组）+ 按故障类型专属恢复路径思想（借鉴 Claude Code）
        L1 物理恢复改写为「phonefast daemon 重启 + 重新 observe 校准」而非 Portal a11y 重启
状态管理：跨轮状态显式化为单一 State 对象（借鉴 Claude Code）+ 多级消息压缩（工具预算→局部压缩→全局摘要）
模型层：Route provider 抽象 + catalog（借鉴 opencode）+ generateObject 结构化断言
        这是「连接 Claude Code 自定义模型」的工程基础
智能层：FastAgent(Direct) 为主，XML 协议；Reasoning 可选，按需派生子 agent（借鉴 Claude Code AgentTool 思想而非固定双层）
会话层：admission/execution 轻量分离（借鉴 opencode 思想，不上 Effect/durable clustering）
横切：Trajectory 复盘（借鉴 mobilerun）+ 简化 System Context（借鉴 opencode）
```

---

## 八、下一步

基于本分析，fastaget 的后续设计文档应细化：

1. phonefast 适配层：`observe` 输出 → IndexedFormatter → UIState 的具体数据结构
2. 自愈四层接口与重试参数（对齐 mobilerun 经验值，物理恢复改写为 phonefast daemon 重启）
3. 模型 provider Route 抽象 + Claude Code 自定义模型接入方案（对齐 opencode openai-compatible route）
4. ToolRegistry 最小动作集 + 工具输出边界
5. CLI 骨架与用例/断言数据结构
6. FastAgent 循环状态显式化（State 对象）+ 分级消息压缩策略（对齐 Claude Code 状态机与四级压缩思路）
