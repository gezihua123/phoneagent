"""LLM 流式事件实体——提取自 pi-ai 的 AssistantMessageEvent 协议。

对应 pi/packages/ai/src/types.ts:491 的事件联合类型，逐一对齐：

  pi AssistantMessageEvent          fastaget StreamEventType
  ─────────────────────────         ──────────────────────
  start                             START
  text_start                        TEXT_START
  text_delta                        TEXT_DELTA
  text_end                          TEXT_END
  thinking_start                    THINKING_START
  thinking_delta                    THINKING_DELTA
  thinking_end                      THINKING_END
  toolcall_start                    TOOLCALL_START
  toolcall_delta                    TOOLCALL_DELTA
  toolcall_end                      TOOLCALL_END
  done (reason, message)            DONE (stop_reason, final)
  error (reason, error)             ERROR (stop_reason, error)

裁剪说明：pi 每个事件携带 `partial: AssistantMessage`（供 UI 原地更新）。
fastaget 无 UI 渲染需求，consumer 自行累积 delta 即可，故不携带 partial 快照。
事件类型与语义保持完整对齐。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastaget.llm.delegate import LLMResponse, ToolCall


class StreamEventType(str, Enum):
    """流式事件类型（与 pi AssistantMessageEvent 一一对应）。"""

    START = "start"
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    THINKING_START = "thinking_start"
    THINKING_DELTA = "thinking_delta"
    THINKING_END = "thinking_end"
    TOOLCALL_START = "toolcall_start"
    TOOLCALL_DELTA = "toolcall_delta"
    TOOLCALL_END = "toolcall_end"
    DONE = "done"
    ERROR = "error"


@dataclass
class LLMStreamEvent:
    """一次流式增量事件。

    字段语义（对齐 pi）：
      type:          事件类型
      content_index: 内容块序号（一个响应可含多个 text/thinking/tool_use 块）
      delta:         *_DELTA 事件的增量文本
      content:       *_END 事件的完整块内容
      tool_call:     TOOLCALL_END 事件的完整工具调用
      stop_reason:   DONE/ERROR 的停止原因（end_turn/tool_use/max_tokens/error/...）
      final:         DONE 事件携带的完整 LLMResponse（与 complete() 解析结果字段级一致）
      error:         ERROR 事件的错误信息
    """

    type: StreamEventType
    content_index: int = 0
    delta: str = ""
    content: str = ""
    tool_call: "ToolCall | None" = None
    stop_reason: str = ""
    final: "LLMResponse | None" = None
    error: str = ""

    # ── 便捷构造 ──

    @classmethod
    def done(cls, final: "LLMResponse") -> "LLMStreamEvent":
        return cls(type=StreamEventType.DONE, stop_reason=final.stop_reason, final=final)

    @classmethod
    def failed(cls, error: str, stop_reason: str = "error") -> "LLMStreamEvent":
        return cls(type=StreamEventType.ERROR, stop_reason=stop_reason, error=error)
