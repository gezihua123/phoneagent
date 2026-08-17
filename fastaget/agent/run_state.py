"""RunState：一次 FastAgent.run(goal) 执行期间的完整状态。

v3 简化：砍掉 Guard 体系，所有跨轮状态收敛于此。判定逻辑在 FastAgent
主循环中作为普通方法，不另建"状态机"类。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastaget.agent.types import Step


@dataclass
class RunState:
    """一次 run(goal) 的完整状态。"""

    goal: str = ""
    session_id: str = ""

    # ── 对话 ──
    messages: list[dict[str, Any]] = field(default_factory=list)

    # ── 轨迹 ──
    steps: list["Step"] = field(default_factory=list)
    step_count: int = 0
    turn_count: int = 0

    # ── 累计指标 ──
    cost_usd: float = 0.0

    # ── 终局 ──
    terminal: bool = False
    success: bool = False
    summary: str = ""

    # ── 跨轮跟踪 ──
    last_tool: str = ""                  # 上一轮最后一个工具名（停滞豁免用）

    # ── 待注入反馈（吸收 pi pendingMessages 机制）──
    # 各检查点（纯文本催促/停滞告警/LLM 失败）不再就地 append messages，
    # 统一写入此队列，由循环顶部 _drain_pending 一次性注入——注入点唯一。
    pending_feedback: list[str] = field(default_factory=list)

    # ── 运行时引用（非状态机：不持久化、不转移、纯数据访问）──
    # 让无状态能力（ErrorReflection）能访问 memory.errors，不在能力间传引用
    _memory_ref: Any = None
