# 公平分析：pi 模式 vs 当前 fastaget 设计

> 2026-07-24
>
> 不预设立场，分别列出 pi 模式的收益和代价，对照 fastaget 的具体情况做判断。

---

## 一、先量化当前代码

| 指标 | 数值 |
|------|------|
| Agent 核心文件 | 4 个（fast_agent / tool_executor / guards / progress） |
| Guard 数量 | 5 个（Protocol / Complete / Progress / max_steps / consecutive_fails） |
| Guard 稳定性 | 高——v2.0 设计后基本没变过 |
| ToolExecutor 职责数 | 5 个（解析 + 执行 + 效果解读 + 轮末观察 + 进度检测） |
| 主循环 `run()` 行数 | 13 行 |
| 主循环隐式依赖（`self.xxx`） | 14 个 |
| 散落在不同模块的判定点 | 7 个 |
| 测试方式 | 集成测试为主（跑完整 case → 看结果） |

---

## 二、pi 模式的收益（如果采用）

### 收益 1：ToolExecutor 职责爆炸被治愈

**当前**：`ToolExecutor.turn()` 做了 5 件事（118 行）。

```python
# turn() 的 5 个职责，强行塞进一个方法：
# A) 解析 tool_use → 9 行
# B) 逐工具执行 + fire_hook → 46 行
# C) 效果解读（observation_data → 同步指纹） → 70 行
# D) 效果解读（is_complete → terminal + 覆盖判定） → 82 行
# E) 轮末 auto-observe → 14 行
# F) 进度健康检测 → 14 行
```

**pi 模式**：每个职责变成一个独立回调，各自独立可测。

**收益评估**：**高**。当前 `turn()` 是 fastaget 里最复杂的单个方法。pi 模式天然强制拆小。

### 收益 2：主循环透明度

**当前**：`run()` 13 行，但看这 13 行你完全不知道：
- LLM 纯文本时有什么行为（藏在 `_llm_turn` 里）
- 停滞检测何时触发（藏在 `executor.turn` 里）
- complete 判定何时生效（藏在 `executor.turn` 和 `_result` 里）

**pi 模式**：所有行为注入点在循环体中显式可见。

**收益评估**：**中高**。对新人理解代码有帮助。但对熟悉代码的人，跳进对应方法看也是 2 秒的事。

### 收益 3：单元可测性

**当前**：测 `ProtocolGuard` 需要 `guard = ProtocolGuard(limit=2); guard.on_text_end()`——其实已经可以独立测。但测"ProtocolGuard 在 agent 循环中何时被调用"需要构造完整 FastAgent。

**pi 模式**：`shouldStopAfterTurn` 回调可以脱离循环独立测试。

**收益评估**：**中**。当前的 Guard 类本身已经独立可测。不可测的是"编排逻辑"（在什么时机调哪个 Guard），但这是一个编排函数，本身就不需要单元测试——集成测试覆盖即可。

### 收益 4：新增行为成本降低

**当前**：加一个能力 = 新建类 + 改 `__init__` 参数 + 改 `run()`/`executor.turn()` 调用点。

**pi 模式**：加一个能力 = 新增回调 + 插入 config 列表。

**收益评估**：**理论上高，实际上低**。因为 fastaget 的 5 个 Guard 已经是稳定集合，过去 3 个版本没有新增第 6 个。为"可能永远不会发生的新增"而重构，是 YAGNI 违规。

### 收益 5：Provider 无关性

**收益评估**：**低**。fastaget 绑定 deepseek-v4 Anthropic 兼容端点，不会换。消息格式边界收益不抵成本。

### 收益 6：LLM 流式 / 双循环 / 并行工具执行

**收益评估**：**零**。这些是 pi 作为通用 agent runtime 的需求，fastaget 不需要。

---

**收益总结**：5 个收益中，1 个高、1 个中高、1 个中、1 个理论、1 个低。净收益是有，但不压倒性。

---

## 三、pi 模式的代价（如果采用）

### 代价 1：调用链变长——调试变难

**当前**：发生问题时的调用链：

```
run() → _llm_turn() → self._protocol.on_text_end()
```
3 层，全是类方法调用。在 stack trace 里一眼看到。

**pi 模式**：

