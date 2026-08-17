# FastAgent 激进简化设计

> 日期: 2026-07-22 | 决策: 纯函数管道 State→State + 保留 RunState + 砍掉其余

## 目标

1. 砍掉所有过度抽象（ProgressMonitor / CompletePolicy / Builder / 多层 Config）
2. 所有 prompt 文本外置（代码中零 fallback）
3. 主循环退化为 4 个纯函数管道，每个 `(RunState) -> RunState`

---

## 一、砍掉清单

| 文件/模块 | 原行数 | 理由 |
|-----------|--------|------|
| `progress_monitor.py` | 216 | 停滞检测退化为 run() 内 3 个 if |
| `policy.py` | 217 | Complete 判定退化为 1 个 if（最后操作失败→覆盖） |
| `agent_builder.py` | 200 | 配置只剩 max_steps + system_prompt，无需 Builder |
| `ProgressConfig` dataclass | ~60 | 13 字段中 10 个过度参数化，阈值固定为合理默认值 |
| `PerceptionConfig` dataclass | ~15 | vision/observe_format 不再需要 |
| `LoggingConfig` dataclass | ~10 | verbose/hooks 直接传参 |
| `RunLimits` dataclass | ~15 | max_steps 直接传参，error_thresh/llm_retries 固定 |
| `_FB_*_FALLBACK` 15 个回退字符串 | ~80 | prompt 一律走外置文件，文件不存在就不注入 |
| `_SYSTEM_PROMPT_FALLBACK` | ~40 | 同上 |
| `_OPTIMIZED_PROMPT_FALLBACK` | ~40 | 同上 |

**总计砍掉 ~900 行**（fast_agent.py 从 1013 → 预计 ~300）。

---

## 二、保留清单

| 模块 | 理由 |
|------|------|
| `RunState` (精简到 11 字段) | 显式状态容器，Claude Code 模式核心 |
| `hooks.py` | 可观测性协议，不干扰主循环 |
| `context.py` (DeviceContext) | 设备上下文注入，独立职责 |
| `screen_observer.py` | observe 去重+压缩，独立职责 |
| `tools/registry.py` | 工具注册+执行，独立职责 |
| `history.py` (MessageHistory) | 消息压缩，可选独立职责 |

---

## 三、核心架构：4 函数管道

```python
def run(self, goal: str) -> AgentResult:
    state = RunState(goal=goal)
    state = self._init(state)          # observe + 构建初始消息
    while not state.terminal and state.step_count < self.max_steps:
        state = self._llm_turn(state)  # 调 LLM → 返回新 State
        if state.terminal:
            break
        state = self._execute(state)   # 执行工具 → 检查 complete
        if state.terminal:
            break
        state = self._observe(state)   # 自动观察 → 停滞/失败检测
    return self._result(state)
```

每个函数签名：**`(RunState) -> RunState`**，用 `dataclasses.replace` 返回新对象。

与 Claude Code 的对应：

| Claude Code | 新 FastAgent |
|---|---|
| `preprocess(messages)` | 砍掉（消息量小） |
| `callModel(state)` | `_llm_turn(state)` |
| `runTools(state)` | `_execute(state)` |
| `injectAttachments(state)` | `_observe(state)` |
| `check maxTurns` | `state.terminal` + `step_count >= max_steps` |

---

## 四、RunState 精简

```python
@dataclass
class RunState:
    goal: str
    messages: list[dict] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    step_count: int = 0
    cost_usd: float = 0.0
    consecutive_fails: int = 0
    # 终局
    terminal: bool = False
    success: bool = False
    summary: str = ""
    # 停滞检测（3 个字段替代 ProgressMonitor 216 行）
    _fingerprints: list[str] = field(default_factory=list)
    _stagnation_count: int = 0
    _last_el_count: int = 0
```

砍掉的 7 个字段：`llm_call_count`/`llm_time_total`/`tool_time_total`/`t_start`/`monitor`/`last_response`/`llm_elapsed`/`tool_results`/`turn_tool_names`/`should_stop`。计时移到 hooks，临时变量不跨阶段共享。

---

## 五、各阶段内部设计

### 5.1 `_init(state)` — observe + 构建首条消息

```
1. observer.initial() → screen_text, el_count
2. DeviceContext.from_phonefast(pf, goal) → dev_ctx
3. _load_domain_template(goal) → domain（plans/*.txt 关键词匹配）
4. system_prompt 从 meta/prompts/baseline.txt 加载
5. 组装首条 user 消息：goal + dev_ctx + domain + screen_text
6. 初始化指纹：state._fingerprints = [observer.fingerprint]
7. fire hook: on_auto_observe
```

砍掉：
- `_needs_plan()`（20 字符判简单/复杂）→ 领域模板本身含 plan 指令
- `verify_mode` 分支（strict/fast 文案追加）→ prompt 文件自行包含
- `MessageHistory` 可选注入 → agent 自己维护 messages list
- `vision` 截图注入 → 不需要

### 5.2 `_llm_turn(state)` — 一次 LLM 调用

```
1. llm.complete(system_prompt, state.messages, tools) → resp
2. 若 resp is None（网络失败）：consecutive_fails += 1，return
3. 成功则 consecutive_fails = 0
4. 无 tool_calls → 模型主动结束：terminal=True, return
5. 追加 assistant 消息到 state.messages
6. fire hook: on_llm_end
```

砍掉：
- 输出校验重试（`_validate_llm_output` + `VALIDATION_MAX_RETRIES`）→ 工具执行层兜底
- 上下文压力检测（`_check_context_pressure`）→ 消息量小不需要
- LLM 网络层重试循环 → 下沉到 `llm.complete()` 内部

