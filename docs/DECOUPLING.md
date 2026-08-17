# 解耦设计——参照 pi/agent-loop.ts 降低耦合度

> 2026-07-24
>
> 逐一分析 fastaget 当前的耦合点，给出 pi 式的解耦方案。
> 原则：只借需要的那部分，不过度工程。

---

## 一、耦合地图：当前谁依赖谁

```
FastAgent.__init__
  ├─ 创建 ScreenObserver(phonefast)           ← 耦合 1：知道 Observer 具体类
  ├─ 创建 ActionContext(phonefast)            ← 耦合 2：知道 Context 具体类
  ├─ 创建 ProtocolGuard()                     ← 耦合 3：知道 Guard 具体类
  ├─ 创建 CompleteGuard()                     ← 耦合 4
  ├─ 创建 ProgressGuard()                     ← 耦合 5
  ├─ 创建 ToolExecutor(registry, observer,    ← 耦合 6：知道 Executor 构造函数签名
  │       progress_guard, complete_guard)
  ├─ 加载 _load_prompt("baseline")            ← 耦合 7：知道文件系统路径
  ├─ 调用 self.llm.complete(...)              ← 耦合 8：知道 LLM 调用方式
  └─ 保存 self._assert_tools                  ← 耦合 9：知道工具分类

FastAgent.run()
  ├─ self.observer.initial()                  ← 耦合 10：知道观察者 API
  ├─ DeviceContext.from_phonefast(...)        ← 耦合 11：知道设备上下文
  ├─ _load_domain_template(goal)              ← 耦合 12：知道领域模板加载
  ├─ self.llm.complete(system, msgs, tools)   ← 耦合 13：知道 LLM 协议
  ├─ self._protocol.on_text_end()             ← 耦合 14：知道 Guard 判定方法
  ├─ self._executor.turn(state, ctx, _fire)   ← 耦合 15：传内部方法给 executor
  └─ self._complete.fallback(...)             ← 耦合 16：知道 Guard 判定方法

ToolExecutor.turn()
  ├─ self._observer.after_action()            ← 耦合 17：Executor 知道 Observer API
  ├─ self._observer.note_observed()           ← 耦合 18
  ├─ self._observer.fingerprint / element_count ← 耦合 19
  ├─ ctx.refresh(self._observer.last_ui)      ← 耦合 20：Executor 知道 Context API
  ├─ self._progress.record() / .check()       ← 耦合 21：Executor 知道 ProgressGuard
  ├─ self._complete.judge_success()           ← 耦合 22：Executor 知道 CompleteGuard
  ├─ _load_feedback(name)                     ← 耦合 23：Executor 知道文件系统
  └─ fire_hook("on_tool_start", ...)          ← 耦合 24：字符串事件分发

消息格式（全局耦合）
  └─ 全链路裸 dict，与 Anthropic Messages API 耦合  ← 耦合 25
```

**25 个耦合点，核心问题是 3 个模块互相知道对方的内部细节。**

---

## 二、pi 的解耦机制：Config 对象

pi 把**所有耦合点收敛到一个 `AgentLoopConfig` 对象**中。主循环不知道 Observer、Guard、LLM 格式、Prompt 路径——它只知道 config 上的回调签名。

```typescript
// pi 的主循环：零具体依赖
async function runLoop(context, config, emit, signal, streamFn) {
  while (true) {
    // 上下文转换——不知道是压缩还是去重
    if (config.transformContext) {
      messages = await config.transformContext(messages, signal);
    }

    // 消息格式转换——不知道是 Anthropic 还是 OpenAI
    const llmMessages = await config.convertToLlm(messages);

    // LLM 调用——不知道具体 endpoint
    const response = await streamFunction(config.model, llmContext, config);

    // 工具执行前——不知道谁在拦截
    if (config.beforeToolCall) {
      const result = await config.beforeToolCall(ctx, signal);
      if (result?.block) { ... }
    }

    // 工具执行后——不知道谁在修改结果
    if (config.afterToolCall) {
      const modified = await config.afterToolCall(ctx, signal);
    }

    // 终止判定——不知道谁在做判定
    if (await config.shouldStopAfterTurn?.(ctx)) {
      return;
    }
  }
}
```

**核心洞察**：主循环从"知道一切"变成"只编排生命周期，具体行为由外部注入"。

---

## 三、fastaget 的解耦方案：LoopConfig

### 3.1 需要哪些回调？

对照 pi 的全部 10 个回调，对 fastaget 做一次筛选：

