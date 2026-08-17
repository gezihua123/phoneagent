"""统一的终端输出格式 (Rich-based).

所有 emoji、前缀、分隔符集中在此类——需要改一处，全局生效。
报告样式通过 Rich (Panel/Rule/markup) 实现，Console 负责布局。

Style reference: mobilerun — emoji-prefixed, clean single-line logging.
See rich_console.py for implementation details.
"""
from __future__ import annotations

from fastaget.format.rich_console import RichConsole as Console

__all__ = ["Console"]
