#!/usr/bin/env python3
"""Insert a Lemon8 app card into wd2.xml (fixed attribute names).

Handles both revert (if a previous broken insertion exists) and new insertion.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

META = Path(__file__).resolve().parent.parent
XML_PATH = META / "wd2.xml"
CARD_HEIGHT = 522

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_bounds(s):
    m = _BOUNDS_RE.match(s)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0, 0)


def fmt_bounds(l, t, r, b):
    return f"[{l},{t}][{r},{b}]"


def shift_bounds(s, dy):
    l, t, r, b = parse_bounds(s)
    return fmt_bounds(l, t + dy, r, b + dy)


def shift_subtree(elem, dy):
    b = elem.get("bounds", "")
    if b:
        elem.set("bounds", shift_bounds(b, dy))
    for child in elem:
        shift_subtree(child, dy)


# Standard attribute set for all nodes
_STD_ATTRS = {
    "index": "0",
    "text": "",
    "resource-id": "",
    "class": "android.view.View",
    "package": "com.android.vending",
    "content-desc": "",
    "checkable": "false",
    "checked": "false",
    "clickable": "false",
    "enabled": "true",
    "focusable": "false",
    "focused": "false",
    "scrollable": "false",
    "long-clickable": "false",
    "password": "false",
    "selected": "false",
    "bounds": "[0,0][0,0]",
}


def make_node(overrides: dict) -> ET.Element:
    """Create a <node> with standard attrs + overrides (hyphenated keys)."""
    attrs = dict(_STD_ATTRS)
    attrs.update(overrides)
    return ET.Element("node", attrs)


def build_lemon8_card(top: int) -> ET.Element:
    """Build the Lemon8 card tree, modeled after the first sponsored card."""
    ct = top  # card top
    cb = top + CARD_HEIGHT  # card bottom

    card = make_node({
        "index": "4",
        "clickable": "true",
        "focusable": "true",
        "bounds": fmt_bounds(63, ct, 1080, cb),
    })

    # App info block
    card.append(make_node({
        "content-desc": "Lemon8\nLemon8 Inc.\n包含广告\n",
        "bounds": fmt_bounds(252, ct + 42, 825, ct + 222),
    }))

    # Install button container
    install_ctr = make_node({
        "clickable": "true",
        "focusable": "true",
        "bounds": fmt_bounds(857, ct + 43, 1017, ct + 169),
    })
    install_wrap = make_node({
        "content-desc": "安装",
        "bounds": fmt_bounds(899, ct + 76, 975, ct + 135),
    })
    install_wrap.append(make_node({
        "text": "安装",
        "class": "android.widget.TextView",
        "bounds": fmt_bounds(899, ct + 76, 975, ct + 135),
    }))
    install_ctr.append(install_wrap)
    install_ctr.append(make_node({
        "class": "android.widget.Button",
        "bounds": fmt_bounds(857, ct + 53, 1017, ct + 158),
    }))
    card.append(install_ctr)

    # "包含内购商品"
    card.append(make_node({
        "text": "包含内购商品",
        "class": "android.widget.TextView",
        "bounds": fmt_bounds(870, ct + 158, 1005, ct + 199),
    }))

    # Rating info
    card.append(make_node({
        "clickable": "true",
        "focusable": "true",
        "content-desc": "有 8万 条评价，平均评分为 4.5 星",
        "bounds": fmt_bounds(63, ct + 254, 344, ct + 431),
    }))

    # Content rating info
    card.append(make_node({
        "clickable": "true",
        "focusable": "true",
        "content-desc": "内容分级为12 岁以上",
        "bounds": fmt_bounds(431, ct + 257, 712, ct + 428),
    }))

    # Downloads info
    card.append(make_node({
        "clickable": "true",
        "focusable": "true",
        "content-desc": "下载量超过 5,000万次",
        "bounds": fmt_bounds(799, ct + 254, 1080, ct + 431),
    }))

    # Tag text
    card.append(make_node({
        "text": "分享你的生活方式",
        "class": "android.widget.TextView",
        "content-desc": "分享你的生活方式",
        "bounds": fmt_bounds(63, ct + 452, 420, ct + 501),
    }))

    return card


def revert_lemon8(scroll_node):
    """Remove any existing Lemon8 card and unshift subsequent nodes."""
    removed = False
    for i, child in enumerate(list(scroll_node)):
        # Check for Lemon8 card: clickable, bounds top around 1950
        b = child.get("bounds", "")
        if not b:
            continue
        _, t, _, _ = parse_bounds(b)
        # Look for Lemon8 in any descendant's content-desc or content_desc
        is_lemon8 = False
        for desc in child.iter("node"):
            cd = desc.get("content-desc", "") or desc.get("content_desc", "")
            if "Lemon8" in cd:
                is_lemon8 = True
                break
            tx = desc.get("text", "")
            if tx == "分享你的生活方式":
                is_lemon8 = True
                break
        if is_lemon8:
            scroll_node.remove(child)
            removed = True
            print(f"  Removed existing Lemon8 card at index {i}")
            # Unshift subsequent siblings
            for sib in list(scroll_node):
                sb = sib.get("bounds", "")
                if sb:
                    _, st, _, _ = parse_bounds(sb)
                    if st >= t + CARD_HEIGHT:
                        shift_subtree(sib, -CARD_HEIGHT)
                        old_idx = int(sib.get("index", "0"))
                        sib.set("index", str(old_idx - 1))
            # Also clean up any content_desc (underscore) attributes
            break

    # Also clean up content_desc attributes from broken insertion
    if not removed:
        for elem in scroll_node.iter("node"):
            if elem.get("content_desc"):
                del elem.attrib["content_desc"]

    return removed


def insert_lemon8(scroll_node):
    """Insert Lemon8 card after the detailed card (index 3, ends at y=1950)."""
    SHIFT_THRESHOLD = 1971  # bottom section starts here

    # Shift bottom section down
    for child in list(scroll_node):
        b = child.get("bounds", "")
        if b:
            _, t, _, _ = parse_bounds(b)
            if t >= SHIFT_THRESHOLD:
                shift_subtree(child, CARD_HEIGHT)
                old_idx = int(child.get("index", "0"))
                child.set("index", str(old_idx + 1))

    # Insert Lemon8 card at index 4
    lemon8 = build_lemon8_card(top=1950)
    scroll_node.insert(4, lemon8)


def write_xml_with_entities(root, path):
    """Write XML, converting newlines in attributes to &#10; entities."""
    xml_str = ET.tostring(root, encoding="unicode")

    # Fix: also remove any lingering content_desc (underscore) attributes
    xml_str = xml_str.replace(' content_desc="', ' content-desc="')

    # Replace literal \n inside attribute values with &#10;
    xml_str = re.sub(
        r'(\w+-?\w*=")([^"]*\n[^"]*)(")',
        lambda m: m.group(1) + m.group(2).replace("\n", "&#10;") + m.group(3),
        xml_str,
    )

    header = "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
    path.write_text(header + xml_str, encoding="utf-8")