| pi 回调 | fastaget 需要？ | 理由 |
|---------|:---:|------|
| `transformContext` | ✅ | 上下文压缩/去重——需要，当前在 observer 里 |
| `convertToLlm` | ✅ | 消息格式转换——需要，解耦 Anthropic 协议 |
| `beforeToolCall` | ✅ | 工具执行前拦截——需要，设备状态检查 |
| `afterToolCall` | ✅ | 工具执行后修改——需要，complete 判定、效果解读 |
| `shouldStopAfterTurn` | ✅ | 终止判定——需要，替代分散的 Guard 判定 |
| `prepareNextTurn` | ❌ | 切模型/thinking——fastaget 单模型，不需要 |
| `getSteeringMessages` | ❌ | 运行时消息注入——单任务不需要 |
| `getFollowUpMessages` | ❌ | 完成后消息注入——单任务不需要 |
| `getApiKey` | ❌ | 动态密钥——单端点不需要 |
| `reasoning` 字段 | ❌ | thinking 开关——已简化为 `force_tool_use` |

**需要 5 个回调，不需要 5 个。**

### 3.2 fastaget 的 LoopConfig

```python
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


# ── 各回调的上下文类型 ──

@dataclass
class ToolCallContext:
    """before_tool_call / after_tool_call 的入参。"""
    name: str
    args: dict[str, Any]
    step_index: int
    result: "ActionResult | None" = None   # after 时有值
    is_error: bool = False                  # after 时有值
    steps_so_far: list["Step"] = field(default_factory=list)


@dataclass
class TurnContext:
    """should_stop_after_turn 的入参。"""
    turn_index: int
    step_count: int
    messages: list[dict[str, Any]]
    steps: list["Step"]
    last_llm_response: "LLMResponse | None" = None
    last_tool_name: str = ""
    terminal: bool = False
    success: bool = False
    summary: str = ""


@dataclass
class BeforeToolVerdict:
    """before_tool_call 的返回。None 表示放行。"""
    block: bool = False
    reason: str = ""


@dataclass
class AfterToolVerdict:
    """after_tool_call 的返回。None 表示不修改。"""
    result_override: str | None = None      # 覆盖 to_llm_text()
    is_error_override: bool | None = None   # 覆盖 is_error
    terminal: bool = False                  # 设置后本轮终止
    success: bool = False
    summary: str = ""


@dataclass
class StopVerdict:
    """should_stop_after_turn 的返回。"""
    terminal: bool = False
    success: bool = False
    summary: str = ""
    feedback: str = ""  # 非空时注入到 messages


# ── LoopConfig：5 个回调 + 2 个配置值 ──

@dataclass
class LoopConfig:
    """Agent 循环的可插拔配置。

    主循环只知道这些回调的签名，不知道具体实现。
    所有 Guard/Observer/LLM 细节都在回调的闭包里。
    """

    # ── 消息管线 ──
    transform_context: Callable[[list[dict]], list[dict]] = lambda msgs: msgs
    convert_to_llm: Callable[[str, list[dict]], list[dict]] = None

    # ── 工具执行管线 ──
    before_tool_call: Callable[[ToolCallContext], BeforeToolVerdict | None] = \
        lambda ctx: None
    after_tool_call: Callable[[ToolCallContext], AfterToolVerdict | None] = \
        lambda ctx: None

    # ── Turn 生命周期 ──
    should_stop_after_turn: Callable[[TurnContext], StopVerdict] = \
        lambda ctx: StopVerdict()

    # ── 执行参数 ──
    max_turns: int = 15
    force_tool_use: bool = True
```

### 3.3 改造后的主循环

```python
class FastAgent:
    """Agent 主循环：只做编排，零具体依赖。"""

    def __init__(self, config: LoopConfig, hooks: list[AgentHook] | None = None):
        self._config = config
        self._hooks = hooks or []
        # agent 不再创建任何 Guard / Observer / Executor / Context
        # 这些全部在 config 回调的闭包里

    def run(self, goal: str) -> AgentResult:
        state = self._build_initial_state(goal)

        while not state.terminal and state.turn < self._config.max_turns:
            # ── Pre-turn：上下文处理 ──
            state.messages = self._config.transform_context(state.messages)

            # ── LLM 调用 ──
            llm_msgs = self._config.convert_to_llm(state.system_prompt, state.messages)
            resp = self._call_llm(llm_msgs)  # ← 也由 config 提供？
            state = self._append_assistant(state, resp)

            # ── Post-LLM：LLM 返回后的检查（text-only 催促等）──
            # （集成在 should_stop_after_turn 中，见下文）

            # ── 工具执行 ──
            state = self._execute_tools(state)

            # ── Post-turn：统一终止判定 ──
            verdict = self._config.should_stop_after_turn(TurnContext(
                turn_index=state.turn,
                step_count=state.step_count,
                messages=state.messages,
                steps=state.steps,
                last_llm_response=resp,
                terminal=state.terminal,
                success=state.success,
                summary=state.summary,
            ))
            if verdict.terminal:
                state = replace(state, terminal=True,
                               success=verdict.success, summary=verdict.summary)
            if verdict.feedback:
                state.messages.append({"role": "user", "content": [
                    {"type": "text", "text": verdict.feedback}]})

        return self._build_result(state)
```

