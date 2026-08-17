# mobilerun 架构分析与 fastaget 借鉴

> 仓库: https://github.com/droidrun/mobilerun | 主包: `mobilerun/` | 架构: llama_index Workflow 事件驱动
> 分析日期: 2026-07-16

## 摘要

mobilerun 是基于 `llama_index.core.workflow` 的事件驱动 Agent 框架，三种 agent：
- **FastAgent** — 直接执行（ReAct）
- **ManagerAgent** — 规划（plan-execute）
- **ExecutorAgent** — 原子动作执行（单轮）

由 `reasoning` 标志在 `MobileAgent.start_handler` 分发模式。

---

## 1. 提示词分析

### 1.1 文件位置

prompt 用 **Jinja2 模板** 存放在 `mobilerun/config/prompts/<agent>/`，由 `PromptLoader.load_prompt()` 渲染：

- `config/prompts/fast_agent/system.jinja2` + `user.jinja2`
- `config/prompts/executor/system.jinja2`（+ `rev1.jinja2`）
- `config/prompts/manager/system.jinja2`（+ `rev1.jinja2`、`stateless.jinja2`、`trained.jinja2`）

配套解析器：`agent/manager/prompts.py`（`parse_manager_response`）、`agent/executor/prompts.py`（`parse_executor_response`）、`agent/utils/prompt_resolver.py`（用户可覆盖）。支持版本切换（rev1/trained/stateless）。

### 1.2 结构（FastAgent）

7 段：角色定义 → 工具调用格式（XML）→ Context（ui_state/phone_state/memory/chat history）→ Available Tools → Available Secrets → Response Format（few-shot）→ Important Rules。

角色定义极简带语气：
```
You are Mobilerun — a sharp, clever agent that controls {{ platform }} devices
through tools. You've got a dry sense of humor and you read screens like a pro. Be concise.
```

**自定义 XML 协议**（非 OpenAI function-calling）：
```
<function_calls>
<invoke name="TOOL_NAME">
<parameter name="PARAM_NAME">value</parameter>
</invoke>
</function_calls>
```

**parallel_tools 条件分支** — 同一 block 可放多个 invoke 顺序执行，prompt 指导何时批处理：
```
Prefer combining actions in one block when targets are visible and won't move —
e.g. type into a field then tap a button on the same dialog. Use separate calls
when an action may change the screen.
```

**Manager prompt** — plan-execute 规划者，输出固定四段 XML：`<thought>` / `<add_memory>` / `<plan>` / `<request_accomplished success="true|false">`。含 8 条 Guidelines + error_history 触发 `<potentially_stuck>` 块。

**Executor prompt** — "dumb robot"，LITERAL EXECUTION RULE：禁止思考合理性，只字面转换 subgoal 为一个原子动作：
```
You are a dumb robot. Find the exact text/element mentioned in the subgoal ...
Whatever the current subgoal says to do, do that EXACTLY. Do not substitute
with what you think is better. Do not optimize.
```

### 1.3 token 量级

| Prompt | 模板 | 渲染后 |
|--------|------|--------|
| FastAgent | ~600 token | 2500-3000 token（+12工具描述） |
| Manager | ~750 token | 1500-2500 token |
| Executor | ~700 token | 1200-2000 token |

靠 `limit_history`（`LLM_HISTORY_LIMIT*2`）裁剪历史控制总 token。

### 1.4 可借鉴设计

| 设计 | 借鉴建议 |
|------|---------|
| 角色分层 + 机械执行器 | plan-execute 的 executor 禁止"优化"，只字面执行 subgoal |
| `<add_memory>` 跨步记忆 | append-only memory，离开屏幕前存数据，每步注入，减少历史扫描 |
| 错误历史注入 `<potentially_stuck>` | 连续失败 N 次注入失败日志，触发重规划而非死磕 |
| Few-shot 示例内嵌 | system prompt 加 1-2 个完整 trace 示例（thought→tool→observation） |
| parallel_tools 条件分支 | 同屏多动作批处理指令，减少往返 |
| 输出格式校验+重试 | 缺字段时回灌 error_message 让模型重写（`_validate_and_retry`） |
| prompt 可外部覆盖 | `PromptResolver` 支持用户自定义覆盖，便于 A/B 测试 |

---

## 2. Agent Loop 与扩展设计

### 2.1 主循环文件

- **顶层协调器**：`agent/droid/droid_agent.py`（`MobileAgent(Workflow)`）— 模式分发
- **直接执行**：`agent/fast_agent/fast_agent.py`（`FastAgent(Workflow)`）
- **规划**：`agent/manager/manager_agent.py`（`ManagerAgent(Workflow)`）
- **执行**：`agent/executor/executor_agent.py`（`ExecutorAgent(Workflow)`）
- **共享状态**：`agent/droid/state.py`（`MobileAgentState`：message_history/action_history/memory/plan/step_number）

