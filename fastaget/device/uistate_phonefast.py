"""FlatrefParser：按 | 分隔符结构化解析 phonefast flatref 格式 → UIState。

flatref 格式（4 个语义组，由 " | " 分隔）：

  Group 1 (identity): #N text="xxx" id="xxx" desc="xxx" (ClassName)
  Group 2 (bounds):   bounds=[x1,y1][x2,y2]
  Group 3 (flags):    [clickable] [focused] [selected] [disabled]
  Group 4 (tree):     depth=D parent=#M

旧格式（legacy dump/sum）兼容保留：
  [N] text="xxx" id="xxx" desc="xxx" (Class) [flags] bounds=[x1,y1][x2,y2]
"""
from __future__ import annotations

import re

from fastaget.device.uistate import Element, UIState, UIParser, parse_bounds as _parse_bounds

# ── Group 拆分 ────────────────────────────────────────────────────────

# "| " 分隔符后紧跟 bounds= / [ / depth= 的才是 group separator
_GROUP_SEP_RE = re.compile(r' \| (?=bounds=|\[|depth=)')

# ── Identity Group (#N + attrs + class) ──────────────────────────────

_IDX_RE = re.compile(r"#(\d+)")
_ATTR_RE = re.compile(r'(text|id|desc)="([^"]*)"')
_CLASS_RE = re.compile(r"\((\w+(?:\.\w+)*)\)")  # (ClassName) or (fully.qualified.Class)

# ── Flags Group ──────────────────────────────────────────────────────

_FLAG_RE = re.compile(r"\[(clickable|scrollable|long-clickable|checked|focused|selected|disabled)\]")

# ── Tree Group ───────────────────────────────────────────────────────

_TREE_DEPTH_RE = re.compile(r"depth=(\d+)")
_TREE_PARENT_RE = re.compile(r"parent=#(\d+)")


class FlatrefParser:
    """解析 phonefast flatref 格式文本 → UIState。

    按 | 分隔符将每行拆成 4 个语义组独立解析，避免属性值中特殊字符干扰。
    兼容旧格式 [N] ...（legacy dump/sum）。
    """

    def parse(self, raw_text: str) -> UIState:
        elements: list[Element] = []
        lines = self._join_continuations(raw_text.splitlines())
        for line in lines:
            el = self._parse_line(line)
            if el is not None:
                elements.append(el)
        from fastaget.device.uistate import normalize_bounds
        normalize_bounds(elements)
        return UIState(elements)

    # ── 续行合并 ──────────────────────────────────────────────────

    @staticmethod
    def _join_continuations(raw_lines: list[str]) -> list[str]:
        """不以 #N 或 [N 开头的行视为上一行的续行。"""
        merged: list[str] = []
        buf = ""
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith("["):
                if buf:
                    merged.append(buf)
                buf = line
            else:
                buf += " " + line
        if buf:
            merged.append(buf)
        return merged

    # ── 行解析 ────────────────────────────────────────────────────

    @staticmethod
    def _parse_line(line: str) -> Element | None:
        """解析一行：自动检测 flatref vs legacy 格式。"""
        line = line.strip()
        if line.startswith("#"):
            return FlatrefParser._parse_flatref(line)
        if line.startswith("["):
            return FlatrefParser._parse_legacy(line)
        return None

    # ── flatref 结构化解析 ────────────────────────────────────────

    @staticmethod
    def _parse_flatref(line: str) -> Element | None:
        """按 | 分组解析 flatref 格式一行。

        #N text="..." id="..." desc="..." (Class) | bounds=[...] | [flags] | depth=D parent=#M
        """
        groups = _GROUP_SEP_RE.split(line, maxsplit=3)
        if len(groups) < 2:
            return None

        identity = groups[0].strip()
        bounds_str = groups[1].strip() if len(groups) > 1 else ""
        flags_str = groups[2].strip() if len(groups) > 2 else ""

        # 解析各组
        idx = FlatrefParser._parse_identity_index(identity)
        if idx is None:
            return None

        attrs = dict(_ATTR_RE.findall(identity))
        class_names = _CLASS_RE.findall(identity)
        cls = class_names[-1] if class_names else "View"

        bounds = _parse_bounds(bounds_str)
        if bounds is None:
            return None

        flags = FlatrefParser._parse_flags(flags_str)
        clickable = "clickable" in flags

        return Element(
            index=idx,
            text=attrs.get("text"),
            id=attrs.get("id"),
            desc=attrs.get("desc"),
            cls=cls,
            clickable=clickable,
            bounds=bounds,
            flags=flags,
        )

    @staticmethod
    def _parse_identity_index(identity: str) -> int | None:
        m = _IDX_RE.match(identity)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_flags(flags_str: str) -> set[str]:
        """解析 flags 字符串。格式：'[clickable] [focused] ...' 或空。"""
        return set(_FLAG_RE.findall(flags_str))

    # ── legacy 格式兼容 ────────────────────────────────────────────

    _LEGACY_LINE_RE = re.compile(r"^\[(?P<idx>\d+)\]\s(?P<rest>.*)$")

    @staticmethod
    def _parse_legacy(line: str) -> Element | None:
        """解析旧格式 [N] text="..." ... bounds=[...]。"""
        m = FlatrefParser._LEGACY_LINE_RE.match(line.strip())
        if not m:
            return None
        idx = int(m.group("idx"))
        rest = m.group("rest")

        attrs = dict(_ATTR_RE.findall(rest))
        class_matches = _CLASS_RE.findall(rest)
        cls = class_matches[-1] if class_matches else "View"
        flags = set(_FLAG_RE.findall(rest))
        clickable = "clickable" in flags

        bounds = _parse_bounds(rest)
        if bounds is None:
            return None

        return Element(
            index=idx,
            text=attrs.get("text"),
            id=attrs.get("id"),
            desc=attrs.get("desc"),
            cls=cls,
            clickable=clickable,
            bounds=bounds,
            flags=flags,
        )

    # ── 坐标规范化 ────────────────────────────────────────────────

    @staticmethod
    def _normalize_bounds(elements: list[Element]) -> None:
        """交换 x1>x2 或 y1>y2 的非法组合。"""
        for e in elements:
            x1, y1, x2, y2 = e.bounds
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            e.bounds = (x1, y1, x2, y2)


# 模块级默认实例（保持向后兼容）
phonefast_parser = FlatrefParser()
