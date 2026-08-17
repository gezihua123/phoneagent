# 通用能力设计——单任务测试 Agent 的能力模型

> 2026-07-24
>
> 目标：重新定义 fastaget 的"能力"是什么，用统一的生命周期接口替换当前分散的 5 个状态机，降低侵入性。

---

## 一、问题诊断：当前 5 个状态机的"侵入"在哪

### 1.1 现状：3 个模块 × 5 个判定点

```
FastAgent.run()
  ┌─ _llm_turn()
  │     └─ ProtocolGuard.on_text_end()     ← 侵入点 1：LLM 不调 tool 时催 complete
  │
  └─ executor.turn()
        ├─ CompleteGuard.judge_success()    ← 侵入点 2：complete 工具被调时的判定
        ├─ ProgressGuard.record()          ← 侵入点 3：喂指纹
        └─ ProgressGuard.check()           ← 侵入点 4：停滞/退化/连败判定

FastAgent._result()
  └─ CompleteGuard.fallback()             ← 侵入点 5：步数耗尽后的 assert 回退

RunState 自身：
  └─ consecutive_fails 计数               ← 侵入点 6：分散在 _llm_turn 和 executor 两处更新
  └─ max_steps 硬编码在 while 条件         ← 侵入点 7：唯一在主循环可见的判定
```

**侵入性表现在三个维度**：

1. **空间分散**：判定逻辑散落在 `fast_agent.py`、`tool_executor.py`、`guards.py`、`progress.py` 四个文件
2. **时机不一致**：有 LLM 后的、工具执行中的、轮末的、最终收尾的——各自在不同生命周阶段触发
3. **主循环不可见**：`run()` 的 while 循环看起来只有 `_llm_turn` + `executor.turn`，但实际有 7 个隐性分支点

### 1.2 根因：把"通用能力"建模成了"状态机"

回头看这 5 个状态机本质上是什么：

| 状态机 | 真正的通用能力 | 为什么不需要是状态机 |
|--------|-------------|-------------------|
| `ProgressGuard` | **停滞检测**：N 轮屏幕没变化 → 终止 | 指纹窗口是本轮数据，不需要跨轮状态机——每次轮末计算最近 N 轮即可 |
| `ProtocolGuard` | **协议合规**：LLM N 次不调 tool → 催促/终止 | 一个计数器，放 RunState 不比单独 Guard 类更差 |
| `CompleteGuard` | **终局校验**：complete(success=true) 但最后操作失败 → 覆盖 | 无状态——纯扫 steps 历史，不需要是个"Guard" |
| `consecutive_fails` | **容错边界**：连续失败 N 次 → 终止 | 一个 RunState 字段 + 一处判定，不应分散在两处 |
| `max_steps` | **执行边界**：步数上限 | 就是一个数字比较，while 条件就够了 |

**结论**：这 5 个"状态机"其实只有 2 个有真正的跨轮状态（停滞窗口 + 协议计数），另外 3 个是纯判定逻辑。把它们全包装成 Guard 类是过度工程。

---

## 二、重新定义：单任务测试 Agent 的通用能力

一个单任务执行的测试 agent，只需要 **4 个通用能力**：

### 2.1 边界控制（Bounded Execution）

**做什么**：保证 agent 不会无限执行。

- 步数上限（`max_steps`）——确定性终止
- 时间上限（`max_duration`）——适用于慢 case

**为什么是通用能力**：任何 agent 循环都需要，不是测试场景特判。实现就是 while 条件 + 一个计数器。

### 2.2 容错（Fault Tolerance）

**做什么**：区分"可以自动恢复"和"应该放弃"的失败。

- LLM 网络瞬断 → 重试 N 次，超限注入反馈
- 设备 I/O 瞬断 → phonefast warmup + 重新 observe
- 工具执行异常 → 转 ActionResult.fail 喂回 LLM 自愈
- 连续失败边界 → N 次连续失败后终止（而非无限重试）

**为什么是通用能力**：移动设备的网络/daemon 不稳定是普遍约束，不是 case 特判。

### 2.3 停滞感知（Progress Awareness）

**做什么**：检测 agent 是否在无意义循环。

- 屏幕指纹 N 轮不变 → 可能在反复点同一个不存在的按钮
- 页面元素骤降 → 可能跳到了空白页/崩溃
- 连续返回/home/等待 → 豁免（这些工具不以改变屏幕为目的）

**为什么是通用能力**：LLM 会陷入重复模式是通用现象，不针对任何 app 或 case。

### 2.4 收尾协议（Completion Protocol）

**做什么**：确保 agent 以结构化的方式结束，而非"话说到一半就不说了"。

- 强制 LLM 必须调 `complete(success=...)` 或 `assert(passed=...)` 结束
- LLM 用纯文本结束 → 提醒它调 complete
- complete 声称成功但最后操作失败 → 覆盖为失败
- 步数耗尽前已 assert 通过 → 视为成功（回退）

