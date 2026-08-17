# 吸收 pi 三个能力的设计：ReAct 循环骨架 / 双循环 / 流式 LLM

> 2026-07-24
>
> 来源：pi/packages/agent/src/agent-loop.ts
> 红线：**ReAct 采样保持一致**——LLM 请求的采样面（model / system prompt / messages 构建 /
> tools / tool_choice / max_tokens / thinking 开关 / cache_control / retry 参数）一律不动。
> 三个能力只改**循环骨架**与**传输方式**，不改任何发给模型的内容。

---

## 〇、采样不动清单（验收红线）

以下内容在本次改造中**禁止变更**：

| 项 | 当前值/位置 | 说明 |
|---|---|---|
| model | `AnthropicHTTPDelegate(model=...)` | 构造参数，不动 |
| system prompt | `meta/prompts/baseline.txt` 等 | 内容与加载方式不动 |
| 首条消息构建 | `_init()`：goal + device ctx + 领域模板 + 屏幕 | 不动 |
| messages 追加格式 | Anthropic dict（user/assistant/tool_result） | 不动 |
| tools 定义 | `registry.definitions()` | 不动 |
| tool_choice | `{"type": "any"}`（force_tool_use 时） | 不动 |
| max_tokens | thinking_max_tokens 提升逻辑 | 不动 |
| thinking 开关 | `_MODEL_CAPABILITIES` 查找 | 不动 |
| cache_control 标记 | system / tools / 最后 2 条 message | 不动 |
| retry 参数 | `LLM_RETRIES=2, BASE_DELAY=1.0` | 不动 |

**允许变更的唯一请求字段**：`body["stream"] = true`（传输层开关，不影响采样分布）。
**响应组装必须透明**：流式收到的最终 `LLMResponse` 与非流式 `complete()` 的解析结果
字段级一致（text / tool_calls / stop_reason / cost_usd）——流式只改变"怎么收"，不改变"收到什么"。

---

## 一、pi 中的三个能力 → fastaget 的吸收形态

| pi 能力 | pi 中的形态 | fastaget 吸收形态 | 不吸收的部分 |
|---|---|---|---|
| ReAct 循环 | `runLoop` 内层：pending→stream→tools→checks | 单 turn 管道：`steering→_llm_turn→_execute_tools→_post_turn_checks` | partial message 原地更新（无 UI 渲染需求） |
| 双循环 | 外层 follow-up + 内层 steering 注入 | 外层 = run 结束时可续跑（可选 follow_up 源）；内层 = 统一 steering 注入点 | 用户在 agent 运行时打字注入（无人交互场景） |
| 流式 LLM | `streamFunction` → EventStream（text/thinking/toolcall delta） | `LLMDelegate.stream()` → Iterator[LLMStreamEvent]，默认 fallback 到 complete() | 流式工具执行（tool_use 到达即执行）——移动端工具串行，收益为零 |

---

## 二、能力 1：ReAct 循环骨架

pi 内层循环的本质结构（每个 turn 四步）：

```
while hasMoreToolCalls or pendingMessages:
    ① 处理 pending 消息（注入到 context，再调 LLM）
    ② 调 LLM（流式收 assistant 消息）
    ③ 执行 tool_calls → tool_results 追加回 context
    ④ turn 末判定（shouldStopAfterTurn）
```

fastaget 当前（v3 简化后）的循环：

```
while not terminal and turn < max_turns:
    _llm_turn          # ②
    _handle_text_only  # ②.5 协议催促（直接 append feedback）
    _execute_tools     # ③
    _post_turn_checks  # ④（直接 append feedback）
```

**差异只有一点**：pi 把"要注入的消息"统一在 ① 处理；fastaget 把 feedback 散落
append 在 ②.5 和 ④ 里。**吸收方式 = 加统一的 pending 注入点，feedback 不再就地 append**：

```python
def run(self, goal):
    state = self._init(goal)
    while not state.terminal and state.turn_count < self.max_turns:
        state.turn_count += 1

        # ① 注入 pending 消息（steering + 上轮检查产生的 feedback）
        state = self._drain_pending(state)

        # ② LLM
        state = self._llm_turn(state)
        if state.terminal: break
        if not self._has_tool_calls(state):
            state = self._handle_text_only(state)   # 改为写 pending_feedback
            continue                               # 有 feedback 待注入 → 回 ①
        if state.terminal: break

        # ③ 工具
        state = self._execute_tools(state, ...)
        if state.terminal: break

        # ④ 轮末检查（改为写 pending_feedback / terminal）
        state = self._post_turn_checks(state)
    return self._build_result(state)
```

配套改动：`RunState` 加一个字段——

```python
pending_feedback: list[str] = field(default_factory=list)
```

`_handle_text_only` / `_check_stagnation` / `_check_degradation` / LLM 失败分支，
从 `state.messages.append(...)` 改为 `state.pending_feedback.append(fb_text)`。
`_drain_pending` 在循环顶部统一注入（顺序：外部 steering 在前，内部 feedback 在后）。

