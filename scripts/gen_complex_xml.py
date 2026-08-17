#!/usr/bin/env python3
"""Generate complex Android UI hierarchy XML files for benchmarking.

Creates three high-complexity scenarios:
  - wd3.xml: Play Store search results with 5 app cards (5 install buttons)
  - wd4.xml: System Settings page with many similar list/toggle items
  - ui2.xml: Complex article/comment page with nested WebView content
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

META = Path(__file__).resolve().parent.parent
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


_STD = {
    "index": "0", "text": "", "resource-id": "",
    "class": "android.view.View", "package": "",
    "content-desc": "", "checkable": "false", "checked": "false",
    "clickable": "false", "enabled": "true", "focusable": "false",
    "focused": "false", "scrollable": "false", "long-clickable": "false",
    "password": "false", "selected": "false", "bounds": "[0,0][0,0]",
}


def mk(pkg, overrides):
    attrs = dict(_STD)
    attrs["package"] = pkg
    attrs.update(overrides)
    return ET.Element("node", attrs)


def write_xml(root, path):
    xml_str = ET.tostring(root, encoding="unicode")
    xml_str = re.sub(
        r'(\w+-?\w*=")([^"]*\n[^"]*)(")',
        lambda m: m.group(1) + m.group(2).replace("\n", "&#10;") + m.group(3),
        xml_str,
    )
    header = "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
    path.write_text(header + xml_str, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# wd3.xml: Play Store search "社交" → 5 app cards with install buttons
# ═══════════════════════════════════════════════════════════════════════════

def build_app_card(pkg, name, dev, rating_desc, tag, top, card_h=400,
                   install_y_offset=43, info_y_offset=254):
    """Build a sponsored-app card (compact version without screenshots)."""
    ct = top
    cb = top + card_h
    card = mk(pkg, {
        "index": "0", "clickable": "true", "focusable": "true",
        "bounds": fmt_bounds(63, ct, 1080, cb),
    })
    # App info
    card.append(mk(pkg, {
        "content-desc": f"{name}\n{dev}\n包含广告\n",
        "bounds": fmt_bounds(252, ct + 42, 825, ct + 222),
    }))
    # Install button container
    ic = mk(pkg, {
        "clickable": "true", "focusable": "true",
        "bounds": fmt_bounds(857, ct + install_y_offset,
                             1017, ct + install_y_offset + 126),
    })
    iw = mk(pkg, {
        "content-desc": "安装",
        "bounds": fmt_bounds(899, ct + install_y_offset + 33,
                             975, ct + install_y_offset + 92),
    })
    iw.append(mk(pkg, {
        "text": "安装", "class": "android.widget.TextView",
        "bounds": fmt_bounds(899, ct + install_y_offset + 33,
                             975, ct + install_y_offset + 92),
    }))
    ic.append(iw)
    ic.append(mk(pkg, {
        "class": "android.widget.Button",
        "bounds": fmt_bounds(857, ct + install_y_offset + 10,
                             1017, ct + install_y_offset + 115),
    }))
    card.append(ic)
    # In-app purchase text
    card.append(mk(pkg, {
        "text": "包含内购商品", "class": "android.widget.TextView",
        "bounds": fmt_bounds(870, ct + 158, 1005, ct + 199),
    }))
    # Rating info
    card.append(mk(pkg, {
        "clickable": "true", "focusable": "true",
        "content-desc": rating_desc,
        "bounds": fmt_bounds(63, ct + info_y_offset,
                             344, ct + info_y_offset + 177),
    }))
    # Content rating
    card.append(mk(pkg, {
        "clickable": "true", "focusable": "true",
        "content-desc": "内容分级为12 岁以上",
        "bounds": fmt_bounds(431, ct + info_y_offset + 3,
                             712, ct + info_y_offset + 174),
    }))
    # Downloads
    card.append(mk(pkg, {
        "clickable": "true", "focusable": "true",
        "content-desc": "下载量超过 1,000万次",
        "bounds": fmt_bounds(799, ct + info_y_offset,
                             1080, ct + info_y_offset + 177),
    }))
    # Tag
    card.append(mk(pkg, {
        "text": tag, "class": "android.widget.TextView",
        "content-desc": tag,
        "bounds": fmt_bounds(63, ct + info_y_offset + 198,
                             420, ct + info_y_offset + 247),
    }))
    return card


def gen_wd3():
    """Play Store search result for '社交' with 5 app cards."""
    pkg = "com.android.vending"
    root = mk(pkg, {
        "class": "android.widget.FrameLayout",
        "bounds": "[0,0][1080,2400]",
    })

    # Main container
    main = mk(pkg, {"bounds": "[0,80][1080,2300]"})
    root.append(main)

    # Scrollable content area
    scroll = mk(pkg, {
        "scrollable": "true",
        "bounds": "[0,230][1080,2300]",
    })
    main.append(scroll)

    # "赞助商广告" header
    scroll.append(mk(pkg, {
        "text": "赞助商广告", "class": "android.widget.TextView",
        "bounds": "[63,285][211,332]",
    }))

    # 5 app cards, each 400px tall, gap 45px
    apps = [
        ("小红书", "行吟信息科技(上海)有限公司",
         "有 19万 条评价，平均评分为 3.7 星", "购物避坑指南小红书经验"),
        ("TikTok", "TikTok Pte. Ltd.",
         "有 500万 条评价，平均评分为 4.5 星", "短视频社区"),
        ("Lemon8", "Lemon8 Inc.",
         "有 8万 条评价，平均评分为 4.5 星", "分享你的生活方式"),
        ("微博", "北京微梦创科网络技术有限公司",
         "有 80万 条评价，平均评分为 3.9 星", "随时随地发现新鲜事"),
        ("Instagram", "Instagram",
         "有 300万 条评价，平均评分为 4.0 星", "连接朋友分享生活"),
    ]

    y = 356
    card_h = 400
    gap = 45
    for i, (name, dev, rating, tag) in enumerate(apps):
        card = build_app_card(pkg, name, dev, rating, tag, y, card_h)
        scroll.append(card)
        y += card_h + gap

    # Bottom: "与您搜索过的内容相关"
    bottom = mk(pkg, {"bounds": fmt_bounds(0, y, 1080, y + 135)})
    bottom.append(mk(pkg, {
        "text": "赞助商广告", "class": "android.widget.TextView",
        "bounds": fmt_bounds(63, y + 55, 211, y + 102),
    }))
    bottom.append(mk(pkg, {
        "text": "与您搜索过的内容相关", "class": "android.widget.TextView",
        "bounds": fmt_bounds(251, y + 42, 731, y + 114),
    }))
    bottom.append(mk(pkg, {
        "clickable": "true", "focusable": "true",
        "content-desc": "更多选项",
        "bounds": fmt_bounds(912, y + 16, 1038, y + 135),
    }))
    scroll.append(bottom)

    # Top search bar
    topbar = mk(pkg, {"bounds": "[0,80][1080,227]"})
    topbar.append(mk(pkg, {
        "clickable": "true", "focusable": "true", "long-clickable": "true",
        "content-desc": "转到上一层级",
        "bounds": "[43,122][106,185]",
    }))
    topbar.append(mk(pkg, {
        "text": "社交", "class": "android.widget.TextView",
        "bounds": "[148,119][300,188]",
    }))
    topbar.append(mk(pkg, {
        "clickable": "true", "focusable": "true", "long-clickable": "true",
        "content-desc": "在 Google Play 中搜索",
        "bounds": "[849,122][912,185]",
    }))
    topbar.append(mk(pkg, {
        "clickable": "true", "focusable": "true", "long-clickable": "true",
        "content-desc": "语音搜索",
        "bounds": "[975,122][1038,185]",
    }))
    main.append(topbar)

    # Bottom nav bar (5 tabs)
    navbar = mk(pkg, {"bounds": "[0,2300][1080,2400]"})
    tabs = ["游戏", "应用", "搜索", "图书", "我"]
    for i, tab in enumerate(tabs):
        tab_x = i * 216
        tab_node = mk(pkg, {
            "clickable": "true" if i != 2 else "false",
            "focusable": "true" if i != 2 else "false",
            "selected": "true" if i == 2 else "false",
            "bounds": fmt_bounds(tab_x, 2300, tab_x + 216, 2400),
        })
        tab_node.append(mk(pkg, {
            "text": tab, "class": "android.widget.TextView",
            "bounds": "[0,0][0,0]",
        }))
        navbar.append(tab_node)
    root.append(navbar)

    write_xml(root, META / "wd3.xml")
    total_nodes = sum(1 for _ in root.iter("node"))
    print(f"  wd3.xml: {total_nodes} nodes, 5 app cards (5 install buttons)")
    return total_nodes


# ═══════════════════════════════════════════════════════════════════════════
# wd4.xml: System Settings page with many similar toggle/list items
# ═══════════════════════════════════════════════════════════════════════════

def gen_wd4():
    """Android System Settings page with many similar items."""
    pkg = "com.android.settings"
    root = mk(pkg, {
        "class": "android.widget.FrameLayout",
        "bounds": "[0,0][1080,2400]",
    })

    # Recycler view (scrollable)
    scroll = mk(pkg, {
        "scrollable": "true",
        "bounds": "[0,176][1080,2400]",
    })
    root.append(scroll)

    # Settings items: (title, summary, has_switch, switch_checked, icon_desc)
    items = [
        ("网络和互联网", "WLAN、移动网络、流量用量", False, False, "网络"),
        ("蓝牙", "已连接到 Pixel Buds Pro", True, True, "蓝牙"),
        ("已连接的设备", "Pixel Buds Pro、Chromebook", False, False, "设备"),
        ("电池", "87% - 预计还能使用 6 小时", False, False, "电池"),
        ("显示", "深色模式、亮度、屏幕超时", False, False, "显示"),
        ("声音和振动", "音量、勿扰、铃声", False, False, "声音"),
        ("通知", "通知历史、对话", False, False, "通知"),
        ("应用", "默认应用、屏幕使用时间", False, False, "应用"),
        ("存储", "已使用 128 GB / 256 GB", False, False, "存储"),
        ("隐私", "权限、活动控件", False, False, "隐私"),
        ("位置信息", "已开启 - 高精度", True, True, "位置"),
        ("安全", "屏幕锁定、指纹、Smart Lock", False, False, "安全"),
        ("密码和帐号", "5 个帐号", False, False, "帐号"),
        ("无障碍", "放大、颜色、时间限制", False, False, "无障碍"),
        ("数字健康与家长控制", "每日屏幕使用时间 3 小时 24 分", False, False, "健康"),
        ("Google", "账号、搜索、助手", False, False, "Google"),
        ("系统", "语言、时间、更新、备份", False, False, "系统"),
        ("关于手机", "Pixel 7 Pro - Android 14", False, False, "关于"),
    ]

    y = 176
    item_h = 144
    for i, (title, summary, has_sw, sw_on, icon_desc) in enumerate(items):
        item = mk(pkg, {
            "index": str(i),
            "clickable": "true" if not has_sw else "false",
            "focusable": "true" if not has_sw else "false",
            "bounds": fmt_bounds(0, y, 1080, y + item_h),
        })
        # Icon
        icon_wrap = mk(pkg, {
            "bounds": fmt_bounds(36, y + 36, 132, y + 108),
        })
        icon_wrap.append(mk(pkg, {
            "content-desc": icon_desc,
            "class": "android.widget.ImageView",
            "bounds": fmt_bounds(36, y + 36, 132, y + 108),
        }))
        item.append(icon_wrap)

        # Text container
        text_ct = mk(pkg, {
            "bounds": fmt_bounds(168, y + 20, 810, y + item_h - 20),
        })
        text_ct.append(mk(pkg, {
            "text": title, "class": "android.widget.TextView",
            "bounds": fmt_bounds(168, y + 30, 810, y + 75),
        }))
        text_ct.append(mk(pkg, {
            "text": summary, "class": "android.widget.TextView",
            "bounds": fmt_bounds(168, y + 75, 810, y + 114),
        }))
        item.append(text_ct)

        # Switch (if applicable)
        if has_sw:
            sw = mk(pkg, {
                "index": "3",
                "class": "android.widget.Switch",
                "text": "开启" if sw_on else "关闭",
                "checkable": "true",
                "checked": "true" if sw_on else "false",
                "clickable": "true",
                "focusable": "true",
                "content-desc": f"{title}开关",
                "bounds": fmt_bounds(900, y + 48, 1044, y + 96),
            })
            item.append(sw)
        else:
            # Chevron arrow
            item.append(mk(pkg, {
                "content-desc": f"查看{title}详情",
                "class": "android.widget.ImageView",
                "bounds": fmt_bounds(984, y + 56, 1020, y + 88),
            }))

        scroll.append(item)
        y += item_h

    # Header bar
    header = mk(pkg, {"bounds": "[0,0][1080,176]"})
    header.append(mk(pkg, {
        "clickable": "true", "focusable": "true",
        "content-desc": "返回",
        "bounds": "[0,0][147,176]",
    }))
    header.append(mk(pkg, {
        "text": "设置", "class": "android.widget.TextView",
        "bounds": "[63,58][300,118]",
    }))
    header.append(mk(pkg, {
        "clickable": "true", "focusable": "true",
        "content-desc": "搜索设置",
        "bounds": "[912,28][1080,148]",
    }))
    root.append(header)

    write_xml(root, META / "wd4.xml")
    total_nodes = sum(1 for _ in root.iter("node"))
    print(f"  wd4.xml: {total_nodes} nodes, 18 settings items (3 switches)")
    return total_nodes


# ═══════════════════════════════════════════════════════════════════════════
# ui2.xml: Complex article + comments page in a news app
# ═══════════════════════════════════════════════════════════════════════════

def gen_ui2():
    """News app article page with header, content, comments, actions."""
    pkg = "com.example.news"
    root = mk(pkg, {
        "class": "android.widget.FrameLayout",
        "bounds": "[0,0][1080,2400]",
    })

    # Main scrollable content
    scroll = mk(pkg, {
        "scrollable": "true",
        "bounds": "[0,176][1080,2200]",
    })
    root.append(scroll)

    # Article title
    scroll.append(mk(pkg, {
        "text": "2024年最值得关注的10款AI工具：从代码生成到图像创作",
        "class": "android.widget.TextView",
        "bounds": "[48,220][1032,380]",
    }))
    # Author info
    scroll.append(mk(pkg, {
        "text": "科技前沿观察",
        "class": "android.widget.TextView",
        "bounds": "[48,400][300,450]",
    }))
    scroll.append(mk(pkg, {
        "text": "2024-03-15 14:30",
        "class": "android.widget.TextView",
        "bounds": "[48,460][300,500]",
    }))
    # Follow button
    scroll.append(mk(pkg, {
        "text": "关注", "class": "android.widget.Button",
        "clickable": "true", "focusable": "true",
        "bounds": "[900,400][1032,470]",
    }))

    # Article body paragraphs
    paragraphs = [
        "随着人工智能技术的快速发展，越来越多的AI工具开始进入我们的日常工作和生活。本文将介绍10款在2024年最值得关注的AI工具，涵盖代码生成、图像创作、文本处理等多个领域。",
        "1. GitHub Copilot：作为最早进入市场的AI编程助手之一，Copilot已经帮助数百万开发者提高了编程效率。它支持多种编程语言，能够根据上下文自动补全代码。",
        "2. Midjourney：这款AI图像生成工具以其出色的艺术风格而闻名，用户只需输入文字描述就能生成高质量的图像作品。",
        "3. ChatGPT：OpenAI的对话式AI模型，能够进行自然语言对话、写作、编程、分析等多种任务，是目前最受欢迎的通用AI工具之一。",
        "4. Stable Diffusion：开源的AI图像生成模型，可以在本地运行，适合对隐私要求较高的用户和开发者。",
        "5. Claude：Anthropic开发的AI助手，以长文本理解和安全性著称，支持超长上下文窗口。",
    ]
    y = 540
    for i, para in enumerate(paragraphs):
        h = 180 if len(para) > 80 else 100
        scroll.append(mk(pkg, {
            "text": para, "class": "android.widget.TextView",
            "bounds": fmt_bounds(48, y, 1032, y + h),
        }))
        y += h + 30

    # Image placeholder in article
    scroll.append(mk(pkg, {
        "content-desc": "AI工具对比图表",
        "class": "android.widget.ImageView",
        "bounds": fmt_bounds(48, y, 1032, y + 400),
    }))
    y += 430

    # Like / Comment / Share / Bookmark action bar
    actions = [
        ("点赞", "1.2万", "👍"),
        ("评论", "856", "💬"),
        ("收藏", "3.4万", "⭐"),
        ("分享", "分享", "📤"),
    ]
    for i, (label, count, _) in enumerate(actions):
        x = 48 + i * 258
        scroll.append(mk(pkg, {
            "text": f"{label} {count}",
            "class": "android.widget.Button",
            "clickable": "true", "focusable": "true",
            "content-desc": f"{label}按钮",
            "bounds": fmt_bounds(x, y, x + 240, y + 80),
        }))
    y += 120

    # Comments section header
    scroll.append(mk(pkg, {
        "text": "全部评论 856 条",
        "class": "android.widget.TextView",
        "bounds": fmt_bounds(48, y, 600, y + 60),
    }))
    y += 90

    # Comments (5 comments, some with replies)
    comments = [
        ("用户_科技爱好者", "这篇文章总结得很全面！不过我觉得DALL-E 3也应该上榜，它的图像质量不输Midjourney。", "2小时前", "324", True),
        ("用户_设计师小王", "作为一个设计师，我每天都在用Midjourney和Stable Diffusion。两者各有优势，Midjourney的艺术感更强，SD的可控性更好。", "1小时前", "156", False),
        ("用户_开发者", "Copilot确实好用，但有时候生成的代码有bug，需要仔细review。建议新手不要完全依赖AI工具。", "3小时前", "89", False),
        ("用户_产品经理", "有没有推荐的AI产品原型设计工具？除了这篇文章提到的之外。", "45分钟前", "12", True),
        ("用户_学生党", "作为学生，这些工具大多需要付费，有没有免费替代方案推荐？", "30分钟前", "45", False),
    ]

    for i, (user, content, time_str, likes, has_reply) in enumerate(comments):
        # Avatar
        scroll.append(mk(pkg, {
            "content-desc": f"{user}的头像",
            "class": "android.widget.ImageView",
            "bounds": fmt_bounds(48, y, 120, y + 72),
        }))
        # Username
        scroll.append(mk(pkg, {
            "text": user, "class": "android.widget.TextView",
            "bounds": fmt_bounds(140, y, 600, y + 40),
        }))
        # Comment text
        scroll.append(mk(pkg, {
            "text": content, "class": "android.widget.TextView",
            "bounds": fmt_bounds(140, y + 40, 1032, y + 110),
        }))
        # Time + like count
        scroll.append(mk(pkg, {
            "text": f"{time_str}  点赞 {likes}",
            "class": "android.widget.TextView",
            "bounds": fmt_bounds(140, y + 110, 600, y + 145),
        }))
        # Like button
        scroll.append(mk(pkg, {
            "content-desc": f"给{user}的评论点赞",
            "clickable": "true", "focusable": "true",
            "class": "android.widget.Button",
            "bounds": fmt_bounds(920, y + 100, 1032, y + 145),
        }))
        y += 160

        # Reply (for some comments)
        if has_reply:
            scroll.append(mk(pkg, {
                "text": "用户_科技爱好者 回复：DALL-E 3确实不错，但考虑到是闭源API，本文侧重于有独立产品的工具。",
                "class": "android.widget.TextView",
                "bounds": fmt_bounds(180, y, 1032, y + 90),
            }))
            scroll.append(mk(pkg, {
                "text": "1小时前  点赞 23",
                "class": "android.widget.TextView",
                "bounds": fmt_bounds(180, y + 90, 600, y + 125),
            }))
            y += 150

    # Comment input bar at bottom of scroll
    scroll.append(mk(pkg, {
        "text": "写评论...", "class": "android.widget.EditText",
        "clickable": "true", "focusable": "true",
        "bounds": fmt_bounds(48, y, 900, y + 72),
    }))
    scroll.append(mk(pkg, {
        "text": "发送", "class": "android.widget.Button",
        "clickable": "true", "focusable": "true",
        "bounds": fmt_bounds(920, y, 1032, y + 72),
    }))

    # Top app bar
    topbar = mk(pkg, {"bounds": "[0,0][1080,176]"})
    topbar.append(mk(pkg, {
        "clickable": "true", "focusable": "true",
        "content-desc": "返回",
        "bounds": "[0,0][147,176]",
    }))
    topbar.append(mk(pkg, {
        "text": "文章详情", "class": "android.widget.TextView",
        "bounds": "[400,58][680,118]",
    }))
    topbar.append(mk(pkg, {
        "clickable": "true", "focusable": "true",
        "content-desc": "更多",
        "bounds": "[912,0][1080,176]",
    }))
    root.append(topbar)

    # Bottom action bar
    bottombar = mk(pkg, {"bounds": "[0,2200][1080,2400]"})
    bottombar.append(mk(pkg, {
        "text": "写评论...", "class": "android.widget.EditText",
        "clickable": "true", "focusable": "true",
        "bounds": "[48,2230][800,2370]",
    }))
    for i, (label, _) in enumerate([("点赞", ""), ("收藏", ""), ("分享", "")]):
        x = 820 + i * 86
        bottombar.append(mk(pkg, {
            "content-desc": label,
            "clickable": "true", "focusable": "true",
            "class": "android.widget.Button",
            "bounds": fmt_bounds(x, 2230, x + 80, 2370),
        }))
    root.append(bottombar)

    write_xml(root, META / "ui2.xml")
    total_nodes = sum(1 for _ in root.iter("node"))
    print(f"  ui2.xml: {total_nodes} nodes, article+5 comments+actions")
    return total_nodes


# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("🔧 Generating complex XML variants...")
    n1 = gen_wd3()
    n2 = gen_wd4()
    n3 = gen_ui2()
    print(f"\n✅ Generated 3 complex XML files ({n1 + n2 + n3} total nodes)")
    print("   wd3.xml - Play Store search with 5 install buttons")
    print("   wd4.xml - Settings page with 18 items + 3 switches")
    print("   ui2.xml - News article with comments and nested replies")


if __name__ == "__main__":
    main()