**关键变化**：`FastAgent.run()` 里不再出现 `observer`、`protocol_guard`、`complete_guard`、`progress_guard`、`executor`、`ctx`、`_fire` 这些词——只有 `self._config.xxx()`。

---

## 四、耦合点逐个解耦

### 4.1 消息格式解耦（耦合 7/11/12/13/25）

**当前**：所有消息构建点直接拼 Anthropic 格式 dict。

**解耦**：`convert_to_llm` 回调负责内部消息 → LLM 格式转换。

```python
# config 闭包
def _build_default_convert(llm: LLMDelegate, system_prompt: str):
    def convert(system: str, messages: list[dict]) -> list[dict]:
        # 当前就是透传（内部已经用 Anthropic 格式），将来换协议只改这里
        return messages
    return convert
```

短期不改消息格式（成本高收益低），但**架构上留好这个边界**——所有消息构建仍然用 dict，但 LLM 调用的入参统一过 `convert_to_llm`，不直接从 `state.messages` 取。

### 4.2 Observer 解耦（耦合 1/10/17/18/19/20）

**当前**：Agent 和 Executor 都直接调 `observer.xxx()`。

**解耦**：Observer 封装进 `before_tool_call` / `after_tool_call` 的闭包里，主循环不感知。

```python
def _build_observer_hooks(observer: ScreenObserver, ctx: ActionContext):
    """Observer 相关逻辑全部封装在这里，主循环零感知。"""

    def after_tool(ctx: ToolCallContext) -> AfterToolVerdict | None:
        if ctx.result is None:
            return None
        # 效果解读：observation_data → 同步指纹
        obs = ctx.result.observation_data
        if obs is not None:
            text, count = obs
            observer.note_observed(text, count)
            if observer.last_ui is not None:
                ctx.refresh(observer.last_ui)
        return None  # 不修改结果

    return after_tool
```

### 4.3 Guard 解耦（耦合 3/4/5/14/16/21/22）

**当前**：3 个 Guard 实例散落在 Agent 和 Executor 的构造和调用中。

**解耦**：Guard 逻辑全部收敛到 `should_stop_after_turn` 和 `after_tool_call` 回调。

```python
def _build_guard_callbacks(
    progress: ProgressGuard,
    protocol: ProtocolGuard,
    complete: CompleteGuard,
    action_tools: set[str],
    assert_tools: set[str],
) -> tuple[Callable, Callable]:
    """把所有 Guard 逻辑封装成 2 个回调。"""

    def after_tool(ctx: ToolCallContext) -> AfterToolVerdict | None:
        """CompleteGuard.judge_success：complete 后覆盖判定。"""
        if not (ctx.result and ctx.result.is_complete):
            return None
        declared = bool(ctx.result.data.get("success", True))
        success = complete.judge_success(declared, ctx.steps_so_far, action_tools)
        return AfterToolVerdict(
            terminal=True, success=success,
            summary=str(ctx.result.data.get("result", "")),
        )

    def should_stop(ctx: TurnContext) -> StopVerdict:
        """集成所有 Guard 的终止判定。"""

        # 1) max_turns ——已在 while 条件，不需要
        # 2) 停滞检测（ProgressGuard）
        progress.record(observer.fingerprint, observer.element_count)  # ← 需要 observer 引用
        v = progress.check(ctx.last_tool_name, 0)  # consecutive_fails 移入 TurnContext
        if v and v.force_terminal:
            return StopVerdict(terminal=True, success=v.success, summary=v.summary)
        if v and v.kind:
            return StopVerdict(feedback=_load_feedback(v.kind))

        # 3) 协议催促（ProtocolGuard）
        if ctx.last_llm_response and not ctx.last_llm_response.tool_calls:
            v = protocol.on_text_end()
            if v.force_terminal:
                return StopVerdict(terminal=True, success=v.success, summary=v.summary)
            if v.kind:
                return StopVerdict(feedback=_load_feedback(v.kind))

        # 4) assert 回退（CompleteGuard.fallback）
        if ctx.terminal and not ctx.success:
            fb = complete.fallback(ctx.steps, assert_tools, ctx.summary)
            if fb:
                return StopVerdict(terminal=True, success=fb[0], summary=fb[1])

        return StopVerdict()

    return after_tool, should_stop
```

