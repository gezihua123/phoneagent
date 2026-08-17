"""UIState：屏幕状态的抽象数据模型。

职责：
  1. Element — 单个 UI 元素的数据结构，与数据源无关
  2. UIState — 一次屏幕观察的状态，提供 index → 坐标查询（编号枢纽）
  3. UIParser Protocol — 解析器协议，各数据源实现自己的解析逻辑

数据源实现层：
  - uistate_phonefast.py：解析 phonefast observe 文本
  - uistate_wd4.py（未来）：解析 uiautomator XML
  - scenariokit/xmltext.py：scenariokit XML → phonefast 文本互转

清洗与格式化见 uiprocessor.py，仅依赖 UIState 抽象。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

# ── 共用 bounds 解析（4 个 parser 共用）──

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_bounds(bounds_str: str) -> tuple[int, int, int, int] | None:
    """从 "[x1,y1][x2,y2]" 提取坐标。无效返回 None。"""
    m = _BOUNDS_RE.search(bounds_str)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))


def normalize_bounds(elements: list["Element"]) -> None:
    """交换 x1>x2 或 y1>y2 的非法组合——所有 parser 共用。"""
    for e in elements:
        x1, y1, x2, y2 = e.bounds
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        e.bounds = (x1, y1, x2, y2)


@dataclass
class Element:
    """一个 UI 元素，与数据源无关。"""

    index: int
    text: str | None
    id: str | None
    desc: str | None
    cls: str
    clickable: bool
    bounds: tuple[int, int, int, int]  # x1,y1,x2,y2
    flags: set[str] = field(default_factory=set)  # [clickable]/[checked]/[scrollable]/...

    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def label(self) -> str:
        """人类/LLM 可读的元素标签：优先 text，次 desc，次 id。"""
        return self.text or self.desc or self.id or self.cls

    def area(self) -> float:
        x1, y1, x2, y2 = self.bounds
        return max(0, x2 - x1) * max(0, y2 - y1)

    def contains(self, other: "Element") -> bool:
        """self 是否完全包含 other。"""
        x1, y1, x2, y2 = self.bounds
        ox1, oy1, ox2, oy2 = other.bounds
        return (
            x1 <= ox1 and y1 <= oy1 and x2 >= ox2 and y2 >= oy2
            and self.area() > other.area() > 0
        )


class UIState:
    """一次屏幕观察后的状态（纯数据模型）。

    由 UIParser 实现生产，uiprocessor 负责清洗 + 格式化。
    """

    def __init__(self, elements: list[Element]) -> None:
        self.elements = elements
        self._by_index = {e.index: e for e in elements}

    def get_coords(self, index: int) -> tuple[int, int]:
        """按 index 查元素中心点。不存在则抛 ValueError。"""
        el = self._by_index.get(index)
        if el is None:
            available = list(self._by_index.keys())[:20]
            raise ValueError(
                f"element index {index} not found; available: {available}"
            )
        return el.center()

    def find_by_text(self, text: str) -> Element | None:
        """按文本精确匹配找第一个元素。"""
        for e in self.elements:
            if e.text == text:
                return e
        return None

    def find_all_by_text(self, text: str) -> list[Element]:
        """按文本精确匹配找所有元素。"""
        return [e for e in self.elements if e.text == text]


class UIParser(Protocol):
    """解析器协议：各数据源实现自己的解析逻辑，产出统一 UIState。"""

    def parse(self, raw_text: str) -> UIState:
        ...