```
run() → cfg.should_stop(turnCtx) → composed_callback() → protocol_check() → guard.on_text_end()
```
5 层，中间多了 2 层匿名/闭包调用。stack trace 里 `composed_callback` 和 `protocol_check` 是闭包，不带类名，定位需要多看一层。

**代价评估**：**中**。不是致命问题，但确实增加了调试心智负担。Python 的 lambda/闭包 traceback 比 TypeScript 更难读（没有函数名）。

### 代价 2：默认行为不再"一眼可见"

**当前**：打开 `fast_agent.py`，`__init__` 里直接看到：

```python
self._protocol = protocol_guard or ProtocolGuard()
self._complete = complete_guard or CompleteGuard()
```

你知道默认用了什么 Guard，参数是什么。

**pi 模式**：需要找到 config 工厂函数（可能在另一个文件），找到 `build_should_stop()`，看到它组合了 `protocol_check` + `progress_check` + `complete_check` 三个闭包，每个闭包内部才调用对应的 Guard。

**代价评估**：**中高**。当前"打开 fast_agent.py 就知道全貌"的体验会变成"追工厂函数 → 追闭包 → 追 Guard"。对维护者是退步。

### 代价 3：Config 对象有且仅有一个实例 = 过度抽象

**当前**：FastAgent 的构造参数就是 default value：

```python
def __init__(self, ..., protocol_guard=None, complete_guard=None, progress_guard=None):
```

不传就用默认。传了就替换。不需要额外的"工厂"概念。

**pi 模式**：引入 `LoopConfig` + 工厂函数 + 回调组装，但实际生产环境只会用默认 config。**为"理论上可替换"而建的抽象，如果从未被替换过，就是废的。**

```python
# 生产代码：
config = build_default_config(llm, observer, guards, ...)  # 每次都是这个
agent = FastAgent(config)

# 如果从来没有写过：
config = LoopConfig(
    should_stop=custom_stop_check,   # ← 这一行从未出现过
)
```

**代价评估**：**中**。pi 的 `AgentLoopConfig` 几乎所有字段都是 optional，且基本只用于默认值。fastaget 如果引入但从未替换过回调，config 对象就是纯 boilerplate。

### 代价 4：类型安全丢失

**当前**：Guard 是具体类，调用 `guard.on_text_end()` → 返回 `GuardVerdict`——IDE 有自动补全和类型检查。

```python
verdict = self._protocol.on_text_end()  # IDE 知道返回 GuardVerdict
if verdict.force_terminal: ...         # IDE 知道 force_terminal 是 bool
```

**pi 模式**：回调是 `Callable[[TurnContext], StopVerdict]`，但闭包内部可以做任何事——类型检查只能保证签名一致，不能保证行为正确。Python 的 Callable 类型比 TypeScript 的函数类型弱得多。

```python
cfg.should_stop(turnCtx)  # IDE 只知道返回 StopVerdict，不知道内部做了什么
```

**代价评估**：**低中**。Python 本来就不是强类型语言，这个代价在 Python 生态里可接受。但对于习惯了 IDE 辅助的开发者是退步。

### 代价 5：新增概念——团队学习成本

**当前**：概念少——Agent、Guard、Observer、Executor、RunState。新人读代码 1 小时能理解。

**pi 模式**：新增 Config、Callback、Factory、Context 对象（TurnContext、ToolCallContext）、Verdict 对象（StopVerdict、AfterToolVerdict、BeforeToolVerdict）。概念数量翻倍。

**代价评估**：**低中**。概念本身不复杂，但积少成多。fastaget 当前的优势之一是"小且易懂"，加概念会稀释这个优势。

---

**代价总结**：5 个代价，2 个中高、2 个中、1 个低中。核心代价是**调试变难 + 默认行为不再一眼可见**。

---

## 四、公平结论

### 两句话总结

**pi 模式解决的真实问题**：ToolExecutor 职责爆炸（118 行做 5 件事）、主循环透明度低（13 行背后 7 个分支）。

**pi 模式引入的新问题**：调用链变长（3 层 → 5 层）、默认行为不可见（要追工厂+闭包）、引入过度抽象（Config 大概率只有一个实例）。

### 对于 fastaget，pi 模式是一个**有收益但也确实有代价**的选择

不是"明显更好"或"明显更差"，而是**拿"调试便利性 + 一眼可见"换"模块解耦 + 可扩展性"**。

