# 架构方案总览——当前问题 + 四种解法

> 2026-07-24
>
> 先对齐问题，再列出所有可能的解法及其代价。选型应该在充分讨论后做，而不是边写边改。

---

## 一、问题对齐

当前 fastaget 有 3 个真实问题 + 1 个感知问题：

### 真实问题

**P1：ToolExecutor 职责爆炸。** `turn()` 方法 118 行，做了 5 件事——解析 tool_use、逐工具执行、效果解读（观察 + complete 判定）、轮末 auto-observe、进度健康检测。同时持有 Observer 和 Guard 引用，违反了"纯设备操作"的设计目标。

**P2：判定点散落，主循环不透明。** `run()` 13 行，看代码完全不知道有 7 个隐性判定分支。ProtocolGuard 藏在 `_llm_turn`，ProgressGuard + CompleteGuard 藏在 `ToolExecutor.turn()`，assert 回退藏在 `_result`。

**P3：状态的持有与使用分离太远。** `ProgressGuard._fingerprints` 在 `tools/progress.py`，`ProtocolGuard._nudges` 在 `agent/guards.py`，`consecutive_fails` 在 `RunState`。看一个行为需要横跳 3 个文件。

### 感知问题

**P4："5 个状态机"的概念负担。** Guard 这个名字暗示"有状态、会转移"，但实际 5 个里只有 2 个（ProgressGuard 指纹窗口、ProtocolGuard nudge 计数）有真正的跨轮状态。CompleteGuard 完全无状态。consecutive_fails 只是一个计数器。max_steps 只是一个数字比较。把简单计数器包装成"状态机"是过度抽象。

---

## 二、四种解法

### 方案 A：全盘 pi 模式

**核心**：引入 `LoopConfig` 对象，把所有行为策略定义为回调函数。主循环只编排生命周期时机，不 import 任何 Guard/Observer/Executor 类。

```python
@dataclass
class LoopConfig:
    transform_context: Callable  # 消息预处理
    convert_to_llm: Callable     # 消息 → LLM 格式
    before_tool: Callable        # 工具执行前拦截
    after_tool: Callable         # 工具执行后修改
    should_stop: Callable        # 统一终止判定
    max_turns: int = 15

class FastAgent:
    def __init__(self, config: LoopConfig, hooks=None):
        self._cfg = config

    def run(self, goal):
        state = self._init(goal)
        while not state.terminal:
            state.messages = self._cfg.transform_context(state.messages)
            state = self._llm_turn(state)
            state = self._execute_tools(state)
            verdict = self._cfg.should_stop(TurnCtx(state))
            if verdict.terminal: ...
```

**删除**：`ToolExecutor` 类、`ProtocolGuard`/`CompleteGuard`/`ProgressGuard` 类、`guards.py`、`progress.py`、`tool_executor.py`。

**收益**：
- 最大解耦——主循环零具体依赖
- 最大可扩展——加能力 = 加回调
- 消息格式可替换（`convert_to_llm` 边界）

**代价**：
- LoopConfig 大概率只有一个实例 → YAGNI 嫌疑
- 闭包调用链深（`run → cfg.should_stop → composed → protocol_check → guard.check`），调试困难
- 打开 fast_agent.py 看不到默认行为——需要追工厂函数找回调组装
- 新增类型多（Config / Context / Verdict / Factory）

**适用**：需要频繁扩展、多 provider、多场景的通用 agent runtime。fastaget 不是。

---

### 方案 B：状态全收 RunState，判定全收 FastAgent 方法（我刚写的）

**核心**：Guard 状态移到 `RunState` 字段，Guard 判定逻辑变成 `FastAgent` 的普通方法。无 config、无回调、无闭包。

