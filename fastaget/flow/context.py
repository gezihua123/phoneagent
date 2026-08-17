"""FlowContext：流程执行时的运行时状态。

贯穿整个 flow 执行，承载：
  - 当前屏幕状态（UIState + 文本 + 包名）
  - 步骤执行结果历史
  - 用户变量（var.xxx）
  - expect 校验结果
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastaget.device.uistate import UIState


@dataclass
class StepResult:
    """一个 flow node 的执行结果。"""
    node_id: str
    success: bool
    summary: str = ""
    cost_usd: float = 0.0
    elapsed: float = 0.0


@dataclass
class ExpectRecord:
    """一条 expectation 的校验记录。"""
    node_id: str          # 所属 node id，用例级为 "_case"
    description: str
    passed: bool
    severity: str         # "critical" | "warn"
    judge: str            # "rule" | "semantic" | "hybrid"
    detail: str = ""      # 求值细节
    elapsed: float = 0.0
    confidence: float = 1.0  # semantic 判定的置信度


class FlowContext:
    """流程执行上下文（可变状态容器）。"""

    def __init__(self, phonefast: Any = None) -> None:
        self._phonefast = phonefast  # 设备级事实查询通道
        self._vars: dict[str, Any] = {}
        self._steps: dict[str, StepResult] = {}
        self._expects: list[ExpectRecord] = []
        self._current_ui: UIState | None = None
        self._current_screen_text: str = ""
        self._current_package: str = ""

    @property
    def phonefast(self) -> Any:
        return self._phonefast

    # ---- 屏幕状态 ----

    def update_screen(self, ui: UIState, screen_text: str = "", package: str = "") -> None:
        from fastaget.device.uiprocessor import processor
        self._current_ui = ui
        self._current_screen_text = screen_text or (processor.format(ui) if ui else "")
        self._current_package = package

    @property
    def current_ui(self) -> UIState | None:
        return self._current_ui

    @property
    def current_screen_text(self) -> str:
        return self._current_screen_text

    @property
    def current_package(self) -> str:
        return self._current_package

    # ---- 步骤结果 ----

    def record_step(self, result: StepResult) -> None:
        self._steps[result.node_id] = result

    def get_step_result(self, node_id: str) -> StepResult | None:
        return self._steps.get(node_id)

    @property
    def all_steps(self) -> list[StepResult]:
        return list(self._steps.values())

    # ---- 变量 ----

    def set_var(self, key: str, value: Any) -> None:
        self._vars[key] = value

    def get_var(self, key: str) -> Any:
        return self._vars.get(key)

    # ---- Expect 记录 ----

    def record_expect(self, rec: ExpectRecord) -> None:
        self._expects.append(rec)

    @property
    def all_expects(self) -> list[ExpectRecord]:
        return list(self._expects)

    @property
    def critical_fails(self) -> list[ExpectRecord]:
        return [e for e in self._expects if not e.passed and e.severity == "critical"]

    @property
    def all_critical_passed(self) -> bool:
        return len(self.critical_fails) == 0
