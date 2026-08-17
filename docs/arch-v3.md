# fastaget V3 架构重梳理——参照 pi/agent-loop.ts 设计

> 撰写日期：2026-07-24
>
> 参照对象：`/Users/mulei/Downloads/pi/packages/agent/src/agent-loop.ts`
> 被审视对象：`fastaget/agent/fast_agent.py` + `fastaget/tools/tool_executor.py` + 周边模块
>
> **目标**：不是"照抄 pi 的设计"，而是**用 pi 的架构语言重新审视 fastaget 当前设计**，
> 识别哪些模式已对齐、哪些是缺失的、哪些是 fastaget 特有场景应该保留差异的。

---

## 一、两套架构的核心差异（一句话对比）

| 维度 | pi/agent-loop.ts | fastaget V2 当前 |
|------|-----------------|-----------------|
| 核心循环 | 双层 while（外层 follow-up，内层 tool-call + steering） | 单层 while（3 阶段管道） |
| 状态传递 | 不可变函数式（每次产新 state） | 不可变 dataclass `replace`（已对齐） |
| 生命周期 Hook | `config` 对象注入 8 个回调（类型安全） | `_fire` 字符串分发 + 4 个 Guard 实例 |
| 工具执行 | 管道式：prepare → validate → before → execute → after → finalize | 单体式：_execute_one（retry wrapper + execute） |
| 消息表示 | AgentMessage（内部）→ `convertToLlm` → Message[]（LLM 边界） | 裸 dict（直接 append 到 messages） |
| 流式 LLM | 边流式边解析 tool_use，partial update 进 context | 同步 `llm.complete()` 等全量返回 |
| 事件系统 | 类型化 `AgentEvent` union type（6 种事件） | 字符串-based `_fire` + Protocol |
| 终止判定 | `shouldStopAfterTurn` 回调（可插拔） | 硬编码 `state.terminal` + Guard 判定 |
| 消息注入 | `getSteeringMessages` / `getFollowUpMessages`（运行时注入） | 不支持（仅静态 feedback 模板注入） |

---

## 二、pi/agent-loop.ts 的核心设计精髓

### 2.1 双层循环模型

```
外层 while (true):           ← 处理 follow-up 消息（agent 本应停止，但有新消息到达）
  内层 while (hasMoreToolCalls || hasPendingMessages):
    处理 pending 消息（steering 注入）
    streamAssistantResponse → 拿到 assistant message
    如果无 tool_call → 本轮结束（内层退出，等外层判断）
    如果有 tool_call → executeToolCalls → tool_results 追加回 context → 继续内层
  检查 followUpMessages → 有则回外层，无则 break
```

**fastaget 当前**：单层 `while not terminal and step < max`，无消息注入机制。

**fastaget 场景是否需要双层？**
- `followUpMessages`（外层）：agent 完成后有新任务介入——**测试 agent 不需要**。一次 `run(goal)` 只执行一个 goal，完成后自然结束。
- `steeringMessages`（内层）：运行时注入纠正/提示——**可能有用**。例如设备断连恢复后注入"设备已恢复，请继续"，或者运维人员手动介入。但宪法要求 agent 自主决策，这种"人工注射"违背原则。→ **暂不需要双层，保持单层即可**。

**结论：双层循环是 pi 作为通用 agent runtime 的需求，fastaget 作为测试 agent 不需要。**

### 2.2 Plugin 式 Config 架构（最值得借鉴的设计）

