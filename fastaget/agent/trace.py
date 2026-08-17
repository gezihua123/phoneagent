"""执行轨迹日志：把 FastAgent 每一步录成「LLM 动作重放」图。

产物（按 session 维度）：
  build/traces/<session_id>.trace.jsonl  — 按序事件流（一行一事件，含 session + run 前缀）
  build/traces/<session_id>.replay.json  — 结构化日志图：
      session 元数据 + runs[]（每个 run 含 nodes/edges/outcome）

SessionReplay 是 AgentHook 实现，以 session 为维度聚合多个 run。
内部委托给 per-run ReplayLogger，session 结束统一落盘。

设计要点：
  - 默认关：make_replay_logger(enabled=False) 返回 None，零开销。
  - faithful：屏幕只在 agent 实际 observe 时记录
  - on_finish 收集 run graph，不单独落盘
  - Session.flush() 统一写入 session 级文件
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastaget.agent.hooks import AgentHook

if TYPE_CHECKING:
    from fastaget.agent.fast_agent import AgentResult
    from fastaget.agent.types import Step
    from fastaget.llm.delegate import LLMResponse
    from fastaget.tools.registry import ActionResult

SCHEMA_VERSION = "2.0"

# 事件类型常量
EV_RUN_START = "run_start"
EV_SCREEN = "screen"
EV_LLM_START = "llm_start"
EV_LLM_END = "llm_end"
EV_TOOL_START = "tool_start"
EV_TOOL_END = "tool_end"
EV_STEP = "step"
EV_FINISH = "finish"

# 屏幕来源
SRC_INITIAL = "initial_observe"
SRC_OBSERVE_TOOL = "observe_tool"
SRC_AUTO_AFTER_ACTION = "auto_observe_after_action"
SRC_RECOVERY = "device_recovery"


def slugify(text: str, maxlen: int = 40) -> str:
    """把任意文本压成文件名安全的短 slug（保留中文字符）。"""
    s = re.sub(r"[^0-9a-zA-Z一-龥]+", "_", str(text)).strip("_").lower()
    return (s[:maxlen] or "run")


def gen_run_id(*, scenario: str | None, variant: str, prompt: str,
               fmt: str, seq: int, goal: str | None) -> str:
    """按 run 维度生成稳定 run_id。scenario 优先，否则用 goal slug。"""
    name = scenario if scenario else (goal or "run")
    return f"{slugify(name)}_{variant or 'base'}_{prompt or 'p'}_{fmt or 'f'}_{seq:03d}"


def extract_usage(response: "LLMResponse | None") -> dict[str, Any]:
    """从 LLMResponse.raw['usage'] 归一提取 token 用量（兼容 Anthropic / DeepSeek key）。"""
    if response is None:
        return {}
    raw = getattr(response, "raw", None)
    if not isinstance(raw, dict):
        return {}
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return {}
    return {
        "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens") or 0,
        "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens") or 0,
        "cache_read_input_tokens": usage.get("cache_read_input_tokens") or 0,
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens") or 0,
    }


def _step_dict(step: "Step") -> dict[str, Any]:
    return {
        "index": step.index,
        "action": step.action,
        "args": step.args,
        "success": step.success,
        "elapsed": round(step.elapsed, 4),
        "cost_usd": step.cost_usd,
        "healed": step.healed,
    }


@dataclass
class ReplayLogger:
    """AgentHook 实现：把一次 agent.run() 录成重放图。

    生命周期：begin_run() → (hook 事件流) → on_finish() 自动 flush()+reset()。
    FlowRunner 复用同一实例时，每个 node 调一次 begin_run，on_finish 负责隔离。
    """

    output_dir: str = "build/traces"
    run_id: str | None = None
    enabled: bool = True
    capture_images: bool = False
    auto_observe_after_action: bool = False
    action_tool_names: set[str] = field(default_factory=set)

    # 运行时依赖（faithful 模式下 phonefast 仅用于只读 current_screen_key）
    _phonefast: Any = field(default=None, repr=False)
    _processor: Any = field(default=None, repr=False)

    # per-run 缓冲
    _meta: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _nodes: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _edges: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _raw: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _screen_index: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _current_node_id: str | None = field(default=None, init=False, repr=False)
    _pending_turn: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _turn_start_node: str | None = field(default=None, init=False, repr=False)
    _seq: int = field(default=0, init=False, repr=False)
    _llm_call_index: int = field(default=0, init=False, repr=False)
    _t_start: float = field(default=0.0, init=False, repr=False)
    _run_active: bool = field(default=False, init=False, repr=False)

    # ---- 配置 ----

    def configure(
        self,
        *,
        phonefast: Any | None = None,
        processor: Any | None = None,
        action_tool_names: set[str] | None = None,
        auto_observe_after_action: bool | None = None,
        capture_images: bool | None = None,
    ) -> "ReplayLogger":
        """注入运行时依赖（phonefast/processor）与富模式开关。返回 self。"""
        if phonefast is not None:
            self._phonefast = phonefast
        if processor is not None:
            self._processor = processor
        if action_tool_names is not None:
            self.action_tool_names = set(action_tool_names)
        if auto_observe_after_action is not None:
            self.auto_observe_after_action = auto_observe_after_action
        if capture_images is not None:
            self.capture_images = capture_images
        return self

    # ---- run 生命周期 ----

    def begin_run(
        self,
        goal: str,
        *,
        scenario: str | None = None,
        variant: str = "",
        prompt: str = "",
        fmt: str = "",
        seq: int = 0,
        model: str | None = None,
        max_steps: int | None = None,
        vision: bool = False,
    ) -> None:
        """开始一个 run：写 meta + run_start 事件，重置 per-run 缓冲。"""
        from datetime import datetime
        self.reset()
        if not self.run_id:
            self.run_id = gen_run_id(
                scenario=scenario, variant=variant, prompt=prompt,
                fmt=fmt, seq=seq, goal=goal,
            )
        self._meta = {
            "run_id": self.run_id,
            "goal": goal,
            "model": model,
            "max_steps": max_steps,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "scenario": scenario,
            "variant": variant,
            "prompt": prompt,
            "format": fmt,
            "seq": seq,
            "vision": vision,
            "agent_version": "fastaget",
        }
        self._t_start = time.time()
        self._run_active = True
        self._append_raw(EV_RUN_START, **{k: v for k, v in self._meta.items()
                                          if k in ("run_id", "goal", "model", "max_steps",
                                                   "scenario", "variant", "prompt", "format", "seq")})

    def reset(self) -> None:
        """清空 per-run 缓冲 + run_id，供下一次 begin_run 重新生成。"""
        self.run_id = None
        self._meta = {}
        self._nodes = []
        self._edges = []
        self._raw = []
        self._screen_index = {}
        self._current_node_id = None
        self._pending_turn = None
        self._turn_start_node = None
        self._seq = 0
        self._llm_call_index = 0
        self._t_start = 0.0
        self._run_active = False

    # ---- AgentHook 实现 ----

    def on_auto_observe(self, element_count: int, *, screen_text: str = "",
                        image_b64: str | None = None, **kwargs: Any) -> None:
        if not self.enabled or not self._run_active:
            return
        self._record_screen(SRC_INITIAL, screen_text or "", image_b64,
                            element_count, step_index=None)

    def on_screen(self, *, source: str, screen_text: str,
                 image_b64: str | None = None, element_count: int = 0,
                 step_index: int | None = None, **kwargs: Any) -> None:
        if not self.enabled or not self._run_active:
            return
        self._record_screen(source, screen_text or "", image_b64,
                            element_count, step_index)

    def on_llm_start(self, call_index: int, message_count: int, **kwargs: Any) -> None:
        if not self.enabled or not self._run_active:
            return
        # 收尾上一轮（若有），用当前屏幕作为上一轮 edge 的 to_node
        self._finalize_turn()
        self._pending_turn = {
            "call_index": call_index,
            "reasoning_text": "",
            "tool_calls": [],
            "tool_results": [],
            "stop_reason": "",
            "cost_usd": None,
            "usage": {},
            "elapsed_ms": 0.0,
        }
        self._turn_start_node = self._current_node_id
        self._llm_call_index = max(self._llm_call_index, call_index + 1)
        self._append_raw(EV_LLM_START, call_index=call_index, message_count=message_count)

    def on_llm_end(self, call_index: int, text: str, tool_count: int,
                   elapsed: float, cost_usd: float | None, *,
                   response: "LLMResponse | None" = None,
                   usage: dict | None = None, stop_reason: str = "",
                   **kwargs: Any) -> None:
        if not self.enabled or not self._run_active:
            return
        if self._pending_turn is None:
            self._pending_turn = {"call_index": call_index, "reasoning_text": "",
                                  "tool_calls": [], "tool_results": [],
                                  "stop_reason": "", "cost_usd": None, "usage": {},
                                  "elapsed_ms": 0.0}
            self._turn_start_node = self._current_node_id
        self._pending_turn["reasoning_text"] = text or ""
        self._pending_turn["stop_reason"] = stop_reason or (
            getattr(response, "stop_reason", "") if response else "")
        self._pending_turn["cost_usd"] = cost_usd
        self._pending_turn["usage"] = usage if usage is not None else extract_usage(response)
        self._pending_turn["elapsed_ms"] = round(elapsed * 1000, 2)
        if response is not None:
            self._pending_turn["tool_calls"] = [
                {"name": tc.name, "input": tc.input, "id": tc.id}
                for tc in response.tool_calls
            ]
            self._pending_turn["request_body"] = getattr(response, "request_body", None)
            self._pending_turn["response_raw"] = getattr(response, "raw", None)
        self._append_raw(EV_LLM_END, call_index=call_index,
                         reasoning_text=text or "", tool_count=tool_count,
                         tool_calls=self._pending_turn["tool_calls"],
                         stop_reason=self._pending_turn["stop_reason"],
                         cost_usd=cost_usd, usage=self._pending_turn["usage"],
                         elapsed_ms=self._pending_turn["elapsed_ms"],
                         request_body=self._pending_turn.get("request_body"),
                         response_raw=self._pending_turn.get("response_raw"))

    def on_tool_start(self, step_index: int, name: str, args: dict, **kwargs: Any) -> None:
        if not self.enabled or not self._run_active:
            return
        self._append_raw(EV_TOOL_START, step_index=step_index, name=name, args=args)

    def on_tool_end(self, step_index: int, name: str,
                    result: str, elapsed: float, success: bool, *,
                    action_result: "ActionResult | None" = None,
                    **kwargs: Any) -> None:
        if not self.enabled or not self._run_active:
            return
        data = {}
        if action_result is not None:
            data = dict(action_result.data) if action_result.data else {}
        post_key = self._read_screen_key()
        entry = {
            "name": name, "success": success,
            "summary": result, "data": data,
            "post_screen_key": post_key,
            "elapsed_ms": round(elapsed * 1000, 2),
        }
        if self._pending_turn is not None:
            self._pending_turn["tool_results"].append(entry)
        self._append_raw(EV_TOOL_END, step_index=step_index, name=name,
                         success=success, summary=result, data=data,
                         post_screen_key=post_key,
                         elapsed_ms=entry["elapsed_ms"])
        # opt-in 富模式：操作类工具后额外 observe（会改变运行行为，仅重放场景用）
        if (self.auto_observe_after_action and self._phonefast is not None
                and name in self.action_tool_names):
            self._auto_observe(step_index)

    def on_step(self, step: "Step", **kwargs: Any) -> None:
        if not self.enabled or not self._run_active:
            return
        self._append_raw(EV_STEP, step=_step_dict(step))

    def on_finish(self, result: "AgentResult", **kwargs: Any) -> None:
        if not self.enabled:
            return
        # 收尾最后一轮 edge
        self._finalize_turn()
        end_cause = self._infer_end_cause(result)
        outcome = {
            "success": result.success,
            "summary": result.summary,
            "reason": "",
            "total_steps": result.steps,
            "total_llm_calls": self._llm_call_index,
            "total_cost_usd": round(result.total_cost_usd, 6),
            "duration_ms": round((time.time() - self._t_start) * 1000, 2) if self._t_start else 0,
            "end_cause": end_cause,
            "complete_overridden": " | 覆盖:" in result.summary,
            "steps_detail": [_step_dict(s) for s in result.steps_detail],
        }
        self._append_raw(EV_FINISH, success=result.success, summary=result.summary,
                         total_steps=result.steps, total_cost_usd=result.total_cost_usd,
                         end_cause=end_cause)
        self._outcome_cache = outcome
        try:
            self.flush()
        finally:
            # 关闭本次 run；下次 begin_run 会 reset 缓冲+run_id，
            # FlowRunner 复用同一实例时各 node 的 trace 互不串台
            self._run_active = False

    # ---- 内部：屏幕/边/事件 ----

    def _read_screen_key(self) -> str | None:
        pf = self._phonefast
        if pf is None:
            return None
        return getattr(pf, "current_screen_key", None)

    def _record_screen(self, source: str, screen_text: str,
                       image_b64: str | None, element_count: int,
                       step_index: int | None) -> None:
        key = self._read_screen_key()
        dedup = key if key else ("text:" + hashlib.md5(
            screen_text.encode("utf-8")).hexdigest()[:12])
        node_id = self._screen_index.get(dedup)
        if node_id is None:
            node_id = f"S{len(self._nodes)}"
            self._screen_index[dedup] = node_id
            self._nodes.append({
                "id": node_id,
                "step_index": step_index,
                "source": source,
                "screen_text": screen_text,
                "image_b64": image_b64 if self.capture_images else None,
                "element_count": element_count,
                "screen_key": key,
            })
        self._current_node_id = node_id
        self._append_raw(EV_SCREEN, node_id=node_id, source=source,
                         screen_text=screen_text, element_count=element_count,
                         screen_key=key, step_index=step_index)

    def _finalize_turn(self) -> None:
        if self._pending_turn is None:
            return
        to_node = self._current_node_id
        edge = {
            "id": f"E{len(self._edges)}",
            "from_node": self._turn_start_node,
            "to_node": to_node,
            "llm_call_index": self._pending_turn["call_index"],
            "reasoning_text": self._pending_turn["reasoning_text"],
            "tool_calls": self._pending_turn["tool_calls"],
            "tool_results": self._pending_turn["tool_results"],
            "stop_reason": self._pending_turn["stop_reason"],
            "cost_usd": self._pending_turn["cost_usd"],
            "usage": self._pending_turn["usage"],
            "elapsed_ms": self._pending_turn["elapsed_ms"],
            "request_body": self._pending_turn.get("request_body"),
            "response_raw": self._pending_turn.get("response_raw"),
        }
        self._edges.append(edge)
        self._pending_turn = None
        self._turn_start_node = self._current_node_id

    def _auto_observe(self, step_index: int) -> None:
        """opt-in 富模式：操作后主动 observe 一次，记录为 auto_observe_after_action 节点。"""
        pf = self._phonefast
        proc = self._processor
        if pf is None or proc is None:
            return
        try:
            raw = pf.observe()
            ui, txt = proc.process(raw.elements_text)
            count = len(ui.elements) if ui else 0
        except Exception:
            return
        self._record_screen(SRC_AUTO_AFTER_ACTION, txt or "", None, count, step_index)

    def _infer_end_cause(self, result: "AgentResult") -> str:
        summary = result.summary or ""
        if "步数上限" in summary:
            return "max_steps"
        if "LLM 连续失败" in summary:
            return "llm_consecutive_fail"
        # 最后一轮若含 complete 工具 → complete_tool；若纯文本结束 → no_tool_call_end
        if self._edges and self._edges[-1]["tool_calls"]:
            names = {tc["name"] for tc in self._edges[-1]["tool_calls"]}
            if "complete" in names:
                return "complete_tool"
            return "no_tool_call_end"
        if not self._edges:
            return "no_tool_call_end"
        return "no_tool_call_end"

    def _append_raw(self, event: str, **data: Any) -> None:
        self._seq += 1
        self._raw.append({
            "seq": self._seq,
            "ts": round((time.time() - self._t_start) * 1000, 2) if self._t_start else 0,
            "event": event,
            **data,
        })

    # ---- 落盘 ----

    def build_graph(self) -> dict[str, Any]:
        outcome = getattr(self, "_outcome_cache", None) or {}
        return {
            "schema_version": SCHEMA_VERSION,
            "meta": dict(self._meta),
            "nodes": list(self._nodes),
            "edges": list(self._edges),
            "outcome": outcome,
        }

    def flush(self) -> None:
        """写两件产物到 output_dir/<run_id>.{trace.jsonl,replay.json}。"""
        if not self.run_id:
            return
        out = Path(self.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        # 1) trace.jsonl —— 原始事件流
        jsonl_path = out / f"{self.run_id}.trace.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for ev in self._raw:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        # 2) replay.json —— 结构化重放图
        graph_path = out / f"{self.run_id}.replay.json"
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump(self.build_graph(), f, ensure_ascii=False, indent=2)


@dataclass
class SessionReplay:
    """AgentHook 实现：以 session 为维度聚合多个 run 的轨迹。

    生命周期：
      begin_session() → begin_run() → (hook 事件流) → begin_run() → ...
      → flush() / end_session() 统一落盘。

    产物：
      <session_id>.trace.jsonl — 所有 run 的原始事件流
      <session_id>.replay.json  — session 级结构化日志图
    """

    session_id: str
    output_dir: str = "build/traces"
    enabled: bool = True
    capture_images: bool = False
    auto_observe_after_action: bool = False
    action_tool_names: set[str] = field(default_factory=set)

    # 运行时依赖
    _phonefast: Any = field(default=None, repr=False)
    _processor: Any = field(default=None, repr=False)

    # session 级缓冲
    _runs: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _run_raw_events: list[list[dict[str, Any]]] = field(default_factory=list, init=False, repr=False)
    _current: ReplayLogger | None = field(default=None, init=False, repr=False)
    _run_seq: int = field(default=0, init=False, repr=False)
    _session_started: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"),
        init=False, repr=False,
    )

    def configure(
        self,
        *,
        phonefast: Any | None = None,
        processor: Any | None = None,
        action_tool_names: set[str] | None = None,
        auto_observe_after_action: bool | None = None,
        capture_images: bool | None = None,
    ) -> "SessionReplay":
        if phonefast is not None:
            self._phonefast = phonefast
        if processor is not None:
            self._processor = processor
        if action_tool_names is not None:
            self.action_tool_names = set(action_tool_names)
        if auto_observe_after_action is not None:
            self.auto_observe_after_action = auto_observe_after_action
        if capture_images is not None:
            self.capture_images = capture_images
        return self

    # ---- AgentHook（委托给当前 run 的 ReplayLogger）----

    def on_auto_observe(self, **kwargs: Any) -> None:
        if self._current:
            self._current.on_auto_observe(**kwargs)

    def on_screen(self, **kwargs: Any) -> None:
        if self._current:
            self._current.on_screen(**kwargs)

    def on_llm_start(self, **kwargs: Any) -> None:
        if self._current:
            self._current.on_llm_start(**kwargs)

    def on_llm_end(self, **kwargs: Any) -> None:
        if self._current:
            self._current.on_llm_end(**kwargs)

    def on_tool_start(self, **kwargs: Any) -> None:
        if self._current:
            self._current.on_tool_start(**kwargs)

    def on_tool_end(self, **kwargs: Any) -> None:
        if self._current:
            self._current.on_tool_end(**kwargs)

    def on_step(self, **kwargs: Any) -> None:
        if self._current:
            self._current.on_step(**kwargs)

    # ---- run 生命周期 ----

    def begin_run(
        self,
        goal: str,
        *,
        scenario: str | None = None,
        variant: str = "",
        prompt: str = "",
        fmt: str = "",
        model: str | None = None,
        max_steps: int | None = None,
        vision: bool = False,
    ) -> None:
        """开始一个 run。创建 per-run ReplayLogger，事件委托给它。"""
        self._run_seq += 1
        rl = ReplayLogger(
            output_dir=self.output_dir,
            enabled=self.enabled,
            capture_images=self.capture_images,
            auto_observe_after_action=self.auto_observe_after_action,
            action_tool_names=self.action_tool_names,
        )
        rl.configure(
            phonefast=self._phonefast,
            processor=self._processor,
            action_tool_names=self.action_tool_names,
            auto_observe_after_action=self.auto_observe_after_action,
            capture_images=self.capture_images,
        )
        rl.run_id = gen_run_id(
            scenario=scenario, variant=variant, prompt=prompt,
            fmt=fmt, seq=self._run_seq, goal=goal,
        )
        rl.begin_run(
            goal, scenario=scenario, variant=variant, prompt=prompt,
            fmt=fmt, seq=self._run_seq, model=model,
            max_steps=max_steps, vision=vision,
        )
        self._current = rl

    def on_finish(self, result: "AgentResult", **kwargs: Any) -> None:
        """收尾当前 run，收集 graph + 原始事件到 session 缓冲。"""
        if self._current is None:
            return
        # 收尾 edge + 设置 outcome（build_graph 需要）
        self._current._finalize_turn()
        end_cause = self._current._infer_end_cause(result)
        self._current._outcome_cache = {
            "success": result.success,
            "summary": result.summary,
            "total_steps": result.steps,
            "total_llm_calls": self._current._llm_call_index,
            "total_cost_usd": round(result.total_cost_usd, 6),
            "duration_ms": round((time.time() - self._current._t_start) * 1000, 2) if self._current._t_start else 0,
            "end_cause": end_cause,
        }
        graph = self._current.build_graph()
        self._runs.append(graph)

        # 保存原始事件（包含 finish marker）
        raw = list(self._current._raw)
        raw.append({
            "event": "finish",
            "run_id": self._current.run_id,
            "success": result.success,
            "summary": result.summary,
            "total_steps": result.steps,
            "total_cost_usd": result.total_cost_usd,
            "end_cause": end_cause,
        })
        self._run_raw_events.append(raw)
        self._current._run_active = False

    # ---- 落盘 ----

    def build_session_graph(self) -> dict[str, Any]:
        total_steps = sum(r.get("outcome", {}).get("total_steps", 0) for r in self._runs)
        total_cost = sum(r.get("outcome", {}).get("total_cost_usd", 0) for r in self._runs)
        all_success = all(r.get("outcome", {}).get("success", False) for r in self._runs)
        return {
            "schema_version": SCHEMA_VERSION,
            "session": {
                "session_id": self.session_id,
                "started_at": self._session_started,
                "run_count": len(self._runs),
                "total_steps": total_steps,
                "total_cost_usd": round(total_cost, 6),
                "all_success": all_success,
            },
            "runs": self._runs,
        }

    def flush(self) -> None:
        """写入 session 级文件。"""
        if not self.session_id or not self._runs:
            return
        out = Path(self.output_dir)
        out.mkdir(parents=True, exist_ok=True)

        sid = self.session_id

        # trace.jsonl — 所有 run 的完整原始事件流
        jsonl_path = out / f"{sid}.trace.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "seq": 0, "ts": 0,
                "event": "session_start",
                "session_id": sid,
                "started_at": self._session_started,
                "run_count": len(self._runs),
            }, ensure_ascii=False) + "\n")
            for i, events in enumerate(self._run_raw_events):
                for ev in events:
                    ev["session_id"] = sid
                    f.write(json.dumps(ev, ensure_ascii=False) + "\n")

        # replay.json — session 级结构化日志图
        replay_path = out / f"{sid}.replay.json"
        with open(replay_path, "w", encoding="utf-8") as f:
            json.dump(self.build_session_graph(), f, ensure_ascii=False, indent=2)


def make_replay_logger(
    *,
    enabled: bool,
    output_dir: str = "build/traces",
    phonefast: Any | None = None,
    processor: Any | None = None,
    action_tool_names: set[str] | None = None,
    auto_observe_after_action: bool = False,
    capture_images: bool = False,
) -> ReplayLogger | None:
    """构造 ReplayLogger；enabled=False 时返回 None（hook 列表保持空，零开销）。"""
    if not enabled:
        return None
    logger = ReplayLogger(
        output_dir=output_dir,
        enabled=True,
        capture_images=capture_images,
        auto_observe_after_action=auto_observe_after_action,
    )
    logger.configure(phonefast=phonefast, processor=processor,
                     action_tool_names=action_tool_names,
                     auto_observe_after_action=auto_observe_after_action,
                     capture_images=capture_images)
    return logger
