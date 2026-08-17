# agent-loop.ts vs fastaget 当前设计：根本差异分析

> 2026-07-24

---

## 一、先看两段主循环代码

### pi/agent-loop.ts 的 `runLoop`

```typescript
async function runLoop(currentContext, newMessages, config, signal, emit, streamFn) {
  // 这不是 class 方法，是一个纯 async function
  // 每个依赖都以参数形式显式传入：context, config, emit, signal, streamFn

  while (true) {                                    // 外层：follow-up 消息
    while (hasMoreToolCalls || pendingMessages) {    // 内层：tool-call 循环
      // 1. emit turn_start
      // 2. process pending messages
      // 3. streamAssistantResponse(currentContext, config, signal, emit, streamFn)
      // 4. if error/aborted → return
      // 5. executeToolCalls(currentContext, message, config, signal, emit)
      // 6. emit turn_end
      // 7. prepareNextTurn?.(turnCtx)            ← 可以切 model/thinking
      // 8. shouldStopAfterTurn?.(turnCtx)         ← 终止判定
      // 9. getSteeringMessages?.()                 ← 检查新消息
    }
    followUpMessages = await config.getFollowUpMessages?.()
    if followUpMessages.length > 0 → continue outer
    break
  }
  emit agent_end
}
```

**关键特征**：函数体内**零 `this` 访问**。所有依赖都是参数。

### fastaget 的 `FastAgent.run()`

```python
def run(self, goal: str) -> AgentResult:
    state = RunState(goal=goal)
    state = self._init(state)                          # self.observer / self.phonefast / self.ctx
    while not state.terminal and state.step_count < self.max_steps:  # self.max_steps
        cost_before = state.cost_usd
        state = self._llm_turn(state)                  # self.llm / self.system_prompt / self._tools / self._protocol
        if state.terminal: break
        turn_cost = state.cost_usd - cost_before
        state = self._executor.turn(state, self.ctx, self._fire, turn_cost_usd)
                                                       # self.ctx / self._fire / self._executor
    return self._result(state, goal)                   # self._complete / self._assert_tools
```

**关键特征**：循环体内**每行都访问 `self.xxx`**。依赖全是通过 `self` 隐式获取的实例属性。

---

## 二、根本差异：函数参数 vs 实例属性

这就是两者最底层的分歧。pi 把循环设计为**纯函数**，fastaget 把循环设计为**类方法**。

### pi 的函数式设计意味着什么

```typescript
// 循环本身是一个纯编排函数，不知道任何具体实现
async function runLoop(
  currentContext: AgentContext,     // 所有状态
  newMessages: AgentMessage[],     // 输出收集
  config: AgentLoopConfig,         // 所有行为策略（回调集合）
  signal: AbortSignal | undefined, // 取消信号
  emit: AgentEventSink,            // 事件输出
  streamFunction: StreamFn,        // LLM 通信
): Promise<void>
```

**5 个参数，循环不依赖任何外部对象。测试时传 5 个 mock 即可。**

### fastaget 的类方法设计意味着什么

```python
def run(self, goal: str) -> AgentResult:
    # self 上挂了 12+ 个属性，循环体通过 self 隐式访问：
    #   self.observer        — ScreenObserver
    #   self.phonefast       — 设备连接
    #   self.ctx             — ActionContext
    #   self.llm             — LLM delegate
    #   self.system_prompt   — 提示词文本
    #   self.registry        — 工具注册表
    #   self._tools          — 工具定义列表
    #   self._hooks          — 生命周期回调列表
    #   self._protocol       — ProtocolGuard
    #   self._complete       — CompleteGuard
    #   self._executor       — ToolExecutor
    #   self._assert_tools   — 断言工具名集合
    #   self.max_steps       — 步数限制
    #   self._force_tool_use — 结构化输出开关
```

**循环通过 `self` 隐式访问了 14 个依赖。测试时需构造完整 FastAgent 实例。**

---

## 三、5 个具体的优势

从 pi 的函数式设计出发，派生出 5 个 fastaget 当前不具备的优势：

### 优势 1：可测试性

**pi**：测试任意生命周期阶段，只需构造对应参数。

```typescript
// 测试"LLM 纯文本结束 → 催促 complete"这个行为
// 只需构造一个 config.shouldStopAfterTurn 回调 + mock context
const config = {
  ...baseConfig,
  shouldStopAfterTurn: makeProtocolNudge({ limit: 2 }),
};
await runLoop(context, [], config, undefined, mockEmit, mockStream);
```

**fastaget**：测试同一个行为，需要构造完整 FastAgent。

```python
# 必须先造 llm / phonefast / registry / observer / executor
agent = FastAgent(llm=mock_llm, phonefast=mock_pf, registry=mock_registry,
                  protocol_guard=ProtocolGuard(limit=2))
agent.run("test goal")
# 但 run() 会调 observer.initial()、llm.complete()、executor.turn()……
# 无法只测 ProtocolGuard，必须连锁 mock 所有依赖
```