def main():
    print(f"📄 Reading {XML_PATH}")
    tree = ET.parse(str(XML_PATH))
    root = tree.getroot()

    # Find scrollable container
    scroll_node = None
    for elem in root.iter("node"):
        if elem.get("bounds") == "[0,230][1080,2106]" and \
           elem.get("scrollable") == "true":
            scroll_node = elem
            break
    if scroll_node is None:
        raise RuntimeError("Scrollable container not found")

    # Step 1: Revert any previous insertion
    print("🔄 Step 1: Checking for existing Lemon8 card...")
    revert_lemon8(scroll_node)

    # Step 2: Insert fresh
    print("🔄 Step 2: Inserting Lemon8 card...")
    insert_lemon8(scroll_node)
    print(f"   Card at y=1950, height={CARD_HEIGHT}px")

    # Step 3: Write
    print("🔄 Step 3: Writing XML...")
    write_xml_with_entities(root, XML_PATH)
    print(f"✅ Written → {XML_PATH}")

    # Verify
    content = XML_PATH.read_text(encoding="utf-8")
    if "content-desc=\"Lemon8&#10;" in content:
        print("✅ Verified: content-desc with &#10; entities")
    else:
        print("⚠️  Warning: content-desc not found correctly")
        idx = content.find("Lemon8")
        if idx >= 0:
            print(f"   Context: {repr(content[idx-20:idx+60])}")


if __name__ == "__main__":
    main()