```python
@dataclass
class RunState:
    # ...基础字段...
    stagnation_fps: list[str]      # ← 原 ProgressGuard._fingerprints
    stagnation_count: int          # ← 原 ProgressGuard._stagnation_count
    text_only_count: int           # ← 原 ProtocolGuard._nudges
    consecutive_fails: int         # 已有
    last_tool: str                 # 已有

class FastAgent:
    def run(self, goal):
        state = self._init(goal)
        while not state.terminal and state.turn_count < self.max_turns:
            state = self._llm_turn(state)
            if not self._has_tool_calls(state):
                state = self._handle_text_only(state)
            state = self._execute_tools(state)
            state = self._post_turn_checks(state)  # → _check_stagnation / _check_degradation / _check_fails
        return self._build_result(state)  # → _fallback_assert
```

**删除**：`ToolExecutor`、`ProtocolGuard`、`CompleteGuard`、`ProgressGuard`、`guards.py`、`progress.py`、`tool_executor.py`。

**收益**：
- 全部门槛最低——打开 `fast_agent.py`，所有行为都在一个文件里可见
- 无新增概念——没有 Config/Callback/Verdict/Context/Factory
- 调试最简单——直接方法调用，stack trace 清晰
- 代码量明显减少——删 4 个文件，`fast_agent.py` 从 320 行变 ~300 行
- 状态与判定在一起——看 `_check_stagnation` 就知道它在读 `state.stagnation_fps`

**代价**：
- RunState 字段从 11 个涨到 15 个——稍显臃肿但可接受
- 扩展靠改 `FastAgent` 类本身——不满足"开闭原则"，但对于一个稳定的小代码库，这不是实际痛点
- `_check_xxx` 方法直接访问 `self.observer` / `self.registry`——没有像方案 A 那么彻底解耦

**适用**：小团队、稳定需求、优先可读性 > 可扩展性。就是 fastaget 当前的情况。

---

### 方案 C：保留 Guard 但统一调用接口

**核心**：Guard 仍然作为独立类存在，但全部实现统一的 `TurnHook` 接口（`check(state) -> state`），主循环用列表统一编排。

```python
class TurnHook(Protocol):
    def check(self, state: RunState) -> RunState: ...

class StagnationHook:
    def __init__(self, window=3, limit=6): ...
    def check(self, state: RunState) -> RunState: ...

class ProtocolHook:
    def __init__(self, limit=2): ...
    def check(self, state: RunState) -> RunState: ...

class FastAgent:
    def __init__(self, ..., hooks: list[TurnHook] | None = None):
        self._turn_hooks = hooks or [
            StagnationHook(), ProtocolHook(), CompleteHook()
        ]

    def run(self, goal):
        ...
        for h in self._turn_hooks:
            state = h.check(state)  # 统一接口，统一时机
```

**删除**：`ToolExecutor` 类。Guard 类保留但重命名为 Hook，状态仍在 Hook 内部。

**收益**：
- Guard 仍独立可测（每个 Hook 可脱离 FastAgent 单测）
- 主循环统一编排，可见性强
- 接口统一（`check(state) -> state`），不像现在各 Guard 签名不同
- Hook 可替换、可禁用（传 `NullHook`）

**代价**：
- Guard 状态仍在 Hook 内部，调试时需要看两个文件
- 比方案 B 多一层抽象
- 仍然有"新增类"的仪式感

**适用**：需要 Guard 独立测试、希望未来可能扩展但不想要方案 A 的复杂度。

---

### 方案 D：最小改动——只修 ToolExecutor + 可见性

**核心**：不动 Guard 体系，只做两件事：拆 ToolExecutor、提判定点到主循环。

```python
# 1) ToolExecutor.turn() 拆成独立函数
def execute_tool_sequence(messages, registry, ctx, observer):
    """纯函数：解析 → 执行 → 收集结果 → 解读效果。返回 (messages, steps, observed)。"""
    ...

# 2) 主循环显式编排
def run(self, goal):
    state = self._init(goal)
    while not state.terminal and state.step_count < self.max_steps:
        state = self._llm_turn(state)
        # LLM 后检查（原在 _llm_turn 内）
        if not resp.tool_calls:
            state = self._check_protocol(state)
        state = self._execute_tools(state)
        # 工具后检查（原在 executor.turn 内）
        state = self._check_progress(state)
    # 终局回退（原在 _result 内）
    state = self._check_assert_fallback(state)
    return self._result(state)
```

