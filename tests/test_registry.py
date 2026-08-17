"""ToolRegistry 测试：注册、定义、执行、异常转结构化结果。"""
from fastaget.tools.context import ActionContext
from fastaget.tools.registry import ActionResult, ToolRegistry

from fastaget.scenariokit import MockPhonefast


def _fake_ctx() -> ActionContext:
    return ActionContext(phonefast=None)  # type: ignore[arg-type]


def test_register_and_names():
    reg = ToolRegistry()
    reg.register("ping", lambda **_: ActionResult.ok("pong"), "ping", {})
    assert reg.names() == ["ping"]


def test_execute_unknown_tool():
    reg = ToolRegistry()
    result = reg.execute("nope", {}, _fake_ctx())
    assert not result.success
    assert "Unknown tool" in result.summary


def test_execute_exception_becomes_fail():
    reg = ToolRegistry()

    def boom(*, ctx, **_):
        raise RuntimeError("kaboom")

    reg.register("boom", boom, "boom", {})
    result = reg.execute("boom", {}, _fake_ctx())
    assert not result.success
    assert "kaboom" in result.summary


def test_execute_passes_args_without_ctx():
    reg = ToolRegistry()
    reg.register("add", lambda x, y: ActionResult.ok(f"{x+y}"), "add", {})
    result = reg.execute("add", {"x": 1, "y": 2}, _fake_ctx())
    assert result.success
    assert result.summary == "3"


def test_definitions_shape():
    reg = ToolRegistry()
    reg.register(
        "tap", lambda **_: ActionResult.ok(""), "tap",
        params={"x": {"type": "integer", "required": True}, "y": {"type": "integer", "required": True}},
    )
    defs = reg.definitions()
    assert defs[0]["name"] == "tap"
    params = defs[0]["input_schema"]
    assert params["required"] == ["x", "y"]
    assert params["properties"]["x"]["type"] == "integer"


def test_actionresult_to_llm_text():
    assert ActionResult.ok("done").to_llm_text() == "[OK] done"
    assert ActionResult.fail("bad").to_llm_text() == "[FAILED] bad"


def test_actions_import_clean():
    """回归：actions 模块必须能干净 import（曾因缺 UIState import 导致真机 observe 崩）。"""
    import fastaget.tools.actions as A  # noqa: F401
    assert hasattr(A, "ObserveAction")
    assert hasattr(A, "CompleteAction")


def test_key_tool_registered():
    """key 工具应注册且 name 参数必填。"""
    from fastaget.tools import build_registry
    reg = build_registry()
    assert "key" in reg.names()
    entry = reg.get("key")
    assert entry is not None
    assert entry.params["name"]["required"] is True


def test_action_key_calls_phonefast():
    """KeyAction 调用 phonefast.key。"""
    from fastaget.tools.actions import KeyAction
    pf = MockPhonefast('[0] text="A" (TextView) bounds=[0,0][10,10]')
    ctx = ActionContext(phonefast=pf)
    res = KeyAction()(ctx=ctx, name="enter")
    assert res.success
    assert "key(enter)" in pf.actions
    assert res.data["name"] == "enter"