```typescript
interface AgentLoopConfig {
  model: Model;
  apiKey?: string;
  getApiKey?: (provider: string) => Promise<string>;

  // ── 生命周期 Hook（全部可插拔）──
  transformContext?: (messages, signal) => Promise<AgentMessage[]>;  // 上下文转换
  convertToLlm: (messages) => Promise<Message[]>;                     // 消息格式转换
  prepareNextTurn?: (ctx) => Promise<NextTurnSnapshot | undefined>;  // 下一轮准备（切 model/thinking）
  shouldStopAfterTurn?: (ctx) => Promise<boolean>;                    // 终止判定
  beforeToolCall?: (ctx, signal) => Promise<{block?, reason?} | undefined>;  // 工具执行前拦截
  afterToolCall?: (ctx, signal) => Promise<Partial<AgentToolResult> | undefined>; // 工具执行后修改
  getSteeringMessages?: () => Promise<AgentMessage[]>;                // 运行时消息注入
  getFollowUpMessages?: () => Promise<AgentMessage[]>;                // 完成后消息注入
  toolExecution?: "parallel" | "sequential";                          // 工具执行模式
  reasoning?: {...};                                                   // thinking 配置
}
```

**对比 fastaget 当前**：
```python
class FastAgent:
    def __init__(
        self,
        llm, phonefast, registry,
        max_steps=15,
        system_prompt=None,
        hooks: list[AgentHook] | None = None,     # 对应事件流，但只有 observe 没有拦截
        force_tool_use=True,
        protocol_guard=None,                       # 对应 shouldStopAfterTurn 的一个特化
        complete_guard=None,                       # 对应 afterToolCall 的一个特化
        progress_guard=None,                       # 对应 transformContext + shouldStopAfterTurn
        stagnation_exempt_tools=None,
    ):
```

**关键差距**：

1. **config 是"回调集合"而非"实例集合"**：pi 的 config 是一个扁平对象，包含所有 hook 回调，运行时按需调用。fastaget 的 Guard 是独立实例，需要手动传递和组合。

2. **Hook 可以改变控制流**：pi 的 `beforeToolCall` 可以 `block`（阻止执行），`afterToolCall` 可以修改结果，`shouldStopAfterTurn` 可以终止。fastaget 的 Guard 只能"注入 feedback 文本"或"设置 terminal 标志"，对中间状态的修改能力弱。

3. **消息格式转换是显式的**：pi 的 `convertToLlm` 在 LLM 调用边界做转换，内部消息（AgentMessage）和 LLM 消息（Message[]）是两种类型。fastaget 全链路都用裸 dict，到 LLM 调用时直接透传——**消息表示与 LLM 协议强耦合**。

**借鉴方案**：不照搬 config 对象，但提取 fastaget 自己的 `LoopConfig` 概念：
- 将 `transformContext`（上下文压缩/截断）、`shouldStopAfterTurn`（终止判定）、`beforeToolCall`/`afterToolCall`（工具拦截）提取为可替换回调
- Guard 实例下沉为 config 回调的默认实现，保持可替换性
- 保留 fastaget 的"Guard 分散自持状态"设计，但将 Guard 的判断时机映射到 config 回调

### 2.3 工具执行管道（prepare → validate → before → execute → after → finalize）

```
prepareToolCall:
  1. 查 registry 找 tool 定义
  2. prepareArguments（工具自行预处理参数）
  3. validateToolArguments（参数校验）
  4. beforeToolCall hook（可 block 阻止执行）
  → 返回 PreparedToolCall（kind: "prepared"）或 ImmediateToolCallOutcome（kind: "immediate"）

executePreparedToolCall:
  1. tool.execute(id, args, signal, onPartialResult)
  2. 支持 partial update（流式工具结果）

finalizeExecutedToolCall:
  1. afterToolCall hook（可修改 result/isError/details/terminate）
  2. 返回 FinalizedToolCallOutcome

terminate 判定:
  shouldTerminateToolBatch: 所有工具 result.terminate === true → 批次终止
```

**对比 fastaget 当前 `_execute_one`**：
```python
def _execute_one(self, name, inputs, step_idx, cost, ctx):
    # 1. registry.execute（含自动 ctx 注入）  ← prepare + validate 合体
    # 2. with_retry 包装                      ← 仅 L2 重试，无 before/after hook
    # 3. PhonefastError → _recover_device     ← L1 恢复
    # 4. Exception → ActionResult.fail         ← 兜底
    # 返回 (Step, ActionResult)
```

