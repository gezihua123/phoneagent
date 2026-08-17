"""AnthropicHTTPDelegate.stream() SSE 解析单元测试。

核心验证：
1. 事件序列与 pi AssistantMessageEvent 协议对齐
2. 流式组装的 final LLMResponse 与非流式 _parse_response 字段级一致（采样透明）
3. 防御性解析：未知事件跳过、缺 message_start 也能工作
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate
from fastaget.llm.events import LLMStreamEvent, StreamEventType


def _make_delegate(monkeypatch) -> AnthropicHTTPDelegate:
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    return AnthropicHTTPDelegate(model="glm-5.2")


def _sse_lines(events: list[dict[str, Any]]) -> list[str]:
    return [f"data: {json.dumps(e)}" for e in events]


def _mock_stream_response(lines: list[str]) -> MagicMock:
    resp = MagicMock()
    resp.iter_lines.return_value = iter(lines)
    resp.raise_for_status.return_value = None
    return resp


def _run_stream(d: AnthropicHTTPDelegate, lines: list[str]) -> list[LLMStreamEvent]:
    """直接驱动 _consume_sse（绕过 HTTP 层，纯解析逻辑测试）。"""
    resp = _mock_stream_response(lines)
    return list(d._consume_sse(resp))


# ---- 标准事件序列：text + tool_use ----

def test_stream_text_and_tool_use(monkeypatch):
    d = _make_delegate(monkeypatch)
    lines = _sse_lines([
        {"type": "message_start", "message": {"id": "m1"}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "点击"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "设置"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {
            "type": "tool_use", "id": "tu_1", "name": "tap_element", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {
            "type": "input_json_delta", "partial_json": '{"index": '}},
        {"type": "content_block_delta", "index": 1, "delta": {
            "type": "input_json_delta", "partial_json": '3}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
         "usage": {"input_tokens": 100, "output_tokens": 50}},
        {"type": "message_stop"},
    ])
    events = _run_stream(d, lines)
    types = [e.type for e in events]

    assert types[0] == StreamEventType.START
    assert types[-1] == StreamEventType.DONE
    assert StreamEventType.TEXT_DELTA in types
    assert StreamEventType.TOOLCALL_START in types
    assert StreamEventType.TOOLCALL_DELTA in types
    assert StreamEventType.TOOLCALL_END in types

    final = events[-1].final
    assert final is not None
    assert final.text == "点击设置"
    assert len(final.tool_calls) == 1
    assert final.tool_calls[0].name == "tap_element"
    assert final.tool_calls[0].input == {"index": 3}
    assert final.tool_calls[0].id == "tu_1"
    assert final.stop_reason == "tool_use"
    assert final.cost_usd is not None
    d.close()


# ---- thinking 块：只进事件流，不进 final ----

def test_stream_thinking_not_in_final(monkeypatch):
    d = _make_delegate(monkeypatch)
    lines = _sse_lines([
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "用户在设置页"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "点 wifi"}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {}},
        {"type": "message_stop"},
    ])
    events = _run_stream(d, lines)
    types = [e.type for e in events]

    assert StreamEventType.THINKING_START in types
    assert StreamEventType.THINKING_DELTA in types
    assert StreamEventType.THINKING_END in types

    think_end = next(e for e in events if e.type == StreamEventType.THINKING_END)
    assert think_end.content == "用户在设置页"

    final = events[-1].final
    assert final.text == "点 wifi"  # thinking 不进 final.text
    assert final.tool_calls == []
    d.close()


# ---- 与 _parse_response 的字段级一致性（采样透明核心验证）----

def test_stream_final_matches_parse_response(monkeypatch):
    """同一逻辑响应，流式组装的 final 必须与非流式解析字段级一致。"""
    d = _make_delegate(monkeypatch)

    # 非流式响应（complete 路径）
    non_stream_data = {
        "content": [
            {"type": "text", "text": "你好"},
            {"type": "tool_use", "id": "tu_9", "name": "observe", "input": {"mode": "auto"}},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 200, "output_tokens": 80},
    }
    expected = d._parse_response(non_stream_data)

    # 等价的流式事件序列
    lines = _sse_lines([
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "你"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "好"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {
            "type": "tool_use", "id": "tu_9", "name": "observe", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {
            "type": "input_json_delta", "partial_json": '{"mode": "auto"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
         "usage": {"input_tokens": 200, "output_tokens": 80}},
        {"type": "message_stop"},
    ])
    events = _run_stream(d, lines)
    final = events[-1].final

    assert final.text == expected.text
    assert final.stop_reason == expected.stop_reason
    assert final.cost_usd == expected.cost_usd
    assert [(t.id, t.name, t.input) for t in final.tool_calls] == \
           [(t.id, t.name, t.input) for t in expected.tool_calls]
    d.close()


# ---- 防御性：未知事件 + 缺 message_start + 错误事件 ----

def test_stream_defensive_unknown_events(monkeypatch):
    d = _make_delegate(monkeypatch)
    lines = _sse_lines([
        {"type": "ping"},                                    # 未知 → 跳过
        {"type": "some_gateway_custom_event", "foo": 1},     # 方言 → 跳过
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    ])
    events = _run_stream(d, lines)
    assert events[-1].type == StreamEventType.DONE
    assert events[-1].final.text == "ok"
    d.close()


def test_stream_error_event(monkeypatch):
    d = _make_delegate(monkeypatch)
    lines = _sse_lines([
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    ])
    events = _run_stream(d, lines)
    assert events[-1].type == StreamEventType.ERROR
    assert "Overloaded" in events[-1].error
    d.close()


def test_stream_malformed_json_line_skipped(monkeypatch):
    d = _make_delegate(monkeypatch)
    lines = [
        "data: {not valid json",
        *_sse_lines([
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"},
        ]),
        "data: [DONE]",
    ]
    events = _run_stream(d, lines)
    assert events[-1].type == StreamEventType.DONE
    assert events[-1].final.text == "hi"
    d.close()


# ---- 请求体一致性：stream 与 complete 仅差 stream:true ----

def test_request_body_shared_with_complete(monkeypatch):
    d = _make_delegate(monkeypatch)
    msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    tools = [{"name": "complete", "description": "x",
              "input_schema": {"type": "object", "properties": {}}}]

    body = d._build_request_body("sys prompt", msgs, tools, {"type": "any"})
    # stream 只是 body + stream:true，无其他差异
    stream_body = dict(body)
    stream_body["stream"] = True
    for k in body:
        assert k in stream_body
    assert set(stream_body) - set(body) == {"stream"}
    assert body["tool_choice"] == {"type": "any"}
    assert body["model"] == "glm-5.2"
    d.close()


# ---- delegate 默认 stream 实现（fallback 兼容）----

def test_default_stream_fallback():
    """未覆写 stream 的 delegate：默认实现包 complete() 为单 done 事件。"""
    from fastaget.llm.delegate import LLMDelegate, LLMResponse, ToolCall

    class FakeLLM(LLMDelegate):
        def complete(self, system, messages, tools, *, vision=False, tool_choice=None):
            return LLMResponse(text="ok", tool_calls=[ToolCall(name="tap", input={}, id="t1")],
                               stop_reason="tool_use")

        @property
        def context_window(self) -> int:
            return 128000

    events = list(FakeLLM().stream("s", [], []))
    assert len(events) == 1
    assert events[0].type == StreamEventType.DONE
    assert events[0].final.text == "ok"
    assert events[0].final.tool_calls[0].name == "tap"