**删除**：`ToolExecutor` 类（改成独立函数）。保留所有 Guard 类。

**收益**：
- 风险最低——Guard 一个不动
- 拆 ToolExecutor 独立可测
- 主循环能看到所有行为时机

**代价**：
- Guard 仍然有 5 个类，状态仍然分散
- 未解决 P3（状态和使用的分离）
- 改了个半成品，后面可能还要再改

**适用**：紧急需要降低 ToolExecutor 复杂度但又不想大改。

---

## 三、四种方案对照

| | A: 全盘 pi | B: 状态收 RunState | C: 统一 Hook 接口 | D: 最小改动 |
|---|---|---|---|---|
| 删除 ToolExecutor | ✅ | ✅ | ✅ | ✅ |
| 删除 Guard 类 | ✅ | ✅ | ❌（重命名） | ❌（保留） |
| 状态位置 | Hook 闭包内 | RunState | Hook 实例内 | Hook 实例内 |
| 判定可见性 | ✅ 全在主循环 | ✅ 全在主循环 | ✅ 全在主循环 | ✅ 部分在主循环 |
| 新增概念 | 5 个（Config/Ctx/Verdict/Factory/Callback） | 0 | 1 个（TurnHook 接口） | 0 |
| 独立可测性 | ✅ 回调独立可测 | ❌ 方法绑定 FastAgent | ✅ Hook 独立可测 | ✅ Guard 已有测试 |
| 调试友好度 | ⭐⭐ 闭包链长 | ⭐⭐⭐ 直接方法调用 | ⭐⭐⭐ 接口调用 | ⭐⭐⭐ 不变 |
| 代码量变化 | +100行 → -100行 | -100 行 | ±0 | -50 行 |
| 默认行为可见 | ❌ 需追工厂函数 | ✅ 在类定义里 | ✅ 在 __init__ 默认参数 | ✅ 不变 |
| 扩展成本 | 加回调 | 改类 | 加 Hook | 改方法+调试点 |
| 宪法改动 | 第六条需改 | 第六条需改 | 第六条需改 | 不改 |

---

## 四、我的判断

**方案 A（全盘 pi）最不适合 fastaget。** 不是为了贬低 pi——pi 的设计在其自身场景（多 provider、流式、双循环、子 agent 编排）下是合理的。但 fastaget 是单模型、单任务、同步执行、稳定 Guard 集合。方案 A 会引入 5 个新概念但只用到 1 个实例，YAGNI 违规明显。闭包调试困难是真实代价。

**方案 B（状态收 RunState）最直接，但 Guard 的独立可测性确实丢了。** 目前 Guard 可以脱离 FastAgent 构造单测（`g = ProtocolGuard(limit=2); g.on_text_end()`），收进 FastAgent 方法后只能集成测。但我认为这个代价可接受——当前的单测本来也测不了"编排逻辑"（什么时机调哪个 Guard），只能测 Guard 自身逻辑。而 Guard 自身逻辑（计数 → 超限 → 返回终结信号）简单到不需要独立单测。

**方案 C（统一 Hook 接口）是 B 和旧设计之间的折中。** 如果你觉得 Guard 的独立可测性很重要，或者未来确实可能频繁新增 Hook（比如 case 定制停滞策略），方案 C 是最合适的。

**方案 D 是过渡性的。** 适合"现在就需要修 ToolExecutor，但 Guard 的事下个版本再说"。

我的建议是 **B 或 C**，取决于你对"Guard 独立可测"这个需求的重视程度。
