"""PreconditionGate：前置条件门控能力（参照 PI before_task 检查模式）。

复用 Flow 层的 ExpectationEvaluator + ConditionEvaluator，
在 pre_run 阶段检查设备/环境状态，提前过滤不可执行的任务。

PI 参考：agent-loop.ts before_task——任务执行前先验证环境就绪，
条件不满足则 early-return 不调 LLM。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from fastaget.agent.capabilities import Capability, TurnSnapshot
from fastaget.device.uiprocessor import processor

if TYPE_CHECKING:
    from fastaget.agent.run_state import RunState
    from fastaget.flow.expectation import Expectation


@dataclass
class PreconditionGate:
    """前置条件门控：pre_run 阶段检查，critical 失败直接终止。

    无状态——每次 run() 构造新实例，不新增状态机（宪法第六条 5 上限）。
    依赖：ExpectationEvaluator（复用 flow 层）、phonefast（设备查询）。

    PI 对应：before_task 检查 → 条件不满足时 skip task，零 token 浪费。
    """

    expectations: "list[Expectation]"
    evaluator: Any                            # ExpectationEvaluator（鸭子类型避免硬依赖）
    phonefast: Any                            # 供 ConditionEvaluator 查询设备事实

    def __call__(self, state: "RunState", snap: TurnSnapshot) -> "RunState":
        if snap.phase != "pre_run":
            return state

        # 构建最小 FlowContext（ConditionEvaluator 只需 screen_text + phonefast）
        ctx = _MinimalFlowContext(phonefast=self.phonefast)

        # 刷新屏幕供 screen.* 条件使用
        try:
            raw = self.phonefast.observe()
            ui_state, screen_text = processor.process(raw.elements_text)
            ctx.update_screen(ui_state, screen_text)
        except Exception:
            pass  # 屏幕不可用时 screen.* 条件自然返回 False

        # 求值所有前置条件
        records = self.evaluator.check_all(self.expectations, ctx, "_precondition")

        # critical 失败 → 立即终止（PI 的 early-return 模式）
        critical_fails = [r for r in records if not r.passed and r.severity == "critical"]
        if critical_fails:
            detail = "; ".join(
                f"{r.description}: {r.detail}" for r in critical_fails
            )
            return replace(state, terminal=True, success=False,
                          summary=f"前置条件不满足: {detail}")

        # 通过 → 将已验证的事实注入首条消息（给 LLM 起点信息，不需重复验证）
        verified = [r for r in records if r.passed]
        if verified:
            lines = ["## Verified preconditions"]
            lines += [f"- ✓ {r.description}" for r in verified]
            state.pending_feedback.insert(0, "\n".join(lines))

        return state


class _MinimalFlowContext:
    """最小 FlowContext——ConditionEvaluator 仅需 current_screen_text 和 phonefast。

    ExpectationEvaluator.check_all() 要求 FlowContext，但 precondition 场景
    不需要 steps/vars/expects 历史——创建最小子集避免依赖 flow 层的完整上下文。
    """

    def __init__(self, phonefast: Any = None) -> None:
        self.phonefast = phonefast
        self._screen_text: str = ""
        self._ui: Any = None

    def update_screen(self, ui: Any, screen_text: str = "") -> None:
        self._ui = ui
        self._screen_text = screen_text

    @property
    def current_ui(self) -> Any:
        return self._ui

    @property
    def current_screen_text(self) -> str:
        return self._screen_text

    @property
    def current_package(self) -> str:
        return ""
