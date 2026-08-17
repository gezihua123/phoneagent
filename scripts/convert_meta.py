#!/usr/bin/env python3
"""Convert Android UI-hierarchy XML dumps into multiple structured formats.

Reads every ``*.xml`` file under ``meta/`` and produces five representations
of the same node tree:

  1. ``.yml``        — hierarchical YAML preserving the nested tree.
  2. ``.jsonl``      — one JSON object per line; tree flattened with
                       ``id`` / ``parent`` / ``depth`` fields.
  3. ``.flattext``   — indented plain text (phonefast ``ui`` style).
  4. ``.simplexml``  — simplified XML keeping only meaningful attributes
                       (drops empty strings and ``false`` booleans).
  5. ``.flatref``    — flat text with explicit ``#N`` node IDs and
                       ``parent=#M`` references (no indentation).

Usage::

    python3 convert_meta.py              # convert meta/*.xml → meta/
    python3 convert_meta.py -o out/      # write outputs to out/
    python3 convert_meta.py -v           # verbose (print per-file summary)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Node attribute schema
# ---------------------------------------------------------------------------

# Boolean attributes on <node> elements in Android uiautomator dumps.
# Stored here with underscores (matching the dict keys we produce).
_BOOL_ATTRS = (
    "checkable",
    "checked",
    "clickable",
    "enabled",
    "focusable",
    "focused",
    "scrollable",
    "long_clickable",
    "password",
    "selected",
)

# All attributes we extract, in display order.
_ATTR_ORDER = (
    "index",
    "text",
    "resource_id",
    "class",
    "package",
    "content_desc",
    "bounds",
) + _BOOL_ATTRS

# XML attribute name → our dict key (hyphens → underscores).
_ATTR_KEY_MAP = {
    "resource-id": "resource_id",
    "content-desc": "content_desc",
    "long-clickable": "long_clickable",
}


def _attr_key(name: str) -> str:
    return _ATTR_KEY_MAP.get(name, name.replace("-", "_"))


def _parse_bool(val: str) -> bool:
    return val.strip().lower() == "true"


# ---------------------------------------------------------------------------
# XML → structured node tree
# ---------------------------------------------------------------------------


def parse_node(elem: ET.Element) -> Dict[str, Any]:
    """Convert a <node> XML element into a dict, recursing into children."""
    node: Dict[str, Any] = {}

    # String / int attributes
    node["index"] = int(elem.get("index", "0"))
    node["text"] = elem.get("text", "")
    node["resource_id"] = elem.get("resource-id", "")
    node["class"] = elem.get("class", "")
    node["package"] = elem.get("package", "")
    node["content_desc"] = elem.get("content-desc", "")
    node["bounds"] = elem.get("bounds", "")

    # Boolean attributes — _BOOL_ATTRS already uses underscore keys,
    # so map back to the XML attribute name (hyphenated) for elem.get().
    for attr in _BOOL_ATTRS:
        xml_attr = attr.replace("_", "-")
        node[attr] = _parse_bool(elem.get(xml_attr, "false"))

    # Recurse
    children = [parse_node(child) for child in elem.findall("node")]
    node["children"] = children
    return node


def parse_hierarchy_xml(path: Path) -> Dict[str, Any]:
    """Parse a full uiautomator dump file.

    Returns ``{"rotation": str, "children": [node, ...]}``.
    """
    tree = ET.parse(str(path))
    root = tree.getroot()  # <hierarchy>
    result: Dict[str, Any] = {
        "rotation": root.get("rotation", "0"),
        "children": [parse_node(n) for n in root.findall("node")],
    }
    return result


# ---------------------------------------------------------------------------
# Flatten the tree for line-oriented formats
# ---------------------------------------------------------------------------


def flatten_tree(
    tree: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Walk the tree depth-first, returning a flat list with id/parent/depth."""
    flat: List[Dict[str, Any]] = []
    counter = 0

    def walk(node: Dict[str, Any], parent: Optional[int], depth: int) -> None:
        nonlocal counter
        node_id = counter
        counter += 1
        entry = {"id": node_id, "parent": parent, "depth": depth}
        # Copy all attributes except children
        for k in _ATTR_ORDER:
            entry[k] = node.get(k)
        flat.append(entry)
        for child in node.get("children", []):
            walk(child, node_id, depth + 1)

    for child in tree["children"]:
        walk(child, None, 0)
    return flat


