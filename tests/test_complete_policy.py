"""Effect-as-Data 约定测试。

v2.1：工具是纯设备操作，效果通过 ActionResult.data 声明，
由 agent 主循环统一解释——工具自身零 ctx 副作用。
- CompleteAction → data 声明终结（is_complete）
- ObserveAction → data 声明屏幕观察（observation_data）
- Agent/ctx 不再被工具反向写入
"""
from fastaget.tools.actions import CompleteAction, ObserveAction
from fastaget.tools.context import ActionContext
from fastaget.tools.registry import ActionResult

from fastaget.scenariokit import MockPhonefast

_TEST_SCREEN = '[0] text="test" (TextView) [clickable] bounds=[0,0][10,10]'


def _mock_pf() -> MockPhonefast:
    return MockPhonefast(_TEST_SCREEN)


class TestCompleteAction:
    """complete 工具通过 data 声明终结，零 ctx 副作用。"""

    def test_declares_complete_on_success(self):
        ctx = ActionContext(phonefast=_mock_pf())
        result = CompleteAction()(ctx=ctx, result="done", success=True)
        assert result.is_complete is True
        assert result.data["success"] is True
        assert result.data["result"] == "done"

    def test_declares_complete_on_failure(self):
        ctx = ActionContext(phonefast=_mock_pf())
        result = CompleteAction()(ctx=ctx, result="failed task", success=False)
        assert result.is_complete is True
        assert result.data["success"] is False

    def test_no_ctx_side_effects(self):
        """工具不写 ctx 任何 agent 侧字段（ctx 无 termination 属性）。"""
        ctx = ActionContext(phonefast=_mock_pf())
        CompleteAction()(ctx=ctx, result="ok", success=True)
        assert not hasattr(ctx, "termination") or ctx.__dict__.get("termination") is None

    def test_result_text_format(self):
        ctx = ActionContext(phonefast=_mock_pf())
        result = CompleteAction()(ctx=ctx, result="ok")
        assert result.to_llm_text() == "[OK] complete: ok"


class TestObserveAction:
    """observe 工具通过 data 声明屏幕观察，零 observer 副作用。"""

    def test_returns_observation_data(self):
        ctx = ActionContext(phonefast=_mock_pf())
        result = ObserveAction()(ctx=ctx)
        assert result.success is True
        obs = result.observation_data
        assert obs is not None
        text, count = obs
        assert isinstance(text, str) and text
        assert count == 1  # mock 屏幕含 1 个元素

    def test_no_observer_dependency(self):
        """ctx 无 observer 字段，工具不接触任何 agent 组件。"""
        ctx = ActionContext(phonefast=_mock_pf())
        assert not hasattr(ctx, "observer") or "observer" not in ctx.__dict__
        result = ObserveAction()(ctx=ctx)  # 不炸
        assert result.success is True


class TestActionResultConventions:
    """ActionResult 显式约定（工厂方法 + 属性）。"""

    def test_complete_factory(self):
        r = ActionResult.complete(result="done", success=False)
        assert r.is_complete is True
        assert r.success is False
        assert r.data["result"] == "done"

    def test_non_complete_result(self):
        r = ActionResult.ok("tapped", x=1, y=2)
        assert r.is_complete is False

    def test_observation_data_present(self):
        r = ActionResult.ok("observed", elements="[0] a", count=3)
        assert r.observation_data == ("[0] a", 3)

    def test_observation_data_absent(self):
        r = ActionResult.ok("tapped", x=1, y=2)
        assert r.observation_data is None

    def test_observation_data_partial_absent(self):
        """只有 elements 没有 count（或反之）→ 不算观察声明。"""
        assert ActionResult.ok("x", elements="[0] a").observation_data is None
        assert ActionResult.ok("x", count=3).observation_data is None
