"""Steering：运行时消息注入——提取自 pi 的 getSteeringMessages / QueueMode 概念。

对应 pi/packages/agent/src/agent-loop.ts 的 pendingMessages 机制：
  - pi 每轮循环顶部调用 config.getSteeringMessages()，把返回的消息
    注入 context 后再发起下一次 LLM 调用
  - fastaget 的吸收形态：SteeringSource 协议 + 每轮循环顶部 _drain_pending

实体对象：
  SteeringMessage — 一条待注入的消息（对应 pi 注入的 AgentMessage，
                    fastaget 只需 text + source 两个字段）
  SteeringSource  — 注入源协议（对应 pi 的 getSteeringMessages 回调）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SteeringMessage:
    """一条待注入的运行时消息。

    source 标记来源（"external"=外部注入，"feedback"=内部护栏反馈），
    供 trace 归因；注入到 messages 时统一转为 user role 文本块。
    """

    text: str
    source: str = "external"


class SteeringSource(Protocol):
    """steering 注入源。每轮循环顶部被询问一次。"""

    def poll(self) -> list[SteeringMessage]:
        """返回本轮要注入的消息列表（可为空）。必须不抛异常。"""
        ...


class NullSteering:
    """默认：无注入。"""

    def poll(self) -> list[SteeringMessage]:
        return []


@dataclass
class QueueSteering:
    """队列注入源：评测器 / 人工 / 外部监控可在 agent 运行中塞入纠正消息。

    Usage::

        q = QueueSteering()
        agent = FastAgent(llm, pf, registry, steering=q)
        # 另一个线程/回调里：
        q.push("检测到系统弹窗，请先按 back")
    """

    _queue: list[SteeringMessage] = field(default_factory=list)
    _lock: Any = field(default_factory=lambda: __import__("threading").Lock())

    def push(self, text: str, *, source: str = "external") -> None:
        with self._lock:
            self._queue.append(SteeringMessage(text=text, source=source))

    def poll(self) -> list[SteeringMessage]:
        with self._lock:
            out, self._queue = self._queue, []
        return out


@dataclass
class KnowledgeSteering:
    """PI 式 pull 模型：poll() 无参，自持轮次计数器，渐进式注入。

    - 首轮不注入（load_startup_knowledge 已注入 §6 app 模板）
    - 第 3/6/9 轮各拉取一个知识层（操作模式 → 组件库 → 边界情况）
    - 不读 RunState、不加状态机字段——完全自包含
    """

    goal: str
    _turn: int = field(default=0, init=False)

    def reset(self) -> None:
        """外层续跑（_rearm）时清零轮次计数。"""
        self._turn = 0

    def poll(self) -> list[SteeringMessage]:
        self._turn += 1
        if self._turn <= 1:
            return []
        if self._turn % 3 != 0:
            return []
        # 渐进注入：第 3 轮=操作模式, 第 6 轮=组件库, 第 9 轮=边界+A11Y
        stage = "stuck" if self._turn >= 9 else ("tab,create" if self._turn >= 6 else "")
        from fastaget.agent.prompts import load_steering_knowledge
        text = load_steering_knowledge(self.goal, {"turn": self._turn, "stage": stage})
        if not text:
            return []
        return [SteeringMessage(
            text=f"## Operation Reference\n{text}",
            source="knowledge_pull",
        )]
