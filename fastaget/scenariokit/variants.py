"""variants: 屏幕变体生成器。

从 base XML 派生多种屏幕变体，覆盖真实自动化中的常见状态。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def _shift_bounds(xml_str: str, dy: int) -> str:
    """将所有节点 bounds 的 y 坐标整体下移 dy（模拟滚动）。"""
    def repl(m: re.Match) -> str:
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return f"[{x1},{y1 + dy}][{x2},{y2 + dy}]"
    return re.sub(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", repl, xml_str)


def _set_attr(xml_str: str, desc_match: str, attr: str, value: str) -> str:
    """将 content-desc 含 desc_match 的节点的 attr 改为 value。"""
    root = ET.fromstring(xml_str)

    def walk(elem: ET.Element) -> None:
        if elem.tag == "node":
            d = elem.get("content-desc", "")
            if desc_match in d:
                elem.set(attr, value)
        for child in elem:
            walk(child)

    walk(root)
    return ET.tostring(root, encoding="unicode")


def _strip_nodes(xml_str: str, desc_contains: str) -> str:
    """删除 content-desc 或 text 含指定串的节点。"""
    root = ET.fromstring(xml_str)

    def prune(parent: ET.Element) -> None:
        for child in list(parent):
            d = child.get("content-desc", "")
            t = child.get("text", "")
            if desc_contains in d or desc_contains in t:
                parent.remove(child)
            else:
                prune(child)

    prune(root)
    return ET.tostring(root, encoding="unicode")


def _add_noise(xml_str: str, count: int = 5) -> str:
    """在根节点末尾插入若干噪声 View 节点。"""
    root = ET.fromstring(xml_str)
    top = root.find("node")
    if top is None:
        return xml_str
    for i in range(count):
        noise = ET.SubElement(top, "node")
        noise.set("text", f"噪声元素{i}")
        noise.set("content-desc", "")
        noise.set("resource-id", "")
        noise.set("class", "android.widget.TextView")
        noise.set("package", "com.android.settings")
        noise.set("clickable", "false")
        y = 200 + i * 60
        noise.set("bounds", f"[200,{y}][400,{y + 40}]")
    return ET.tostring(root, encoding="unicode")


def make_variants(base_xml: str) -> dict[str, str]:
    """从 base XML 派生多种屏幕变体。"""
    return {
        "baseline": base_xml,
        "bt_off": _set_attr(base_xml, "蓝牙开关", "checked", "false"),
        "loc_off": _set_attr(base_xml, "位置信息开关", "checked", "false"),
        "scrolled": _shift_bounds(base_xml, 200),
        "truncated": _strip_nodes(base_xml, "存储"),
        "noisy": _add_noise(base_xml, 5),
    }