**为什么是通用能力**：测试 agent 必须给出明确的 pass/fail + 原因，不能含糊结束。

---

## 三、统一接口：Capability = 生命周期回调

### 3.1 核心思想

**一个通用能力 = 一组生命周期回调，签名统一为 `(RunState) -> RunState`**。

不做独立的"Guard 类 + 各自调用时机"，改为：
- 所有能力实现同一个 `Capability` 接口（4 个生命周期方法）
- 主循环在每个生命周期点**遍历所有能力**，依次调用
- 每个能力可以：返回原 state（无操作）、注入消息、设置 terminal

### 3.2 生命周期定义

```
run(goal)
  │
  ├─ _init                     # 首轮 observe + 设备上下文 + 消息组装
  │
  └─ while not terminal:
       │
       ├─ 【pre_turn】          ← 能力介入点 1：LLM 调用前
       │   判断：上下文压力？连续失败？该不该继续？
       │
       ├─ _llm_turn             ← LLM 调用
       │
       ├─ 【post_llm】          ← 能力介入点 2：LLM 返回后、工具执行前
       │   判断：LLM 纯文本？模型报错？该不该催 complete？
       │
       ├─ executor.turn()       ← 工具执行
       │
       ├─ 【post_turn】         ← 能力介入点 3：工具执行后、下一轮前
       │   判断：停滞？退化？该不该终止？
       │
       └─ (loop back)

  └─ _result
       │
       └─ 【finalize】          ← 能力介入点 4：结果组装时
           判断：assert 回退？summary 修正？
```

**4 个介入点，统一签名，统一编排。主循环一目了然。**

### 3.3 Capability 接口

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass
class CapabilityResult:
    """能力介入后的产出：修改后的 state + 可选副作用标记。"""
    state: "RunState"          # 修改后的 state（可能 terminal/success 已变）
    feedback: str = ""         # 非空时注入到 messages 的反馈文本
    event: str = ""            # 非空时触发 hook 事件

class Capability(Protocol):
    """通用能力接口——单任务测试 agent 的 4 个生命周期介入点。

    每个方法签名统一：(RunState) -> RunState。
    能力可以持有内部状态（如停滞窗口），但对外接口统一。
    """

    def pre_turn(self, state: "RunState") -> "RunState":
        """LLM 调用前。例如：上下文压力检测。"""
        ...

    def post_llm(self, state: "RunState") -> "RunState":
        """LLM 返回后。例如：纯文本催促 complete。"""
        ...

    def post_turn(self, state: "RunState") -> "RunState":
        """工具执行后。例如：停滞检测。"""
        ...

    def finalize(self, state: "RunState") -> "RunState":
        """结果组装时。例如：assert 回退。"""
        ...
```

### 3.4 主循环改造

```python
def run(self, goal: str) -> AgentResult:
    state = RunState(goal=goal)
    state = self._init(state)

    while not state.terminal and state.turn_count < self._max_turns:
        # ── pre_turn：所有能力在 LLM 前检查 ──
        for cap in self._capabilities:
            state = cap.pre_turn(state)
        if state.terminal:
            break

        # ── LLM 调用 ──
        state = self._llm_turn(state)
        if state.terminal:
            break

        # ── post_llm：LLM 返回后检查（纯文本？报错？）──
        for cap in self._capabilities:
            state = cap.post_llm(state)
        if state.terminal:
            break

        # ── 工具执行 ──
        cost_before = state.cost_usd
        state = self._executor.turn(state, self.ctx)
        if state.terminal:
            break

        # ── post_turn：工具执行后检查（停滞？退化？）──
        for cap in self._capabilities:
            state = cap.post_turn(state)

    # ── finalize：结果组装前最后检查 ──
    for cap in self._capabilities:
        state = cap.finalize(state)

    return self._result(state)
```

**对比当前**：

```python
# 当前 run()：看起来只有 2 步，实际有 7 个隐性分支
while not state.terminal and state.step_count < self.max_steps:
    state = self._llm_turn(state)       # ← ProtocolGuard 藏在这里
    if state.terminal: break
    state = self._executor.turn(...)    # ← ProgressGuard + CompleteGuard 藏在这里