**结论**：pi 可以在不启动完整 agent 的情况下测试单个策略。fastaget 不行。

### 优势 2：可扩展性

**pi**：新增一个行为 = 新增一个 config 回调，循环**零改动**。

```typescript
// 加一个"每轮耗时超过 30s 就终止"的超时策略
const config = {
  ...baseConfig,
  shouldStopAfterTurn: async (ctx) => {
    if (ctx.elapsed > 30_000) {
      return { terminal: true, success: false, summary: "timeout" };
    }
    return baseConfig.shouldStopAfterTurn(ctx);  // 组合原判定
  },
};
// runLoop 代码一行不改
```

**fastaget**：新增一个行为 = 新建 Guard 类 + 在 `__init__` 加参数 + 在 `run()` 加调用点。

```python
# 加超时策略：需要 3 处改动
# 1. 新建 TimeoutGuard 类
# 2. FastAgent.__init__ 加 timeout_guard 参数
# 3. run() 循环里加 self._timeout.check(state) 调用
```

**结论**：pi 的新增策略是"组合回调"，fastaget 的新增策略是"改 3 个文件"。

### 优势 3：可替换性

**pi**：替换一个策略就是换一个函数引用。不需要 sub-class，不需要 interface 匹配。

```typescript
// 把"停滞检测"从指纹比对换成 AI 判断——只需换一个回调
const config = {
  ...baseConfig,
  shouldStopAfterTurn: aiBasedStagnationCheck,  // 签名一样即可
};
```

**fastaget**：替换策略需要实现 Guard 接口，注入到 `__init__`，且调用点必须知道这个方法存在。

```python
# ProgressGuard 换 AI 版
class AIProgressGuard:
    def check(self, last_tool, fails) -> GuardVerdict: ...
    def record(self, fp, el_count): ...

agent = FastAgent(..., progress_guard=AIProgressGuard())
# 但 executor.turn() 里硬编码了 self._progress.record() 和 self._progress.check()
# 新的 AIProgressGuard 必须实现完全相同的两个方法，签名一致
```

**结论**：pi 的替换是"换一个函数"，fastaget 的替换是"实现完整接口 + 保证调用点参数兼容"。

### 优势 4：可见性（控制流透明度）

**pi**：读 `runLoop` 函数，你看到**每一个**行为可以介入的时机。

```typescript
// 15 行代码，5 个显式注入点
while (hasMoreToolCalls || pendingMessages.length > 0) {
    // ① 处理 pending 消息
    // ② streamAssistantResponse           ← LLM 调用
    // ③ 检查 error/aborted
    // ④ executeToolCalls                   ← 工具执行（含 before/after hook）
    // ⑤ prepareNextTurn                    ← 可介入：改 model/thinking
    // ⑥ shouldStopAfterTurn                ← 可介入：终止判定
    // ⑦ getSteeringMessages                ← 可介入：新消息注入
}
```

**fastaget**：读 `run()` 看到 3 行，但实际行为分散在 4 个文件。

```python
# run() 里看到：
while not state.terminal and state.step_count < self.max_steps:
    state = self._llm_turn(state)         # → 跳进 _llm_turn → 发现 ProtocolGuard
    state = self._executor.turn(...)      # → 跳进 executor.turn → 发现 ProgressGuard + CompleteGuard
return self._result(state, goal)          # → 跳进 _result → 发现 CompleteGuard.fallback
```

**结论**：pi 的循环是**扁平透明的编排图**，fastaget 的循环是**嵌套的调用树**。

### 优势 5：LLM Provider 无关性

**pi**：内部消息格式 (`AgentMessage`) 与 LLM 协议格式 (`Message[]`) 是两种类型，转换发生在 `convertToLlm` 这一处。

```typescript
// 循环内部全程用 AgentMessage
const messages: AgentMessage[] = context.messages;

//仅在 LLM 调用边界转换
const llmMessages = await config.convertToLlm(messages);

// 换 provider：只改 convertToLlm 实现，循环零改动
```

**fastaget**：全链路裸 dict，格式与 Anthropic API 耦合。

```python
# _init 里构建：
{"role": "user", "content": [{"type": "text", "text": ...}]}

# _llm_turn 里追加：
{"role": "assistant", "content": [{"type": "tool_use", "id": ..., "name": ..., "input": ...}]}

# executor.turn 里追加：
{"role": "user", "content": [{"type": "tool_result", "tool_use_id": ..., "content": ...}]}

# 换 OpenAI provider：需要修改上面 3 处消息构建点
```

**结论**：pi 的消息格式解耦是"一处转换"，fastaget 是"到处耦合"。

---

## 四、对 fastaget 来说，哪些优势真正重要？

| 优势 | fastaget 场景下重要吗？ | 理由 |
|------|:---:|------|
| 可测试性 | ⭐⭐⭐⭐⭐ | 当前单测必须构造完整 agent，阻碍快速迭代 |
| 可扩展性 | ⭐⭐⭐⭐⭐ | 每加一个能力要改 3 个文件，违反"开闭原则" |
| 可替换性 | ⭐⭐⭐⭐ | Guard 替换是理论上的，实际很重 |
| 可见性 | ⭐⭐⭐⭐ | 主循环 3 行但实际 7 个分支，代码审查容易漏 |
| Provider 无关性 | ⭐⭐ | 绑定 deepseek-v4 Anthropic 兼容端点，短期不会换 |

