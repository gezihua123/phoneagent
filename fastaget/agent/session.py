"""Session：一次交互会话。

职责：
  1. 生成 session_id，贯穿所有 run() 调用
  2. 集成 SessionReplay，以 session 为维度记录轨迹
  3. snapshot / restore 持久化，支持中断后恢复

Usage::

    session = Session(agent=agent, trace=True)
    r1 = session.run("打开设置")   # begin_run → agent → on_finish（收集 graph）
    r2 = session.run("关闭蓝牙")   # 同上
    session.flush()               # 统一落盘 session 级 trace + replay
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastaget.agent.fast_agent import AgentResult, FastAgent


@dataclass
class Session:
    """一次交互会话。"""

    agent: FastAgent
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace: bool = False
    logging: bool = True
    _created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    _run_count: int = field(default=0, init=False)
    _total_steps: int = field(default=0, init=False)
    _total_cost: float = field(default=0.0, init=False)
    _replay: Any = field(default=None, init=False, repr=False)  # SessionReplay | None
    _log_adapters: bool = field(default=False, init=False, repr=False)

    def run(self, goal: str) -> AgentResult:
        """执行一个目标。PI 对齐：同 Session 内多次 run() 自动复用
        agent session state（messages/内存/指纹），等价于 PI 的
        "同一个 runLoop context 多个 follow-up"——第二个 run 能看到
        第一个 run 的全部执行历史，避免重复探索相同的事实。

        自动注入 session_id + 管理 trace/日志 生命周期。
        """
        # 初始化 logging（懒加载，首次 run 时）
        if self.logging and not self._log_adapters:
            self._log_adapters = True  # 标记已初始化
            from fastaget.logging import setup_logging
            setup_logging(session_id=self.id)

        # 初始化 SessionReplay（懒加载，首次 run 时）
        if self.trace and self._replay is None:
            self._replay = self._make_replay()

        # trace: begin_run
        if self._replay is not None:
            model = getattr(self.agent.llm, "model", None)
            self._replay.begin_run(
                goal=goal, model=model, max_steps=self.agent.max_steps,
            )

        # PI 对齐：首次 run 初始化新 session，后续 run 复用 state
        result = self.agent.run(goal, new_session=(self._run_count == 0))
        result.session_id = self.id

        # trace: on_finish（收集 run graph 到 session 缓冲）
        if self._replay is not None:
            self._replay.on_finish(result)

        self._run_count += 1
        self._total_steps += result.steps
        self._total_cost += result.total_cost_usd

        return result

    def flush(self) -> None:
        """统一落盘 session 级 trace + replay 文件。"""
        if self._replay is not None:
            self._replay.flush()

    def _make_replay(self) -> Any:
        """懒创建 SessionReplay。"""
        from fastaget.agent.trace import SessionReplay
        from fastaget.device.uiprocessor import processor

        registry = self.agent.registry
        tool_names = registry.action_tool_names() if registry else set()
        sr = SessionReplay(
            session_id=self.id,
            output_dir="build/traces",
            enabled=True,
            action_tool_names=tool_names,
        )
        sr.configure(
            phonefast=self.agent.observer.phonefast,
            processor=processor,
            action_tool_names=tool_names,
        )
        # 注入为 agent hook
        current_hooks = list(self.agent._hooks or [])
        current_hooks.append(sr)
        self.agent._hooks = current_hooks
        return sr

    # ---- 快照 / 恢复 ----

    def snapshot(self) -> dict[str, Any]:
        """导出会话快照（可落盘 JSON 后恢复）。

        包含 session 元数据。
        """
        return {
            "session_id": self.id,
            "created_at": self._created_at,
            "run_count": self._run_count,
            "total_steps": self._total_steps,
            "total_cost_usd": round(self._total_cost, 6),
        }

    def save(self, path: str) -> None:
        """持久化到 JSON 文件。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.snapshot(), f, ensure_ascii=False, indent=2)

    @classmethod
    def restore(
        cls,
        data: dict[str, Any],
        agent: FastAgent,
    ) -> "Session":
        """从快照恢复会话。"""
        session = cls(
            agent=agent,
            id=data.get("session_id", uuid.uuid4().hex[:12]),
            _created_at=data.get("created_at", ""),
        )
        session._run_count = data.get("run_count", 0)
        session._total_steps = data.get("total_steps", 0)
        session._total_cost = data.get("total_cost_usd", 0.0)

        return session

    @classmethod
    def load(cls, path: str, agent: FastAgent) -> "Session":
        """从 JSON 文件恢复会话。"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.restore(data, agent)

    # ---- 统计 ----

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "session_id": self.id,
            "created_at": self._created_at,
            "run_count": self._run_count,
            "total_steps": self._total_steps,
            "total_cost_usd": round(self._total_cost, 6),
        }
