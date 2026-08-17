"""回归测试：观察数据必须注入 messages + 停滞两级升级反馈。

背景（v3.x 确认的确认死循环根因）：
  观察类工具（observe/key(enter)/scroll_to_find）通过 ActionResult.data 带回
  observation_data（全量屏幕文本），但 _execute_tools 只同步指纹 + 发 hook，
  屏幕文本不进 messages——LLM 只拿到 "[OK] observed screen, N elements" 摘要，
  看不到屏幕内容，只能反复调 observe 试图看到（反复确认死循环）。

本测试用剧本化 LLM + 序列屏幕 MockPhonefast 确定性验证：
  A. observe / key(enter) 带回的屏幕文本注入 messages（修复 1）
  B. 屏幕持续无变化时停滞反馈从 stagnation_warn 升级为 stagnation_force（修复 2）
  C. 相同屏幕的重复 observe 不重复注入全量文本（指纹去重）
"""
from __future__ import annotations

from dataclasses import dataclass

from fastaget.agent.fast_agent import FastAgent
from fastaget.agent.capabilities import CompletionSignal, StagnationDetector, TurnSnapshot
from fastaget.agent.run_state import RunState
from fastaget.device.phonefast import ObserveResult
from fastaget.llm.delegate import LLMResponse, ToolCall
from fastaget.tools import build_registry

from fastaget.scenariokit.device import MockPhonefast

# ── flatref 格式屏幕（UIProcessor 可解析；bounds 为 [x1,y1][x2,y2] 两对括号）──
# 必须带 3 行 header：ScreenObserver._make_fingerprint 跳过前 3 行（真实 phonefast
# 输出的 header），无 header 时指纹退化为空串哈希，去重逻辑失效（mock 保真度）。
_HEADER = "Interactive elements on screen:\n========================================\nformat: flatref"
_HOME = (
    _HEADER + "\n" +
    '#0 text="主屏幕" id="home" (TextView) | bounds=[100,200][900,300] | [clickable] | depth=0 parent=#0'
)
_BAIDU = (
    _HEADER + "\n" +
    '#0 text="搜索框" id="search" (EditText) | bounds=[100,200][900,300] | [clickable] | depth=0 parent=#0\n'
    '#1 text="百度一下" id="btn" (Button) | bounds=[300,400][700,500] | [clickable] | depth=0 parent=#0'
)


class _SeqPhonefast(MockPhonefast):
    """每次 observe 返回序列中的下一个屏幕（耗尽后重复最后一个）。"""

    def __init__(self, texts: list[str]):
        super().__init__(screen_text=texts[0])
        self._texts = texts
        self._obs_count = 0

    def observe(self, concise: bool = True, max_elements: int = 80) -> ObserveResult:
        text = self._texts[min(self._obs_count, len(self._texts) - 1)]
        self._obs_count += 1
        return ObserveResult(elements_text=text, image_b64=None)


# ---------------------------------------------------------------------------
# 剧本化 LLM：按序返回固定 tool_use 序列
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedToolCallLLM:
    """无 stream 方法 → _stream_collect 回退 complete()（duck-typed 兼容路径）。"""

    script: list[ToolCall]
    _calls: int = 0
    last_messages: list | None = None

    @property
    def context_window(self) -> int:
        return 128_000

    def complete(self, system, messages, tools, *, vision=False, tool_choice=None):
        self.last_messages = messages
        if self._calls < len(self.script):
            tc = self.script[self._calls]
            self._calls += 1
            return LLMResponse(text="", tool_calls=[tc], stop_reason="tool_use")
        # 剧本耗尽 → 默认 complete 成功（防 max_steps 跑满）
        return LLMResponse(
            text="",
            tool_calls=[ToolCall(name="complete", input={"result": "done", "success": True}, id="c_end")],
            stop_reason="tool_use",
        )


def _make_agent(script: list[ToolCall], pf: MockPhonefast) -> tuple[FastAgent, _ScriptedToolCallLLM]:
    llm = _ScriptedToolCallLLM(script=script)
    registry = build_registry()
    agent = FastAgent(llm, pf, registry, max_steps=10)
    return agent, llm


def _user_texts(agent_messages: list) -> str:
    """拼接所有 user 消息中的纯文本块（屏幕注入的落点）。"""
    parts: list[str] = []
    for m in agent_messages:
        if m.get("role") != "user":
            continue
        for b in m.get("content", []):
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# A. 观察文本注入 messages（修复 1）
# ---------------------------------------------------------------------------


