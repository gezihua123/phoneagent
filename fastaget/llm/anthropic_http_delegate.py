"""AnthropicHTTPDelegate：用 httpx 直连 Anthropic Messages API。

原生 tool-calling + prompt caching，消除子进程启动开销和正则解析失败。

关键优化：
1. 持久 httpx.Client + 连接池复用
2. system prompt 加 cache_control，多步用例越长 cache 收益越大
3. 原生 tools 参数，模型输出结构化 tool_use 块，不再解析自由文本
4. 禁用 thinking（ReAct 只需动作输出）

流式（吸收 pi streamFn）：stream() 走 SSE，请求体与 complete() 共用
_build_request_body（仅多 "stream": true）——采样面单一来源，从构造上
保证流式/非流式发给模型的内容逐字节一致。

DeepSeek Anthropic 兼容端点：POST {ANTHROPIC_BASE_URL}/v1/messages，x-api-key 鉴权。
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Iterator

import httpx

from dataclasses import dataclass

from fastaget.llm.delegate import (
    LLMDelegate, LLMResponse, NonRetryableLLMError, ToolCall,
)
from fastaget.llm.events import LLMStreamEvent, StreamEventType


@dataclass(frozen=True)
class ModelCapabilities:
    """模型能力声明（替代关键字推断）。"""
    thinking: bool = True
    vision: bool = False
    context_window: int = 128_000
    default_max_tokens: int = 4096
    thinking_max_tokens: int = 8192


# 已知模型的能力表（按子串匹配，最后匹配到的生效）
_MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    "deepseek-v4-pro": ModelCapabilities(thinking=False),
    "deepseek-v4": ModelCapabilities(thinking=False),
    "deepseek-v4-flash": ModelCapabilities(thinking=False),
    "deepseek-v4-lite": ModelCapabilities(thinking=False),
    "glm-5.2": ModelCapabilities(thinking=False),
    "glm-5": ModelCapabilities(thinking=False),
    "glm-4.6": ModelCapabilities(thinking=False),
    "glm-4": ModelCapabilities(thinking=False),
}
_DEFAULT_CAPABILITIES = ModelCapabilities(thinking=False)


class AnthropicHTTPDelegate(LLMDelegate):
    """Anthropic Messages API 直连 delegate（原生 tool-calling）。"""

    # cache_control 标记的 system prompt 最小长度（太短不值得缓存）
    _CACHE_MIN_SYSTEM_CHARS: int = 200
    # HTTP 错误响应的截断长度
    _ERROR_BODY_MAX_CHARS: int = 300
    # 4xx 中除 429（rate limit）外均为请求本身问题——重试必复现，不可重试
    _NON_RETRYABLE_STATUS: frozenset = frozenset({400, 401, 403, 404, 422})

    @classmethod
    def _raise_http_error(cls, e: "httpx.HTTPStatusError") -> None:
        """HTTP 错误 → RuntimeError（保留状态码+响应体）；4xx 归 NonRetryableLLMError。

        流式响应的 body 未 read——直接读 .text 抛 ResponseNotRead，丢失真实
        状态码（P1-10）。先 read() 再取 text，读不出也不掩盖原始状态码。
        """
        status = e.response.status_code
        try:
            e.response.read()
            detail = (e.response.text or "")[:cls._ERROR_BODY_MAX_CHARS]
        except Exception:
            detail = ""
        msg = f"HTTP {status}: {detail}"
        if status in cls._NON_RETRYABLE_STATUS:
            raise NonRetryableLLMError(msg) from e
        raise RuntimeError(msg) from e
    # 每百万 token 价格（默认 deepseek-v4-pro 定价，可通过构造参数覆盖）
    _PRICE_INPUT_PER_M: float = 0.14     # deepseek: $0.14/M input
    _PRICE_OUTPUT_PER_M: float = 0.28    # deepseek: $0.28/M output
    _PRICE_CACHE_READ_PER_M: float = 0.014   # deepseek: 10% of input
    _PRICE_CACHE_WRITE_PER_M: float = 0.14   # deepseek: same as input

    def __init__(
        self,
        model: str = "deepseek-v4-pro",
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 120.0,
        connect_timeout: float = 10.0,
        max_connections: int = 5,
        disable_thinking: bool | None = None,
        max_tokens: int = 4096,
        thinking_max_tokens: int = 8192,
        temperature: float | None = None,
    ) -> None:
        self.model = model
        self._base_url = (
            base_url
            or os.environ.get("ANTHROPIC_BASE_URL")
            or "https://api.deepseek.com/anthropic"
        ).rstrip("/")
        self._token = (
            token
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_API_KEY")
        )
        # thinking: None=从模型注册表查找，True/False=显式控制
        caps = self._lookup_model(model)
        if disable_thinking is None:
            self._disable_thinking = not caps.thinking
        else:
            self._disable_thinking = disable_thinking
        # 开启 thinking 时自动提升 max_tokens（推理消耗 token，避免 tool_use 截断）
        if not self._disable_thinking and max_tokens < caps.thinking_max_tokens:
            self._max_tokens = caps.thinking_max_tokens
        else:
            self._max_tokens = max_tokens

        self._context_window = caps.context_window
        self._temperature = temperature
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._max_connections = max_connections

        if os.environ.get("FA_DEBUG"):
            print(f"    [Delegate] model={model} thinking={'OFF' if self._disable_thinking else 'ON'} "
                  f"max_tokens={self._max_tokens} ctx={self._context_window}")
        limits = httpx.Limits(
            max_keepalive_connections=max_connections,
            max_connections=max_connections,
            keepalive_expiry=30.0,
        )
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            limits=limits,
        )

    @classmethod
    def _lookup_model(cls, model: str) -> ModelCapabilities:
        """从注册表查找模型能力，未匹配时返回默认值。"""
        for prefix, caps in _MODEL_CAPABILITIES.items():
            if prefix in model:
                return caps
        return _DEFAULT_CAPABILITIES

    def _require_token(self) -> None:
        if not self._token:
            raise RuntimeError(
                "未配置模型凭证。请设置环境变量 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY"
            )

    # ---- 请求体构建（complete/stream 共用，采样面单一来源）----

    def _build_request_body(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """构建 Anthropic Messages 请求体。complete/stream 唯一来源。"""
        # system + tools + 最后 2 条 message 加 cache_control
        system_block = [{"type": "text", "text": system}]
        if len(system) > self._CACHE_MIN_SYSTEM_CHARS:
            system_block[0]["cache_control"] = {"type": "ephemeral"}

        # 标记最后 2 条 message 的 content 为可缓存
        # deep copy 最后 2 条（会被注入 cache_control），其余 shallow copy——避免
        # 在 caller 的 state.messages 上累积 cache_control 标记（每次 retry 都会再跑）
        last_n = min(2, len(messages))
        msgs = [copy.deepcopy(m) for m in messages[-last_n:]]
        for msg in msgs:
            content = msg.get("content", [])
            if isinstance(content, list) and content:
                content[0]["cache_control"] = {"type": "ephemeral"}
        msgs = list(messages[:-last_n]) + msgs if last_n < len(messages) else msgs

        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": system_block,
            "messages": msgs,
        }
        if tools:
            # 标记 tools 列表为可缓存
            body["tools"] = [dict(t) for t in tools]  # shallow copy
            if body["tools"]:
                body["tools"][0]["cache_control"] = {"type": "ephemeral"}
            body["tool_choice"] = tool_choice or {"type": "auto"}
        if self._disable_thinking:
            body["thinking"] = {"type": "disabled"}
        if self._temperature is not None:
            body["temperature"] = self._temperature
        return body

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        vision: bool = False,
        tool_choice: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """同步 HTTP 调用（原生 tool-calling + prompt caching）。"""
        self._require_token()
        body = self._build_request_body(system, messages, tools, tool_choice)

        try:
            resp = self._ensure_client().post(
                f"{self._base_url}/v1/messages",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            self._raise_http_error(e)
        except httpx.RequestError as e:
            raise RuntimeError(f"HTTP request failed: {e}")

        data = resp.json()
        result = self._parse_response(data)
        result.request_body = body
        return result

    def _parse_response(self, data: dict) -> LLMResponse:
        """解析 Anthropic 响应：提取 text + tool_use 块。"""
        content = data.get("content", [])
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    name=block.get("name", ""),
                    input=block.get("input", {}) or {},
                    id=block.get("id", ""),
                ))

        return LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=data.get("stop_reason", ""),
            cost_usd=self._estimate_cost(data.get("usage", {})),
            raw=data,
        )

    @staticmethod
    def _estimate_cost(usage: dict) -> float | None:
        """成本估算（complete/stream 共用同一公式）。"""
        if not usage or not usage.get("input_tokens"):
            return None
        inp = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_creation = usage.get("cache_creation_input_tokens", 0)
        cls = AnthropicHTTPDelegate
        return round(
            inp * cls._PRICE_INPUT_PER_M / 1e6
            + out * cls._PRICE_OUTPUT_PER_M / 1e6
            + cache_read * cls._PRICE_CACHE_READ_PER_M / 1e6
            + cache_creation * cls._PRICE_CACHE_WRITE_PER_M / 1e6,
            6,
        )

    # ---- 流式（SSE）----

    def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        vision: bool = False,
        tool_choice: dict[str, Any] | None = None,
    ) -> Iterator[LLMStreamEvent]:
        """SSE 流式调用。请求体与 complete() 共用 _build_request_body，
        仅多 "stream": true——采样面逐字节一致。

        产出事件序列（对齐 pi AssistantMessageEvent）：
          START → (THINKING_START/DELTA* | TEXT_START/DELTA* |
                   TOOLCALL_START/DELTA*/END)* → DONE | ERROR
        thinking 内容只进事件流，不进 final LLMResponse（与
        _parse_response 只解析 text+tool_use 的行为一致）。
        """
        self._require_token()
        body = self._build_request_body(system, messages, tools, tool_choice)
        body["stream"] = True

        try:
            with self._ensure_client().stream(
                "POST",
                f"{self._base_url}/v1/messages",
                headers=self._headers(),
                json=body,
            ) as resp:
                resp.raise_for_status()
                yield from self._consume_sse(resp, request_body=body)
        except httpx.HTTPStatusError as e:
            self._raise_http_error(e)
        except httpx.RequestError as e:
            raise RuntimeError(f"HTTP request failed: {e}")

    def _consume_sse(self, resp: httpx.Response, request_body: dict | None = None) -> Iterator[LLMStreamEvent]:
        """解析 Anthropic SSE 事件流。防御性：未知事件跳过，缺 message_start
        也能工作（网关方言兼容）。

        Anthropic 事件序列：
          message_start → content_block_start → content_block_delta* →
          content_block_stop → ... → message_delta → message_stop
        delta 子类型：text_delta / thinking_delta / input_json_delta。
        """
        # 按 index 追踪每个 content block 的类型与累积内容
        block_types: dict[int, str] = {}
        block_texts: dict[int, list[str]] = {}
        block_jsons: dict[int, list[str]] = {}
        tool_meta: dict[int, tuple[str, str]] = {}  # index → (id, name)
        stop_reason = ""
        usage: dict = {}

        yield LLMStreamEvent(type=StreamEventType.START)

        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                ev = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")

            if etype == "message_start":
                # message_start 携带 usage.input_tokens——必须收否则 cost 永远 None
                msg = ev.get("message", {})
                if isinstance(msg, dict) and msg.get("usage"):
                    usage.update(msg["usage"])

            elif etype == "content_block_start":
                idx = ev.get("index", 0)
                block = ev.get("content_block", {})
                btype = block.get("type", "text")
                block_types[idx] = btype
                block_texts.setdefault(idx, [])
                if btype == "tool_use":
                    block_jsons.setdefault(idx, [])
                    tool_meta[idx] = (block.get("id", ""), block.get("name", ""))
                    yield LLMStreamEvent(type=StreamEventType.TOOLCALL_START, content_index=idx)
                elif btype == "thinking":
                    yield LLMStreamEvent(type=StreamEventType.THINKING_START, content_index=idx)
                else:
                    yield LLMStreamEvent(type=StreamEventType.TEXT_START, content_index=idx)

            elif etype == "content_block_delta":
                idx = ev.get("index", 0)
                delta = ev.get("delta", {})
                dtype = delta.get("type", "")
                if dtype == "thinking_delta":
                    block_texts.setdefault(idx, []).append(delta.get("thinking", ""))
                    yield LLMStreamEvent(type=StreamEventType.THINKING_DELTA,
                                         content_index=idx, delta=delta.get("thinking", ""))
                elif dtype == "input_json_delta":
                    block_jsons.setdefault(idx, []).append(delta.get("partial_json", ""))
                    yield LLMStreamEvent(type=StreamEventType.TOOLCALL_DELTA,
                                         content_index=idx, delta=delta.get("partial_json", ""))
                else:  # text_delta（含方言 fallback）
                    block_texts.setdefault(idx, []).append(delta.get("text", ""))
                    yield LLMStreamEvent(type=StreamEventType.TEXT_DELTA,
                                         content_index=idx, delta=delta.get("text", ""))

            elif etype == "content_block_stop":
                idx = ev.get("index", 0)
                btype = block_types.get(idx, "text")
                if btype == "tool_use":
                    raw_json = "".join(block_jsons.get(idx, []))
                    try:
                        tool_input = json.loads(raw_json) if raw_json.strip() else {}
                    except json.JSONDecodeError:
                        tool_input = {}
                    tid, tname = tool_meta.get(idx, ("", ""))
                    yield LLMStreamEvent(type=StreamEventType.TOOLCALL_END,
                                         content_index=idx,
                                         tool_call=ToolCall(name=tname, input=tool_input, id=tid))
                elif btype == "thinking":
                    yield LLMStreamEvent(type=StreamEventType.THINKING_END,
                                         content_index=idx,
                                         content="".join(block_texts.get(idx, [])))
                else:
                    yield LLMStreamEvent(type=StreamEventType.TEXT_END,
                                         content_index=idx,
                                         content="".join(block_texts.get(idx, [])))

            elif etype == "message_delta":
                delta = ev.get("delta", {})
                if delta.get("stop_reason"):
                    stop_reason = delta["stop_reason"]
                # message_delta.usage 只含 output_tokens——update 而非 replace，
                # 否则丢掉 message_start 带来的 input_tokens / cache_* tokens
                if ev.get("usage"):
                    usage.update(ev["usage"])

            elif etype == "message_stop":
                pass  # 组装在循环后统一做

            elif etype == "error":
                yield LLMStreamEvent.failed(
                    error=str(ev.get("error", {}).get("message", "stream error")))
                return
            # ping / 未知类型 → 跳过（message_start 已在上方处理）

        # 组装最终 LLMResponse：text 只收 text 块（thinking 不进），
        # 与 _parse_response 的提取规则字段级一致
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for idx in sorted(block_types):
            btype = block_types[idx]
            if btype == "text":
                text_parts.append("".join(block_texts.get(idx, [])))
            elif btype == "tool_use":
                raw_json = "".join(block_jsons.get(idx, []))
                try:
                    tool_input = json.loads(raw_json) if raw_json.strip() else {}
                except json.JSONDecodeError:
                    tool_input = {}
                tid, tname = tool_meta.get(idx, ("", ""))
                tool_calls.append(ToolCall(name=tname, input=tool_input, id=tid))

        final = LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            cost_usd=self._estimate_cost(usage),
            raw={"usage": usage},  # 供 ConsoleHook.on_llm_end 读 token 用量
            request_body=request_body,
        )
        yield LLMStreamEvent.done(final)

    @property
    def context_window(self) -> int:
        return self._context_window

    def _ensure_client(self) -> httpx.Client:
        """获取可用客户端——close() 后可自动重建（复用构造函数参数）。"""
        if self._client is None:
            limits = httpx.Limits(
                max_keepalive_connections=self._max_connections,
                max_connections=self._max_connections,
                keepalive_expiry=30.0,
            )
            self._client = httpx.Client(
                timeout=httpx.Timeout(self._timeout, connect=self._connect_timeout),
                limits=limits,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None  # type: ignore[assignment]
