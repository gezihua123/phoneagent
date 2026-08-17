"""LLM 驱动的上下文压缩——pi compaction.ts 简化实现。

触发条件：消息历史超 512KB（≈128K tokens，deepseek-v4-pro 上限）。
触发时：LLM 摘要历史 → 替换旧消息 + 保留最近 ~200KB。
fastaget 当前规模（~240KB）远不到触发线，仅兜底。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastaget.llm.delegate import LLMDelegate

_logger = logging.getLogger(__name__)

# 触发阈值：512KB 文本（≈128K tokens）
_COMPACT_THRESHOLD_CHARS: int = 512 * 1024
# 压缩后保留的最近消息量（≈50K tokens）
_KEEP_RECENT_CHARS: int = 200 * 1024
# 单条消息粗略估算（image 块按 4.8K chars 计）
_EST_IMAGE_CHARS: int = 4800

_SUMMARIZE_SYSTEM = (
    "You are a context summarization assistant. Produce structured summaries. "
    "Do NOT continue the conversation. ONLY output the summary."
)

_SUMMARIZE_PROMPT = """The messages above are from an Android phone automation agent
performing a test task. Summarize the key information needed to continue.

Use this EXACT format:

## Goal
[The task objective]

## Progress
### Done
- [Completed actions with results]

### Current State
- [Current screen/page and key UI elements]

### Issues
- [Errors or blockers encountered]

## Next Steps
- [What should happen next]

Preserve exact package names, button labels, element text, coordinates, and error messages. Be concise but complete."""


def _msg_chars(msg: dict[str, Any]) -> int:
    """单条消息的字符数（对齐 pi estimateTokens）。"""
    content = msg.get("content", [])
    chars = 0
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type", "")
            if btype == "text":
                chars += len(block.get("text", ""))
            elif btype in ("tool_use", "tool_result"):
                chars += len(str(block.get("input", block.get("content", ""))))
            elif btype == "image":
                chars += _EST_IMAGE_CHARS
    return chars


def _estimate_chars(messages: list[dict[str, Any]]) -> int:
    """估算消息列表总字符数。"""
    return sum(_msg_chars(m) for m in messages)


def _find_cut_point(messages: list[dict[str, Any]]) -> int:
    """从尾部向前找切割点：保留最近 ~200KB 消息的 turn 边界（user message 开头）。

    避开 tool_result：若 user 消息的 content 含 tool_result 块，其前导 assistant
    tool_use 必须同进同出——否则 API 报 'tool_result without tool_use'。向前再找
    一个非 tool_result 的 user 消息。
    """
    accumulated = 0
    for i in range(len(messages) - 1, -1, -1):
        accumulated += _msg_chars(messages[i])
        if accumulated >= _KEEP_RECENT_CHARS:
            # 向前找最近的 user message（不劈开 turn）
            for j in range(i, -1, -1):
                if messages[j].get("role") == "user" and not _is_tool_result_batch(messages[j]):
                    return j
            return i
    return 0


def _is_tool_result_batch(msg: dict[str, Any]) -> bool:
    """消息是否为 tool_result 批次（content 含 tool_result 块）。"""
    content = msg.get("content", [])
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _generate_summary(messages: list[dict[str, Any]], llm: "LLMDelegate") -> str:
    """调 LLM 生成历史摘要。"""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", [])
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    text += block.get("text", "") + "\n"
                elif btype == "tool_use":
                    text += f"[tool: {block.get('name', '?')}({block.get('input', {})})]\n"
                elif btype == "tool_result":
                    text += f"[result: {block.get('content', '')[:200]}]\n"
        parts.append(f"[{role}] {text.strip()}")

    conversation = "\n".join(parts)
    prompt = f"<conversation>\n{conversation}\n</conversation>\n\n{_SUMMARIZE_PROMPT}"

    try:
        resp = llm.complete(
            _SUMMARIZE_SYSTEM,
            [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            [],
        )
        return resp.text or "(summary unavailable)"
    except Exception:
        return "(summary unavailable)"


def compact(messages: list[dict[str, Any]], llm: "LLMDelegate") -> list[dict[str, Any]] | None:
    """压缩消息历史。返回新消息列表，不需要压缩时返回 None。

    流程：估算 → 判断 → 切割 → LLM 摘要 → 替换（goal 消息原样保留）。
    """
    if _estimate_chars(messages) < _COMPACT_THRESHOLD_CHARS:
        return None

    cut_idx = _find_cut_point(messages)
    if cut_idx <= 1:  # 无可压缩历史（goal + 不够长）
        return None

    history = messages[1:cut_idx]  # 跳过首条 goal 消息
    retained = messages[cut_idx:]
    if not history:
        return None

    summary = _generate_summary(history, llm)
    # 摘要失败（网络错误/API 超时等）→ 不替换，保留原消息，下次再试
    if summary == "(summary unavailable)":
        _logger.warning("compaction summary LLM call failed, keeping original messages")
        return None

    return [
        messages[0],  # goal 原样保留
        {"role": "user", "content": [{"type": "text", "text": f"[Context Summary]\n{summary}"}]},
        *retained,
    ]
