#!/usr/bin/env python3
"""Generate a polished HTML mockup of the Google Play search results page from wd.xml."""

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path

META = Path(__file__).resolve().parent.parent
XML_PATH = META / "wd.xml"
HTML_PATH = META / "wd_mockup.html"

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_bounds(s):
    m = _BOUNDS_RE.match(s)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0, 0)


def extract_apps(root):
    """Extract app card data from the XML tree."""
    apps = []
    for elem in root.iter("node"):
        desc = elem.get("content-desc", "")
        b = elem.get("bounds", "")
        if not b or not desc:
            continue
        l, t, r, bot = parse_bounds(b)
        if r - l < 500 or bot - t < 80:
            continue
        # Parse multi-line desc
        lines = [ln.strip() for ln in desc.split("\n") if ln.strip()]
        if len(lines) < 2:
            continue
        app_name = lines[0]
        # Check if it's an app card (has developer name, rating, etc.)
        if any(kw in desc for kw in ["星级", "已安装", "下载量"]):
            apps.append({
                "name": app_name,
                "developer": lines[1] if len(lines) > 1 else "",
                "rating": next((ln for ln in lines if "星级" in ln), ""),
                "downloads": next((ln for ln in lines if "下载量" in ln), ""),
                "badge": next((ln for ln in lines if "重大更新" in ln or "已安装" in ln), ""),
                "bounds": (l, t, r, bot),
                "is_installed": "已安装" in desc,
            })
    return apps


def extract_searches(root):
    """Extract search history entries."""
    searches = []
    for elem in root.iter("node"):
        desc = elem.get("content-desc", "")
        b = elem.get("bounds", "")
        if not b:
            continue
        l, t, r, bot = parse_bounds(b)
        if "搜索" in desc and "采用" not in desc and r - l > 500:
            searches.append({
                "text": desc.strip(),
                "bounds": (l, t, r, bot),
            })
    return searches