return self._result(state, goal)        # ← CompleteGuard.fallback 藏在这里
```

改造后的主循环**完全透明**：每个生命周期点，所有能力的介入都可见。

---

## 四、现有 Guard → Capability 的映射

### 4.1 容错能力（FaultTolerance）

```python
@dataclass
class FaultTolerance:
    """容错：LLM 重试 + 设备恢复 + 连续失败边界。"""
    max_consecutive_fails: int = 3
    llm_retries: int = 2
    _consecutive_fails: int = 0  # 内部状态

    def pre_turn(self, state: RunState) -> RunState:
        # 连续失败边界 → 终止
        if self._consecutive_fails >= self.max_consecutive_fails:
            return replace(state, terminal=True, success=False,
                          summary=f"连续 {self._consecutive_fails} 次失败")
        return state

    def post_llm(self, state: RunState) -> RunState:
        # LLM 调用成功 → 重置（通过外部传入，此处只读取）
        return state

    def post_turn(self, state: RunState) -> RunState:
        # 本轮工具全失败 → 计数+1；有成功 → 重置
        if self._all_tools_failed(state):
            self._consecutive_fails += 1
        else:
            self._consecutive_fails = 0
        return state

    # 无 finalize 介入
```

**替代**：`consecutive_fails` 字段 + `_llm_turn` 和 `executor` 两处散落的计数更新逻辑。

### 4.2 停滞感知（StagnationDetector）

```python
@dataclass
class StagnationDetector:
    """停滞感知：指纹窗口 + 元素变化检测。"""
    window: int = 3
    limit: int = 6
    exempt_tools: frozenset[str] = field(default_factory=lambda: frozenset({
        "back", "home", "launch", "wait", "shell", "assert",
    }))
    _fingerprints: list[str] = field(default_factory=list)
    _count: int = 0
    _last_el: int = 0

    def feed(self, fingerprint: str, el_count: int) -> None:
        """外部喂观测数据（每轮调一次）。"""
        ...

    def post_turn(self, state: RunState) -> RunState:
        last_tool = self._last_action(state)
        if last_tool in self.exempt_tools:
            return state

        # 窗口内指纹全相同 → 停滞计数+1
        # 超限 → terminal；否则 → 注入 feedback
        ...
```

**替代**：`ProgressGuard`（完全相同的逻辑，只是接口从 `check()` 变成 `post_turn()`）。

### 4.3 收尾协议（CompletionProtocol）

```python
@dataclass
class CompletionProtocol:
    """收尾：强制 complete 调用 + 终局校验。"""
    _nudge_limit: int = 2
    _nudges: int = 0
    _action_tools: set[str] = field(default_factory=set)
    _assert_tools: set[str] = field(default_factory=set)

    def post_llm(self, state: RunState) -> RunState:
        """LLM 纯文本（无 tool_call）→ 催促 complete 或终止。"""
        if self._has_tool_calls(state):
            self._nudges = 0  # 有 tool call → 重置
            return state

        if self._nudges < self._nudge_limit:
            self._nudges += 1
            return self._inject_feedback(state, "require_complete")

        return replace(state, terminal=True, success=False,
                      summary="LLM 多次以纯文本结束而未调 complete")

    def post_turn(self, state: RunState) -> RunState:
        """complete 被调后：检查'声称成功但最后操作失败'。"""
        if not state.terminal:
            return state
        if not state.success:
            return state
        # 扫 steps：最后一个操作类工具失败 → 覆盖
        ...
        return state

    def finalize(self, state: RunState) -> RunState:
        """终局回退：步数耗尽但已 assert(passed=true) → 视为通过。"""
        if state.success or state.terminal:
            return state  # 正常终止的不走回退
        # 扫 steps：最近一次 assert(passed=true) → 视为成功
        ...
```

**替代**：`ProtocolGuard`（post_llm 部分）+ `CompleteGuard.judge_success`（post_turn 部分）+ `CompleteGuard.fallback`（finalize 部分）——**一个能力统一了三个 Guard**。

### 4.4 边界控制（BoundedExecution）

这个最简单——不需要独立 Capability，直接在主循环的 while 条件里：

```python
while not state.terminal and state.turn_count < self._max_turns:
```

`max_turns` 是 `FastAgent` 的构造参数。如果需要时间上限，加一个 `max_duration` + `pre_turn` 检查即可。

---

## 五、对比总结

| 维度 | 当前（5 状态机） | 改造后（4 通用能力） |
|------|---------------|-------------------|
| 能力数量 | 5 个 Guard + 2 个隐式计数 | 3 个 Capability + 1 个 while 条件 |
| 介入点 | 7 个，散落在 3 个模块 | 4 个生命周期点，全在主循环可见 |
| 接口统一性 | 各 Guard 签名不同（`on_text_end` / `check` / `judge_success` / `fallback`） | 统一 `(RunState) -> RunState` |
| 主循环透明度 | 看 `run()` 不知道有 7 个分支 | `run()` 里每个生命周期点显式列出所有能力 |
| 新增能力 | 需要新建 Guard 类 + 找插入点 + 改主循环 | 新建 Capability + 加到 `_capabilities` 列表 |
| 内部状态 | Guard 自持（对） | Capability 自持（对） |
| 测试 | 每个 Guard 独立测（对） | 每个 Capability 独立测（对） |

### 关键简化

原来 5 个 Guard 被合并为 3 个 Capability：

```
CompleteGuard ─────────┐
ProtocolGuard ─────────┼─→ CompletionProtocol（1 个能力，3 个生命周期介入点）
                       │     post_llm:   催促 complete
                       │     post_turn:  操作失败覆盖
                       │     finalize:   assert 回退

