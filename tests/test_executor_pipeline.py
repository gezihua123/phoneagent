"""TDD Round 1：架构评审 B1/B2/B3 的失败测试（先红后绿）。

B1: step.cost_usd 记累计成本而非本轮成本 → 应为本轮 LLM 成本
B2: baseline.txt 缺失 → 空 system prompt 静默运行 → 应构造期显式报错
B3: 停滞检测阈值内联字面量 → 应可参数化

全部使用虚拟设备（MockPhonefast）+ scripted LLM，不连真机。
"""
from __future__ import annotations

import pytest

from fastaget.agent.capabilities import FaultTolerance, StagnationDetector, TurnSnapshot
from fastaget.agent.fast_agent import FastAgent
from fastaget.agent.run_state import RunState
from fastaget.llm.delegate import ToolCall
from fastaget.tools import build_registry

from fastaget.scenariokit import MockPhonefast


from tests.conftest import FLATREF_SCREEN as _SCREEN, make_llm_response as _resp


class _TwoTurnScriptedLLM:
    """脚本 LLM：turn1 调 tap（成本 0.001），turn2 调 complete（成本 0.005）。

    用于区分"本轮成本"与"累计成本"：若实现正确，
    step[0].cost_usd == 0.001（turn1 成本），
    step[1].cost_usd == 0.005（turn2 成本，而非累计 0.006）。
    """
    model = "test-model"

    def __init__(self):
        self._calls = 0

    def complete(self, system, messages, tools, *, vision=False, **_):
        self._calls += 1
        if self._calls == 1:
            return _resp(tool_calls=[
                ToolCall(name="back", input={}, id="t1"),
            ], cost=0.001)
        return _resp(tool_calls=[
            ToolCall(name="complete", input={"result": "done", "success": True}, id="t2"),
        ], cost=0.005)

    def close(self):
        pass


class TestStepCostAttribution:
    """B1：step.cost_usd 应是生成该工具调用的本轮 LLM 成本，不是累计值。"""

    def test_step_cost_is_per_turn_not_cumulative(self):
        pf = MockPhonefast(_SCREEN)
        llm = _TwoTurnScriptedLLM()
        agent = FastAgent(llm, pf, build_registry(), max_steps=5)
        result = agent.run("test goal")

        assert len(result.steps_detail) == 2
        step1_cost = result.steps_detail[0].cost_usd
        step2_cost = result.steps_detail[1].cost_usd
        assert step1_cost == pytest.approx(0.001), (
            f"step1 应为 turn1 成本 0.001，实际 {step1_cost}")
        assert step2_cost == pytest.approx(0.005), (
            f"step2 应为 turn2 成本 0.005，实际 {step2_cost}（累计 bug）")


class TestEmptySystemPromptFailsLoudly:
    """B2：baseline.txt 缺失/为空 → 构造期显式报错，不静默跑空 prompt。"""

    def test_empty_system_prompt_raises(self, monkeypatch):
        monkeypatch.setattr(
            "fastaget.agent.fast_agent._load_prompt", lambda name: "")
        pf = MockPhonefast(_SCREEN)
        with pytest.raises(ValueError, match="system_prompt|baseline"):
            FastAgent(_TwoTurnScriptedLLM(), pf, build_registry())

    def test_explicit_prompt_bypasses_check(self, monkeypatch):
        """显式传入 system_prompt 时不受 baseline 文件缺失影响。"""
        monkeypatch.setattr(
            "fastaget.agent.fast_agent._load_prompt", lambda name: "")
        pf = MockPhonefast(_SCREEN)
        agent = FastAgent(
            _TwoTurnScriptedLLM(), pf, build_registry(),
            system_prompt="custom prompt")
        # custom prompt 是前缀（sandbox ref 可能追加在后面）
        assert agent.system_prompt.startswith("custom prompt")


class TestCompleteProtocolNudge:
    """B7 修复：LLM 纯文本结束 → 催促调 complete → 结构化声明；拒不调用 → 诚实判失败。"""

    class _TextEndLLM:
        """永远以纯文本结束（不调 complete）。"""
        model = "test-model"

        def complete(self, system, messages, tools, *, vision=False, **_):
            return _resp(text="我觉得已经搞定了")

        def close(self):
            pass

    class _NudgeThenCompleteLLM:
        """第一次纯文本结束，被催促后调 complete(success=true)。"""
        model = "test-model"

        def __init__(self):
            self._calls = 0

        def complete(self, system, messages, tools, *, vision=False, **_):
            self._calls += 1
            if self._calls == 1:
                return _resp(text="先说说")
            return _resp(tool_calls=[
                ToolCall(name="complete", input={"result": "done", "success": True}, id="t1"),
            ])

        def close(self):
            pass

    def test_text_end_nudged_then_complete_succeeds(self):
        pf = MockPhonefast(_SCREEN)
        agent = FastAgent(self._NudgeThenCompleteLLM(), pf, build_registry(), max_steps=5)
        result = agent.run("test goal")
        assert result.success is True
        assert result.summary == "done"

    def test_text_end_stubborn_fails_honestly(self):
        """拒不调 complete → success=False，摘要点明协议违规。"""
        pf = MockPhonefast(_SCREEN)
        agent = FastAgent(self._TextEndLLM(), pf, build_registry(), max_steps=5)
        result = agent.run("test goal")
        assert result.success is False
        assert "自动终止" in result.summary

    def test_nudge_does_not_count_as_step(self):
        """催促轮不消耗步数预算（step 只计工具调用）。"""
        pf = MockPhonefast(_SCREEN)
        agent = FastAgent(self._NudgeThenCompleteLLM(), pf, build_registry(), max_steps=5)
        result = agent.run("test goal")
        # 只有 complete 一个工具调用
        assert result.steps == 1