class TestObservationTextInjected:
    """观察类工具带回的屏幕文本必须进入 LLM 可见的 messages。

    契约：工具描述承诺"返回屏幕"的，屏幕文本必须送达 LLM——
    覆盖全部声明 observation_data 的工具（observe/key(enter)/
    scroll_to_find/wait_and_observe）。
    """

    @staticmethod
    def _assert_baidu_visible(script: list[ToolCall], texts: list[str]) -> None:
        pf = _SeqPhonefast(texts)
        agent, llm = _make_agent(script, pf)
        agent.run("打开浏览器，跳转到百度")
        injected = _user_texts(llm.last_messages)
        assert "搜索框" in injected, "工具带回的新屏幕文本必须注入 messages"
        assert "百度一下" in injected

    def test_observe_tool_screen_text_in_messages(self):
        """LLM 显式调 observe → 新屏幕全文注入，不再是只读摘要的'瞎子'。"""
        self._assert_baidu_visible(
            [ToolCall(name="observe", input={}, id="t1")],
            [_HOME, _BAIDU],  # init=home, observe→baidu
        )

    def test_key_enter_screen_text_in_messages(self):
        """key(enter) 自动 observe 带回的屏幕文本同样注入（跳转后 LLM 能看到新页面）。"""
        self._assert_baidu_visible(
            [ToolCall(name="key", input={"name": "enter"}, id="t1")],
            [_HOME, _BAIDU],  # init=home, enter 后→baidu
        )

    def test_scroll_to_find_screen_text_in_messages(self):
        """scroll_to_find 找到目标后带回的屏幕文本注入。"""
        self._assert_baidu_visible(
            [ToolCall(name="scroll_to_find", input={"text": "搜索框"}, id="t1")],
            [_HOME, _BAIDU, _BAIDU],  # init=home（无目标）, swipe 后→baidu（找到）
        )

    def test_wait_and_observe_screen_text_in_messages(self):
        """wait_and_observe 带回的屏幕文本注入。"""
        self._assert_baidu_visible(
            [ToolCall(name="wait_and_observe", input={"seconds": 0}, id="t1")],
            [_HOME, _BAIDU],
        )

    def test_batch_tap_then_observe_injects(self):
        """批次 [tap, observe]：observe 是批次内最新信息 → 注入 observe 的屏幕。"""
        self._assert_baidu_visible(
            [ToolCall(name="tap", input={"x": 100, "y": 100}, id="t1"),
             ToolCall(name="observe", input={}, id="t2")],
            [_HOME, _BAIDU],  # init=home, observe→baidu
        )

    def test_batch_observe_then_tap_auto_observes(self):
        """批次 [observe, tap]：动作在观察之后 → 不被 observed 抑制，auto-observe 取最新屏幕。

        此前 observed=True 会抑制轮末 auto-observe，tap 后的新屏幕永远不进
        messages——批次顺序导致的"瞎子"缺口。
        """
        # init=home, observe→home（未变）, tap 后 auto-observe→baidu
        self._assert_baidu_visible(
            [ToolCall(name="observe", input={}, id="t1"),
             ToolCall(name="tap", input={"x": 100, "y": 100}, id="t2")],
            [_HOME, _HOME, _BAIDU],
        )


# ---------------------------------------------------------------------------
# B. 停滞两级升级反馈（修复 2）
# ---------------------------------------------------------------------------


def _stagnate(det: StagnationDetector, state: RunState, n: int, tool: str = "tap") -> RunState:
    snap = TurnSnapshot(phase="post_turn", fingerprint="same:fp",
                        element_count=10, last_tool=tool)
    for _ in range(n):
        state = det(state, snap)
    return state


class TestStagnationEscalation:
    """屏幕持续无变化：软提示 → 强制命令（禁止再 observe）。"""

    def test_first_warning_is_soft(self):
        det = StagnationDetector(window=2, force_limit=2)
        state = RunState(goal="t")
        state = _stagnate(det, state, 2)  # window=2 → 第 2 条起 count=1
        assert state.pending_feedback, "首次停滞应有软提示"
        # 软提示标志："WARNING"；强制命令是 "MANDATORY"（stagnation_force）
        assert "WARNING" in state.pending_feedback[-1]
        assert "do NOT observe again" not in state.pending_feedback[-1]

    def test_escalates_to_force(self):
        det = StagnationDetector(window=2, force_limit=2)
        state = RunState(goal="t")
        state = _stagnate(det, state, 3)  # count=2 → force
        assert "do NOT observe again" in state.pending_feedback[-1], \
            "count 达到 force_limit 必须升级为强制命令"

    def test_force_limit_configurable(self):
        """force_limit 是构造参数（不严格写死），可整体调大保持软提示。"""
        det = StagnationDetector(window=2, force_limit=99)
        state = RunState(goal="t")
        state = _stagnate(det, state, 5)
        assert all("do NOT observe again" not in fb for fb in state.pending_feedback)