### 4.4 工具执行解耦（耦合 6/15/24）

**当前**：`ToolExecutor` 被 FastAgent 创建，接收 `state + ctx + fire_hook`。

**解耦**：工具执行简化——`before_tool_call` / `after_tool_call` 已经从 config 注入，Executor 只需要 `execute_one(name, args, ctx) -> (Step, ActionResult)`，不再持有任何 Guard 引用。

```python
class ToolExecutor:
    """极简工具执行引擎。只做：解析 tool_use → 逐工具执行 → 收集结果。

    before/after hook 由外部通过 LoopConfig 注入，本类不持有。
    """

    def __init__(self, registry: ToolRegistry):
        self._registry = registry
        self._no_retry = registry.no_retry_tool_names()

    def turn(
        self,
        state: RunState,
        ctx: ActionContext,
        config: LoopConfig,  # ← 接收整个 config，只取其 tool hook
    ) -> tuple[RunState, list[Step], list[dict]]:
        """执行本轮工具。返回 (新 state, 产生的 steps, tool_result 消息块)。"""
        tool_uses = self._parse_tool_uses(state)
        if not tool_uses:
            return state, [], []

        steps: list[Step] = []
        results: list[dict] = []
        terminal = False
        final_success = False
        final_summary = ""

        for tc in tool_uses:
            state = replace(state, step_count=state.step_count + 1)

            # before hook
            before_ctx = ToolCallContext(name=tc["name"], args=tc.get("input", {}),
                                        step_index=state.step_count,
                                        steps_so_far=state.steps)
            before = config.before_tool_call(before_ctx)
            if before and before.block:
                step = Step.fail(index=state.step_count, action=tc["name"],
                                result=before.reason)
                steps.append(step)
                results.append(self._mk_result(tc["id"], step))
                continue

            # 执行
            step = self._execute_one(tc["name"], tc.get("input", {}),
                                    state.step_count, ctx)
            steps.append(step)

            # after hook
            after_ctx = ToolCallContext(name=tc["name"], args=tc.get("input", {}),
                                        step_index=state.step_count,
                                        steps_so_far=state.steps + steps,
                                        result=step.action_result,
                                        is_error=not step.success)
            after = config.after_tool_call(after_ctx)
            if after:
                if after.result_override:
                    step.result = after.result_override
                if after.is_error_override is not None:
                    step.success = not after.is_error_override
                if after.terminal:
                    terminal, final_success, final_summary = True, after.success, after.summary

            results.append(self._mk_result(tc["id"], step))
            if terminal:
                break

        state.steps.extend(steps)
        state.messages.append({"role": "user", "content": results})

        if terminal:
            state = replace(state, terminal=True, success=final_success, summary=final_summary)

        return state, steps, results
```

**关键变化**：`ToolExecutor` 不再 import `CompleteGuard`、`ProgressGuard`、`ScreenObserver`、`ActionContext.refresh`。它只知道 `registry` + `execute_one` + `before/after hook 签名`。

### 4.5 事件分发解耦（耦合 24）

**当前**：`_fire("on_tool_start", ...)` 字符串分发。

**解耦**：主循环持有一个 `EventEmitter`，各回调通过 emitter 发事件。

```python
@dataclass
class EventEmitter:
    """类型化事件分发器。替代字符串 _fire。"""
    _hooks: list[AgentHook] = field(default_factory=list)

    def emit(self, event: "AgentEvent", **data: Any) -> None:
        for h in self._hooks:
            try:
                h.on_event(event, **data)
            except Exception:
                pass
```

短期不强制，但方向是从 `_fire("on_tool_start")` 变成 `emit(AgentEvent.TOOL_START)`。

---

## 五、改造前后对比

### 5.1 FastAgent 的依赖变化

```
改造前 FastAgent.__init__ 参数：
  llm, phonefast, registry,
  max_steps, system_prompt, hooks, force_tool_use,
  protocol_guard, complete_guard, progress_guard, stagnation_exempt_tools
  → 13 个参数，创建 Observer/Context/Executor/Guard 共 6 个内部对象

改造后 FastAgent.__init__ 参数：
  config: LoopConfig,
  hooks: list[AgentHook] | None = None
  → 2 个参数，零内部对象创建
```

