#!/usr/bin/env python3
"""Generic converter: Android UI hierarchy XML → HTML mockup.

Renders every visible node as an absolutely-positioned div based on its
``bounds`` attribute.  Elements that represent images (app icons,
screenshots, ImageViews) get placeholder graphics; structural elements
(cards, buttons, search bars) get visible frames.

Usage::

    python3 xml_to_html.py tests/fixtures/wd2.xml     # → tests/fixtures/wd2.html
    python3 xml_to_html.py tests/fixtures/wd2.xml -o out.html
    python3 xml_to_html.py tests/fixtures/*.xml       # batch
"""

from __future__ import annotations

import argparse
import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_bounds(s: str) -> Optional[Tuple[int, int, int, int]]:
    m = _BOUNDS_RE.match(s)
    return tuple(int(x) for x in m.groups()) if m else None


def short_class(cls: str) -> str:
    return cls.rsplit(".", 1)[-1] if cls else "View"


def collect_nodes(root: ET.Element) -> List[Dict[str, Any]]:
    """Walk the tree, collect visible nodes with rendering metadata."""
    nodes: List[Dict[str, Any]] = []
    for elem in root.iter("node"):
        b = elem.get("bounds", "")
        parsed = parse_bounds(b)
        if parsed is None:
            continue
        l, t, r, bot = parsed
        if l == 0 and t == 0 and r == 0 and bot == 0:
            continue
        if r - l < 2 or bot - t < 2:
            continue
        nodes.append({
            "bounds": (l, t, r, bot),
            "text": elem.get("text", ""),
            "desc": elem.get("content-desc", ""),
            "cls": short_class(elem.get("class", "")),
            "clickable": elem.get("clickable", "false") == "true",
            "scrollable": elem.get("scrollable", "false") == "true",
            "long_clickable": elem.get("long-clickable", "false") == "true",
            "checked": elem.get("checked", "false") == "true",
            "selected": elem.get("selected", "false") == "true",
            "enabled": elem.get("enabled", "true") == "true",
            "rid": elem.get("resource-id", ""),
        })
    return nodes


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_ICON_HINTS = {
    "返回": "←",
    "转到上一层级": "←",
    "语音搜索": "🎤",
    "更多选项": "⋮",
    "安装": "⬇",
    "在 Google Play 中搜索": "▶",
}

# Color palette for app icons — hashed by app name
_ICON_COLORS = [
    ("#FF2442", "#FF6080"),  # red
    ("#6C5CE7", "#a29bfe"),  # purple
    ("#00C2FF", "#0080FF"),  # blue
    ("#FFD32A", "#FF6B01"),  # yellow-orange
    ("#01875f", "#2ecc71"),  # green
    ("#e17055", "#fab1a0"),  # orange
    ("#0984e3", "#74b9ff"),  # light blue
    ("#2D3436", "#636e72"),  # dark gray
]


def _icon_colors(name: str) -> Tuple[str, str]:
    h = hash(name) & 0xFFFF
    return _ICON_COLORS[h % len(_ICON_COLORS)]


def _desc_lines(desc: str) -> List[str]:
    return [ln.strip() for ln in desc.split("\n") if ln.strip()]


def _is_app_icon(n: Dict[str, Any]) -> bool:
    """Detect if node is an app icon (small square, no text, in a card)."""
    l, t, r, bot = n["bounds"]
    w, h = r - l, bot - t
    # App icons are roughly square, 80-160px
    if 60 < w < 200 and 60 < h < 200 and abs(w - h) < 40:
        if not n["text"] and not n["desc"]:
            return True
    return False


def _is_screenshot(n: Dict[str, Any]) -> bool:
    desc = n["desc"]
    return bool(desc and "截图" in desc)


def _is_info_item(n: Dict[str, Any]) -> bool:
    desc = n["desc"]
    return bool(desc and any(kw in desc for kw in [
        "评价", "星级", "内容分级", "下载量"
    ]))


def _is_install_btn(n: Dict[str, Any]) -> bool:
    return n["text"] == "安装" or n["desc"] == "安装"


def _is_app_info_block(n: Dict[str, Any]) -> bool:
    """Multi-line content-desc with app name + developer."""
    if not n["desc"]:
        return False
    lines = _desc_lines(n["desc"])
    return len(lines) >= 2 and any(
        kw in n["desc"] for kw in ["广告", "星级", "Inc", "Ltd", "科技", "公司"]
    )


