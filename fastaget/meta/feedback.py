"""反馈模板加载——单一来源，供 agent/tools/capabilities 共用。

从 meta/prompts/feedback.txt 按 section 名加载。
格式：### <name> 开头，到下一个 ### 或文件末尾为该模板内容。
文件不存在或 section 不存在返回 fallback。
"""
from __future__ import annotations

from pathlib import Path

_FEEDBACK_FILE = Path(__file__).resolve().parent / "prompts" / "feedback.txt"
_CACHE: dict[str, str] | None = None


def _load_all() -> dict[str, str]:
    """加载 feedback.txt 并按 ### name 分节缓存。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    _CACHE = {}
    if not _FEEDBACK_FILE.is_file():
        return _CACHE
    current_name = ""
    current_lines: list[str] = []
    for line in _FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            if current_name and current_lines:
                _CACHE[current_name] = "\n".join(current_lines).strip()
            current_name = line[4:].strip()
            current_lines = []
        elif current_name:
            current_lines.append(line)
    if current_name and current_lines:
        _CACHE[current_name] = "\n".join(current_lines).strip()
    return _CACHE


def load_feedback(name: str, fallback: str = "") -> str:
    """加载反馈模板。section 不存在返回 fallback（默认空串）。"""
    return _load_all().get(name, fallback)