### 2.2 Loop 结构：双模式

**Direct 模式（reasoning=False）— ReAct**：
```
StartEvent → start_handler → FastAgentExecuteEvent → execute_task
  → FastAgent.run() → handle_fast_agent_result → FinalizeEvent
```
FastAgent 内部经典 ReAct：`prepare_chat` → `handle_llm_input`（截图+UI state+调 LLM）→ `handle_llm_output`（解析 XML）→ `execute_code`（dispatch 工具）→ `handle_execution_result`（结果回灌）→ 回 `handle_llm_input`。终止：`complete` 工具 或 `step_number >= max_steps`。

**Reasoning 模式（reasoning=True）— Manager-Executor**：
```
StartEvent → start_handler → ManagerInputEvent
  ↻ run_manager → handle_manager_plan
      ├─ (有 answer) → FinalizeEvent
      └─ (有 subgoal) → run_executor → handle_executor_result → ManagerInputEvent (loop)
```
Manager 是"慢思考"规划者，Executor 是"单轮"执行者（每个 subgoal 独立 Workflow，一次 LLM 调用+一次工具执行）。`handle_executor_result` 错误升级：连续 `err_to_manager_thresh` 次失败置 `error_flag_plan=True`，触发 Manager 重规划。

### 2.3 关键设计

**注入式上下文**（不污染原始历史）：每步把 device_state/screenshot/memory 注入到 ephemeral copy 的最后一条 user message blocks，保留 thinking tokens：
```python
messages_to_send = [self.system_prompt] + copy.deepcopy(limited_history)
# last user msg 追加 <memory> / <device_state> / ImageBlock(screenshot)
# second-last user msg 追加 <previous_device_state>
```

**软错误处理**：无工具调用时回灌提示要求用 `complete`；缺 thought 时回灌"先解释再调用"。`_validate_and_retry` 最多 3 次校验 LLM 输出格式。

### 2.4 扩展机制

| 扩展点 | 机制 |
|--------|------|
| 新工具 | `ToolRegistry.register()` / `register_from_dict()`，`ToolEntry(fn, params, description, deps)`；`deps` 声明设备能力依赖，`disable_unsupported(capabilities)` 自动剔除 |
| 新 agent | `agent/` 下新建子包 + `__init__.py`，独立 `Workflow`，由 `start_handler` 路由 |
| 新 provider | `agent/providers/registry.py` + OAuth（anthropic/openai/gemini） |
| MCP 工具 | `mcp/adapter.py` + `client.py`，外部 server 工具适配进 registry |
| 新 prompt | `config/prompts/<agent>/*.jinja2` + `PromptResolver`，多版本可覆盖 |
| UI state provider | `tools/ui/provider.py` + `screenshot_provider.py` + `ios_provider.py` + `stealth_state.py` |

同一 `ToolRegistry` 服务三种 prompt 格式：FastAgent 用 `get_tool_descriptions_xml()`，Executor 用 `get_tool_descriptions_text()`，Manager 用 `get_signatures(exclude=standard)`。

### 2.5 与 fastaget 对比

| 维度 | mobilerun | fastaget |
|------|-----------|----------|
| 架构 | 双模式：ReAct + Manager-Executor 可切换 | 单一 ReAct loop |
| 工具协议 | 自定义 XML | 原生 Anthropic tool-calling |
| 消息历史 | 注入式上下文（不污染历史，保留 thinking） | 全量历史 |
| 记忆 | `<add_memory>` append-only | 无独立记忆层 |
| 错误处理 | 软纠正 + 错误升级阈值 + 输出校验重试 | 单次失败继续 |
| 扩展 | ToolRegistry + deps 能力声明 + MCP + prompt 版本化 | tools.yml 声明式 |
| 终止 | complete 工具 / max_steps / pending message 取消 | max_steps / complete |

**可借鉴**：
1. 双模式开关（简单 ReAct 省 token，复杂 plan-execute）
2. ToolRegistry deps 能力声明 + `disable_unsupported`
3. 注入式上下文（避免历史膨胀）
4. 错误升级阈值 + LLM 输出校验重试
5. Workflow 事件驱动（支持流式/嵌套子 workflow）

---

## 3. 工具设计

### 3.1 文件位置

