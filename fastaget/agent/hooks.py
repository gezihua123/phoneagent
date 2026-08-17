"""Agent 生命周期 Hook 协议 + 内置实现。

仿 LangChain Callback 的设计模式，零外部依赖：
  - AgentHook: 协议定义（on_llm_call / on_tool_exec / on_step / on_finish）
  - TrajectoryRecorder: 落盘实现，记录完整执行链到 JSONL

用途：
  - 失败归因：出问题时回溯完整轨迹（agents.md §4.3 点名缺失的能力）
  - A/B 对比：不同 prompt 的执行链差异一目了然
  - 调试：verbose=False 时静默落盘，出问题再查看
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fastaget.format.console import Console

if TYPE_CHECKING:
    from fastaget.agent.fast_agent import AgentResult
    from fastaget.agent.types import Step
    from fastaget.llm.delegate import LLMResponse
    from fastaget.tools.registry import ActionResult


@runtime_checkable
class AgentHook(Protocol):
    """Agent 生命周期 Hook 协议。

    每个 Hook 在对应事件发生时被调用。实现方只需定义关心的方法。
    FastAgent 在关键节点调 hook，不吃 hook 自身的异常（hook 抛错不应炸 agent）。
    """

    def on_auto_observe(self, element_count: int, *, screen_text: str = "",
                        image_b64: str | None = None, **kwargs: Any) -> None: ...
    def on_llm_start(self, call_index: int, message_count: int, **kwargs: Any) -> None: ...
    def on_llm_stream(self, *, kind: str, delta: str, call_index: int,
                      **kwargs: Any) -> None:
        """流式增量事件（对应 pi 的 message_update）。

        kind: "thinking_delta" | "text_delta"。delta: 增量文本。
        可选实现——旧 hook 不实现也不报错（getattr 分发 + runtime_checkable）。
        """
        ...
    def on_llm_end(self, call_index: int, text: str, tool_count: int,
                   elapsed: float, cost_usd: float | None, *,
                   response: "LLMResponse | None" = None,
                   usage: dict | None = None, stop_reason: str = "",
                   **kwargs: Any) -> None: ...
    def on_steering(self, *, source: str, text: str, **kwargs: Any) -> None:
        """steering 消息注入时触发（外部注入的运行时纠正消息）。"""
        ...
    def on_tool_start(self, step_index: int, name: str, args: dict, **kwargs: Any) -> None: ...
    def on_tool_end(self, step_index: int, name: str,
                    result: str, elapsed: float, success: bool, *,
                    action_result: "ActionResult | None" = None,
                    **kwargs: Any) -> None: ...
    def on_step(self, step: "Step", **kwargs: Any) -> None: ...
    def on_screen(self, *, source: str, screen_text: str,
                  image_b64: str | None = None, element_count: int = 0,
                  step_index: int | None = None, **kwargs: Any) -> None: ...
    def on_finish(self, result: "AgentResult", **kwargs: Any) -> None: ...


@dataclass
class TrajectoryEntry:
    """一条轨迹记录（线程安全由调用方保证）。"""
    seq: int
    ts: float
    event: str
    data: dict[str, Any]


@dataclass
class ConsoleHook:
    """终端实时进度 Hook：每步输出耗时、内容、token 消耗、结果。

    输出格式（每轮 LLM 调用一个分组）：
      🤖 #1  5.5s · $0.0004
        "目标分析：当前在页面中..."
        🎯 tap_element "更多选项"  0.0s ✓  tapped element[24]
           observe  0.1s ✓  43 elements

      🤖 #2  2.2s · $0.0001
        "页面显示打开按钮，没有更新..."
        🎯 back  0.0s ✓

      ✔ PASS  7 steps · $0.0021  Instagram 已是最新版本
    """

    _step: int = field(default=0, init=False)
    _total_steps: int = 15

    # ---- AgentHook 实现 ----

    def on_auto_observe(self, element_count: int, *, screen_text: str = "",
                        image_b64: str | None = None, **kwargs: Any) -> None:
        print(Console.auto_observe(element_count))

    def on_llm_start(self, call_index: int, message_count: int, **kwargs: Any) -> None:
        pass  # 流式不打印开始，等 end 汇总

    def on_llm_end(self, call_index: int, text: str, tool_count: int,
                   elapsed: float, cost_usd: float | None, *,
                   response: "LLMResponse | None" = None,
                   **kwargs: Any) -> None:
        # 尝试从 response.raw 提取 token 用量
        usage: dict = {}
        if response is not None and getattr(response, 'raw', None):
            usage = response.raw.get("usage", {}) if isinstance(response.raw, dict) else {}
        # LLM 文本预览：上限 100 字符
        _MAX_PREVIEW = 100
        if text:
            one_line = text.replace("\n", " ")
            if len(one_line) > _MAX_PREVIEW:
                preview = one_line[:_MAX_PREVIEW] + "…"
            else:
                preview = one_line
        else:
            preview = ""
        # 视觉分组：非首个 LLM turn 前加空行
        if call_index > 0:
            print()
        print(Console.llm_header(
            call=call_index + 1, elapsed=elapsed, cost=cost_usd,
            inp_tok=usage.get("input_tokens", 0),
            out_tok=usage.get("output_tokens", 0),
            cache_tok=usage.get("cache_read_input_tokens", 0),
        ))
        if preview:
            print(Console.llm_text(preview))

    def on_steering(self, *, source: str, text: str, **kwargs: Any) -> None:
        preview = (text or "").replace("\n", " ")[:100]
        print(Console.steering(source, preview))

    def on_screen(self, *, source: str, screen_text: str,
                  image_b64: str | None = None, element_count: int = 0,
                  step_index: int | None = None, **kwargs: Any) -> None:
        pass  # 工具观察已由 on_tool_end 覆盖；全量文本太冗长

    def on_tool_start(self, step_index: int, name: str, args: dict, **kwargs: Any) -> None:
        self._step = step_index
        args_str = self._fmt_args(name, args)
        print(Console.tool_line(name, args_str), end="", flush=True)

    def on_tool_end(self, step_index: int, name: str,
                    result: str, elapsed: float, success: bool, *,
                    action_result: Any = None,
                    **kwargs: Any) -> None:
        raw = (result or "").replace("\n", " ")
        # 剥掉 to_llm_text() 的 [OK]/[FAILED] 前缀——✓/✗ 已由 tool_done 渲染
        if raw.startswith("[OK] "):
            raw = raw[5:]
        elif raw.startswith("[FAILED] "):
            raw = raw[9:]
        print(Console.tool_done(elapsed, success, raw))

    def on_finish(self, result: "AgentResult", **kwargs: Any) -> None:
        print()
        print(Console.case_result(result.success, result.steps,
                                   result.total_cost_usd, result.summary))

    @staticmethod
    def _fmt_args(name: str, args: dict) -> str:
        """格式化工具参数为简洁单行。"""
        if not args:
            return ""
        if name == "tap":
            v = args.get("label") or args.get("element") or ""
            return str(v)[:24]
        if name == "type":
            return str(args.get("text", ""))[:24]
        if name == "launch":
            return str(args.get("app", ""))[:24]
        if name == "swipe":
            d = args.get("direction", "")
            return str(d)[:24]
        if name == "shell":
            return str(args.get("command", ""))[:30]
        # 通用取第一个非空值
        for v in args.values():
            if v:
                return str(v)[:30]
        return ""


@dataclass
class TrajectoryRecorder:
    """落盘 Hook：把每一步完整记录到 JSONL。

    每条记录是一行 JSON，包含时间戳、事件类型、关键数据。
    事后可逐行回放，定位失败根因。

    Usage::

        recorder = TrajectoryRecorder(output_dir="traces")
        agent = FastAgent.builder(llm, pf, registry).with_hooks([recorder]).build()
        result = agent.run("关闭蓝牙")
        recorder.flush()  # → traces/trace_20260710_143025.jsonl
    """

    output_dir: str = "traces"
    entries: list[TrajectoryEntry] = field(default_factory=list)
    _seq: int = field(default=0, init=False)
    _t_start: float = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._t_start = time.time()
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def _append(self, event: str, **data: Any) -> None:
        self._seq += 1
        self.entries.append(TrajectoryEntry(
            seq=self._seq,
            ts=time.time() - self._t_start,
            event=event,
            data=data,
        ))

    # ---- AgentHook 实现 ----

    def on_auto_observe(self, element_count: int, *, screen_text: str = "",
                        image_b64: str | None = None, **kwargs: Any) -> None:
        self._append("auto_observe", elements=element_count,
                     screen_preview=screen_text[:120])

    def on_llm_start(self, call_index: int, message_count: int, **kwargs: Any) -> None:
        self._append("llm_start", call=call_index, messages=message_count)

    def on_llm_end(self, call_index: int, text: str, tool_count: int,
                   elapsed: float, cost_usd: float | None, *,
                   response: "LLMResponse | None" = None,
                   usage: dict | None = None, stop_reason: str = "",
                   **kwargs: Any) -> None:
        self._append("llm_end", call=call_index,
                     text_preview=text[:120], tool_calls=tool_count,
                     stop_reason=stop_reason,
                     elapsed=round(elapsed, 3), cost_usd=cost_usd)

    def on_llm_stream(self, *, kind: str, delta: str, call_index: int,
                      **kwargs: Any) -> None:
        # thinking 流可能很长，只记增量长度和预览，不落全文
        self._append("llm_stream", call=call_index, kind=kind,
                     delta_len=len(delta), delta_preview=delta[:80])

    def on_steering(self, *, source: str, text: str, **kwargs: Any) -> None:
        self._append("steering", source=source, text_preview=text[:120])

    def on_tool_start(self, step_index: int, name: str, args: dict, **kwargs: Any) -> None:
        self._append("tool_start", step=step_index, tool=name, args=args)

    def on_tool_end(self, step_index: int, name: str,
                    result: str, elapsed: float, success: bool, *,
                    action_result: "ActionResult | None" = None,
                    **kwargs: Any) -> None:
        self._append("tool_end", step=step_index, tool=name,
                     success=success, summary=result[:120],
                     elapsed=round(elapsed, 3))

    def on_step(self, step: "Step", **kwargs: Any) -> None:
        self._append("step", index=step.index, action=step.action,
                     success=step.success, result=step.result[:120],
                     elapsed=round(step.elapsed, 3))

    def on_screen(self, *, source: str, screen_text: str,
                  image_b64: str | None = None, element_count: int = 0,
                  step_index: int | None = None, **kwargs: Any) -> None:
        self._append("screen", source=source, element_count=element_count,
                     screen_preview=screen_text[:120], step_index=step_index)

    def on_finish(self, result: "AgentResult", **kwargs: Any) -> None:
        self._append("finish", success=result.success, summary=result.summary[:200],
                     steps=result.steps, cost_usd=result.total_cost_usd)

    # ---- 落盘 ----

    def flush(self, filename: str | None = None) -> str:
        """写入 JSONL 文件，返回文件路径。"""
        if filename is None:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"trace_{ts}.jsonl"
        path = Path(self.output_dir) / filename
        with open(path, "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps({
                    "seq": e.seq,
                    "ts": round(e.ts, 4),
                    "event": e.event,
                    "data": e.data,
                }, ensure_ascii=False) + "\n")
        return str(path)

    def summary(self) -> dict[str, Any]:
        """返回本次执行的统计摘要。"""
        events = [e.event for e in self.entries]
        return {
            "total_events": len(self.entries),
            "llm_calls": events.count("llm_start"),
            "tool_calls": events.count("tool_start"),
            "warnings": events.count("warning"),
            "final_success": (
                self.entries[-1].data.get("success") if self.entries else None
            ),
            "elapsed_total": round(time.time() - self._t_start, 2),
        }