### 5.2 ToolExecutor 的依赖变化

```
改造前 ToolExecutor.__init__ 参数：
  registry, observer, progress_guard, complete_guard
  → import 了 CompleteGuard, ProgressGuard, ScreenObserver, PhonefastError
  → turn() 方法需要 state + ctx + fire_hook

改造后 ToolExecutor.__init__ 参数：
  registry
  → 零外部 import（除了 registry 和 Step）
  → turn() 方法需要 state + ctx + config（只取 before/after hook）
```

### 5.3 文件依赖变化

```
改造前：
  fast_agent.py → guards.py, progress.py, hooks.py, context.py,
                  screen_observer.py, tool_executor.py, run_state.py,
                  llm/delegate.py, heal/retry.py

  tool_executor.py → guards.py, progress.py, screen_observer.py,
                     phonefast.py, heal/retry.py, run_state.py

改造后：
  fast_agent.py → run_state.py, llm/delegate.py, heal/retry.py
                  （config 类型定义可放独立 loop_config.py）

  tool_executor.py → heal/retry.py, run_state.py, phonefast.py
                     （不再 import guards.py / progress.py / screen_observer.py）
```

### 5.4 组装点：从分散到集中

```python
# ── 改造前：组装散落在 FastAgent.__init__ 和 ToolExecutor.__init__ ──
agent = FastAgent(
    llm=llm,
    phonefast=pf,
    registry=registry,
    max_steps=15,
    protocol_guard=ProtocolGuard(limit=2),
    complete_guard=CompleteGuard(),
    progress_guard=ProgressGuard(window=3, limit=6),
    hooks=[TrajectoryRecorder()],
)

# ── 改造后：所有组装集中在一处，注入 config ──
config = LoopConfig(
    max_turns=15,
    convert_to_llm=_build_convert(llm),
    transform_context=_build_compressor(),
    before_tool_call=_build_before_hook(observer),
    after_tool_call=_build_after_hook(observer, complete_guard),
    should_stop_after_turn=_build_stop_check(
        progress_guard, protocol_guard, complete_guard,
        action_tools=registry.action_tool_names(),
        assert_tools=registry.expect_tool_names(),
    ),
)
agent = FastAgent(config=config, hooks=[TrajectoryRecorder()])
```

**所有"怎么做"的知识集中到了 config 的组装代码里，主循环只负责"何时调用"。**

---

## 六、与宪法兼容性

| 宪法条款 | 影响 |
|---------|------|
| **第一条：Agent 只收 goal** | 不变 |
| **第二条：防作弊** | 不变 |
| **第六条：状态机 5 上限** | **需要修改**：Guard 仍然存在，但不再"侵入主循环"。上限从"5 个 Guard 类"改为"5 个 config 回调"——回调总数恰好也是 5 |
| **逻辑下沉** | 强化：Guard 逻辑下沉到 config 闭包，主循环不感知 |
| **参数化优于内联** | 强化：config 的所有阈值都是构造参数 |

**第六条修订建议**：

> 旧：状态机总数硬上限 = 5，分散到各自 owner
>
> 新：LoopConfig 回调总数硬上限 = 5（`transform_context` / `convert_to_llm` / `before_tool_call` / `after_tool_call` / `should_stop_after_turn`），新增回调需满足"主循环不应知道此逻辑"标准。Guard 仍可存在（作为回调的默认实现），但主循环不得直接 import Guard 类。

---

## 七、实施路径

### Phase 1：LoopConfig 提取（最优先，改组织不改行为）

1. 定义 `LoopConfig` dataclass + 5 个回调类型
2. 写 `build_default_config(observer, guards, ...)` 工厂函数
3. FastAgent 改为接收 `config: LoopConfig`，内部通过 config 回调驱动
4. **不改任何 Guard/Observer/Executor 内部逻辑**，只改调用方式

### Phase 2：ToolExecutor 瘦身

1. Executor 不再持有 `observer` / `progress_guard` / `complete_guard` 引用
2. 效果解读（observation_data / is_complete）移到 `after_tool_call` 回调
3. Auto-observe 逻辑移到 `after_tool_call` 回调或 `transform_context`

### Phase 3：消息格式边界（可选，低优先级）

1. `convert_to_llm` 成为显式转换点
2. 内部消息格式可以保持与 Anthropic 兼容，但所有 LLM 调用都过这个转换

### 不做

- 不改消息类型（AgentMessage dataclass）——成本高于收益
- 不引入 pi 的 EventStream / Response Stream
- 不添加 `prepareNextTurn` / `getSteeringMessages` 等 fastaget 不需要的回调
