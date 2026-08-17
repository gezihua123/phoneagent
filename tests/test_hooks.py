"""TrajectoryRecorder 单元测试：JSONL 格式、事件覆盖、时间戳、flush 落盘。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastaget.agent.fast_agent import AgentResult
from fastaget.agent.hooks import TrajectoryRecorder
from fastaget.agent.types import Step


def _rec(*, output_dir: str = "traces_test") -> TrajectoryRecorder:
    return TrajectoryRecorder(output_dir=output_dir)


def _finish(recorder: TrajectoryRecorder) -> None:
    recorder.on_finish(AgentResult(
        session_id="test", success=True, summary="ok",
        steps=3, total_cost_usd=0.01,
        steps_detail=[Step(index=1, thought="", action="tap", args={},
                           result="[OK] tapped", success=True, elapsed=0.1, cost_usd=0.003),
                      Step(index=2, thought="", action="observe", args={},
                           result="[OK] observed", success=True, elapsed=0.05, cost_usd=0.003),
                      Step(index=3, thought="", action="complete", args={},
                           result="[OK] complete: done", success=True, elapsed=0.02, cost_usd=0.004)],
    ))


# ---- 事件覆盖 ----

def test_records_auto_observe():
    r = _rec()
    r.on_auto_observe(element_count=42, screen_text="hello world" * 20)
    assert len(r.entries) == 1
    e = r.entries[0]
    assert e.event == "auto_observe"
    assert e.data["elements"] == 42
    assert "hello world" in e.data["screen_preview"]


def test_records_llm_start_and_end():
    r = _rec()
    r.on_llm_start(call_index=1, message_count=5)
    r.on_llm_end(call_index=1, text="thought", tool_count=2,
                 elapsed=1.5, cost_usd=0.005,
                 response=None, usage=None, stop_reason="tool_use")
    assert len(r.entries) == 2
    assert r.entries[0].event == "llm_start"
    assert r.entries[1].event == "llm_end"
    assert r.entries[1].data["tool_calls"] == 2
    assert r.entries[1].data["elapsed"] == 1.5
    assert r.entries[1].data["cost_usd"] == 0.005


def test_records_llm_stream():
    r = _rec()
    r.on_llm_stream(kind="thinking_delta", delta="首先观察当前屏幕" * 10, call_index=3)
    r.on_llm_stream(kind="text_delta", delta="好的", call_index=3)
    assert len(r.entries) == 2
    assert r.entries[0].event == "llm_stream"
    assert r.entries[0].data["kind"] == "thinking_delta"
    assert r.entries[0].data["delta_len"] > 0
    assert r.entries[1].event == "llm_stream"
    assert r.entries[1].data["kind"] == "text_delta"


def test_records_steering():
    r = _rec()
    r.on_steering(source="external", text="检测到弹窗，请先按 back")
    assert len(r.entries) == 1
    assert r.entries[0].event == "steering"
    assert r.entries[0].data["source"] == "external"
    assert "弹窗" in r.entries[0].data["text_preview"]


def test_records_tool_start_and_end():
    r = _rec()
    r.on_tool_start(step_index=1, name="tap_element", args={"index": 3})
    r.on_tool_end(step_index=1, name="tap_element", result="[OK] tapped",
                  elapsed=0.15, success=True, action_result=None)
    assert r.entries[0].event == "tool_start"
    assert r.entries[0].data["tool"] == "tap_element"
    assert r.entries[0].data["args"] == {"index": 3}
    assert r.entries[1].event == "tool_end"
    assert r.entries[1].data["elapsed"] == 0.15
    assert r.entries[1].data["success"] is True


def test_records_step():
    r = _rec()
    step = Step(index=2, thought="", action="observe", args={},
                result="[OK] observed 15 elements", success=True,
                elapsed=0.08, cost_usd=0.002)
    r.on_step(step=step)
    assert r.entries[0].event == "step"
    assert r.entries[0].data["index"] == 2
    assert r.entries[0].data["action"] == "observe"
    assert r.entries[0].data["elapsed"] == 0.08


def test_records_screen():
    r = _rec()
    r.on_screen(source="observe_tool", screen_text="[1] 设置" * 20,
                element_count=15, step_index=3)
    assert r.entries[0].event == "screen"
    assert r.entries[0].data["source"] == "observe_tool"
    assert r.entries[0].data["element_count"] == 15


def test_records_finish():
    r = _rec()
    _finish(r)
    assert r.entries[-1].event == "finish"
    assert r.entries[-1].data["success"] is True
    assert r.entries[-1].data["steps"] == 3
    assert r.entries[-1].data["cost_usd"] == 0.01


# ---- 时间戳 ----

def test_sequence_monotonically_increases():
    r = _rec()
    for i in range(5):
        r.on_llm_start(call_index=i, message_count=i + 1)
    seqs = [e.seq for e in r.entries]
    assert seqs == [1, 2, 3, 4, 5]


def test_timestamps_are_non_decreasing():
    r = _rec()
    r.on_llm_start(call_index=0, message_count=1)
    time.sleep(0.01)
    r.on_llm_end(call_index=0, text="ok", tool_count=0,
                 elapsed=0.1, cost_usd=0.001)
    assert r.entries[0].ts <= r.entries[1].ts


# ---- flush / 落盘 ----

def test_flush_writes_valid_jsonl(tmp_path: Path):
    d = str(tmp_path / "hooks_traces")
    r = _rec(output_dir=d)
    r.on_auto_observe(element_count=10, screen_text="screen")
    r.on_llm_start(call_index=1, message_count=3)
    path = r.flush()

    assert Path(path).is_file()
    lines = Path(path).read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "seq" in obj
        assert "ts" in obj
        assert "event" in obj
        assert "data" in obj


def test_flush_returns_valid_path():
    r = _rec(output_dir="traces_test")
    path = r.flush()
    assert path.startswith("traces_test/trace_")
    assert path.endswith(".jsonl")
    # cleanup
    Path(path).unlink(missing_ok=True)


def test_empty_flush_creates_empty_file(tmp_path: Path):
    d = str(tmp_path / "empty_traces")
    r = _rec(output_dir=d)
    path = r.flush()
    content = Path(path).read_text(encoding="utf-8").strip()
    assert content == ""


# ---- summary ----

def test_summary_counts_events():
    r = _rec()
    r.on_auto_observe(element_count=5, screen_text="")
    r.on_llm_start(call_index=1, message_count=3)
    r.on_tool_start(step_index=1, name="tap", args={})
    r.on_tool_end(step_index=1, name="tap", result="ok", elapsed=0.1, success=True)
    _finish(r)

    s = r.summary()
    assert s["total_events"] == 5
    assert s["llm_calls"] == 1
    assert s["tool_calls"] == 1
    assert s["final_success"] is True


def test_summary_no_entries():
    r = _rec()
    s = r.summary()
    assert s["total_events"] == 0
    assert s["llm_calls"] == 0
    assert s["final_success"] is None


def test_summary_elapsed_total_is_non_negative():
    r = _rec()
    _finish(r)
    elapsed = r.summary()["elapsed_total"]
    # 墙钟秒（round 到 2 位）——快机器上可为 0.0，不能断言 > 0（flaky）
    assert isinstance(elapsed, (int, float)) and elapsed >= 0.0