def render_node(n: Dict[str, Any]) -> str:
    """Render a single node as an HTML div with appropriate frame/placeholder."""
    l, t, r, bot = n["bounds"]
    w = r - l
    h = bot - t
    text = n["text"]
    desc = n["desc"]
    cls = n["cls"]
    clickable = n["clickable"]

    style_pos = f"left:{l}px;top:{t}px;width:{w}px;height:{h}px"

    # ── Install button ──
    if _is_install_btn(n):
        label = text or "安装"
        return (f'<div class="el install-btn" style="{style_pos}">'
                f'<span>{html.escape(label)}</span></div>')

    # ── Search input (EditText) ──
    if "EditText" in cls or (text and "搜索" in text and h < 80 and w > 300):
        return (f'<div class="el search-input" style="{style_pos}">'
                f'<span>🔍 {html.escape(text or "搜索")}</span></div>')

    # ── Screenshot thumbnails ──
    if _is_screenshot(n):
        num = ""
        m = re.search(r"第\s*(\d+)\s*张", desc)
        if m:
            num = m.group(1)
        total = ""
        m2 = re.search(r"共\s*(\d+)\s*张", desc)
        if m2:
            total = f"/{m2.group(1)}"
        return (f'<div class="el screenshot" style="{style_pos}">'
                f'<div class="shot-placeholder">'
                f'<span class="shot-icon">📷</span>'
                f'<span class="shot-label">截图 {num}{total}</span>'
                f'</div></div>')

    # ── Info items (rating / content rating / downloads) ──
    if _is_info_item(n):
        icon = "⭐"
        label = desc
        if "内容分级" in desc:
            icon = "📋"
            m = re.search(r"(\d+)", desc)
            label = f"{m.group(1)}+" if m else desc
        elif "下载量" in desc:
            icon = "⬇"
            m = re.search(r"超过\s*([\d,]+万?)", desc)
            label = m.group(1) if m else desc
        elif "评价" in desc:
            icon = "⭐"
            m = re.search(r"([\d.]+)\s*星", desc)
            rating = m.group(1) if m else ""
            m2 = re.search(r"([\d万]+)\s*条", desc)
            count = m2.group(1) if m2 else ""
            label = f"{rating} ★"
            sub = f"{count}条评价"
        else:
            sub = ""
        if "评价" in desc:
            return (f'<div class="el info-item" style="{style_pos}">'
                    f'<div class="info-icon">{icon}</div>'
                    f'<div class="info-main">{html.escape(label)}</div>'
                    f'<div class="info-sub">{html.escape(sub)}</div></div>')
        return (f'<div class="el info-item" style="{style_pos}">'
                f'<div class="info-icon">{icon}</div>'
                f'<div class="info-sub">{html.escape(label)}</div></div>')

    # ── App info block (multi-line desc) ──
    if _is_app_info_block(n):
        lines = _desc_lines(desc)
        app_name = lines[0]
        dev = lines[1] if len(lines) > 1 else ""
        extras = [ln for ln in lines[2:] if ln and ln != "包含广告"]
        has_ad = "包含广告" in desc
        inner = f'<div class="app-name">{html.escape(app_name)}</div>'
        if dev:
            inner += f'<div class="app-dev">{html.escape(dev)}</div>'
        if has_ad:
            inner += '<div class="app-ad">📦 广告</div>'
        for ex in extras[:2]:
            inner += f'<div class="app-extra">{html.escape(ex)}</div>'
        return (f'<div class="el app-info" style="{style_pos}">{inner}</div>')

    # ── ImageView → placeholder image ──
    if "ImageView" in cls:
        if w > 80 and h > 80:
            # Large image — gradient placeholder
            return (f'<div class="el img-placeholder" style="{style_pos}">'
                    f'<span>🖼️</span></div>')
        # Small icon image
        icon = _ICON_HINTS.get(desc, "🔹")
        return (f'<div class="el img-small" style="{style_pos}">'
                f'<span>{icon}</span></div>')

    # ── App icon (small square View in card, no text/desc) ──
    if _is_app_icon(n):
        c1, c2 = _icon_colors("default")
        return (f'<div class="el app-icon" style="{style_pos};'
                f'background:linear-gradient(135deg,{c1},{c2});">'
                f'<span></span></div>')

    # ── Text labels ──
    if text and h < 100:
        font_size = min(18, max(11, int(h * 0.5)))
        color = "#5f6368" if h < 35 else "#1a1a1a"
        weight = "600" if h > 40 else "400"
        # Detect section titles
        if text in ("赞助商广告", "与您搜索过的内容相关"):
            color = "#5f6368"
            font_size = 12
            weight = "400"
        elif any(kw in text for kw in ["为您推荐", "活动进行中", "最近的搜索"]):
            font_size = 18
            weight = "600"
        return (f'<div class="el text-label" style="{style_pos};'
                f'font-size:{font_size}px;color:{color};font-weight:{weight};">'
                f'<span>{html.escape(text)}</span></div>')

    # ── Icon with description (back button, voice search, more, etc.) ──
    if desc and not text and h < 120:
        icon = _ICON_HINTS.get(desc, "")
        if not icon:
            if "搜索" in desc:
                icon = "🔍"
            elif "截图" in desc:
                icon = "📷"
            else:
                icon = "🔹"
        label = desc if len(desc) <= 15 else ""
        inner = f'<span class="ico">{icon}</span>'
        if label:
            inner += f'<span class="ico-lbl">{html.escape(label)}</span>'
        return (f'<div class="el icon-btn" style="{style_pos}">{inner}</div>')

    # ── Card containers (large clickable areas) ──
    if clickable and h > 100:
        return (f'<div class="el card-frame" style="{style_pos}"></div>')

    # ── Scrollable containers ──
    if n["scrollable"]:
        return (f'<div class="el scroll-frame" style="{style_pos}"></div>')

    # ── Generic view — subtle frame ──
    return f'<div class="el view-frame" style="{style_pos}"></div>'


