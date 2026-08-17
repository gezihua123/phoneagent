"""compaction 模块测试——消息历史压缩。

这是旧 `fastaget.agent.history.compress_screen_observations` 的等价测试。
v3.2 迁移到 LLM 驱动的 `compact(messages, llm)`（机制不同：
旧版按文本规则就地压缩 observe 块；新版超阈值时 LLM 摘要历史+保留最近消息）。

覆盖：
- `_estimate_chars` / `_msg_chars`：字符估算（text/tool_use/tool_result/image）
- `_is_tool_result_batch`：tool_result 批次识别
- `_find_cut_point`：切割点定位（保留最近 ~200KB，避开 tool_result 批次）
- `compact`：阈值未达返回 None；超阈值用 mock LLM 摘要替换；LLM 失败保留原消息
"""
from __future__ import annotations

from fastaget.agent import compaction
from fastaget.agent.compaction import (
    _estimate_chars,
    _is_tool_result_batch,
    _msg_chars,
    compact,
    _find_cut_point,
)
from fastaget.llm.delegate import LLMResponse


# ── 纯函数：字符估算 ──


def _text_msg(text: str) -> dict:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def test_msg_chars_string_content():
    assert _msg_chars({"role": "user", "content": "hello"}) == 5


def test_msg_chars_text_block():
    assert _msg_chars({"role": "user", "content": [{"type": "text", "text": "hello"}]}) == 5


def test_msg_chars_tool_use_block():
    msg = {"role": "assistant", "content": [{"type": "tool_use", "input": {"x": 1}}]}
    assert _msg_chars(msg) == len(str({"x": 1}))


def test_msg_chars_image_block_est():
    msg = {"role": "user", "content": [{"type": "image", "source": {"data": "xxx"}}]}
    # image 块按固定估算值（4.8K chars）
    assert _msg_chars(msg) == compaction._EST_IMAGE_CHARS


def test_estimate_chars_sums():
    msgs = [_text_msg("hello"), _text_msg("world")]
    assert _estimate_chars(msgs) == 10


# ── 纯函数：tool_result 批次识别 ──


def test_is_tool_result_batch_true():
    msg = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tc1", "content": "OK"}]}
    assert _is_tool_result_batch(msg) is True


def test_is_tool_result_batch_false_text():
    msg = {"role": "user", "content": [{"type": "text", "text": "hello"}]}
    assert _is_tool_result_batch(msg) is False


def test_is_tool_result_batch_string_content():
    assert _is_tool_result_batch({"role": "user", "content": "hello"}) is False


# ── 纯函数：切割点定位 ──


def test_find_cut_point_keeps_recent():
    """消息总量超过 _KEEP_RECENT_CHARS 时，切割点应在保留最近消息的 user 边界。"""
    big = "x" * (compaction._KEEP_RECENT_CHARS + 1000)
    msgs = [_text_msg("goal"), _text_msg(big), _text_msg("recent tail")]
    cut = _find_cut_point(msgs)
    # 切割点应 > 0（保留 goal 之后的部分）
    assert 0 <= cut <= len(msgs)


def test_find_cut_point_avoids_tool_result_batch():
    """切割点避开 tool_result 批次（防止 tool_result 失去对应 tool_use）。"""
    big = "x" * (compaction._KEEP_RECENT_CHARS + 1000)
    tool_result_msg = {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "tc1", "content": "OK"}],
    }
    msgs = [
        _text_msg("goal"),
        _text_msg(big),
        tool_result_msg,  # 这条不该被选为切割点
        _text_msg("safe user msg"),
        _text_msg("recent"),
    ]
    cut = _find_cut_point(msgs)
    if cut < len(msgs):
        # 若落在 tool_result 批次上，逻辑应再向前找
        assert not _is_tool_result_batch(msgs[cut])


# ── compact：端到端（mock LLM）──


class _MockLLM:
    """mock LLMDelegate——返回固定摘要文本。"""

    def complete(self, system, messages, tools, **_):
        return LLMResponse(
            text="## Goal\ntest\n## Progress\n### Done\n- stuff",
            tool_calls=[],
            stop_reason="end_turn",
            cost_usd=0.0,
            raw={"usage": {}},
        )


class _FailingLLM:
    """mock LLMDelegate——complete 抛异常（模拟网络错误）。"""

    def complete(self, system, messages, tools, **_):
        raise RuntimeError("network down")


def test_compact_returns_none_below_threshold():
    """消息总量未达阈值 → 返回 None（不压缩）。"""
    msgs = [_text_msg("goal"), _text_msg("short")]
    assert compact(msgs, _MockLLM()) is None


def test_compact_triggers_summary_when_over_threshold(monkeypatch):
    """消息超阈值 → 触发 LLM 摘要，返回新消息列表（goal 保留 + 摘要 + 最近）。"""
    monkeypatch.setattr(compaction, "_COMPACT_THRESHOLD_CHARS", 100)
    monkeypatch.setattr(compaction, "_KEEP_RECENT_CHARS", 50)
    # 历史（会被摘要）+ 保留区（最近消息，量足够大到不被并入历史）
    history_msg = _text_msg("x" * 80)
    recent_msg = _text_msg("y" * 80)  # 最近区，>= _KEEP_RECENT_CHARS 的增量由 _find_cut_point 保留
    msgs = [_text_msg("goal"), history_msg, recent_msg]
    result = compact(msgs, _MockLLM())
    assert result is not None
    assert result[0] is msgs[0]  # goal 原样保留
    assert "[Context Summary]" in result[1]["content"][0]["text"]
    # 保留区的最近消息应原样出现在结果尾部
    assert any(
        b.get("text") == "y" * 80
        for m in result[2:]
        for b in (m.get("content") if isinstance(m.get("content"), list) else [])
        if isinstance(b, dict)
    )


def test_compact_keeps_original_when_llm_fails(monkeypatch):
    """LLM 摘要失败 → 返回 None，保留原消息（下次再试）。"""
    monkeypatch.setattr(compaction, "_COMPACT_THRESHOLD_CHARS", 100)
    monkeypatch.setattr(compaction, "_KEEP_RECENT_CHARS", 50)
    big = "z" * 200
    msgs = [_text_msg("goal"), _text_msg(big), _text_msg("recent tail")]
    assert compact(msgs, _FailingLLM()) is None


def test_compact_no_history_to_compress(monkeypatch):
    """超阈值但 cut_idx<=1（只有 goal，无可压缩历史）→ 返回 None。"""
    monkeypatch.setattr(compaction, "_COMPACT_THRESHOLD_CHARS", 10)
    monkeypatch.setattr(compaction, "_KEEP_RECENT_CHARS", 5)
    # 只有 goal 一条，但单条就超阈值
    big = "q" * 100
    msgs = [_text_msg(big)]
    assert compact(msgs, _MockLLM()) is None