def generate_html():
    tree = ET.parse(str(XML_PATH))
    root = tree.getroot()
    apps = extract_apps(root)
    searches = extract_searches(root)

    # Build app cards HTML
    app_cards_html = ""
    for app in apps:
        is_lemon8 = "Lemon8" in app["name"]
        highlight = "highlight" if is_lemon8 else ""
        badge_html = f'<span class="new-badge">新增</span>' if is_lemon8 else ""

        rating_stars = ""
        if app["rating"]:
            rating_num = re.search(r"(\d+\.?\d*)", app["rating"])
            if rating_num:
                score = float(rating_num.group(1))
                full_stars = int(score)
                half_star = 1 if score - full_stars >= 0.5 else 0
                empty_stars = 5 - full_stars - half_star
                rating_stars = "★" * full_stars + "⯨" * half_star + "☆" * empty_stars

        btn_class = "btn-installed" if app["is_installed"] else "btn-install"
        btn_text = "已安装" if app["is_installed"] else "安装"

        # Determine icon gradient based on app name
        gradients = {
            "小红书": "linear-gradient(135deg, #FF2442, #FF6080)",
            "Manus AI": "linear-gradient(135deg, #6C5CE7, #a29bfe)",
            "CapCut": "linear-gradient(135deg, #00C2FF, #0080FF)",
            "Tacticool": "linear-gradient(135deg, #2D3436, #636e72)",
            "Lemon8": "linear-gradient(135deg, #FFD32A, #FF6B01)",
        }
        icon_bg = gradients.get(app["name"], "linear-gradient(135deg, #74b9ff, #0984e3)")
        icon_letter = app["name"][0] if app["name"] else "?"

        detail_parts = []
        if app["developer"]:
            detail_parts.append(html.escape(app["developer"]))
        if app["rating"]:
            detail_parts.append(html.escape(app["rating"]))
        if app["downloads"]:
            detail_parts.append(html.escape(app["downloads"]))
        detail_str = " · ".join(detail_parts)

        app_cards_html += f"""
    <div class="app-card {highlight}">
      <div class="app-icon" style="background: {icon_bg};">{icon_letter}</div>
      <div class="app-info">
        <div class="app-name">{html.escape(app['name'])} {badge_html}</div>
        <div class="app-detail">{detail_str}</div>
        <div class="app-rating">{rating_stars}</div>
      </div>
      <button class="{btn_class}">{btn_text}</button>
    </div>"""

    # Build search history HTML
    search_html = ""
    for s in searches:
        search_html += f"""
    <div class="search-item">
      <span class="search-icon">🔍</span>
      <span class="search-text">{html.escape(s['text'])}</span>
      <span class="search-arrow">↗</span>
    </div>"""

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Google Play 搜索结果 — 模拟界面 (含 Lemon8)</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #e8eaed;
    font-family: "Google Sans", "Noto Sans SC", "PingFang SC", -apple-system, sans-serif;
    display: flex;
    justify-content: center;
    padding: 30px 20px;
  }}
  .phone {{
    width: 540px;
    background: #fff;
    border-radius: 24px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.12);
    overflow: hidden;
    position: relative;
  }}
  .status-bar {{
    height: 40px;
    background: #fff;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 20px;
    font-size: 13px;
    color: #1a1a1a;
  }}
  .search-bar {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 16px;
    background: #fff;
    border-bottom: 1px solid #f1f3f4;
  }}
  .back-btn {{
    width: 40px; height: 40px;
    display: flex; align-items: center; justify-content: center;
    color: #5f6368;
    font-size: 22px;
    cursor: pointer;
    border-radius: 50%;
  }}
  .back-btn:hover {{ background: #f1f3f4; }}
  .search-input {{
    flex: 1;
    height: 44px;
    background: #f1f3f4;
    border-radius: 22px;
    display: flex;
    align-items: center;
    padding: 0 18px;
    color: #5f6368;
    font-size: 15px;
  }}
  .voice-btn {{
    width: 40px; height: 40px;
    display: flex; align-items: center; justify-content: center;
    color: #5f6368;
    font-size: 20px;
    cursor: pointer;
    border-radius: 50%;
  }}
  .voice-btn:hover {{ background: #f1f3f4; }}

  .content {{
    padding: 0;
  }}
  .section-label {{
    font-size: 13px;
    color: #5f6368;
    padding: 16px 20px 8px;
  }}
  .section-title {{
    font-size: 20px;
    font-weight: 600;
    color: #1a1a1a;
    padding: 8px 20px 12px;
  }}
  .section-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 20px 12px;
  }}
  .more-btn {{
    color: #5f6368;
    font-size: 22px;
    cursor: pointer;
  }}

  .app-card {{
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 12px 20px;
    cursor: pointer;
    transition: background 0.15s;
    position: relative;
  }}
  .app-card:hover {{ background: #f8f9fa; }}
  .app-card.highlight {{
    background: #e6f4ea;
    border: 2px dashed #01875f;
    border-radius: 12px;
    margin: 4px 8px;
    padding: 10px 12px;
  }}
  .app-icon {{
    width: 56px; height: 56px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
    color: #fff;
    font-weight: bold;
    flex-shrink: 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }}
  .app-info {{
    flex: 1;
    min-width: 0;
  }}
  .app-name {{
    font-size: 16px;
    font-weight: 600;
    color: #1a1a1a;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .new-badge {{
    background: #01875f;
    color: #fff;
    font-size: 10px;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: 500;
  }}
  .app-detail {{
    font-size: 12px;
    color: #5f6368;
    margin-top: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .app-rating {{
    font-size: 12px;
    color: #ffb300;
    margin-top: 2px;
    letter-spacing: 1px;
  }}
  .btn-install {{
    background: #01875f;
    color: #fff;
    border: none;
    border-radius: 20px;
    padding: 8px 20px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.15s;
  }}
  .btn-install:hover {{ background: #01704a; }}
  .btn-installed {{
    background: #e8eaed;
    color: #5f6368;
    border: none;
    border-radius: 20px;
    padding: 8px 20px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    flex-shrink: 0;
  }}

  .search-item {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 20px;
    cursor: pointer;
    transition: background 0.15s;
  }}
  .search-item:hover {{ background: #f8f9fa; }}
  .search-icon {{
    font-size: 18px;
    color: #5f6368;
  }}
  .search-text {{
    flex: 1;
    font-size: 15px;
    color: #1a73e8;
  }}
  .search-arrow {{
    color: #5f6368;
    font-size: 18px;
  }}

  .divider {{
    height: 1px;
    background: #f1f3f4;
    margin: 0 20px;
  }}
  .bottom-nav {{
    height: 60px;
    background: #fff;
    border-top: 1px solid #e8eaed;
    display: flex;
    align-items: center;
    justify-content: space-around;
  }}
  .nav-item {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    color: #5f6368;
    font-size: 11px;
    cursor: pointer;
  }}
  .nav-item.active {{ color: #01875f; }}
  .nav-icon {{
    font-size: 20px;
  }}

  .lemon8-callout {{
    background: #e6f4ea;
    border-radius: 12px;
    margin: 8px 12px;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .callout-icon {{
    font-size: 28px;
  }}
  .callout-text {{
    font-size: 13px;
    color: #01875f;
    line-height: 1.5;
  }}
  .callout-text strong {{ font-size: 14px; }}
</style>
</head>
<body>
<div class="phone">
  <div class="status-bar">
    <span>12:00</span>
    <span>📶 📶 🔋</span>
  </div>

  <div class="search-bar">
    <div class="back-btn">←</div>
    <div class="search-input">搜索应用和游戏</div>
    <div class="voice-btn">🎤</div>
  </div>

  <div class="content">
    <div class="section-label">赞助商广告</div>
    <div class="section-header">
      <span class="section-title" style="padding:0">为您推荐</span>
      <span class="more-btn">⋮</span>
    </div>

    {app_cards_html}

    <div class="lemon8-callout">
      <span class="callout-icon">🍋</span>
      <div class="callout-text">
        <strong>新增条目：Lemon8</strong><br>
        bounds=[0,1160][1080,1347] · clickable · long-clickable<br>
        content-desc="Lemon8 / Lemon8 Inc. / 星级：4.5 / 下载量超过 5,000万次"
      </div>
    </div>

    <div class="divider"></div>

    <div class="section-title">最近的搜索</div>
    {search_html}

    <div style="height:20px;"></div>
  </div>

  <div class="bottom-nav">
    <div class="nav-item"><span class="nav-icon">🎮</span>游戏</div>
    <div class="nav-item"><span class="nav-icon">📱</span>应用</div>
    <div class="nav-item active"><span class="nav-icon">🔍</span>搜索</div>
    <div class="nav-item"><span class="nav-icon">📚</span>图书</div>
    <div class="nav-item"><span class="nav-icon">👤</span>我</div>
  </div>
</div>
</body>
</html>"""

    HTML_PATH.write_text(html_content, encoding="utf-8")
    print(f"✅ HTML mockup → {HTML_PATH}")
    print(f"   {len(apps)} app cards, {len(searches)} search history items")


if __name__ == "__main__":
    generate_html()