ProgressGuard ──────────→ StagnationDetector（1 个能力，1 个介入点）
                             post_turn:  停滞/退化/连败检测

consecutive_fails ─────┐
_llm_turn 中的重试逻辑 ─┼─→ FaultTolerance（1 个能力，2 个介入点）
                            pre_turn:   连续失败边界
                            post_turn:  成/败计数

max_steps ──────────────→ while 条件（不需要能力封装）
```

---

## 六、能力注册与默认组合

```python
class FastAgent:
    def __init__(
        self,
        llm, phonefast, registry,
        *,
        max_turns: int = 15,
        system_prompt: str | None = None,
        hooks: list[AgentHook] | None = None,
        capabilities: list[Capability] | None = None,  # ← 新参数
        force_tool_use: bool = True,
    ):
        self._max_turns = max_turns
        self._capabilities = capabilities or self._default_capabilities(registry)

    @staticmethod
    def _default_capabilities(registry: ToolRegistry) -> list[Capability]:
        """默认能力组合：容错 + 停滞 + 收尾。"""
        return [
            FaultTolerance(max_consecutive_fails=3),
            StagnationDetector(
                exempt_tools=frozenset({"back", "home", "launch", "wait",
                                        "shell", "assert"}),
            ),
            CompletionProtocol(
                action_tools=registry.action_tool_names(),
                assert_tools=registry.expect_tool_names(),
            ),
        ]
```

**扩展方式**：只需实现 `Capability` 接口，加到列表即可：

```python
# 自定义：每个 case 超时 60 秒
class TimeoutCapability:
    def __init__(self, max_seconds: int = 60):
        self._deadline = time.time() + max_seconds

    def pre_turn(self, state: RunState) -> RunState:
        if time.time() > self._deadline:
            return replace(state, terminal=True, success=False,
                          summary="任务超时")
        return state

agent = FastAgent(
    llm, pf, registry,
    capabilities=[
        FaultTolerance(),
        StagnationDetector(),
        CompletionProtocol(...),
        TimeoutCapability(max_seconds=60),  # ← 只加一行
    ],
)
```

---

## 七、与宪法的兼容性

| 宪法条款 | 当前 | 改造后 |
|---------|------|-------|
| **第六条：状态机 5 上限** | 5 个 Guard 占满配额 | 3 个 Capability（不称为"状态机"），本质是 4 个生命周期回调 |
| **分散到各自 owner** | Guard 自持状态 ✓ | Capability 自持状态 ✓ |
| **需才可加** | 当前 5 个满足 | 改为 3 个（合并冗余），新增需四条件全中 |
| **不集中 agent 主循环** | Guard 散落多处但主循环不可见 | 主循环可见编排，但判定逻辑在 Capability 内部 |
| **工具名从 registry 注入** | ✓ | ✓（不变） |
| **阈值构造参数化** | ✓ | ✓（不变） |

**宪法第六条需要调整**：不再以"状态机数量"为约束，改为**"通用能力数量 + 每个能力 ≤ 2 个生命周期介入点"**。理由：
- 状态机数量是手段，不是目标——真正的目标是**控制复杂度、保持可理解性**
- 3 个 Capability × 平均 2 个介入点 = 6 个判定路径，比原来的 7 个隐性分支更少且更可见
- Capability 接口统一，新增能力的边际复杂度远低于新增 Guard

---

## 八、不做的事

1. **不引入 pi 的 Plugin Config 对象**：fastaget 不需要 `getApiKey`/`prepareNextTurn`/`getSteeringMessages` 等通用 agent runtime 才需要的回调。Capability 接口就是 fastaget 的全部扩展点。

2. **不引入 Middleware Chain 模式**：Capability 之间不需要"短路"（一个返回 terminal 后跳过后续）——这个逻辑已经在 while 循环的 `if state.terminal: break` 里了。每个生命周期点内 Capability 按序执行，任何一个设置 terminal 后在**当前介入点**内继续执行（让所有能力都有机会记录状态），但 while 循环在下一个介入点前看到 terminal 就 break。

3. **Capability 之间不互相依赖**：每个 Capability 只依赖 RunState + 自身内部状态，不依赖其他 Capability 的执行结果。这是比 Middleware Chain 更简单的约束。

4. **不改变 Effect-as-Data**：工具仍然通过 `ActionResult.data` 声明效果（`observation_data`/`is_complete`），Capability 只消费这些声明做判定，不替代 Effect-as-Data。