# ---------------------------------------------------------------------------
# v1.14: 低元素盲区拆分 + CompletionSignal 冷却
# ---------------------------------------------------------------------------


def _low_element_turns(det: StagnationDetector, state: RunState,
                       els: list[int], fps: list[str],
                       tools: list[str] | None = None) -> RunState:
    """喂入若干轮 post_turn 快照（el/fp/last_tool 可控），返回最终 state。"""
    if tools is None:
        tools = ["observe"] * len(els)
    for el, fp, t in zip(els, fps, tools):
        snap = TurnSnapshot(phase="post_turn", fingerprint=fp,
                            element_count=el, last_tool=t)
        state = det(state, snap)
    return state


class TestBlindZone:
    """取景器/播放器等低元素屏：持续低元素→盲区引导(用设备事实)，而非误报"wait for load"。"""

    def test_blind_zone_fires_on_persistent_low_element(self):
        # 3 轮 el=3(取景器)，fp 每轮变(计时器抖动) → 持续低元素→blind_zone
        det = StagnationDetector(window=2, blind_persist=3)
        state = RunState(goal="t")
        state = _low_element_turns(det, state,
                                   els=[3, 3, 3], fps=["fp0", "fp1", "fp2"],
                                   tools=["tap_element", "wait_and_observe", "observe"])
        assert any("DEVICE FACTS" in fb for fb in state.pending_feedback), \
            "持续低元素(取景器)应注入 blind_zone 引导用设备事实"

    def test_degradation_not_wait_advice(self):
        # 骤降(20→2)+flux → degradation 触发，但建议"observe"而非"wait"(防死循环)
        det = StagnationDetector(window=2, blind_persist=3)
        state = RunState(goal="t")
        state = _low_element_turns(det, state,
                                   els=[20, 2], fps=["desk", "cam"],
                                   tools=["launch", "observe"])
        assert any("observe ONCE more" in fb for fb in state.pending_feedback), \
            "骤降+flux 应触发 degradation 且建议 observe(非 wait)"
        assert all("wait for load recovery" not in fb for fb in state.pending_feedback), \
            "degradation 不得再建议 wait(致 observe→wait→observe 死循环)"

    def test_blind_zone_skipped_when_agent_uses_fact_tool(self):
        # 持续低元素但 agent 已在用 shell 查证 → 不 nag(它在做对的事)
        det = StagnationDetector(window=2, blind_persist=3)
        state = RunState(goal="t")
        state = _low_element_turns(det, state,
                                   els=[3, 3, 3], fps=["fp0", "fp1", "fp2"],
                                   tools=["shell", "shell", "shell"])
        assert all("DEVICE FACTS" not in fb for fb in state.pending_feedback), \
            "agent 已在用 shell(fact 工具)查证，blind_zone 不应 nag"

    def test_blind_zone_fires_once_per_episode(self):
        # 持续低元素 5 轮 → blind_zone 只注入一次(去抖)
        det = StagnationDetector(window=2, blind_persist=3)
        state = RunState(goal="t")
        state = _low_element_turns(det, state,
                                   els=[3, 3, 3, 3, 3],
                                   fps=["fp0", "fp1", "fp2", "fp3", "fp4"],
                                   tools=["observe"] * 5)
        count = sum(1 for fb in state.pending_feedback if "DEVICE FACTS" in fb)
        assert count == 1, f"持续低元素 episode 只注入一次，实际 {count}"

    def test_blind_zone_resets_when_elements_recover(self):
        # 低元素→恢复→再低元素：第二次 episode 应能再次触发
        det = StagnationDetector(window=2, blind_persist=3)
        state = RunState(goal="t")
        # 第一次 episode：3 轮低元素→触发
        state = _low_element_turns(det, state,
                                   els=[3, 3, 3], fps=["a", "b", "c"],
                                   tools=["observe"] * 3)
        first = sum(1 for fb in state.pending_feedback if "DEVICE FACTS" in fb)
        assert first == 1
        # 恢复(高元素)→重置 episode
        state = _low_element_turns(det, state,
                                   els=[20], fps=["d"], tools=["observe"])
        # 第二次 episode：3 轮低元素→应再次触发
        state = _low_element_turns(det, state,
                                   els=[3, 3, 3], fps=["e", "f", "g"],
                                   tools=["observe"] * 3)
        total = sum(1 for fb in state.pending_feedback if "DEVICE FACTS" in fb)
        assert total == 2, f"恢复后再次进入盲区应能再触发，实际 {total}"