**missing pieces**:
- 没有 `beforeToolCall`（执行前拦截——例如 pre-condition 检查）
- 没有 `afterToolCall`（执行后修改——当前 Effect-as-Data 解读在 `ToolExecutor.turn()` 里硬编码，不在工具执行管道内）
- 没有 `prepareArguments`（参数预处理钩子，pi 用这个实现 typed tool 的参数标准化）
- 没有 `validateToolArguments`（参数 schema 校验，pi 有 `validateToolArguments`，fastaget 依赖 `inspect.signature` + TypeError）

**借鉴方案**：
- 将 `_execute_one` 拆成管道：`_prepare → _validate → _before_hook → _execute → _after_hook → _finalize`
- `before_hook` 可 block（如设备断连、权限不足）
- `after_hook` 可修改 result（当前 `CompleteGuard.judge_success` 就是 `after_hook` 的一种）
- 保留 `Effect-as-Data`（`observation_data`/`is_complete`），但将解读从 `ToolExecutor.turn()` 移到 `after_hook` 回调中

### 2.4 流式 LLM + 事件驱动

```typescript
// pi: 流式响应，逐步更新 context
const response = await streamFunction(model, llmContext, config);

for await (const event of response) {
  switch (event.type) {
    case "start":        partialMessage = event.partial; context.messages.push(partialMessage);
    case "text_delta":   partialMessage = event.partial; context.messages[last] = partialMessage;
    case "toolcall_delta": ... // 流式工具调用
    case "done":         finalMessage = await response.result(); ...
  }
}
```

**fastaget 当前**：
```python
resp = with_retry(lambda: self.llm.complete(system_prompt, messages, tools, ...))
# 同步等全量返回，无流式
```

**fastaget 是否需要流式？**
- **优点**：首 token 延迟更低，工具调用边到达边执行（pi 的 streamingToolExecution 特性）
- **缺点**：fastaget 的 deepseek-v4 端点 → Anthropic 兼容协议，流式支持取决于端点
- **结论**：当前非流式可用，但架构上应预留流式接口。尤其对于"模型输出很长但只需取 tool_use 块"的场景，流式可提前终止解析。

**借鉴方案**：将 `_llm_turn` 改为 iterable/async generator 模式，而非同步 block。

### 2.5 消息边界（AgentMessage vs Message[]）

pi 在整个 agent 循环中使用 `AgentMessage`（支持 assistant/text/toolCall/toolResult 等类型），**仅在 LLM 调用边界**通过 `config.convertToLlm` 转换为 provider 原生的 `Message[]`。

**fastaget 当前**：全程裸 dict，直接 append 到 `state.messages`，格式与 Anthropic Messages API 耦合。

**为什么这很重要**：
- 当前 fastaget 的消息是裸 dict，换一个 LLM provider（如 OpenAI 兼容）需要修改所有消息构建点
- pi 的 `convertToLlm` 是**一个集中的转换函数**，换协议只需改一处
- 内部消息格式独立于 LLM 协议，可以携带更多 meta 信息（timestamp/cost/step_index）

**借鉴方案**：
- 定义 fastaget 的 `AgentMessage` 类型（dataclass，含 role/content/timestamp/step 等）
- 在 `_llm_turn` 调用 LLM 前，统一 `convert_to_llm_messages(agent_messages)` 转换
- 保留与 Anthropic API 的兼容性，但不再耦合

### 2.6 事件系统的类型化

pi 定义了类型化事件：
```
agent_start | turn_start | message_start | message_end |
message_update | tool_execution_start | tool_execution_update |
tool_execution_end | turn_end | agent_end
```

**fastaget 当前**：`_fire(method_name, **kwargs)` + `AgentHook` Protocol（runtime_checkable，字符串方法名匹配）。

**对比**：
- pi 的 `message_update` 事件允许外部监听器实时跟踪 assistant 消息的构建过程（partial update）
- pi 的 `tool_execution_update` 允许工具报告中间进度（长任务可观测）
- fastaget 的 `AgentHook` Protocol 是一次性回调（start/end），无中间状态更新

