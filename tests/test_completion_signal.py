"""CompletionSignal 能力测试——连续纯操作无验证时提示收尾。

这是旧 `fast_agent._check_progress` 完成信号分支的等价测试，
迁移到 v3.2 的 Capability 体系后，判定逻辑落在
`fastaget.agent.capabilities.CompletionSignal`（post_turn 阶段生效）。

覆盖场景：
- 连续 N 步纯操作（tap/type/swipe）无 observe/complete → 触发收尾提示
- 含查询工具（observe/shell/assert）→ 重置计数，不触发
- 触发后重置，不重复提醒
- limit 不足时不触发
"""
from __future__ import annotations

from fastaget.agent.capabilities import CompletionSignal, TurnSnapshot
from fastaget.agent.run_state import RunState


def _snap_post_turn(last_tool: str) -> TurnSnapshot:
    """构造 post_turn 阶段快照，只填 last_tool。"""
    return TurnSnapshot(phase="post_turn", last_tool=last_tool)


def _state() -> RunState:
    return RunState(goal="test")


def test_no_signal_below_limit():
    """连续纯操作不足 limit → 不触发。"""
    cs = CompletionSignal(limit=3)
    state = _state()
    cs(state, _snap_post_turn("tap_element"))
    cs(state, _snap_post_turn("tap_element"))
    # 只 2 步 < limit 3
    assert state.pending_feedback == []


def test_signal_on_consecutive_pure_actions():
    """连续 limit 步纯操作无验证 → 触发收尾提示。"""
    cs = CompletionSignal(limit=3)
    state = _state()
    cs(state, _snap_post_turn("tap_element"))
    cs(state, _snap_post_turn("tap_element"))
    assert state.pending_feedback == []
    cs(state, _snap_post_turn("tap_element"))
    assert len(state.pending_feedback) == 1


def test_observe_resets_counter():
    """含 observe 验证 → 重置计数，不触发。"""
    cs = CompletionSignal(limit=3)
    state = _state()
    cs(state, _snap_post_turn("tap_element"))
    cs(state, _snap_post_turn("tap_element"))
    cs(state, _snap_post_turn("observe"))  # 查询工具重置
    cs(state, _snap_post_turn("tap_element"))
    assert state.pending_feedback == []


def test_assert_resets_counter():
    """含 assert → 重置计数，不触发。"""
    cs = CompletionSignal(limit=3)
    state = _state()
    cs(state, _snap_post_turn("tap_element"))
    cs(state, _snap_post_turn("assert"))
    cs(state, _snap_post_turn("tap_element"))
    assert state.pending_feedback == []


def test_shell_resets_counter():
    """含 shell（查询工具）→ 重置计数，不触发。"""
    cs = CompletionSignal(limit=3)
    state = _state()
    cs(state, _snap_post_turn("tap_element"))
    cs(state, _snap_post_turn("tap_element"))
    cs(state, _snap_post_turn("shell"))
    cs(state, _snap_post_turn("tap_element"))
    assert state.pending_feedback == []


def test_no_repeat_after_triggered():
    """触发后重置，后续需再次累积满 limit 才触发。"""
    cs = CompletionSignal(limit=3)
    state = _state()
    # 累积 3 步触发
    for _ in range(3):
        cs(state, _snap_post_turn("tap_element"))
    assert len(state.pending_feedback) == 1
    # 触发后重置，再来 1 步不应触发
    cs(state, _snap_post_turn("tap_element"))
    assert len(state.pending_feedback) == 1


def test_mixed_pure_actions_trigger():
    """不同纯操作混搭（tap/swipe/type）但都无验证 → 仍触发。"""
    cs = CompletionSignal(limit=3)
    state = _state()
    cs(state, _snap_post_turn("tap_element"))
    cs(state, _snap_post_turn("swipe"))
    cs(state, _snap_post_turn("type"))
    assert len(state.pending_feedback) == 1


def test_other_phase_ignored():
    """非 post_turn 阶段不生效。"""
    cs = CompletionSignal(limit=1)
    state = _state()
    cs(state, TurnSnapshot(phase="pre_turn", last_tool="tap_element"))
    assert state.pending_feedback == []
