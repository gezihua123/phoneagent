"""outcomes: 判定器注册表 + evaluate_scenario_outcome。

职责：场景成功判定。判定逻辑分散在独立 checker 函数，通过 @register_outcome_checker
注册，evaluate_scenario_outcome 只做分发。新增判定模式不改分发主逻辑。
不含场景定义（那是 scenarios 的职责）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from fastaget.scenariokit.scenarios import (
    Scenario,
    _point_in_bounds,
    _resolve_gt_bounds,
)

if TYPE_CHECKING:
    from fastaget.agent.fast_agent import AgentResult
    from fastaget.scenariokit.device import MockPhonefast, Screen


@dataclass
class OutcomeContext:
    """判定上下文，打包判定所需的全部信息。"""
    scenario: "Scenario"
    nodes: list[dict]
    pf: "MockPhonefast"
    result: "AgentResult | None"
    screens: "dict[str, Screen] | None"
    prompt_name: str

    @property
    def gt_bounds(self) -> tuple[int, int, int, int] | None:
        return _resolve_gt_bounds(self.scenario, self.nodes)

    @property
    def final_screen(self) -> str:
        return getattr(self.pf, "current_screen_key", "")

    @property
    def agent_success(self) -> bool:
        return self.result.success if self.result else False

    @property
    def agent_summary(self) -> str:
        return self.result.summary if self.result else ""


# 判定器注册表：check 名 → checker 函数
_OUTCOME_CHECKERS: dict[str, Callable[[OutcomeContext], tuple[bool, str]]] = {}


def register_outcome_checker(check_name: str) -> Callable:
    """装饰器：注册判定器。新增判定模式用此装饰器，不改分发主逻辑。

    Usage::

        @register_outcome_checker("my_new_check")
        def _check_my_new(ctx: OutcomeContext) -> tuple[bool, str]:
            ...
    """
    def decorator(fn: Callable[[OutcomeContext], tuple[bool, str]]) -> Callable:
        _OUTCOME_CHECKERS[check_name] = fn
        return fn
    return decorator


@register_outcome_checker("tap_in_gt")
def _check_tap_in_gt(ctx: OutcomeContext) -> tuple[bool, str]:
    """tap 坐标必须落在目标元素 bounds 内。"""
    if ctx.gt_bounds is None:
        return False, "目标元素在当前变体中不存在"
    hit = any(_point_in_bounds(t.x, t.y, ctx.gt_bounds) for t in ctx.pf.taps)
    if not ctx.pf.taps:
        steps_info = f" (steps={ctx.result.steps})" if ctx.result else ""
        return False, f"agent 未执行任何 tap{steps_info}"
    if not hit:
        taps_s = ", ".join(f"({t.x},{t.y})" for t in ctx.pf.taps)
        return False, f"tap 未落在 GT{ctx.gt_bounds} 内，实际: {taps_s}"
    if ctx.screens is not None:
        return True, f"tap 命中 GT + 屏幕转到 {ctx.final_screen}"
    if not ctx.agent_success:
        return False, f"agent 未成功完成: {ctx.agent_summary[:80]}"
    return True, "tap 命中 GT + complete success"


def _action_present(act: str, ctx: OutcomeContext) -> bool:
    """动作匹配：精确或前缀（type 匹配 type(lanya)，back 匹配 back 或 key(back)）。"""
    if act in ctx.pf.actions:
        return True
    if any(a.startswith(act + "(") for a in ctx.pf.actions):
        return True
    if act == "back" and "key(back)" in ctx.pf.actions:
        return True
    if act == "back" and ctx.screens is not None:
        start_key = getattr(ctx.scenario, "start_screen", "")
        start_scr = ctx.screens.get(start_key)
        if start_scr and start_scr.back_screen and ctx.final_screen == start_scr.back_screen:
            return True
    return False


@register_outcome_checker("action_match")
def _check_action_match(ctx: OutcomeContext) -> tuple[bool, str]:
    """actions 日志含指定动作（如 back）。"""
    expected = ctx.scenario.expected_action
    matched = _action_present(expected, ctx)
    screen_transitioned = False
    if ctx.screens is not None and expected == "back":
        start_key = getattr(ctx.scenario, "start_screen", "")
        start_scr = ctx.screens.get(start_key)
        if start_scr and start_scr.back_screen and ctx.final_screen == start_scr.back_screen:
            matched = True
            screen_transitioned = True
    if screen_transitioned:
        return True, f"返回成功：屏幕转到 {ctx.final_screen}"
    if matched and ctx.agent_success:
        return True, "动作匹配 + complete success"
    return False, f"未匹配 {expected}，actions={ctx.pf.actions[:5]}"


@register_outcome_checker("action_all")
def _check_action_all(ctx: OutcomeContext) -> tuple[bool, str]:
    """多动作序列（如 type + key(enter)）。"""
    required = ctx.scenario.expected_actions or [ctx.scenario.expected_action]
    missing = [a for a in required if not _action_present(a, ctx)]
    if missing:
        return False, f"缺少动作 {missing}，实际 actions={ctx.pf.actions[:8]}"
    if not ctx.agent_success:
        return False, f"动作齐全但 agent 未 complete success: {ctx.agent_summary[:60]}"
    if ctx.screens is not None and getattr(ctx.scenario, "target_screen", ""):
        if ctx.final_screen == ctx.scenario.target_screen:
            return True, f"动作齐全 + 屏幕转到 {ctx.final_screen}"
        return False, f"动作齐全但屏幕未到 {ctx.scenario.target_screen}，实际 {ctx.final_screen}"
    return True, f"动作齐全: {required}"


@register_outcome_checker("no_change_success")
def _check_no_change_success(ctx: OutcomeContext) -> tuple[bool, str]:
    """幂等/状态感知：complete(success) 且屏幕未转到 forbidden_screens。"""
    if not ctx.agent_success:
        return False, f"agent 未 complete success: {ctx.agent_summary[:80]}"
    forbidden = ctx.scenario.forbidden_screens
    if forbidden and ctx.final_screen in forbidden:
        return False, f"屏幕误转到 {ctx.final_screen}（不应操作却操作了）"
    return True, f"状态感知正确，屏幕保持 {ctx.final_screen}"


@register_outcome_checker("expect_fail")
def _check_expect_fail(ctx: OutcomeContext) -> tuple[bool, str]:
    """期望 agent 主动 complete(fail)：无响应/目标不存在/工具失败场景。"""
    if not ctx.agent_success:
        return True, f"符合预期(agent 主动 fail): {ctx.agent_summary[:80]}"
    return False, f"不符合预期(agent 误判成功): {ctx.agent_summary[:80]}"


@register_outcome_checker("complete_success")
def _check_complete_success(ctx: OutcomeContext) -> tuple[bool, str]:
    """兜底：以 agent 的 complete 结果为准。"""
    return ctx.agent_success, ctx.agent_summary[:100]


def evaluate_scenario_outcome(
    scenario: "Scenario",
    nodes: list[dict],
    pf: "MockPhonefast",
    result: "AgentResult | None" = None,
    *,
    screens: "dict[str, Screen] | None" = None,
    prompt_name: str = "",
) -> tuple[bool, str]:
    """统一场景成功判定入口（分发到注册的判定器，不集中 if/elif）。

    新增判定模式只需注册新 checker，不改此函数。返回 (success, reason)。
    """
    ctx = OutcomeContext(
        scenario=scenario, nodes=nodes, pf=pf, result=result,
        screens=screens, prompt_name=prompt_name,
    )
    check = scenario.check or "complete_success"
    checker = _OUTCOME_CHECKERS.get(check, _OUTCOME_CHECKERS["complete_success"])
    return checker(ctx)
