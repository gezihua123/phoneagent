"""ReAct Agent 轨迹类型。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Step:
    """一步轨迹记录。"""

    index: int
    thought: str  # 模型推理
    action: str  # 工具名 或 "final_answer"
    args: dict
    result: str  # Observation 文本
    success: bool
    elapsed: float
    cost_usd: float | None = None
    healed: bool = False