在当前阶段（代码量小、Guard 稳定、团队小），这个交易的净收益**略正但不显著**。但如果 fastaget 未来持续膨胀（更多能力、更多设备、更复杂的判定逻辑），pi 模式的解耦收益会越来越大于其抽象代价。

---

## 五、推荐的中间路线

不完全照搬 pi 模式，而是**取其原则、留当前结构**：

### 改 1：ToolExecutor 瘦身（解决最大痛点）

当前 `ToolExecutor` 的 5 个职责拆成独立函数：

```python
def _execute_one_tool(name, args, step_idx, registry, ctx) -> tuple[Step, ActionResult]:
    """纯函数：执行单个工具 + 自愈。零外部依赖。"""
    ...

def _apply_tool_effects(step, ar, state, observer, ctx) -> RunState:
    """纯函数：解读 ActionResult.data 的效果声明。"""
    ...

def _auto_observe_if_needed(had_observation, state, observer, ctx) -> RunState:
    """纯函数：轮末 auto-observe。"""
    ...
```

主循环直接调这些函数，不再通过 ToolExecutor 类中转。

**收益**：ToolExecutor 消失，每个函数 ≤ 30 行，各自独立可测。**没有引入 config/callback/closure 等新概念**。

### 改 2：判定点统一到主循环（解决透明度）

当前 7 个判定点散落在 `_llm_turn` / `executor.turn()` / `_result`。改为在主循环中显式编排：

```python
def run(self, goal):
    state = self._init(goal)
    while not state.terminal and state.turn < self.max_turns:
        # LLM 调用
        state = self._call_llm(state)

        # ── 所有 post-LLM 判定（原来藏在 _llm_turn 里）──
        if self._is_text_only(state):
            state = self._nudge_complete(state)      # ← 原来藏在 _llm_turn 的 ProtocolGuard

        # ── 工具执行 ──
        state = self._execute_tools(state)

        # ── 所有 post-tool 判定（原来藏在 executor.turn 里）──
        state = self._check_stagnation(state)         # ← 原来藏在 executor 的 ProgressGuard
        state = self._check_consecutive_fails(state)  # ← 原来藏在两处

    # ── 终局判定（原来藏在 _result 里）──
    state = self._fallback_assert(state)              # ← 原来藏在 _result 的 CompleteGuard
    return AgentResult(...)
```

**Guard 类仍然存在**，但调用它们的时机**在主循环中一览无余**。不需要 config/callback 抽象。

**收益**：主循环从"13 行看不到全貌"变成"20 行看到全部"。没有引入新概念。

### 改 3：Guard 保持为类，不变成闭包

```python
class FastAgent:
    def __init__(self, ..., guards: list[TurnGuard] | None = None):
        self._guards = guards or [
            ProtocolGuard(limit=2),
            ProgressGuard(window=3, limit=6),
            CompleteGuard(),
        ]

    def _post_turn_checks(self, state):
        for g in self._guards:
            state = g.check(state)
        return state
```

保持 Guard 是具体类（IDE 友好、可独立测试），但调用统一到一个循环里（可扩展）。

### 不做的事

- 不引入 `LoopConfig` 对象——默认只有一个实例的抽象是 YAGNI
- 不引入闭包回调——保留类方法调用（调试友好）
- 不引入 `TurnContext` / `BeforeToolVerdict` 等中间对象——直接用 RunState 和 GuardVerdict
- 不改消息格式——绑定 Anthropic 兼容端点不需要 Provider 无关性

---

## 六、对比总结

| 维度 | 当前 | 全盘 pi | 中间路线 |
|------|------|---------|---------|
| 主循环代码行数 | 13 | 25 | 20 |
| 主循环可见的判定点 | 2（while 条件 + break） | 5 | 6 |
| 需要跳转才能理解的行为 | 7 个 | 0 个 | 0 个 |
| 调试调用链深度 | 3 层 | 5 层 | 3 层 |
| 新增行为成本 | 改 3 文件 | 加 1 回调 | 加类 + 插入列表 |
| 新增概念数 | 0 | 5（Config/Callback/Factory/Context/Verdict） | 0 |
| Guard 独立可测试 | ✅ | ✅ | ✅ |
| 默认行为一眼可见 | ✅ | ❌（工厂+闭包） | ✅ |
| Provider 无关 | ❌ | ✅ | ❌ |
| 代码量变化 | — | +100 行 | -50 行 |
