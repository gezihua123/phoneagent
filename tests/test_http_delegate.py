"""AnthropicHTTPDelegate 单元测试（原生 tool-calling 版）。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate


# ---- token / env ----

def test_token_from_env_auth_token(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token-123")
    d = AnthropicHTTPDelegate(model="glm-5.2")
    assert d._token == "test-token-123"
    d.close()


def test_token_from_env_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-456")
    d = AnthropicHTTPDelegate(model="glm-5.2")
    assert d._token == "test-key-456"
    d.close()


def test_token_missing_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = AnthropicHTTPDelegate(model="glm-5.2")
    with pytest.raises(RuntimeError, match="未配置模型凭证"):
        d._require_token()
    d.close()


def test_base_url_default_is_deepseek(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    d = AnthropicHTTPDelegate(model="deepseek-v4-pro")
    assert d._base_url == "https://api.deepseek.com/anthropic"
    d.close()


def test_close_is_idempotent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    d = AnthropicHTTPDelegate(model="glm-5.2")
    d.close()
    d.close()


# ---- tool-calling request/response ----

def test_complete_with_tools_parses_tool_use(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    d = AnthropicHTTPDelegate(model="glm-5.2")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "id": "msg_1",
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "tap", "input": {"x": 540, "y": 300}},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }
    with patch.object(d._client, "post", return_value=mock_resp) as mock_post:
        resp = d.complete(
            system="sys",
            messages=[{"role": "user", "content": "tap it"}],
            tools=[{"name": "tap", "description": "tap", "input_schema": {}}],
        )
    assert resp.stop_reason == "tool_use"
    assert resp.wants_tool is True
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "tap"
    assert resp.tool_calls[0].input == {"x": 540, "y": 300}
    assert resp.tool_calls[0].id == "tu_1"
    # cost 估算
    assert resp.cost_usd is not None
    assert resp.cost_usd > 0

    body = mock_post.call_args[1]["json"]
    assert body["model"] == "glm-5.2"
    assert body["tools"][0]["name"] == "tap"
    assert body["tool_choice"] == {"type": "auto"}
    # system 应是数组格式
    assert isinstance(body["system"], list)
    d.close()


def test_complete_end_turn_no_tools(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    d = AnthropicHTTPDelegate(model="glm-5.2")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": "任务完成"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    with patch.object(d._client, "post", return_value=mock_resp):
        resp = d.complete("sys", [{"role": "user", "content": "hi"}], [])
    assert resp.wants_tool is False
    assert resp.text == "任务完成"
    d.close()


# ---- error handling ----

def test_http_error_converts_to_runtime_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    import httpx

    d = AnthropicHTTPDelegate(model="glm-5.2")
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error", request=MagicMock(), response=mock_resp
    )
    with patch.object(d._client, "post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            d.complete("sys", [{"role": "user", "content": "hi"}], [])
    d.close()


# ---- stream() 错误处理（P1-10 回归）----

class _ErrByteStream:
    """模拟 httpx 流式响应体（未 read 状态）。"""

    def __init__(self, payload: bytes):
        self._payload = payload

    def __iter__(self):
        yield self._payload

    def close(self):
        pass


def _make_stream_response(status: int, body: bytes):
    """构造与 client.stream() 一致的未读流式 Response——.text 会抛 ResponseNotRead。"""
    import httpx
    req = httpx.Request("POST", "https://example.com/v1/messages")
    resp = httpx.Response(status, request=req, stream=_ErrByteStream(body))
    return resp


class _FakeStreamCtx:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *args):
        return False


def _stream_with_error(d, status: int, body: bytes):
    """让 d.stream() 走到 raise_for_status 抛 HTTPStatusError 的路径。"""
    import httpx
    resp = _make_stream_response(status, body)
    err = httpx.HTTPStatusError("err", request=resp.request, response=resp)

    real_resp = MagicMock()
    real_resp.raise_for_status.side_effect = err
    with patch.object(d._client, "stream", return_value=_FakeStreamCtx(real_resp)):
        return list(d.stream("sys", [{"role": "user", "content": "hi"}], []))


def test_stream_http_error_reads_body_safely(monkeypatch):
    """P1-10 核心回归：流式响应未 read 时，错误信息不得抛 ResponseNotRead，
    必须带出真实状态码与响应体（错误归因）。"""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    d = AnthropicHTTPDelegate(model="deepseek-v4-pro")
    with pytest.raises(RuntimeError, match="HTTP 400"):
        _stream_with_error(d, 400, b'{"error": {"message": "invalid request"}}')
    d.close()


def test_stream_4xx_is_non_retryable(monkeypatch):
    """400/401/403/404/422 是请求本身问题——重试必复现，必须标记不可重试。"""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    from fastaget.llm.delegate import NonRetryableLLMError
    d = AnthropicHTTPDelegate(model="deepseek-v4-pro")
    with pytest.raises(NonRetryableLLMError):
        _stream_with_error(d, 400, b"bad request")
    d.close()


def test_stream_5xx_remains_retryable(monkeypatch):
    """5xx/429 是可重试故障——不得归入 NonRetryableLLMError。"""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    from fastaget.llm.delegate import NonRetryableLLMError
    d = AnthropicHTTPDelegate(model="deepseek-v4-pro")
    try:
        _stream_with_error(d, 500, b"server error")
        raise AssertionError("should have raised")
    except NonRetryableLLMError:
        raise AssertionError("500 不得标记为不可重试")
    except RuntimeError as e:
        assert "HTTP 500" in str(e)
    d.close()


# ---- no hardcoded token ----

def test_no_hardcoded_token_in_source():
    from pathlib import Path
    src_file = Path(__file__).parent.parent / "fastaget" / "llm" / "anthropic_http_delegate.py"
    src = src_file.read_text()
    assert "sk-ant-" not in src.lower()