**借鉴方案**：当前 fastaget 的事件粒度对测试 agent 场景已经足够（不需要 message_update 级别的粒度）。但应改为类型化事件（`Enum` 取代字符串 `"on_tool_start"`），避免拼写错误。

### 2.7 终止判定的可插拔性

pi: `shouldStopAfterTurn` 是一个回调，可以组合多个判定条件（tool_results 分析 / max_turns / stop_reason / 外部信号）。

fastaget 当前：终止判定分散在多处：
- `state.terminal`（主循环检查）
- `_complete.judge_success`（complete 工具执行后的终端判断）
- `_progress.check`（停滞终止）
- `_protocol.on_text_end`（协议催促终止）
- `_complete.fallback`（步数耗尽后的 assert 回退）

**这是 fastaget 做得比 pi 更精细的地方**——多种终止条件各自有独立 Guard，状态分散不集中。但问题是这些判定发生在**不同时机**（工具执行中、LLM 调用后、最终结果组装时），缺乏一个统一的"终止判定点"。

**改进方向**：保留 Guard 的分散自治设计（宪法第六条），但**在每个 turn 结束后统一调用一次 `shouldStopAfterTurn` 回调**，由回调内部编排各 Guard 的检查顺序。这不是"集中状态"，而是"集中决策入口"——Guard 仍各自持有状态，但在一个统一的时机点被询问。

---

## 三、fastaget V3 架构方案

### 3.1 核心循环改造：引入 LoopConfig

```python
@dataclass
class LoopConfig:
    """Agent 循环的可插拔配置。回调默认实现来自 Guard 体系。"""

    # ── 消息管线 ──
    transform_context: Callable[[list[AgentMessage]], list[AgentMessage]] | None = None
    convert_to_llm: Callable[[list[AgentMessage], str], list[dict]]  # 消息 → LLM 格式

    # ── 工具执行管线 ──
    before_tool_call: Callable[[ToolCallContext], ToolCallVerdict | None] | None = None
    after_tool_call: Callable[[ToolCallContext], ToolCallVerdict | None] | None = None

    # ── Turn 生命周期 ──
    prepare_next_turn: Callable[[TurnContext], TurnConfig | None] | None = None
    should_stop_after_turn: Callable[[TurnContext], StopVerdict] | None = None

    # ── 工具执行模式 ──
    tool_execution: Literal["sequential"] | Literal["parallel"] = "sequential"

    # ── LLM 配置 ──
    force_tool_use: bool = True
    max_turns: int = 15
```

**关键决策**：

- **不需要双层循环**：fastaget 的 `run(goal)` 是一次性任务，无 follow-up/steering 消息概念
- **不需要流式**：deepseek-v4 的 Anthropic 兼容端点同步调用已经稳定，流式增加复杂度但收益有限
- **保留 Guard 分散自治**：Guard 类仍然自持状态，但通过 `LoopConfig` 回调接入循环，而非直接硬编码在 `FastAgent.__init__`
- **消息类型化**：新增 `AgentMessage` dataclass，在 LLM 调用边界做一次 `convert_to_llm` 转换

### 3.2 新的核心循环

```python
def run(self, goal: str) -> AgentResult:
    state = RunState(goal=goal)
    state = self._init(state)

    while not state.terminal and state.turn_count < self._config.max_turns:
        # 1) 上下文处理（压缩/截断/去重等）
        agent_msgs = self._to_agent_messages(state.messages)
        if self._config.transform_context:
            agent_msgs = self._config.transform_context(agent_msgs)

        # 2) LLM 调用（消息边界：AgentMessage → LLM 格式）
        llm_msgs = self._config.convert_to_llm(agent_msgs, self.system_prompt)
        state = self._llm_turn(state, llm_msgs)
        if state.terminal:
            break

        # 3) 工具执行（管道式）
        state = self._executor.turn(state, self.ctx)
        if state.terminal:
            break

        # 4) Turn 后判定（统一入口，各 Guard 内部编排）
        turn_ctx = TurnContext(message=..., tool_results=..., state=state)
        stop = self._config.should_stop_after_turn(turn_ctx)
        if stop.terminal:
            state = replace(state, terminal=True, success=stop.success, summary=stop.summary)
            break

        # 5) 下一轮准备（切 model/thinking）
        next_cfg = self._config.prepare_next_turn(turn_ctx)
        if next_cfg:
            ...  # 更新 model/thinking level 等

    return self._result(state)
```