---

## 五、fastaget 应该改什么？改到什么程度？

### 应该改的核心：去掉 `self.xxx` 隐式依赖

当前循环体 `self._llm_turn(state)` → `self._executor.turn(state, self.ctx, self._fire)` → `self._result(state, goal)`——所有依赖都通过 `self` 隐式传入。

pi 的做法是**所有依赖通过 config 显式传入**。对 fastaget 来说，只需要引入一个 `LoopConfig` 对象，把 5 个关键行为收敛成回调：

```python
@dataclass
class LoopConfig:
    # 5 个回调 = 主循环的所有扩展点
    convert_to_llm: Callable  # 消息 → LLM 格式
    before_tool: Callable     # 工具执行前
    after_tool: Callable      # 工具执行后
    should_stop: Callable     # 终止判定（替代 3 个 Guard 的 7 个判定点）
    transform_context: Callable  # 消息预处理

    # 2 个配置值
    max_turns: int = 15
    force_tool_use: bool = True
```

### 改完后的主循环

```python
def run(self, goal: str) -> AgentResult:
    state = self._init(goal)                    # 首轮组装（需要 observer/phonefast，通过闭包注入）
    cfg = self._loop_config

    while not state.terminal and state.turn < cfg.max_turns:
        # ── 消息预处理 ──
        state.messages = cfg.transform_context(state.messages)

        # ── LLM 调用 ──
        llm_msgs = cfg.convert_to_llm(state.system_prompt, state.messages)
        state = self._llm_turn(state, llm_msgs)

        # ── 工具执行 ──
        for tc in self._parse_tool_uses(state):
            before = cfg.before_tool(ToolCtx(name=tc.name, args=tc.input))
            if before.block: ...
            result = self._execute_one(tc.name, tc.input)
            after = cfg.after_tool(ToolCtx(name=tc.name, args=tc.input, result=result))
            if after.terminal: ...

        # ── 终止判定（统一入口，替代 7 个分散判定点）──
        stop = cfg.should_stop(TurnCtx(state))
        if stop.terminal:
            state = replace(state, terminal=True, success=stop.success, summary=stop.summary)

    return AgentResult(...)
```

### 不改的

| pi 特性 | 不改的理由 |
|---------|-----------|
| 双层 while（follow-up 消息） | 单任务执行，无后续消息 |
| 流式 LLM 响应 | 同步调用足够快，流式增加状态管理复杂度 |
| `prepareNextTurn`（切模型） | 单模型 |
| `getSteeringMessages`（消息注入） | 无人机交互 |
| AgentMessage 类型化 | 短期成本高于收益，`convert_to_llm` 回调先留好边界即可 |
| 工具并行执行 | 移动端工具必须串行 |
| abortSignal | 无取消场景 |

### 关键删除

改造后可以删除的东西：

```
删除 ToolExecutor 类          → 工具执行逻辑直接在主循环（本来就是 3 个 for 循环 + before/after 回调）
删除 ProtocolGuard 类         → 逻辑移到 should_stop 回调
删除 CompleteGuard 类         → 逻辑移到 after_tool 和 should_stop 回调
删除 ProgressGuard 类         → 逻辑移到 should_stop 回调（内部仍可保留指纹窗口数据结构）
删除 _fire 字符串分发          → 改为一组类型化 emit 调用
删除 fast_agent.py 中的       → _load_prompt / _load_feedback / _load_domain_template
  模块级 prompt 加载函数        （移到 config 工厂函数或独立模块）
```

**文件依赖从**：
```
fast_agent.py → guards.py, progress.py, hooks.py, context.py,
                screen_observer.py, tool_executor.py, run_state.py,
                llm/delegate.py, heal/retry.py
```

**变成**：
```
fast_agent.py → run_state.py, llm/delegate.py, heal/retry.py, loop_config.py
loop_config.py → guards.py, progress.py, screen_observer.py, context.py  (只在工厂函数里 import)
```

**主循环模块不再 import 任何 Guard / Observer / Context 类。**

---

## 六、宪法适配

| 条款 | 影响 |
|------|------|
| 第六条（状态机 5 上限） | 改为"LoopConfig 回调 5 上限"——回调恰好 5 个 |
| Guard 分散自治 | Guard 数据结构仍存在（如指纹窗口），但判定逻辑收敛到 config 回调，不再作为独立 import |
| 逻辑下沉 | 强化：Guard/Observer 逻辑下沉到 config 闭包/工厂函数，主循环零感知 |
| 参数化优于内联 | 强化：config 的所有阈值都是构造参数，回调可整体替换 |
| 工具名不硬编码 | 不变：`action_tools`/`assert_tools` 仍从 registry 注入 config 工厂 |
