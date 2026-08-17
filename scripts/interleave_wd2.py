#!/usr/bin/env python3
"""Reorder cards in wd2.xml so 小红书 and Lemon8 alternate.

Current order:  小红书(simple) → 小红书(detailed) → Lemon8(simple)
New order:      小红书(simple) → Lemon8(simple) → 小红书(detailed)

Strategy:
  1. Parse XML, find the scrollable container.
  2. Extract the 3 card subtrees + bottom section.
  3. Reorder: [card1, card3, card2, bottom].
  4. Recalculate vertical positions (shift each subtree's bounds).
  5. Write XML with proper &#10; entity escaping.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

META = Path(__file__).resolve().parent.parent
XML_PATH = META / "wd2.xml"

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_bounds(s):
    m = _BOUNDS_RE.match(s)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0, 0)


def fmt_bounds(l, t, r, b):
    return f"[{l},{t}][{r},{b}]"


def shift_subtree(elem, dy):
    """Shift element and all descendants by dy pixels vertically."""
    b = elem.get("bounds", "")
    if b:
        l, t, r, bb = parse_bounds(b)
        elem.set("bounds", fmt_bounds(l, t + dy, r, bb + dy))
    for child in elem:
        shift_subtree(child, dy)


def card_identity(elem):
    """Return 'xiaohongshu' or 'lemon8' based on descendant content-desc."""
    for desc in elem.iter("node"):
        cd = desc.get("content-desc", "")
        if "小红书" in cd:
            return "xiaohongshu"
        if "Lemon8" in cd:
            return "lemon8"
        tx = desc.get("text", "")
        if "小红书" in tx:
            return "xiaohongshu"
        if "Lemon8" in tx:
            return "lemon8"
    return "unknown"


def write_xml_with_entities(root, path):
    xml_str = ET.tostring(root, encoding="unicode")
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

    # Find scrollable container [0,230][1080,2106]
    scroll_node = None
    for elem in root.iter("node"):
        if elem.get("scrollable") == "true" and \
           elem.get("bounds", "").startswith("[0,230]"):
            scroll_node = elem
            break
    if scroll_node is None:
        raise RuntimeError("Scrollable container not found")

    children = list(scroll_node)
    print(f"  Found {len(children)} children in scroll container")

    # Classify children:
    #   header_text: "赞助商广告" (index 0)
    #   more_options: "更多选项" (index 1)
    #   cards: the 3 app cards
    #   bottom: the bottom sponsored section
    header = None
    more_opt = None
    cards = []
    bottom = None

    for child in children:
        b = child.get("bounds", "")
        # Check if it's the "赞助商广告" header text
        for desc in child.iter("node"):
            if desc.get("text") == "赞助商广告":
                _, t, _, _ = parse_bounds(b)
                if t < 400:  # top header
                    header = child
                    break
                else:  # bottom header (part of bottom section)
                    bottom = child
                    break
        if header is child or bottom is child:
            continue
        # Check if it's "更多选项"
        cd = child.get("content-desc", "")
        if "更多选项" in cd:
            more_opt = child
            continue
        # Check if it's the bottom section (contains "与您搜索过的内容相关")
        is_bottom = False
        for desc in child.iter("node"):
            if "与您搜索" in desc.get("text", ""):
                bottom = child
                is_bottom = True
                break
        if is_bottom:
            continue
        # Otherwise it's a card
        cards.append(child)

    print(f"  Header: {header is not None}")
    print(f"  More options: {more_opt is not None}")
    print(f"  Cards: {len(cards)}")
    for i, c in enumerate(cards):
        b = c.get("bounds", "")
        _, t, _, bb = parse_bounds(b)
        print(f"    Card {i}: {card_identity(c):14s} "
              f"y={t}→{bb} (h={bb - t})")
    print(f"  Bottom: {bottom is not None}")

    assert len(cards) == 3, f"Expected 3 cards, got {len(cards)}"
    assert all(c is not None for c in [header, more_opt, bottom])

    # Identify cards
    # Card 0: 小红书 simple  (y=356, h=522)
    # Card 1: 小红书 detailed (y=923, h=1027)
    # Card 2: Lemon8 simple  (y=1950, h=522)
    card_xhs_simple = cards[0]   # 小红书 simple
    card_xhs_detail = cards[1]   # 小红书 detailed
    card_lemon8      = cards[2]   # Lemon8 simple

    # Record original tops and heights
    def get_top(elem):
        return parse_bounds(elem.get("bounds", ""))[1]

    def get_bot(elem):
        return parse_bounds(elem.get("bounds", ""))[3]

    # New order: 小红书(simple), Lemon8(simple), 小红书(detailed)
    new_order = [card_xhs_simple, card_lemon8, card_xhs_detail]

    # Calculate new positions
    # Card 1 stays at y=356 (unchanged)
    # Gap between cards = 45px (matching original gap between card1 and card2)
    GAP = 45
    BOTTOM_GAP = 21  # original gap between card3 and bottom

    new_tops = []
    y = get_top(card_xhs_simple)  # 356
    for card in new_order:
        new_tops.append(y)
        h = get_bot(card) - get_top(card)
        y += h + GAP

    # Bottom section new top
    bottom_new_top = y - GAP + BOTTOM_GAP

    # Compute deltas and shift
    for card, new_top in zip(new_order, new_tops):
        old_top = get_top(card)
        delta = new_top - old_top
        if delta != 0:
            shift_subtree(card, delta)
            ident = card_identity(card)
            print(f"  Shifted {ident:14s} by {delta:+5d}  "
                  f"({old_top}→{new_top})")

    # Shift bottom section
    bottom_old_top = get_top(bottom)
    bottom_delta = bottom_new_top - bottom_old_top
    if bottom_delta != 0:
        shift_subtree(bottom, bottom_delta)
        print(f"  Shifted bottom       by {bottom_delta:+5d}  "
              f"({bottom_old_top}→{bottom_new_top})")

    # Reorder children in scroll_node
    # New order: header, more_opt, card1, card2, card3, bottom
    # Remove all children and re-add in new order
    for child in list(scroll_node):
        scroll_node.remove(child)
    scroll_node.append(header)
    scroll_node.append(more_opt)
    for i, card in enumerate(new_order):
        card.set("index", str(i + 2))
        scroll_node.append(card)
    bottom.set("index", str(len(new_order) + 2))
    scroll_node.append(bottom)

    # Write
    write_xml_with_entities(root, XML_PATH)
    print(f"\n✅ Written → {XML_PATH}")

    # Verify
    content = XML_PATH.read_text(encoding="utf-8")
    xhs_count = content.count("小红书")
    lem_count = content.count("Lemon8")
    print(f"  小红书 mentions: {xhs_count}")
    print(f"  Lemon8 mentions: {lem_count}")


if __name__ == "__main__":
    main()