### 3.3 工具执行管道改造

当前 `_execute_one` 拆成管道：

```python
def _execute_one(self, name, inputs, step_idx, ctx, config):
    # 1) prepare: 查 registry + 参数预处理
    tool = self._registry.get(name)
    if not tool:
        return Step.fail(f"Unknown tool: {name}")

    # 2) validate: 参数校验
    try:
        validated = validate_args(tool, inputs)
    except ValidationError as e:
        return Step.fail(str(e))

    # 3) before hook: 执行前拦截
    before = config.before_tool_call(ToolCallContext(name=name, args=validated, ctx=ctx))
    if before and before.block:
        return Step.fail(before.reason or "blocked")

    # 4) execute: 实际执行（含 L1/L2 自愈）
    result = self._do_execute(name, validated, ctx)

    # 5) after hook: 执行后修改
    after = config.after_tool_call(ToolCallContext(name=name, args=validated, result=result))
    if after:
        result = _merge_result(result, after)

    return Step.from_result(name, validated, result)
```

### 3.4 事件系统类型化

```python
from enum import Enum, auto

class AgentEvent(Enum):
    AGENT_START = auto()
    TURN_START = auto()
    LLM_START = auto()
    LLM_END = auto()
    TOOL_START = auto()
    TOOL_END = auto()
    TOOL_UPDATE = auto()    # 新增：长任务的中间进度
    SCREEN = auto()
    TURN_END = auto()
    AGENT_END = auto()

# Hook 协议改为单方法 + event type 分发
class AgentHook(Protocol):
    def on_event(self, event: AgentEvent, **data: Any) -> None: ...
```

### 3.5 消息类型化

```python
@dataclass
class AgentMessage:
    role: Literal["user", "assistant", "tool_result"]
    content: list[ContentBlock]  # text | tool_use | tool_result
    timestamp: float = 0.0
    turn_index: int = 0
    meta: dict = field(default_factory=dict)  # cost/tokens/...

# convert_to_llm 只在 LLM 调用时执行一次
def convert_to_llm(messages: list[AgentMessage], system_prompt: str) -> list[dict]:
    """将 fastaget 内部消息转换为当前 LLM provider 的原生格式。"""
    ...
```

### 3.6 与 Guard 体系的衔接

当前 5 个 Guard 与 LoopConfig 回调的映射：

| Guard | 映射到 LoopConfig 回调 | 说明 |
|-------|----------------------|------|
| `ProgressGuard` | `should_stop_after_turn`（惰性部分）+ `transform_context`（进度反馈注入） | 检查停滞/退化/连败 |
| `ProtocolGuard` | `should_stop_after_turn`（text-only 收敛） | LLM 不调 tool 时的催促 |
| `CompleteGuard.judge_success` | `after_tool_call` | complete 工具执行后的覆盖判定 |
| `CompleteGuard.fallback` | `should_stop_after_turn`（终局回退） | 步数耗尽后的 assert 回退 |
| `max_steps` | `should_stop_after_turn`（硬编码边界） | 循环上限 |

```python
# 默认 LoopConfig 工厂：用 Guard 实例构建
def default_loop_config(
    progress: ProgressGuard,
    protocol: ProtocolGuard,
    complete: CompleteGuard,
    max_turns: int,
) -> LoopConfig:
    return LoopConfig(
        max_turns=max_turns,
        convert_to_llm=convert_anthropic_messages,
        after_tool_call=complete_after_hook(complete),
        should_stop_after_turn=compose_stop_checks(
            max_turns_check(max_turns),
            progress_stop_check(progress),
            protocol_stop_check(protocol),
            complete_fallback_check(complete),
        ),
    )
```