**采样影响**：注入的消息仍是 `{"role":"user","content":[{"type":"text",...}]}`，
文本仍来自 `meta/prompts/feedback/*.txt`——消息内容与现在逐字节一致，只是注入时机
统一到循环顶部。✅ 采样不动。

---

## 三、能力 2：双循环

### 3.1 内层 steering 源

pi 的 `config.getSteeringMessages()` 每轮被询问"有没有要插入的消息"。
fastaget 的吸收形态——一个可选的注入源协议：

```python
# fastaget/agent/steering.py
class SteeringSource(Protocol):
    def poll(self) -> list[str]:
        """每轮循环顶部调用。返回要注入的 user 文本列表（可为空）。"""
        ...
```

两个默认实现：

```python
class QueueSteering:
    """外部注入队列：评测器/人工/监控可在 agent 运行中塞纠正消息。"""
    def __init__(self): self._q: list[str] = []
    def push(self, text: str) -> None: self._q.append(text)
    def poll(self) -> list[str]:
        out, self._q = self._q, []
        return out

class NullSteering:
    def poll(self) -> list[str]: return []
```

`FastAgent.__init__` 加参数 `steering: SteeringSource | None = None`（默认 NullSteering）。
`_drain_pending` 顺序：`steering.poll()` 的消息在前，`state.pending_feedback` 在后。

**用途**：
- 评测 harness 发现设备异常（如弹窗遮挡）→ `push("检测到系统弹窗，请先按 back")`
- 交互调试时人工纠偏
- 为 flow runner 的跨节点信息传递留口

### 3.2 外层 follow-up 循环

pi 的外层：内层循环自然结束（无 tool_call 且无 pending）后，问 `getFollowUpMessages()`，
有新消息则注入继续，否则退出。

fastaget 的吸收形态——**run 结束时可续跑，默认关闭**：

```python
def run(
    self, goal: str,
    *,
    follow_up: Callable[[AgentResult], str | None] | None = None,
) -> AgentResult:
    """外层循环。follow_up=None（默认）时行为与现在完全一致：
    terminal 即返回。给定 follow_up 时，每次 terminal 后询问下一个 goal，
    返回 None 结束；返回新 goal 文本则复用同一 session（messages 保留）续跑。
    """
```

续跑语义：
- `state.terminal` 重置为 False，`text_only_count` / `stagnation_count` 清零（新目标重新计）
- `messages` **保留**（session 连续——模型看得到上一目标的完整轨迹）
- `steps` / `step_count` / `cost_usd` 累计（费用归因连续）
- 最终返回**最后一次** run 的 AgentResult，附 `prior_results` 列表（可选，先不加字段，
  由调用方在 follow_up 回调里自行收集每次的中间结果）

**默认行为零变化**：`follow_up=None` 时外层循环只跑一圈，与当前逐字节等价。

**用途**：
- `flow/runner.py` 多节点 flow 复用 session（当前它复用 FastAgent 实例但消息是断的）
- 交互式调试：`run("打开设置")` → 完成后 → `follow_up` 给 `"再关掉蓝牙"`，同会话续跑

**明确不做**：评测 case 之间**不**走外层循环——评测要求每 case 全新 session
（状态污染红线，宪法），eval_aw 仍然每 case 新建 FastAgent。

---

## 四、能力 3：流式 LLM 响应

### 4.1 接口（delegate.py，新增可选方法）

```python
@dataclass
class LLMStreamEvent:
    """流式增量事件。"""
    type: str          # "thinking_delta" | "text_delta" | "done" | "error"
    delta: str = ""    # 增量文本（thinking/text）
    final: LLMResponse | None = None   # type=="done" 时的完整响应
    error: str = ""                    # type=="error" 时的错误信息

class LLMDelegate:
    def complete(...) -> LLMResponse: ...   # 现有，保留不动

    def stream(self, system, messages, tools, *,
               vision=False, tool_choice=None) -> Iterator[LLMStreamEvent]:
        """可选。默认实现：调 complete() 包成单个 done 事件——
        所有既有 delegate（ScriptedLLM、测试 mock）零改动自动兼容。"""
        resp = self.complete(system, messages, tools, vision=vision, tool_choice=tool_choice)
        yield LLMStreamEvent(type="done", final=resp)
```

**关键**：`stream` 有默认实现，不是抽象方法。既有测试里的 ScriptedLLM / FakeLLM
不用改一行。

### 4.2 AnthropicHTTPDelegate 的 SSE 实现

请求体与 `complete()` **逐字段一致**，仅多 `"stream": true`。
用 `httpx.Client.stream("POST", ...)` + SSE 行解析，消费 Anthropic 事件序列：