# ---------------------------------------------------------------------------
# Full HTML document
# ---------------------------------------------------------------------------


def generate_html(nodes: List[Dict[str, Any]], title: str = "UI Mockup") -> str:
    if not nodes:
        return "<html><body><p>No visible nodes found.</p></body></html>"

    page_w = max(n["bounds"][2] for n in nodes)
    page_h = max(n["bounds"][3] for n in nodes)

    # Sort: large containers first (bottom), small elements last (top)
    def area(n):
        l, t, r, b = n["bounds"]
        return (r - l) * (b - t)

    sorted_nodes = sorted(nodes, key=area, reverse=True)
    elements_html = "\n".join(render_node(n) for n in sorted_nodes)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #1a1a2e;
    font-family: "Google Sans", "Noto Sans SC", "PingFang SC",
                 -apple-system, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 20px;
    gap: 12px;
  }}
  .toolbar {{
    display: flex;
    gap: 12px;
    align-items: center;
    color: #e0e0e0;
    font-size: 14px;
  }}
  .toolbar button {{
    background: #01875f;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
    cursor: pointer;
  }}
  .toolbar button:hover {{ background: #01704a; }}
  .toolbar button.outline-btn {{ background: #555; }}
  .phone {{
    width: {page_w}px;
    height: {page_h}px;
    background: #fff;
    border-radius: 16px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    position: relative;
    overflow: hidden;
    transform-origin: top center;
  }}

  /* ── Base element ── */
  .el {{
    position: absolute;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }}

  /* ── Frames ── */
  .card-frame {{
    border: 1.5px solid #e0e0e0;
    border-radius: 12px;
    background: #fff;
  }}
  .card-frame:hover {{
    border-color: #01875f;
    background: #f0faf5;
  }}
  .scroll-frame {{
    border: 1px dashed #ccc;
  }}
  .view-frame {{
    border: 1px dotted rgba(0,0,0,0.06);
  }}

  /* ── Install button ── */
  .install-btn {{
    background: #01875f;
    color: #fff;
    border-radius: 24px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
  }}
  .install-btn:hover {{ background: #01704a; }}
  .install-btn span {{ color: #fff; }}

  /* ── Search input ── */
  .search-input {{
    background: #f1f3f4;
    border-radius: 28px;
    padding: 0 20px;
    justify-content: flex-start;
    color: #5f6368;
    font-size: 16px;
  }}

  /* ── App info block ── */
  .app-info {{
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    padding: 0 12px;
    text-align: left;
  }}
  .app-name {{
    font-size: 15px;
    font-weight: 600;
    color: #1a1a1a;
    line-height: 1.3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
  }}
  .app-dev {{
    font-size: 12px;
    color: #5f6368;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
  }}
  .app-ad {{
    font-size: 10px;
    color: #999;
    margin-top: 2px;
  }}
  .app-extra {{
    font-size: 11px;
    color: #5f6368;
    margin-top: 1px;
  }}

  /* ── Text label ── */
  .text-label {{
    justify-content: flex-start;
    padding: 0 4px;
  }}
  .text-label span {{
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
  }}

  /* ── Icon button (back, voice, more, etc.) ── */
  .icon-btn {{
    flex-direction: column;
    gap: 2px;
    color: #5f6368;
    cursor: pointer;
    border-radius: 50%;
  }}
  .icon-btn:hover {{ background: rgba(0,0,0,0.05); }}
  .icon-btn .ico {{
    font-size: 22px;
  }}
  .icon-btn .ico-lbl {{
    font-size: 10px;
    text-align: center;
  }}

  /* ── App icon placeholder ── */
  .app-icon {{
    border-radius: 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.15);
  }}

  /* ── Image placeholder (large ImageView) ── */
  .img-placeholder {{
    background: linear-gradient(135deg, #e0e0e0, #bdbdbd);
    border-radius: 8px;
    color: #757575;
    font-size: 32px;
  }}

  /* ── Small image / icon ── */
  .img-small {{
    color: #5f6368;
    font-size: 20px;
  }}

  /* ── Screenshot ── */
  .screenshot {{
    border-radius: 12px;
    overflow: hidden;
  }}
  .shot-placeholder {{
    width: 100%;
    height: 100%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: rgba(255,255,255,0.85);
  }}
  .screenshot:nth-child(3n+1) .shot-placeholder {{
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
  }}
  .screenshot:nth-child(3n+2) .shot-placeholder {{
    background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
  }}
  .screenshot:nth-child(3n+3) .shot-placeholder {{
    background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
  }}
  .shot-icon {{
    font-size: 28px;
  }}
  .shot-label {{
    font-size: 12px;
    font-weight: 500;
  }}

  /* ── Info item (rating / content / downloads) ── */
  .info-item {{
    flex-direction: column;
    justify-content: center;
    text-align: center;
    border-left: 1px solid #e0e0e0;
    padding: 4px;
    gap: 2px;
  }}
  .info-item:first-child {{
    border-left: none;
  }}
  .info-icon {{
    font-size: 20px;
    color: #5f6368;
  }}
  .info-main {{
    font-size: 14px;
    font-weight: 600;
    color: #1a1a1a;
  }}
  .info-sub {{
    font-size: 11px;
    color: #5f6368;
  }}
</style>
</head>
<body>
<div class="toolbar">
  <span>📐 {page_w}×{page_h}px · {len(nodes)} nodes</span>
  <button onclick="toggleOutlines()" class="outline-btn">Toggle All Outlines</button>
  <button onclick="scaleFit()">Fit Width</button>
</div>
<div class="phone" id="phone">
{elements_html}
</div>
<script>
  let outlined = false;
  function toggleOutlines() {{
    outlined = !outlined;
    document.querySelectorAll('.el').forEach(el => {{
      if (outlined) {{
        el.style.outline = '1px solid rgba(255,0,0,0.4)';
      }} else {{
        el.style.outline = '';
      }}
    }});
  }}
  function scaleFit() {{
    const phone = document.getElementById('phone');
    const scale = Math.min(1, (window.innerWidth - 80) / {page_w});
    phone.style.transform = 'scale(' + scale + ')';
    phone.style.marginBottom = (-{page_h} * (1 - scale)) + 'px';
  }}
  window.addEventListener('load', scaleFit);
  window.addEventListener('resize', scaleFit);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def convert_file(xml_path: Path, out_path: Optional[Path] = None) -> Path:
    if out_path is None:
        out_path = xml_path.with_suffix(".html")

    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    nodes = collect_nodes(root)

    title = f"UI Mockup — {xml_path.name}"
    html_str = generate_html(nodes, title=title)
    out_path.write_text(html_str, encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert Android UI hierarchy XML to HTML mockup."
    )
    parser.add_argument("inputs", nargs="+", help="XML file(s) to convert")
    parser.add_argument("-o", "--output", default=None,
                        help="Output HTML path (single file only)")
    args = parser.parse_args()

    for inp in args.inputs:
        xml_path = Path(inp).resolve()
        if not xml_path.exists():
            print(f"❌ Not found: {xml_path}", flush=True)
            continue
        if args.output and len(args.inputs) == 1:
            out = Path(args.output).resolve()
        else:
            out = None
        result = convert_file(xml_path, out)
        print(f"✅ {xml_path.name} → {result}")


if __name__ == "__main__":
    main()