---

## 四、不应该照搬的 pi 设计

| pi 特性 | 不照搬的理由 |
|---------|------------|
| 双层 while 循环 | fastaget 无 follow-up/steering 消息概念，单任务单次执行 |
| 流式 partial update | deepseek-v4 端点同步调用已稳定，流式增加复杂度但测试 agent 不感知首 token 延迟 |
| `getApiKey` 动态鉴权 | fastaget 单端点部署，无需运行时切换 |
| `prepareArguments` 类型标准化 | fastaget 工具参数简单（index/text/package），不需要 typed tool 层 |
| `isConcurrencySafe` 工具分批 | 移动端操作大多有副作用且需顺序执行，并发收益极小 |
| `tool_execution_update` 流式进度 | 当前 fastaget 工具执行 <1s，无长任务 |
| Effect/EventStream 返回值 | fastaget 同步 `return AgentResult` 即可，不需要 Reactive Stream |
| `stopReason === "length"` 截断恢复 | deepseek-v4 极少触发，暂不需要专项恢复路径 |
| `abortSignal` | 当前无取消场景 |

---

## 五、实施路线图

### Phase 1：消息类型化（基础改造，影响面大但不改行为）

1. 定义 `AgentMessage` dataclass
2. 实现 `convert_to_llm`（Anthropic 格式）
3. 将 `RunState.messages` 从 `list[dict]` 改为 `list[AgentMessage]`
4. 适配所有消息构建点

### Phase 2：LoopConfig 提取（不改行为，只改组织方式）

1. 定义 `LoopConfig` dataclass + 默认工厂函数
2. 将 Guard 实例映射到 LoopConfig 回调
3. FastAgent 接收 `loop_config: LoopConfig` 参数（替代分散的 guard 参数）
4. 主循环改为通过 config 回调驱动

### Phase 3：工具执行管道化

1. 拆 `_execute_one` 为 `prepare → validate → before → execute → after → finalize`
2. `before_hook` / `after_hook` 从 LoopConfig 注入
3. `CompleteGuard.judge_success` 迁移到 `after_hook`

### Phase 4：事件系统类型化（可选，低优先）

1. `AgentEvent` Enum 替代字符串方法名
2. `AgentHook.on_event(event, **data)` 替代多方法 Protocol
3. 向后兼容旧的 `TrajectoryRecorder`

### 不做（属于过度工程）

- 双层 while 循环
- LLM 流式响应
- 工具并行执行
- abortSignal / 取消机制
- prepareArguments 类型标准化
- API key 动态解析

---

## 六、总结

**pi/agent-loop.ts 对 fastaget 最核心的启示**：

1. **Plugin 架构 > Guard 实例注入**：将 Guard 的能力映射为 LoopConfig 回调，主循环不依赖具体 Guard 类名，只依赖回调签名
2. **消息边界**：AgentMessage ≠ LLM Message[]，在 LLM 调用边界做一次转换，解耦内部表示与 provider 协议
3. **工具执行管道**：prepare → validate → before_hook → execute → after_hook → finalize，每个阶段可插拔
4. **统一终止判定点**：所有 Guard 的判定结果汇集到 `shouldStopAfterTurn`，不影响 Guard 的分散自治状态

**fastaget 应该保留的自身优势**：
- 3 阶段状态管道（`_init → _llm_turn → executor.turn`）的清晰职责划分
- RunState 不可变 dataclass + `replace` 的函数式状态传递
- Effect-as-Data（`observation_data` / `is_complete`）的工具-系统解耦
- Guard 分散自治持有状态（宪法第六条）
- 四层自愈体系（L1 设备/L2 工具/L3 模型/L4 编排）
