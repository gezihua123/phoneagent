"""xmltext: XML ↔ phonefast observe 文本转换 + 节点解析。

职责：uiautomator XML dump → phonefast observe 文本格式，及反向解析。
不含清洗/格式化（那是 fastaget.uiprocessor 的职责），不含变体生成（那是 variants 的职责）。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from fastaget.device.uistate import UIState
from fastaget.device.uistate_phonefast import phonefast_parser


def _parse_bool(val: str) -> bool:
    return val.strip().lower() == "true"


def _short_class(cls: str) -> str:
    return cls.rsplit(".", 1)[-1] if cls else "View"


def _is_meaningful(elem: ET.Element) -> bool:
    """与 UIProcessor.filter 的语义有效性一致：可交互或有语义内容。"""
    if _parse_bool(elem.get("clickable", "false")):
        return True
    if elem.get("text", ""):
        return True
    if elem.get("content-desc", ""):
        return True
    return False


def _bounds_tuple(elem: ET.Element) -> tuple[int, int, int, int]:
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", elem.get("bounds", "[0,0][0,0]"))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0, 0)


def _infer_screen(root: ET.Element) -> tuple[int, int]:
    """从 [0,0][W,H] 形根节点推断屏幕尺寸（与 UIProcessor._infer_screen 一致）。"""
    sw, sh = 1080, 2400
    for elem in root.iter("node"):
        x1, y1, x2, y2 = _bounds_tuple(elem)
        if x1 == 0 and y1 == 0:
            sw = max(sw, x2)
            sh = max(sh, y2)
    return sw, sh


def _is_visible(elem: ET.Element, sw: int, sh: int) -> bool:
    """与 UIProcessor.filter 的几何 + 屏幕内可见过滤一致。"""
    x1, y1, x2, y2 = _bounds_tuple(elem)
    if x2 - x1 <= 0 or y2 - y1 <= 0:
        return False
    if x2 <= 0 or y2 <= 0 or x1 >= sw or y1 >= sh:
        return False
    return True


def _all_nodes(root: ET.Element) -> list[tuple[ET.Element, list[ET.Element]]]:
    """深度优先遍历，返回 (node, ancestors) 列表。"""
    result: list[tuple[ET.Element, list[ET.Element]]] = []

    def walk(elem: ET.Element, ancestors: list[ET.Element]) -> None:
        if elem.tag == "node":
            result.append((elem, ancestors[:]))
        for child in elem:
            walk(child, ancestors + [elem])

    walk(root, [])
    return result


def xml_to_phonefast_text(xml_str: str) -> str:
    """将 uiautomator XML dump 转为 phonefast observe 文本格式。

    只保留 meaningful 且可见的节点（与 UIProcessor.filter 三层清洗一致），
    分配连续 index。输出格式与 UIState.parse 的正则完全匹配。
    """
    root = ET.fromstring(xml_str)
    sw, sh = _infer_screen(root)
    nodes = _all_nodes(root)
    lines = [
        "Interactive elements on screen:",
        "=" * 50,
    ]
    idx = 0
    for elem, _ancestors in nodes:
        if not _is_meaningful(elem):
            continue
        if not _is_visible(elem, sw, sh):
            continue
        text = elem.get("text", "")
        desc = elem.get("content-desc", "")
        rid = elem.get("resource-id", "")
        cls = _short_class(elem.get("class", ""))
        x1, y1, x2, y2 = _bounds_tuple(elem)

        parts = [f"[{idx}]"]
        if text:
            parts.append(f'text="{text}"')
        if rid:
            short = rid.split("/")[-1] if "/" in rid else rid
            parts.append(f'id="{short}"')
        if desc:
            parts.append(f'desc="{desc}"')
        parts.append(f"({cls})")
        flags = []
        for attr, label in (
            ("clickable", "clickable"),
            ("scrollable", "scrollable"),
            ("long-clickable", "long-clickable"),
            ("checked", "checked"),
            ("focused", "focused"),
            ("selected", "selected"),
        ):
            if _parse_bool(elem.get(attr, "false")):
                flags.append(f"[{label}]")
        parts.extend(flags)
        parts.append(f"bounds=[{x1},{y1}][{x2},{y2}]")
        lines.append(" ".join(parts))
        idx += 1
    lines.append("=" * 50)
    lines.append("Use tap_element with index=N or text='...' to interact.")
    return "\n".join(lines) + "\n"


def parse_meaningful_nodes(xml_str: str) -> list[dict[str, Any]]:
    """解析 XML 中所有 meaningful 且可见的节点，返回带 index 的字典列表。

    index 与 xml_to_phonefast_text 的编号一致。
    """
    root = ET.fromstring(xml_str)
    sw, sh = _infer_screen(root)
    nodes = _all_nodes(root)
    result = []
    idx = 0
    for elem, ancestors in nodes:
        if not _is_meaningful(elem):
            continue
        if not _is_visible(elem, sw, sh):
            continue
        result.append({
            "idx": idx,
            "text": elem.get("text", ""),
            "desc": elem.get("content-desc", ""),
            "rid": elem.get("resource-id", ""),
            "class": _short_class(elem.get("class", "")),
            "clickable": _parse_bool(elem.get("clickable", "false")),
            "checked": _parse_bool(elem.get("checked", "false")),
            "bounds": _bounds_tuple(elem),
            "elem": elem,
            "ancestors": ancestors,
        })
        idx += 1
    return result


def parse_meaningful_nodes_from_text(phonefast_text: str) -> list[dict[str, Any]]:
    """从 phonefast observe 文本反向解析 meaningful 节点列表。"""
    state = phonefast_parser.parse(phonefast_text)
    result: list[dict[str, Any]] = []
    for el in state.elements:
        result.append({
            "idx": el.index,
            "text": el.text or "",
            "desc": el.desc or "",
            "rid": el.id or "",
            "class": el.cls,
            "clickable": el.clickable,
            "checked": False,
            "bounds": el.bounds,
            "elem": None,
            "ancestors": [],
        })
    return result