- 注册中心：`agent/tool_registry.py`
- 执行上下文：`agent/action_context.py`（`ActionContext`：driver/ui/credential_manager/state_provider）
- 结果类型：`agent/action_result.py`（`ActionResult(success, summary)`）
- UI state：`tools/ui/state.py`、`provider.py`、`screenshot_provider.py`、`stealth_state.py`
- 辅助：`tools/helpers/`（coordinate/element_search/geometry/images）
- 格式化/过滤：`tools/formatters/indexed_formatter.py`、`tools/filters/concise_filter.py`/`detailed_filter.py`
- 原子工具实现：依赖包 `mobilerun_core_local`（非本仓库）

### 3.2 工具清单（12 个，索引+坐标双轨）

| 工具 | 签名 | 层次 |
|------|------|------|
| `click` | `(index: int)` | 原子，索引点击 |
| `click_at` | `(x: int, y: int)` | 原子，坐标点击 |
| `click_area` | `(x1,y1,x2,y2)` | 半复合，区域中心 |
| `long_press` | `(index: int)` | 原子 |
| `long_press_at` | `(x: int, y: int)` | 原子 |
| `type` | `(text, index, clear=False)` | 原子 |
| `type_secret` | `(secret_id, index)` | 复合，凭据管理器注入 |
| `swipe` | `(coordinate, coordinate2, duration=1.0)` | 原子 |
| `system_button` | `(button)` back/home/enter | 原子 |
| `open_app` | `(text)` 按名字/描述打开 | 复合 |
| `wait` | `(duration=1.0)` | 原子 |
| `complete` | `(success, message)` | 流控，Executor 屏蔽 |

### 3.3 签名与返回值

统一 `ActionResult(success: bool, summary: str)`：
```python
if isinstance(result, ActionResult): action_result = result
elif isinstance(result, tuple):      action_result = ActionResult(success=result[0], summary=str(result[1]))
elif isinstance(result, str):        success = not result.startswith("Failed"); ...
```

参数 schema 是简单 dict，`get_param_types()` 生成扁平映射供 XML 解析器类型强转。

### 3.4 抽象层次：双轨设计

每个动作同时提供"索引化"（`click(index)`，依赖 a11y tree 打 index，更稳）和"坐标化"（`click_at(x,y)`，兜底）。`click_area` 居中（容错）。

`requires_coordinate_tools` 标志（screenshot-only 模式）触发 `disable_unsupported`，只保留坐标类工具。

### 3.5 与 fastaget 对比及缺口

fastaget 18 个工具更丰富，mobilerun 有而 fastaget 缺的：

| mobilerun 工具 | 价值 | 借鉴建议 |
|----------------|------|---------|
| `type_secret` + credential_manager | 凭据不进 prompt/历史 | 登录场景加凭据管理，工具只收 secret_id |
| `click_area(x1,y1,x2,y2)` | 区域中心点击，容错 | 处理"按钮区域"类目标 |
| `long_press` / `long_press_at` | 长按手势 | 触发复制/粘贴菜单 |
| `complete(success, message)` | 终止信号结构化 | finish 带 success/failure 语义 |
| `open_app(text)` 自然语言名 | "Calendar" 而非包名 | 加名→包解析层 |
| deps 能力声明 + `disable_unsupported` | 按设备能力裁剪工具集 | 工具声明依赖，自动 hide 不可用 |
| indexed_formatter + concise/detailed filter | UI 粒度可调，控 token | observe 加过滤层级 |
| stealth_state + input_text(wpm) | 模拟人类输入防检测 | 反检测需求 |
| MCP 适配器 | 外部工具无缝接入 | 扩展能力不改核心 |

---

## 4. fastaget Top 5 借鉴建议（按 ROI 排序）

| # | 借鉴项 | 预期收益 | 实现难度 |
|---|--------|---------|---------|
| 1 | **deps 能力声明 + disable_unsupported** | 工具按设备能力自动裁剪，减少 prompt 噪声 | 中（改 ToolRegistry） |
| 2 | **`<add_memory>` 跨步记忆** | 离开屏幕不丢数据，减少历史扫描 | 中（加 memory 层 + 注入） |
| 3 | **错误升级阈值 + 输出校验重试** | 连续失败触发重规划，比单次失败鲁棒 | 低（改 _check_progress） |
| 4 | **双模式开关** | 简单任务 ReAct 省 token，复杂 plan-execute | 高（加 Manager-Executor） |
| 5 | **工具返回值统一 ActionResult(success, summary)** | 便于回灌和 trajectory | 低（fastaget 已接近） |

### 当前 100% 场景下收益最大

- **deps 能力声明** — screenshot-only 模式自动移除 index 工具，避免 LLM 调不可用工具
- **`<add_memory>`** — 安装/登录等多步任务，离开搜索页后仍记得包名/账号
- **错误升级** — 当前 max_stagnation_rounds=6 已部分实现，可升级为"重规划"
