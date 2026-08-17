"""ConditionEvaluator 单测：规则/上下文/语义条件求值。"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastaget.device.uistate import Element, UIState
from fastaget.flow.condition import ConditionEvaluator
from fastaget.flow.context import FlowContext, StepResult


def _make_ui(texts: list[str]) -> UIState:
    elements = [
        Element(index=i, text=t, id=None, desc=None, cls="TextView",
                clickable=True, bounds=(0, i*100, 100, i*100+50))
        for i, t in enumerate(texts)
    ]
    return UIState(elements)


def test_screen_has_text_matched():
    ctx = FlowContext()
    ctx.update_screen(_make_ui(["Google Play", "Search", "Apps"]), "screen")
    ev = ConditionEvaluator()
    r = ev.eval("{screen.has_text:Google Play}", ctx)
    assert r.matched and r.source == "rule"


def test_screen_has_text_not_matched():
    ctx = FlowContext()
    ctx.update_screen(_make_ui(["Settings", "About"]), "screen")
    ev = ConditionEvaluator()
    r = ev.eval("{screen.has_text:Google Play}", ctx)
    assert not r.matched


def test_screen_not_has_text():
    ctx = FlowContext()
    ctx.update_screen(_make_ui(["Settings", "About"]), "screen")
    ev = ConditionEvaluator()
    r = ev.eval("{screen.not_has_text:Error}", ctx)
    assert r.matched


def test_screen_has_element_by_index():
    ctx = FlowContext()
    ctx.update_screen(_make_ui(["A", "B", "C"]), "screen")
    ev = ConditionEvaluator()
    r = ev.eval("{screen.has_element:index=1}", ctx)
    assert r.matched


def test_screen_package():
    ctx = FlowContext()
    ctx.update_screen(_make_ui([]), "screen", package="com.android.vending")
    ev = ConditionEvaluator()
    r = ev.eval("{screen.package:com.android.vending}", ctx)
    assert r.matched


def test_step_context_success():
    ctx = FlowContext()
    ctx.record_step(StepResult(node_id="search", success=True, summary="ok"))
    ev = ConditionEvaluator()
    r = ev.eval("{step.search.success}", ctx)
    assert r.matched


def test_step_context_not_found():
    ctx = FlowContext()
    ev = ConditionEvaluator()
    r = ev.eval("{step.unknown.success}", ctx)
    assert not r.matched


def test_var_compare_gt():
    ctx = FlowContext()
    ctx.set_var("count", 5)
    ev = ConditionEvaluator()
    r = ev.eval("{var.count>0}", ctx)
    assert r.matched


def test_var_compare_eq():
    ctx = FlowContext()
    ctx.set_var("status", "done")
    ev = ConditionEvaluator()
    r = ev.eval("{var.status==done}", ctx)
    assert r.matched


def test_default_branch():
    ctx = FlowContext()
    ev = ConditionEvaluator()
    r = ev.eval("default", ctx)
    assert r.matched and r.source == "default"


def test_eval_branches_first_match():
    ctx = FlowContext()
    ctx.update_screen(_make_ui(["Google Play"]), "screen")
    ev = ConditionEvaluator()
    branches = [
        {"when": "{screen.has_text:Google Play}", "to": "play"},
        {"when": "default", "to": "retry"},
    ]
    target, result = ev.eval_branches(branches, ctx)
    assert target == "play"
    assert result.matched


def test_eval_branches_default():
    ctx = FlowContext()
    ctx.update_screen(_make_ui(["Settings"]), "screen")
    ev = ConditionEvaluator()
    branches = [
        {"when": "{screen.has_text:Google Play}", "to": "play"},
        {"when": "default", "to": "retry"},
    ]
    target, result = ev.eval_branches(branches, ctx)
    assert target == "retry"
    assert result.source == "default"


def test_semantic_with_judge():
    ctx = FlowContext()
    ctx.update_screen(_make_ui(["小红书"]), "screen")
    judge = MagicMock()
    judge.judge.return_value = MagicMock(satisfied=True, confidence=0.9)
    ev = ConditionEvaluator(semantic_judge=judge)
    r = ev.eval("{llm.judge:屏幕上显示了小红书}", ctx)
    assert r.matched
    assert r.source == "semantic"
    judge.judge.assert_called_once()


# ---- 设备级事实条件 ----

def test_device_pkg_installed_true():
    ctx = FlowContext(phonefast=MagicMock())
    ctx.phonefast.is_package_installed.return_value = True
    ev = ConditionEvaluator()
    r = ev.eval("{device.pkg_installed:com.xingin.xiaohongshu}", ctx)
    assert r.matched
    assert r.source == "device"
    ctx.phonefast.is_package_installed.assert_called_with("com.xingin.xiaohongshu")


def test_device_pkg_installed_false():
    ctx = FlowContext(phonefast=MagicMock())
    ctx.phonefast.is_package_installed.return_value = False
    ev = ConditionEvaluator()
    r = ev.eval("{device.pkg_installed:com.xingin.xiaohongshu}", ctx)
    assert not r.matched
    assert r.source == "device"


def test_device_not_pkg_installed():
    ctx = FlowContext(phonefast=MagicMock())
    ctx.phonefast.is_package_installed.return_value = False
    ev = ConditionEvaluator()
    r = ev.eval("{device.not_pkg_installed:com.xingin.xiaohongshu}", ctx)
    assert r.matched  # 未安装 → not_pkg_installed = true


def test_device_activity_match():
    ctx = FlowContext(phonefast=MagicMock())
    ctx.phonefast.current_package.return_value = "com.android.vending"
    ev = ConditionEvaluator()
    r = ev.eval("{device.activity:com.android.vending}", ctx)
    assert r.matched


def test_device_no_phonefast():
    ctx = FlowContext()  # no phonefast
    ev = ConditionEvaluator()
    r = ev.eval("{device.pkg_installed:com.xxx}", ctx)
    assert not r.matched
    assert "no phonefast" in r.detail