```
message_start            → 初始化累积器
content_block_start      → type=thinking/text/tool_use，开新块
content_block_delta      → thinking_delta / text_delta / input_json_delta 累积
content_block_stop       → 块结束；tool_use 块则 json.loads 累积的 input_json
message_delta            → stop_reason + usage（成本计算与 complete 同公式）
message_stop             → 组装最终 LLMResponse，yield done
```

**透明性保证**：组装逻辑复用与 `_parse_response` 相同的字段提取规则——
text 拼接、tool_use 提取（name/input/id）、stop_reason、cost 公式。
thinking 块**只发 trace 事件，不进 assistant 消息**（与当前 `_parse_response`
只解析 text+tool_use 的行为一致，不改采样面）。

### 4.3 agent 侧消费

```python
def _llm_turn(self, state):
    ...
    tool_choice = self._TOOL_CHOICE_ANY if self._force_tool_use else None
    try:
        resp = with_retry(
            lambda: self._stream_collect(state, tool_choice),   # ← 替换 complete 调用点
            retries=self.LLM_RETRIES, base_delay=self.LLM_RETRY_BASE_DELAY,
        )
    except Exception:
        ...  # 现有失败分支不动
    # 后续 assistant 消息组装不动
```

`_stream_collect`：遍历 `self.llm.stream(...)`（参数与 complete 相同）——
- `thinking_delta` / `text_delta` → `self._emit("on_llm_stream", ...)`（trace 用）
- `done` → 返回 `event.final`
- `error` / 迭代器异常 → raise（交给现有 with_retry + 失败分支，**重试语义不变**）

### 4.4 Hook 扩展（向后兼容）

`AgentHook` 协议加可选方法：

```python
def on_llm_stream(self, *, kind: str, delta: str, call_index: int, **kw) -> None: ...
```

`runtime_checkable` + `getattr` 分发——旧 hook（TrajectoryRecorder 等）不实现也不报错。
TrajectoryRecorder 后续可加 stream 事件记录（thinking 长度、首 token 时间），本轮可不做。

### 4.5 价值与边界

**得到的**：
- deepseek-v4-pro thinking（最多 16k tokens）在 trace 中可见——失败归因从
  "看最终结果猜过程"变成"看 thinking 流定位推理跑偏点"
- 长响应首 token 时间可观测（性能归因：网络 vs 推理）
- 为将来"tool_use 到达即执行"留口（本轮不做）

**不做的**：
- 流式工具执行（tool_use 一到就执行）——fastaget 工具串行且单次 <1s，无收益
- 流式中途 abort——无取消场景
- thinking 块回传给模型——当前就不回传，保持一致

**风险点**：deepseek Anthropic 兼容端点的 SSE 事件集是否与官方
Anthropic 一致——**实施第一步必须先验证**：对端点发一次 `stream:true` 请求，
确认事件序列是 `message_start/content_block_*/message_delta/message_stop`。
若网关有方言（如缺 message_start），在 SSE 解析层做兼容，不影响上层设计。

---

## 五、变更清单

| 文件 | 变更 | 采样影响 |
|---|---|---|
| `llm/delegate.py` | +`LLMStreamEvent`、+`stream()` 默认实现 | 无 |
| `llm/anthropic_http_delegate.py` | +`stream()` SSE 实现（请求体仅 +`stream:true`） | 无（请求其余字段逐字节一致） |
| `agent/run_state.py` | +`pending_feedback: list[str]` | 无 |
| `agent/steering.py`（新） | `SteeringSource` 协议 + `QueueSteering`/`NullSteering` | 无 |
| `agent/fast_agent.py` | 循环顶部 +`_drain_pending`；feedback 改为写 pending；`run()` +`follow_up` 参数；`_llm_turn` 调 `_stream_collect` | 无（注入消息内容/格式不变） |
| `agent/hooks.py` | +`on_llm_stream` 可选方法 | 无 |
| 测试 | ScriptedLLM 零改动（stream 默认 fallback）；新增 SSE 解析单测（mock 事件流） | — |

## 六、实施顺序

1. **验证端点 SSE 方言**（先手测一次，决定解析层兼容范围）
2. `delegate.py`：`LLMStreamEvent` + `stream()` 默认实现（全程 fallback，零行为变化）
3. `anthropic_http_delegate.py`：SSE `stream()` 实现 + 单测（mock SSE 流）
4. `fast_agent.py`：`_stream_collect` 接入 `_llm_turn`（fallback 链：stream 异常→retry→仍失败→现有失败分支）
5. `run_state.py` + steering：pending_feedback 统一注入点，feedback 改写 pending
6. `run()` 外层 follow_up 参数 + 续跑语义
7. 回归：全量测试 + 抽 3 个 case 真机对比（改造前后消息序列逐字节 diff，验证采样不动）

**验收标准（采样不动）**：同一 case、同一 seed 环境下，改造前后发给端点的
messages/tools/system/tool_choice 序列完全一致（stream 字段除外）。