# ---------------------------------------------------------------------------
# Format 1: YAML (hierarchical)
# ---------------------------------------------------------------------------


def to_yaml(tree: Dict[str, Any]) -> str:
    """Serialize the full tree as YAML, preserving hierarchy."""
    return yaml.dump(
        tree,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1000,  # avoid line wrapping of long bounds strings
    )


# ---------------------------------------------------------------------------
# Format 2: JSONL (flat, one node per line)
# ---------------------------------------------------------------------------


def to_jsonl(tree: Dict[str, Any]) -> str:
    """Produce one JSON object per line, each node carrying id/parent/depth."""
    flat = flatten_tree(tree)
    lines = [json.dumps(entry, ensure_ascii=False) for entry in flat]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Format 3: flattext (indented, phonefast-style)
# ---------------------------------------------------------------------------


def _short_class(cls: str) -> str:
    """``android.widget.TextView`` → ``TextView``."""
    return cls.rsplit(".", 1)[-1] if cls else "View"


def _format_flags(node: Dict[str, Any]) -> str:
    """Build ``[clickable] [focused]`` style annotation."""
    flags = []
    for attr in ("clickable", "scrollable", "focused", "checked",
                 "selected", "long_clickable"):
        if node.get(attr):
            flags.append(attr.replace("_", "-"))
    return " ".join(f"[{f}]" for f in flags)


def _node_label(node: Dict[str, Any]) -> str:
    """Build a human-readable label for one node (text / desc / id)."""
    parts = []
    text = node.get("text", "")
    desc = node.get("content_desc", "")
    rid = node.get("resource_id", "")
    if text:
        parts.append(f'text="{text}"')
    if desc and desc != text:
        parts.append(f'desc="{desc}"')
    if rid:
        parts.append(f'id="{rid}"')
    return " ".join(parts) if parts else ""


def to_flattext(tree: Dict[str, Any]) -> str:
    """Indented plain text — each line: ``depth-prefixed [index] label (Class) [flags] bounds``."""
    lines: List[str] = []
    lines.append(f'hierarchy rotation="{tree["rotation"]}"')
    lines.append("=" * 60)

    def walk(node: Dict[str, Any], depth: int) -> None:
        indent = "  " * depth
        idx = node.get("index", 0)
        label = _node_label(node)
        cls = _short_class(node.get("class", ""))
        flags = _format_flags(node)
        bounds = node.get("bounds", "")

        parts = [f"{indent}[{idx}]"]
        if label:
            parts.append(label)
        parts.append(f"({cls})")
        if flags:
            parts.append(flags)
        if bounds:
            parts.append(f"bounds={bounds}")
        lines.append(" ".join(parts))

        for child in node.get("children", []):
            walk(child, depth + 1)

    for child in tree["children"]:
        walk(child, 0)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Format 4: simplexml (only meaningful attributes, no empty/false)
# ---------------------------------------------------------------------------


_SIMPLE_ATTRS = ("index", "text", "resource_id", "class", "package",
                 "content_desc", "bounds") + _BOOL_ATTRS

# Map our key back to XML attribute name for output.
_KEY_TO_XML = {
    "resource_id": "resource-id",
    "content_desc": "content-desc",
    "long_clickable": "long-clickable",
}


def _key_to_xml(k: str) -> str:
    return _KEY_TO_XML.get(k, k)


def _should_keep(key: str, value: Any) -> bool:
    """Decide whether to include an attribute in simplexml output."""
    if isinstance(value, bool):
        return value  # only keep true booleans
    if isinstance(value, str):
        return value != ""  # drop empty strings
    if isinstance(value, int):
        return value != 0
    return value is not None


