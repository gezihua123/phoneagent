"""Session 单元测试：session_id、run 跟踪、stats、快照恢复。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from fastaget.agent.fast_agent import FastAgent
from fastaget.agent.session import Session
from fastaget.tools import build_registry

from fastaget.scenariokit import MockPhonefast

from tests.conftest import FLATREF_SCREEN, OneTurnCompleteLLM


def _fast_agent(**kwargs):
    pf = MockPhonefast(FLATREF_SCREEN)
    llm = OneTurnCompleteLLM()
    return FastAgent(llm, pf, build_registry(), **kwargs)


# ---- 基本属性 ----

def test_session_id_is_generated():
    s = Session(agent=_fast_agent())
    assert len(s.id) == 12
    stats = s.stats
    assert stats["run_count"] == 0
    assert stats["total_steps"] == 0
    assert stats["total_cost_usd"] == 0.0


def test_session_id_is_unique():
    s1 = Session(agent=_fast_agent())
    s2 = Session(agent=_fast_agent())
    assert s1.id != s2.id


# ---- run 跟踪 ----

def test_run_tracks_all_metrics():
    """两次 run：计数递增 + steps/cost 累计 + session_id 注入 + 独立性。"""
    s = Session(agent=_fast_agent())
    r1 = s.run("task A")
    assert s.stats["run_count"] == 1
    assert r1.session_id == s.id
    assert r1.success and r1.steps > 0

    r2 = s.run("task B")
    assert s.stats["run_count"] == 2
    assert s.stats["total_steps"] == r1.steps + r2.steps
    assert s.stats["total_cost_usd"] > 0
    assert r2.success  # 独立：前一次不影响后一次


def test_followup_run_reports_own_steps():
    """P0-3 回归：同 Session 第二次 run（follow-up 路径）必须报告本轮步数。

    背景：_ensure_context 续跑分支曾从旧 context 读 steps_before，
    而 _continue_context 已把 step_count/steps 重置为 0/[]——
    steps=max(0, 新-旧)=0、steps_detail=[]，连带 cli.py 的
    result.steps>0 验证覆盖守卫对续跑场景失效。
    """
    s = Session(agent=_fast_agent())
    r1 = s.run("task A")
    r2 = s.run("task B")
    assert r1.steps > 0
    assert r2.steps > 0, f"follow-up run 必须报告本轮步数，got steps={r2.steps}"
    assert r2.steps_detail, "follow-up run 必须包含本轮 steps_detail"
    assert s.stats["total_steps"] == r1.steps + r2.steps


def test_followup_run_direct_agent_path():
    """P0-3 回归：不经 Session，同一 FastAgent 连续两次 run() 同样命中续跑分支。"""
    agent = _fast_agent()
    r1 = agent.run("task A")
    r2 = agent.run("task B")  # new_session 默认 False → _continue_context 路径
    assert r1.steps > 0
    assert r2.steps > 0, f"direct follow-up run 必须报告本轮步数，got steps={r2.steps}"
    assert r2.steps_detail


# ---- stats ----

def test_stats_reflects_current_state():
    s = Session(agent=_fast_agent())
    s.run("test")
    stats = s.stats
    assert stats["session_id"] == s.id
    assert stats["run_count"] == 1
    assert stats["total_steps"] > 0
    assert stats["total_cost_usd"] > 0


# ---- 快照 ----

def test_snapshot_roundtrip(tmp_path: Path):
    s = Session(agent=_fast_agent())
    s.run("test 1")
    s.run("test 2")

    path = str(tmp_path / "session.json")
    s.save(path)
    assert os.path.isfile(path)

    restored = Session.load(path, agent=_fast_agent())
    assert restored.id == s.id
    assert restored.stats["run_count"] == 2
    assert restored.stats["total_steps"] == s.stats["total_steps"]
    assert restored.stats["total_cost_usd"] == s.stats["total_cost_usd"]


def test_restore_non_existent_file(tmp_path: Path):
    path = str(tmp_path / "nope.json")
    with pytest.raises(FileNotFoundError):
        Session.load(path, agent=_fast_agent())


# ---- trace 开关 ----

def test_trace_disabled_no_crash():
    """trace=False 时 run/flush 不应报错。"""
    s = Session(agent=_fast_agent(), trace=False)
    r = s.run("test")
    assert r.success
    s.flush()  # 不抛异常


def test_trace_enabled_no_crash(tmp_path: Path):
    """trace=True 时 run + flush 正常产出文件。"""
    old = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        s = Session(agent=_fast_agent(), trace=True)
        r = s.run("test")
        assert r.success
        s.flush()
        # build/traces/ 目录应已创建
        traces_dir = Path("build") / "traces"
        assert traces_dir.is_dir()
    finally:
        os.chdir(old)
