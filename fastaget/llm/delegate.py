"""LLM delegate 抽象层（原生 tool-calling 版）。

agent 只依赖 LLMDelegate 接口，具体实现可后期更换。
新设计：delegate 接收完整消息历史 + 工具定义，返回结构化 tool_calls，
不再解析自由文本。消除正则解析失败问题。

流式扩展（吸收 pi streamFn）：stream() 为可选方法，默认实现包 complete()——
所有既有 delegate（ScriptedLLM、测试 mock）零改动自动兼容。
事件实体见 llm/events.py（对齐 pi AssistantMessageEvent 协议）。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from fastaget.llm.events import LLMStreamEvent


@dataclass
class ToolCall:
    """模型发起的一次工具调用。"""

    name: str
    input: dict[str, Any]
    id: str = ""  # tool_use_id，用于匹配 tool_result


class NonRetryableLLMError(RuntimeError):
    """确定性 LLM 调用失败（如 HTTP 400/401/403/404/422）——请求本身有问题，
    相同输入重试必复现。重试层（with_retry 的 should_retry）应直接放行不重试，
    避免浪费重试预算 + 丢失真实错误归因。"""


@dataclass
class LLMResponse:
    """一次模型调用的结果。"""

    text: str = ""  # 模型输出的文本内容（可能为空，当只返回 tool_calls 时）
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""  # "end_turn" | "tool_use" | "max_tokens" | "stop"
    cost_usd: float | None = None
    raw: Any = None
    request_body: Any = None  # 发给 LLM 的完整请求体 {model, max_tokens, system, messages, tools, ...}

    @property
    def wants_tool(self) -> bool:
        """模型是否请求调用工具。"""
        return self.stop_reason == "tool_use" and bool(self.tool_calls)


class LLMDelegate(abc.ABC):
    """模型调用委托接口（原生 tool-calling）。"""

    @abc.abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        vision: bool = False,
        tool_choice: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """同步调用：给 system + messages + tools，返回模型响应（含 tool_calls）。

        messages 为标准 Anthropic 消息格式：
          [{"role": "user", "content": "..."}, {"role": "assistant", "content": [...]}, ...]

        tool_choice: Anthropic Messages API 的工具选择控制，如
          {"type": "any"} 强制模型本轮必须输出 tool_use 块（JSON 结构化输出，
          纯文本结束在协议层被禁止）；None 由实现方决定（通常 "auto"）。

        实现内部可自行管理 async。约定：模型通过原生 tool-calling 输出结构化
        tool_use 块，不再用自由文本协议。
        """
        raise NotImplementedError

    def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        vision: bool = False,
        tool_choice: dict[str, Any] | None = None,
    ) -> "Iterator[LLMStreamEvent]":
        """流式调用（可选）。参数与 complete() 完全一致——采样面不动。

        默认实现：包 complete() 为单个 done 事件。子类（如
        AnthropicHTTPDelegate）可覆写为真实 SSE 流式，中间产出
        thinking_delta/text_delta 等增量事件供 trace。

        约定：事件序列必须以 DONE（携带字段级等同于 complete() 解析结果的
        final LLMResponse）或 ERROR 结束。
        """
        from fastaget.llm.events import LLMStreamEvent

        resp = self.complete(system, messages, tools, vision=vision, tool_choice=tool_choice)
        yield LLMStreamEvent.done(resp)

    @property
    @abc.abstractmethod
    def context_window(self) -> int:
        """模型上下文窗口大小（tokens）。用于上下文压力检测。"""
        raise NotImplementedError

    def close(self) -> None:
        """释放底层资源。"""
        pass