def _escape_attr(val: Any) -> str:
    s = str(val)
    return (s.replace("&", "&amp;")
             .replace('"', "&quot;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


def to_simplexml(tree: Dict[str, Any]) -> str:
    """Simplified XML: drop empty/false attributes, short class names."""
    def build(node: Dict[str, Any]) -> str:
        attrs = []
        for key in _SIMPLE_ATTRS:
            val = node.get(key)
            if key == "class":
                val = _short_class(val) if val else ""
            if _should_keep(key, val):
                attrs.append(f'{_key_to_xml(key)}="{_escape_attr(val)}"')

        attr_str = " ".join(attrs)
        children = node.get("children", [])
        if children:
            inner = "\n" + "\n".join("  " + build(c).replace("\n", "\n  ")
                                     for c in children) + "\n"
            return f"<node {attr_str}>{inner}</node>"
        return f"<node {attr_str} />"

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<hierarchy rotation="{tree["rotation"]}">',
    ]
    for child in tree["children"]:
        # Indent each top-level child
        for line in build(child).split("\n"):
            parts.append("  " + line if line else line)
    parts.append("</hierarchy>")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Format 5: flattext with ref (flat, explicit #id and parent=#M)
# ---------------------------------------------------------------------------


def to_flatref(tree: Dict[str, Any]) -> str:
    """Flat text where every node gets ``#N`` and shows ``parent=#M``.

    No indentation — hierarchy is expressed purely via parent references.
    """
    flat = flatten_tree(tree)
    lines: List[str] = []
    lines.append(f'hierarchy rotation="{tree["rotation"]}"  ({len(flat)} nodes)')
    lines.append("=" * 60)

    for entry in flat:
        nid = entry["id"]
        parent = entry["parent"]
        depth = entry["depth"]
        parent_str = f"parent=#{parent}" if parent is not None else "parent=None"

        label = _node_label(entry)
        cls = _short_class(entry.get("class", ""))
        flags = _format_flags(entry)
        bounds = entry.get("bounds", "")

        parts = [f"#{nid}", parent_str, f"depth={depth}", f"[{entry.get('index', 0)}]"]
        if label:
            parts.append(label)
        parts.append(f"({cls})")
        if flags:
            parts.append(flags)
        if bounds:
            parts.append(f"bounds={bounds}")
        lines.append(" ".join(parts))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Format 6: compact (filtered, wrapper-collapsed, minimal line format)
# ---------------------------------------------------------------------------


_OBFUSCATED_IDS = frozenset({
    "0_resource_name_obfuscated",
})


def _short_rid(rid: str) -> str:
    """Extract short name from ``pkg:id/name`` → ``name``."""
    return rid.split("/")[-1] if "/" in rid else rid


def _is_meaningful(node: Dict[str, Any]) -> bool:
    """A node is meaningful if it carries semantic info or is interactive."""
    if node.get("text"):
        return True
    if node.get("content_desc"):
        return True
    rid = node.get("resource_id", "")
    if rid and not rid.startswith("android:") and _short_rid(rid) not in _OBFUSCATED_IDS:
        return True
    if node.get("clickable"):
        return True
    if node.get("scrollable"):
        return True
    if node.get("long_clickable"):
        return True
    cls = node.get("class", "")
    if "EditText" in cls:
        return True
    return False


def _has_meaningful_descendant(node: Dict[str, Any]) -> bool:
    for child in node.get("children", []):
        if _is_meaningful(child) or _has_meaningful_descendant(child):
            return True
    return False


def _compact_flags(node: Dict[str, Any]) -> str:
    """Single-char flags: +=clickable ~=scrollable !=long-clickable =checked >selected."""
    flags = []
    if node.get("clickable"):
        flags.append("+")
    if node.get("scrollable"):
        flags.append("~")
    if node.get("long_clickable"):
        flags.append("!")
    if node.get("checked"):
        flags.append("=")
    if node.get("selected"):
        flags.append(">")
    return "".join(flags)


def _sanitize(s: str, maxlen: int = 80) -> str:
    """Collapse whitespace, truncate long strings."""
    s = " ".join(s.split())
    if len(s) > maxlen:
        s = s[:maxlen - 1] + "…"
    return s


def _compact_label(node: Dict[str, Any]) -> str:
    """Compact label: T"text" D<desc> #short_id."""
    parts = []
    text = _sanitize(node.get("text", ""))
    desc = _sanitize(node.get("content_desc", ""))
    rid = node.get("resource_id", "")
    if text:
        parts.append(f'T"{text}"')
    if desc and desc != text:
        parts.append(f'D<{desc}>')
    if rid and not rid.startswith("android:") and _short_rid(rid) not in _OBFUSCATED_IDS:
        parts.append(f"#{_short_rid(rid)}")
    return " ".join(parts)


def to_compact(tree: Dict[str, Any]) -> str:
    """Compact format: only meaningful nodes, wrapper chains collapsed.

    Rules:
      - Skip nodes with zero-size bounds (invisible).
      - Skip non-meaningful nodes that are wrapper chains (single path).
      - Keep non-meaningful nodes that group ≥2 meaningful descendants.
      - System resource-ids (android:id/*) don't count as meaningful.
      - Deduplicate: when a child has identical bounds as parent, only
        keep the parent (avoids LLM returning inner element instead of
        the clickable container).
      - Clickable containers are prefixed with "▶" for visual emphasis.

    Line format: ``[l,t][r,b] <flags> <Class> <label>``
    """
    lines: List[str] = [f'hierarchy rotation="{tree["rotation"]}"']

    def walk(node: Dict[str, Any], depth: int, parent_bounds: str = "") -> None:
        bounds = node.get("bounds", "")
        children = node.get("children", [])
        zero = bounds in ("[0,0][0,0]", "", None)

        # Always skip zero-size nodes, but still traverse children
        if zero:
            for child in children:
                walk(child, depth, parent_bounds)
            return

        # Deduplicate: skip this node if its bounds == parent's bounds
        # (e.g., install button container and its inner text share bounds).
        # Keep the one that is clickable/meaningful — the parent was
        # already emitted, so skip the child.
        if bounds == parent_bounds and not node.get("clickable"):
            # But still traverse children (they may differ)
            for child in children:
                walk(child, depth, bounds)
            return

        if _is_meaningful(node):
            indent = "  " * depth
            flags = _compact_flags(node)
            cls = _short_class(node.get("class", ""))
            label = _compact_label(node)
            # Emphasize clickable containers with ▶ prefix
            click_mark = "▶ " if node.get("clickable") else ""
            parts = [indent, bounds]
            if flags:
                parts.append(flags)
            parts.append(cls)
            if label:
                parts.append(label)
            # Add click emphasis after bounds for clickable containers
            line = " ".join(parts)
            if click_mark and not node.get("text"):
                # Only mark containers, not text buttons
                line = f"{indent}{click_mark}{line[len(indent):]}"
            lines.append(line)
            child_depth = depth + 1
        else:
            # Non-meaningful: keep as grouping container if ≥2 children
            # lead to meaningful content; otherwise collapse (wrapper).
            meaningful_kids = sum(
                1 for c in children
                if _is_meaningful(c) or _has_meaningful_descendant(c)
            )
            if meaningful_kids >= 2:
                indent = "  " * depth
                cls = _short_class(node.get("class", ""))
                lines.append(f"{indent}{bounds} {cls}")
                child_depth = depth + 1
            else:
                child_depth = depth

        for child in children:
            walk(child, child_depth, bounds)

    for child in tree["children"]:
        walk(child, 0)

    return "\n".join(lines) + "\n"


_CONVERTERS = {
    ".yml": to_yaml,
    ".jsonl": to_jsonl,
    ".flattext": to_flattext,
    ".simplexml": to_simplexml,
    ".flatref": to_flatref,
    ".compact": to_compact,
}


def convert_file(xml_path: Path, out_dir: Path, verbose: bool = False) -> None:
    """Convert one XML file into all five formats."""
    tree = parse_hierarchy_xml(xml_path)
    stem = xml_path.stem

    for ext, converter in _CONVERTERS.items():
        out_path = out_dir / f"{stem}{ext}"
        content = converter(tree)
        out_path.write_text(content, encoding="utf-8")
        if verbose:
            node_count = len(flatten_tree(tree))
            print(f"  {out_path.name:40s} ({node_count} nodes, {len(content)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert meta/*.xml UI hierarchy dumps into YAML, JSONL, "
                    "flattext, simplexml, and flatref formats.",
    )
    parser.add_argument(
        "-i", "--input",
        default=str(Path(__file__).resolve().parent.parent),
        help="Input directory containing *.xml files (default: meta/)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output directory (default: same as input)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print per-file conversion summary",
    )
    args = parser.parse_args()

    in_dir = Path(args.input).resolve()
    out_dir = Path(args.output).resolve() if args.output else in_dir

    if not in_dir.is_dir():
        print(f"Error: input directory not found: {in_dir}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    xml_files = sorted(in_dir.glob("*.xml"))
    if not xml_files:
        print(f"No .xml files found in {in_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Converting {len(xml_files)} XML file(s) from {in_dir}")
    print(f"Output → {out_dir}")
    print(f"Formats: {', '.join(sorted(_CONVERTERS.keys()))}")
    print("-" * 60)

    for xml_path in xml_files:
        print(f"📄 {xml_path.name}")
        convert_file(xml_path, out_dir, verbose=True)

    print("-" * 60)
    print("✅ Done.")


if __name__ == "__main__":
    main()