class TestForcedStructuredOutput:
    """指定 LLM JSON 结构化输出：API 层 tool_choice 强制每轮必须 tool_use。"""

    class _RecordingLLM:
        """记录 complete() 收到的 kwargs。"""
        model = "test-model"

        def __init__(self):
            self.calls: list[dict] = []

        def complete(self, system, messages, tools, **kwargs):
            self.calls.append(kwargs)
            return _resp(tool_calls=[
                ToolCall(name="complete", input={"result": "ok", "success": True}, id="t1"),
            ])

        def close(self):
            pass

    def test_agent_forces_tool_use_by_default(self):
        llm = self._RecordingLLM()
        pf = MockPhonefast(_SCREEN)
        agent = FastAgent(llm, pf, build_registry(), max_steps=3)
        agent.run("test goal")

        assert llm.calls, "LLM 未被调用"
        for kw in llm.calls:
            assert kw.get("tool_choice") == {"type": "any"}, (
                f"应强制 tool_choice=any 保证结构化输出，实际: {kw.get('tool_choice')}")

    def test_force_tool_use_disabled_passes_none(self):
        llm = self._RecordingLLM()
        pf = MockPhonefast(_SCREEN)
        agent = FastAgent(llm, pf, build_registry(), max_steps=3,
                          force_tool_use=False)
        agent.run("test goal")

        for kw in llm.calls:
            assert kw.get("tool_choice") is None


class TestStagnationThresholdsConfigurable:
    """B3：停滞阈值参数化。

    v3.1 架构：检测逻辑隔离在 StagnationDetector 能力中（capabilities.py），
    独立可测——不需要构造 FastAgent，直接喂 TurnSnapshot 驱动。
    """

    @staticmethod
    def _snap(fp: str = "abc", el: int = 10, tool: str = "tap_element") -> TurnSnapshot:
        return TurnSnapshot(phase="post_turn", fingerprint=fp,
                            element_count=el, last_tool=tool)

    def test_custom_window(self):
        """window=2 时，2 个相同指纹即触发停滞告警（写入 pending_feedback）。"""
        det = StagnationDetector(window=2)
        state = RunState(goal="t")
        state = det(state, self._snap())  # 第 1 条：窗口未满
        assert not state.pending_feedback
        state = det(state, self._snap())  # 第 2 条：窗口全同 → 告警
        assert state.pending_feedback, "window=2 全同指纹应产生停滞告警"
        assert not state.terminal

    def test_custom_limit(self):
        """limit=1 时，第 2 次停滞即强制终止。"""
        det = StagnationDetector(window=3, limit=1)
        state = RunState(goal="t")
        for _ in range(6):
            state = det(state, self._snap())
            if state.terminal:
                break
        assert state.terminal and not state.success

    def test_exempt_tool_not_counted(self):
        """豁免工具（back/home/wait 等）指纹相同也不计停滞。"""
        det = StagnationDetector(window=2, limit=1)
        state = RunState(goal="t")
        for _ in range(5):
            state = det(state, self._snap(tool="back"))
        assert not state.terminal
        assert not state.pending_feedback

    def test_phase_isolation(self):
        """非 post_turn 阶段调用 → 不动作（能力只在自己的生命周期生效）。"""
        det = StagnationDetector(window=2, limit=1)
        state = RunState(goal="t")
        wrong_snap = TurnSnapshot(phase="post_llm")
        for _ in range(5):
            state = det(state, wrong_snap)
        assert not state.terminal
        assert not state.pending_feedback

    def test_fps_bounded(self):
        """P1：_fps 列表不超 window*2（防无界增长）。"""
        det = StagnationDetector(window=3, limit=100)
        state = RunState(goal="t")
        for i in range(100):
            state = det(state, self._snap(fp=f"screen{i}"))
        assert len(det._fps) <= 6  # window*2

    def test_reset_clears_state(self):
        """P10：reset() 清空 _fps + _count，续跑不误判。"""
        det = StagnationDetector(window=2, limit=1)
        state = RunState(goal="t")
        for _ in range(3):
            state = det(state, self._snap())
        assert det._count > 0
        assert len(det._fps) > 0
        det.reset()
        assert det._fps == []
        assert det._count == 0


class TestFaultTolerancePhases:
    """P2 修复验证：FaultTolerance 通过 llm_success 相位重置，无跨列表耦合。"""

    def test_llm_success_resets_count(self):
        """llm_success 相位重置失败计数。"""
        ft = FaultTolerance(limit=3)
        state = RunState(goal="t")
        # 2 次失败
        state = ft(state, TurnSnapshot(phase="llm_failure"))
        state = ft(state, TurnSnapshot(phase="llm_failure"))
        assert ft._fails == 2
        # 成功 → 重置
        state = ft(state, TurnSnapshot(phase="llm_success"))
        assert ft._fails == 0
        # 再失败 1 次 → 不超限（因为之前已重置）
        state = ft(state, TurnSnapshot(phase="llm_failure"))
        assert not state.terminal

    def test_not_in_post_llm_caps(self):
        """FaultTolerance 不应在默认 post_llm_caps 里（无跨列表耦合）。"""
        pf = MockPhonefast(_SCREEN)
        agent = FastAgent(_TwoTurnScriptedLLM(), pf, build_registry())
        cap_types = [type(c).__name__ for c in agent.post_llm_caps]
        assert "FaultTolerance" not in cap_types
        assert "FaultTolerance" in [type(c).__name__ for c in agent.llm_failure_caps]
