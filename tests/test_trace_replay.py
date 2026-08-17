"""历史 trace 回放测试（TDD Round 3）。

从 tests/fixtures/traces/*.trace.jsonl 提取真实执行记录（goal + LLM 决策序列 +
工具序列 + 终局结果），用虚拟设备回放，验证重构后的管道行为保真：

  1. 工具按记录顺序执行（顺序保真）
  2. 终局结果与记录一致（结果保真）

不连真机：LLM 用脚本回放（trace 里的 reasoning_text + tool_calls），
设备用 MockPhonefast（循环屏幕避免指纹停滞干扰长脚本回放）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastaget.agent.fast_agent import FastAgent
from fastaget.llm.delegate import LLMResponse, ToolCall
from fastaget.tools import build_registry

from fastaget.scenariokit import MockPhonefast
from fastaget.scenariokit.device import Screen


# 回放输入固化在 fixtures（原读取 build/traces/ 本地产物——换机即全部静默 skip）
TRACES_DIR = Path(__file__).resolve().parent / "fixtures" / "traces"


# ---- trace 提取 ----

@dataclass
class TraceCase:
    """从一条 trace 提取的首个 run 的可回放 case。"""
    goal: str
    llm_script: list[LLMResponse]      # 按 call_index 顺序
    expected_tools: list[str]          # tool_start 事件的 name 序列
    expected_success: bool
    source: str


def load_trace_case(path: Path) -> TraceCase:
    """解析 trace JSONL，提取首个 run（run_start → 首个 finish 之间）。"""
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    goal = ""
    llm_script: list[LLMResponse] = []
    tools: list[str] = []
    success = False
    seen_finish = False

    for e in events:
        ev = e.get("event")
        if ev == "run_start":
            goal = e.get("goal", "")
        elif ev == "finish":
            success = bool(e.get("success"))
            seen_finish = True
            break  # 只取首个 run
        elif seen_finish:
            break
        elif ev == "llm_end":
            tcs = [
                ToolCall(name=tc["name"], input=tc.get("input", {}), id=tc.get("id", f"tc{i}"))
                for i, tc in enumerate(e.get("tool_calls") or [])
            ]
            llm_script.append(LLMResponse(
                text=e.get("reasoning_text") or "",
                tool_calls=tcs,
                stop_reason=e.get("stop_reason") or ("tool_use" if tcs else "end_turn"),
                cost_usd=e.get("cost_usd") or 0.0,
                raw={"usage": e.get("usage") or {}},
            ))
        elif ev == "tool_start":
            tools.append(e.get("name", ""))

    return TraceCase(
        goal=goal, llm_script=llm_script,
        expected_tools=tools, expected_success=success,
        source=path.name,
    )


# ---- 回放替身 ----

class _ReplayLLM:
    """脚本 LLM：按 trace 记录顺序回放响应；脚本耗尽后返回无工具文本（确定性终止）。"""
    model = "trace-replay"

    def __init__(self, script: list[LLMResponse]):
        self._script = list(script)
        self._idx = 0

    def complete(self, system, messages, tools, *, vision=False, **_):
        if self._idx < len(self._script):
            resp = self._script[self._idx]
            self._idx += 1
            return resp
        # 脚本耗尽：无工具调用 → 管道自然终止
        return LLMResponse(
            text="(trace 回放结束)", tool_calls=[],
            stop_reason="end_turn", cost_usd=0.0, raw={"usage": {}},
        )

    def close(self):
        pass


class _CyclingPhonefast(MockPhonefast):
    """循环屏幕 Mock：每次 observe 轮换不同屏幕，避免静态屏幕触发停滞，
    保证长脚本（>7 轮）能完整回放而不被停滞检测中断。"""

    def __init__(self, screen_texts: list[str]):
        super().__init__(screen_texts[0])
        self._cycle = [Screen(key=f"s{i}", text=t) for i, t in enumerate(screen_texts)]
        self._pos = 0

    def observe(self, concise: bool = True, max_elements: int = 80):
        self._screen = self._cycle[self._pos % len(self._cycle)]
        self._pos += 1
        return super().observe(concise=concise, max_elements=max_elements)


def _distinct_screens(n: int = 8) -> list[str]:
    """生成 n 个内容互异的 phonefast 原始格式屏幕。"""
    return [
        f'[0] text="屏幕{i}" (TextView) [clickable] bounds=[0,{100+i*50}][200,{200+i*50}]\n'
        f'[1] text="按钮{i}" (Button) [clickable] bounds=[200,{100+i*50}][400,{200+i*50}]'
        for i in range(n)
    ]


def _replay(case: TraceCase):
    """回放一个 trace case，返回 (agent执行的工具名序列, AgentResult)。"""
    pf = _CyclingPhonefast(_distinct_screens())
    llm = _ReplayLLM(case.llm_script)
    agent = FastAgent(llm, pf, build_registry(), max_steps=max(20, len(case.llm_script) + 2))
    result = agent.run(case.goal)
    executed = [s.action for s in result.steps_detail]
    return executed, result


# ---- 回放测试 ----

def _require_trace(name: str) -> Path:
    path = TRACES_DIR / name
    assert path.is_file(), f"回放 fixture 缺失（应已提交到 git）: {path}"
    return path


class TestTraceReplay:
    """真实 trace 回放：顺序保真 + 结果保真。"""

    def test_replay_success_case_wifi_off(self):
        """024426f753b2: 打开设置，关闭WiFi — 真实成功 case（11 步 UI 流）。"""
        case = load_trace_case(_require_trace("024426f753b2.trace.jsonl"))
        assert case.expected_success is True  # 数据健康检查

        executed, result = _replay(case)

        # 顺序保真：工具序列与记录一致
        assert executed == case.expected_tools, (
            f"工具序列不一致\n  回放: {executed}\n  记录: {case.expected_tools}")
        # 结果保真
        assert result.success is True, f"成功 case 回放失败: {result.summary}"

    def test_replay_failure_case_sms_stagnation(self):
        """004623074f25: 打开短信发你好给10086 — 真实失败 case（LLM 未 complete）。"""
        case = load_trace_case(_require_trace("004623074f25.trace.jsonl"))
        assert case.expected_success is False  # 数据健康检查

        executed, result = _replay(case)

        # 顺序保真
        assert executed == case.expected_tools, (
            f"工具序列不一致\n  回放: {executed}\n  记录: {case.expected_tools}")
        # 结果保真：LLM 脚本未含 complete(success=true) → 失败
        assert result.success is False

class TestTraceExtraction:
    """trace 提取器本身的健康性。"""

    def test_extracts_goal_and_script(self):
        case = load_trace_case(_require_trace("024426f753b2.trace.jsonl"))
        assert "WiFi" in case.goal or "wifi" in case.goal.lower()
        assert len(case.llm_script) > 0
        assert all(isinstance(r, LLMResponse) for r in case.llm_script)

    def test_first_run_only(self):
        """含 2 个 run 的 trace 只提取首个 run。"""
        case = load_trace_case(_require_trace("004623074f25.trace.jsonl"))
        # 首个 run 的 finish 后不应再有 llm_end 进入 script
        # 004623074f25 首 run 6 步 → script 长度有限
        assert len(case.llm_script) <= 8

    def test_empty_trace_returns_defaults(self):
        """空 trace 提取不应崩溃——返回合理默认值。"""
        from pathlib import Path
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = Path(f.name)
        try:
            case = load_trace_case(path)
            assert case.goal == ""
            assert case.llm_script == []
            assert case.expected_tools == []
            assert case.expected_success is False
        finally:
            path.unlink(missing_ok=True)


class TestReplayEdgeCases:
    """回放边缘情况：脚本耗尽、工具序列超长。"""

    def test_exhausted_script_returns_text_only(self):
        """脚本耗尽后 LLM 返回无工具文本 → 管道自然结束（非挂死）。"""
        llm = _ReplayLLM([])
        resp = llm.complete("system", [{"role": "user", "content": "hi"}], [])
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"

    def test_script_partial_exhausted_mid_run(self):
        """脚本轨迹少于预期 turns → 后续 LLM 调返回无工具文本，agent 自然终止。"""
        case = load_trace_case(_require_trace("024426f753b2.trace.jsonl"))
        # 只取一半脚本
        truncated = TraceCase(
            goal=case.goal,
            llm_script=case.llm_script[:len(case.llm_script) // 2],
            expected_tools=case.expected_tools[:len(case.expected_tools) // 2],
            expected_success=False,  # 半数脚本无法到达 complete
            source=case.source,
        )
        executed, result = _replay(truncated)
        # 必须终止（不挂死）
        assert result.summary != ""
        # 工具数不超半程脚本
        assert len(executed) <= len(truncated.expected_tools)
