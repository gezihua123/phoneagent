"""ReplayLogger 单元测试：重放图结构、屏幕去重、ActionResult.data 保留、
post_screen_key、OFF 路径不变、auto-flush、跨 run reset 隔离。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastaget.scenariokit import MockPhonefast

from fastaget.agent.fast_agent import AgentResult, FastAgent
from fastaget.agent.trace import (
    ReplayLogger,
    extract_usage,
    make_replay_logger,
)
from fastaget.llm.delegate import LLMResponse, ToolCall
from fastaget.tools import build_registry
from fastaget.tools.registry import ActionResult

from tests.conftest import OneTurnCompleteLLM, make_llm_response as _resp


# ---- 测试夹具 ----


def _finish(logger: ReplayLogger, *, success: bool = True, summary: str = "done",
            steps: int = 1, cost: float = 0.0023, steps_detail=None) -> None:
    logger.on_finish(AgentResult(
        session_id="test",
        success=success, summary=summary, steps=steps,
        total_cost_usd=cost, steps_detail=steps_detail or [],
    ))


# ---- 工具函数 ----


class TestUtilities:
    def test_extract_usage_anthropic(self):
        r = _resp(usage={"input_tokens": 7, "output_tokens": 3,
                         "cache_read_input_tokens": 1, "cache_creation_input_tokens": 2})
        u = extract_usage(r)
        assert u == {"input_tokens": 7, "output_tokens": 3,
                     "cache_read_input_tokens": 1, "cache_creation_input_tokens": 2}

    def test_extract_usage_deepseek_keys(self):
        r = LLMResponse(text="x", raw={"usage": {"prompt_tokens": 9, "completion_tokens": 4}})
        u = extract_usage(r)
        assert u["input_tokens"] == 9
        assert u["output_tokens"] == 4

    def test_extract_usage_none(self):
        assert extract_usage(None) == {}


# ---- 图结构 + ActionResult.data 保留 ----


class TestReplayGraphShape:
    def test_multi_tool_turn_preserves_action_data_and_complete(self, tmp_path: Path):
        """一轮里 tap_element + complete：data 保留、end_cause=complete_tool。"""
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.begin_run("goal", scenario="sc", variant="baseline", prompt="baseline",
                         fmt="region", seq=1, model="glm-5.2", max_steps=8, vision=False)
        logger.on_auto_observe(element_count=3, screen_text="screen0", image_b64=None)
        # 一轮：tap_element + complete
        logger.on_llm_start(call_index=0, message_count=1)
        resp = _resp("tap then complete", tool_calls=[
            ToolCall(name="tap_element", input={"index": 5}, id="t1"),
            ToolCall(name="complete", input={"result": "ok", "success": True}, id="t2"),
        ])
        logger.on_llm_end(0, "tap then complete", 2, 1.2, 0.0023,
                          response=resp, stop_reason="tool_use")
        logger.on_tool_start(1, "tap_element", {"index": 5})
        ar_tap = ActionResult.ok("tapped (120,340)", x=120, y=340)
        logger.on_tool_end(1, "tap_element", "[OK] tapped", 0.01, True, action_result=ar_tap)
        logger.on_tool_start(2, "complete", {"result": "ok", "success": True})
        ar_cmp = ActionResult.ok("complete: ok", complete=True, result="ok")
        logger.on_tool_end(2, "complete", "[OK] complete", 0.01, True, action_result=ar_cmp)
        _finish(logger)

        graph = json.loads((tmp_path / f"{logger.run_id}.replay.json").read_text(encoding="utf-8"))
        assert graph["meta"]["scenario"] == "sc"
        assert graph["meta"]["model"] == "glm-5.2"
        # 1 个节点（无 observe，屏幕未变）；1 条边（自环）
        assert len(graph["nodes"]) == 1
        assert len(graph["edges"]) == 1
        edge = graph["edges"][0]
        assert edge["from_node"] == "S0"
        assert edge["to_node"] == "S0"  # 自环：无 observe 刷新
        assert [tc["name"] for tc in edge["tool_calls"]] == ["tap_element", "complete"]
        # ActionResult.data 完整保留
        assert edge["tool_results"][0]["data"] == {"x": 120, "y": 340}
        assert edge["tool_results"][1]["data"] == {"complete": True, "result": "ok"}
        assert edge["usage"]["input_tokens"] == 100
        assert graph["outcome"]["end_cause"] == "complete_tool"
        assert graph["outcome"]["success"] is True

    def test_observe_creates_new_node(self, tmp_path: Path):
        """observe 工具刷新屏幕 → 新节点 + 边 to 新节点。"""
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.begin_run("goal", scenario="s", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=8)
        logger.on_auto_observe(element_count=3, screen_text="screen0")
        logger.on_llm_start(0, 1)
        logger.on_llm_end(0, "obs", 1, 1.0, 0.001,
                          response=_resp("obs", tool_calls=[ToolCall("observe", {}, "o1")]),
                          stop_reason="tool_use")
        logger.on_tool_start(1, "observe", {})
        ar = ActionResult.ok("observed, 5 elements", count=5, elements="screen1")
        logger.on_tool_end(1, "observe", "[OK] observed", 0.01, True, action_result=ar)
        logger.on_screen(source="observe_tool", screen_text="screen1",
                         element_count=5, step_index=1)
        _finish(logger)
        graph = json.loads((tmp_path / f"{logger.run_id}.replay.json").read_text(encoding="utf-8"))
        assert len(graph["nodes"]) == 2
        assert graph["edges"][0]["to_node"] == "S1"


class TestScreenDedup:
    @staticmethod
    def _node_count(logger: ReplayLogger, tmp_path: Path) -> int:
        graph = json.loads((tmp_path / f"{logger.run_id}.replay.json").read_text(encoding="utf-8"))
        return len(graph["nodes"])

    def test_identical_screen_reuses_node(self, tmp_path: Path):
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.begin_run("g", scenario="s", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=8)
        logger.on_screen(source="initial_observe", screen_text="same", element_count=1)
        logger.on_screen(source="observe_tool", screen_text="same", element_count=1)
        _finish(logger)
        assert self._node_count(logger, tmp_path) == 1

    def test_distinct_screen_creates_new_node(self, tmp_path: Path):
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.begin_run("g", scenario="s", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=8)
        logger.on_screen(source="initial_observe", screen_text="a", element_count=1)
        logger.on_screen(source="observe_tool", screen_text="b", element_count=1)
        _finish(logger)
        assert self._node_count(logger, tmp_path) == 2


class TestPostScreenKey:
    def test_mock_phonefast_provides_post_screen_key(self, tmp_path: Path):
        pf = MockPhonefast("[0] text='A' bounds=[0,0][10,10]")
        # 静态 mock 的 current_screen_key
        pf.current_screen_key  # 触发属性检查
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.configure(phonefast=pf)
        logger.begin_run("g", scenario="s", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=8)
        logger.on_auto_observe(1, screen_text="x")
        logger.on_llm_start(0, 1)
        logger.on_llm_end(0, "t", 1, 1.0, 0.001,
                          response=_resp("t", tool_calls=[ToolCall("tap", {"x": 1, "y": 1}, "t1")]),
                          stop_reason="tool_use")
        logger.on_tool_start(1, "tap", {"x": 1, "y": 1})
        logger.on_tool_end(1, "tap", "[OK] tapped", 0.01, True,
                           action_result=ActionResult.ok("tapped", x=1, y=1))
        _finish(logger)
        # node.screen_key 与 tool_end.post_screen_key 都读到了 mock 的 screen key
        raw = [json.loads(l) for l in (tmp_path / f"{logger.run_id}.trace.jsonl").read_text().splitlines()]
        tool_end = [e for e in raw if e["event"] == "tool_end"][0]
        assert tool_end["post_screen_key"] == pf.current_screen_key

    def test_no_phonefast_means_null_screen_key(self, tmp_path: Path):
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.begin_run("g", scenario="s", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=8)
        logger.on_auto_observe(1, screen_text="x")
        logger.on_tool_end(1, "tap", "[OK]", 0.01, True,
                           action_result=ActionResult.ok("ok"))
        # screen_key 为 None（真机路径）
        assert logger._nodes[0]["screen_key"] is None


class TestAutoFlushAndReset:
    def test_on_finish_writes_both_files(self, tmp_path: Path):
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.begin_run("g", scenario="s", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=8)
        logger.on_auto_observe(1, screen_text="x")
        rid = logger.run_id
        _finish(logger)
        assert (tmp_path / f"{rid}.trace.jsonl").exists()
        assert (tmp_path / f"{rid}.replay.json").exists()
        # on_finish 后 run_id + 缓冲保留（供内存内检查）；显式 reset 才清空
        assert logger.run_id == rid
        assert len(logger._nodes) >= 1
        logger.reset()
        assert logger.run_id is None
        assert logger._nodes == []

    def test_reset_between_runs_no_cross_contamination(self, tmp_path: Path):
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        # run 1
        logger.begin_run("g1", scenario="s1", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=8)
        logger.on_auto_observe(1, screen_text="screenA")
        _finish(logger, success=True, summary="done1")
        # run 2（复用同一实例）
        logger.begin_run("g2", scenario="s2", variant="b", prompt="p", fmt="f", seq=2,
                         model="m", max_steps=8)
        logger.on_auto_observe(1, screen_text="screenB")
        _finish(logger, success=True, summary="done2")
        # 两个 run 各自一对文件
        replays = sorted(tmp_path.glob("*.replay.json"))
        traces = sorted(tmp_path.glob("*.trace.jsonl"))
        assert len(replays) == 2
        assert len(traces) == 2
        scenarios = {json.loads(p.read_text())["meta"]["scenario"] for p in replays}
        assert scenarios == {"s1", "s2"}
        # run2 的文件里不该混入 run1 的屏幕
        g2 = [json.loads(p.read_text()) for p in replays if "s2" in json.loads(p.read_text())["meta"]["scenario"]][0]
        assert all(n["screen_text"] == "screenB" for n in g2["nodes"])


class TestOffPathUnchanged:
    """trace 关闭（无 hook / disabled logger）时 agent 行为零变化。"""

    def test_disabled_logger_does_not_change_result(self, tmp_path: Path):
        pf1 = MockPhonefast("[0] text='A' bounds=[0,0][10,10]")
        llm1 = OneTurnCompleteLLM()
        a1 = FastAgent(llm1, pf1, build_registry(), max_steps=5)
        r1 = a1.run("goal")

        pf2 = MockPhonefast("[0] text='A' bounds=[0,0][10,10]")
        llm2 = OneTurnCompleteLLM()
        disabled = ReplayLogger(output_dir=str(tmp_path), enabled=False)
        a2 = FastAgent(llm2, pf2, build_registry(), max_steps=5, hooks=[disabled])
        r2 = a2.run("goal")

        assert r1.success == r2.success
        assert r1.steps == r2.steps
        assert r1.total_cost_usd == r2.total_cost_usd
        assert [s.action for s in r1.steps_detail] == [s.action for s in r2.steps_detail]
        # disabled logger 不落盘
        assert not list(tmp_path.glob("*"))

    def test_make_replay_logger_disabled_returns_none(self):
        assert make_replay_logger(enabled=False) is None


class TestEndCause:
    def test_max_steps_end_cause(self, tmp_path: Path):
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.begin_run("g", scenario="s", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=2)
        logger.on_auto_observe(1, screen_text="x")
        _finish(logger, success=False, summary="未完成（达到步数上限）", steps=2)
        graph = json.loads((tmp_path / f"{logger.run_id}.replay.json").read_text(encoding="utf-8"))
        assert graph["outcome"]["end_cause"] == "max_steps"

    def test_llm_consecutive_fail_end_cause(self, tmp_path: Path):
        logger = ReplayLogger(output_dir=str(tmp_path), enabled=True)
        logger.begin_run("g", scenario="s", variant="b", prompt="p", fmt="f", seq=1,
                         model="m", max_steps=2)
        logger.on_auto_observe(1, screen_text="x")
        _finish(logger, success=False, summary="LLM 连续失败 3 次: timeout", steps=0)
        graph = json.loads((tmp_path / f"{logger.run_id}.replay.json").read_text(encoding="utf-8"))
        assert graph["outcome"]["end_cause"] == "llm_consecutive_fail"