class TestCompletionSignalCooldown:
    """连续操作提醒触发后冷却 N 轮——盲区里 action→observe→action 不反复 nag。"""

    def test_cooldown_suppresses_refire(self):
        sig = CompletionSignal(limit=3, cooldown=4)
        state = RunState(goal="t")
        # 3 连续 action → 触发
        for _ in range(3):
            state = sig(state, TurnSnapshot(phase="post_turn", last_tool="tap_element"))
        assert any("consecutive operations" in fb for fb in state.pending_feedback), \
            "3 连续 action 应触发 completion_signal"
        # 冷却期 4 轮 action → 不应再触发
        state.pending_feedback.clear()
        for _ in range(4):
            state = sig(state, TurnSnapshot(phase="post_turn", last_tool="tap_element"))
        assert not state.pending_feedback, "冷却期内不应重复 nag"

    def test_refire_after_cooldown_expires(self):
        sig = CompletionSignal(limit=3, cooldown=4)
        state = RunState(goal="t")
        # 触发一次
        for _ in range(3):
            state = sig(state, TurnSnapshot(phase="post_turn", last_tool="tap_element"))
        state.pending_feedback.clear()
        # 冷却 4 轮
        for _ in range(4):
            state = sig(state, TurnSnapshot(phase="post_turn", last_tool="tap_element"))
        assert not state.pending_feedback
        # 冷却过期后继续 action → 累计达标再触发
        state = sig(state, TurnSnapshot(phase="post_turn", last_tool="tap_element"))
        assert state.pending_feedback, "冷却过期后累计达标应再触发"

    def test_observe_resets_consecutive(self):
        sig = CompletionSignal(limit=3, cooldown=4)
        state = RunState(goal="t")
        # 2 action + 1 observe → observe 重置 _consecutive，不触发
        for t in ("tap_element", "tap_element", "observe"):
            state = sig(state, TurnSnapshot(phase="post_turn", last_tool=t))
        assert not state.pending_feedback, "observe 重置计数，3 轮内不应触发"


# ---------------------------------------------------------------------------
# C. complete evidence 字段——判断依据可审计
# ---------------------------------------------------------------------------


class TestCompleteEvidence:
    """complete 的 evidence 随 result 进入最终 summary，QA 归因可见。"""

    def test_evidence_flows_to_summary(self):
        pf = _SeqPhonefast([_BAIDU])
        script = [ToolCall(name="complete", input={
            "result": "已跳转到百度", "success": True,
            "evidence": "页面含搜索框与'百度一下'按钮",
        }, id="t1")]
        agent, _ = _make_agent(script, pf)

        result = agent.run("打开浏览器，跳转到百度")

        assert result.success
        assert "已跳转到百度" in result.summary
        assert "百度一下" in result.summary

    def test_no_evidence_backward_compatible(self):
        """不传 evidence → summary 保持原样（向后兼容）。"""
        pf = _SeqPhonefast([_BAIDU])
        script = [ToolCall(name="complete", input={
            "result": "已完成", "success": True,
        }, id="t1")]
        agent, _ = _make_agent(script, pf)

        result = agent.run("打开浏览器，跳转到百度")

        assert result.success
        assert result.summary == "已完成"
        assert "依据" not in result.summary


# ---------------------------------------------------------------------------
# D. 相同屏幕不重复注入（指纹去重）
# ---------------------------------------------------------------------------


class TestIdenticalScreenNotReinjected:
    """连续两次 observe 相同屏幕 → 第二次不注入全量文本（切断确认循环的燃料）。"""

    def test_duplicate_observe_not_reinjected(self):
        # init=home, 第一次 observe→baidu（注入）, 第二次 observe→baidu（相同，不注入）
        pf = _SeqPhonefast([_HOME, _BAIDU, _BAIDU])
        script = [
            ToolCall(name="observe", input={}, id="t1"),
            ToolCall(name="observe", input={}, id="t2"),
        ]
        agent, llm = _make_agent(script, pf)

        agent.run("打开浏览器，跳转到百度")

        # "搜索框" 只在第一次 observe 的注入里出现 1 次
        injected = _user_texts(llm.last_messages)
        occurrences = injected.count("搜索框")
        assert occurrences == 1, \
            f"重复 observe 相同屏幕不应再注入全量文本，实际出现 {occurrences} 次"