### 5.3 `_execute(state)` — 执行工具 + 检查 complete

```
for tc in resp.tool_calls:
    1. registry.execute(tc.name, tc.input, ctx) → result
    2. 记录 step，累加 cost
    3. fire hook: on_tool_start / on_tool_end / on_step
    4. 若 tc.name == "complete"：
       a. success = tc.input.get("success", True)
       b. 唯一判定：最后操作类工具（registry.action_tool_names()）失败 → 覆盖 success=False
       c. terminal=True, return
    5. 追加 tool_result 到 state.messages
    6. 若 tc.name == "observe"：同步 observer 指纹
```

砍掉：
- `CompletePolicy` 协议层 + `DefaultCompletePolicy`（217 行）
- `track_assert` / `apply_fallback`（assert 回退）
- `_has_shell_cheat` 防作弊 → 移到评测层 `verify.py`
- `_recover_device`（L1 设备恢复）→ phonefast 内部处理

### 5.4 `_observe(state)` — 自动观察 + 停滞/失败检测

```
1. 本轮已有 observe → 跳过
2. observer.after_action() → screen_text, el_count
3. 追加屏幕文本到 state.messages
4. 更新指纹：state._fingerprints.append(observer.fingerprint)
5. _check_stagnation(state) → 可能设置 terminal=True
6. _check_consecutive_fails(state) → 可能注入反馈文本
```

砍掉：
- `_prompt_assert_closeup_if_needed`（assert 联动）
- `_inject_memory`（跨步记忆）
- `compress_screen_observations`（消息压缩）

### 5.5 `_check_stagnation(state)` — 内联停滞检测

3 个 if 替代整个 progress_monitor.py：

```python
# 不改变屏幕的工具：停滞计数豁免（shell 查询/back/launch 等）
_STAGNATION_EXEMPT = {"back", "home", "launch", "wait", "shell", "assert"}

def _check_stagnation(state, last_tool_name=""):
    fps = state._fingerprints
    # 1) 停滞：窗口 3 个指纹全相同（但不计豁免工具）
    if len(fps) >= 3 and len(set(fps[-3:])) == 1:
        if last_tool_name not in _STAGNATION_EXEMPT:
            state = replace(state, _stagnation_count=state._stagnation_count + 1)
    else:
        state = replace(state, _stagnation_count=0)

    if state._stagnation_count > 6:
        return replace(state, terminal=True, success=False,
                       summary="屏幕停滞过久，无法继续")

    # 2) 退化：元素骤降到 ≤5 且相对前次 <20%
    if state._last_el_count <= 5 and len(fps) >= 2:
        try:
            prev = int(fps[-2].split(":")[0])
            if prev > 0 and state._last_el_count / prev < 0.2:
                msg = _load_feedback("degradation")
                if msg:
                    state.messages.append(user_msg(msg))
        except ValueError:
            pass

    return state
```

注意：`_STAGNATION_EXEMPT` 是必要的——shell 查询类任务屏幕不变但状态在变，不应计入停滞。

---

## 六、`__init__` 精简

```python
class FastAgent:
    def __init__(
        self,
        llm: LLMDelegate,
        phonefast: Any,
        registry: ToolRegistry,
        *,
        max_steps: int = 15,
        system_prompt: str | None = None,
        hooks: list[AgentHook] | None = None,
    ):
```

**6 个参数** vs 原来 11 个 + 3 个 config dataclass（等价 17 个参数）。

砍掉的参数及原因：
- `error_thresh` → 固定为 3
- `llm_retries` → 固定为 2，下沉到 llm.complete() 内部
- `vision` → 不需要，砍掉视觉模式
- `verify_mode` → prompt 文件自行包含
- `observe_format` → ScreenObserver 默认值
- `verbose` / `verbose_timing` → hooks 覆盖
- `history` 注入 → agent 自己维护 messages
- `device_context` 注入 → _init 内自行采集
- `complete_policy` 注入 → 内联 1 个 if
- `progress_config` 注入 → 内联 3 个 if
- `credential_manager` → tools 自行处理

---

## 七、文件变更清单

### 新增
- （无，只改现有文件）

### 修改
- `fastaget/agent/fast_agent.py` — 主循环重写（1013 → ~300 行）
- `fastaget/agent/run_state.py` — 字段精简（18 → 11）
- `fastaget/agent/__init__.py` — 移除 progress_monitor/policy/agent_builder 导出
- `fastaget/cli.py` — 移除 Builder 调用，改为直接 `FastAgent(llm, pf, registry, max_steps=...)`
- `fastaget/flow/runner.py` — 同上
- `tests/` 相关测试文件 — 适配新接口

### 删除
- `fastaget/agent/progress_monitor.py`
- `fastaget/agent/policy.py`
- `fastaget/agent/agent_builder.py`
- `fastaget/agent/interfaces/agent.py`（Protocol 定义——过度抽象，无运行时价值）

### 不受影响
- `fastaget/agent/hooks.py`
- `fastaget/agent/context.py`
- `fastaget/agent/history.py`
- `fastaget/device/` 全部
- `fastaget/tools/` 全部
- `fastaget/llm/` 全部
- `meta/prompts/` 全部
- `fastaget/verify.py` + `fastaget/eval_aw.py`（评测层）

---

## 八、不变项（宪法合规）

- Agent 只收 goal，自主决策 ✓
- 评测层与 Agent 代码硬隔离 ✓
- 不硬编码工具名/坐标/包名 ✓
- 通用优化优先于 case 特判 ✓
- Context 通过参数注入 ✓
- 异常转结构化结果 ✓
