#!/usr/bin/env python3
"""Plan 分解对比：fastaget vs Claude-Code-style，仅分析不执行。"""
import sys, json, textwrap
sys.path.insert(0, '.')

from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate

# ── 测试用例 ──
CASES = [
    "打开 Google Play，安装小红书",
    "打开设置，关闭蓝牙",
    "打开微信，发送你好给张三",
    "打开设置，连接WiFi名为Office的网络",
    "打开日历，查看今天日程",
    "打开地图，导航到天安门",
    "打开相机，切换到视频模式，开始录制",
    "打开设置，查看电池使用情况",
    "打开浏览器，搜索天气",
    "打开相册，删除最近一张照片",
    "打开短信，给10086发送查询流量",
    "打开设置，卸载微信",
]

# ── 两个 prompt 对比 ──
FA_PROMPT = (
    "你是一个手机自动化 Agent。将目标分解为 3-5 个中间状态。\n"
    "每个状态是从上一状态到目标终点的必经点。\n"
    "只描述界面状态，不描述动作、工具或方法。\n"
    "不要写初始条件（如'设备已解锁''处于桌面'），从第一个操作后的状态开始。\n"
    "格式：子目标N：<当前应处于什么界面状态>"
)

CC_PROMPT = (
    "你是一个操控 Android 手机的自动化测试 Agent。\n\n"
    "## 任务拆解\n"
    "将用户目标分解为子任务。每个子任务描述一个要达成的中间状态。\n"
    "只描述状态，不描述具体的工具调用、坐标或编号。"
)

def run():
    llm = AnthropicHTTPDelegate(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/anthropic",
        token=os.environ["ANTHROPIC_AUTH_TOKEN"],
    )

    results = []
    for goal in CASES:
        fa_msgs = [{"role": "user", "content": [{"type": "text", "text": goal}]}]
        cc_msgs = [{"role": "user", "content": [{"type": "text", "text": goal}]}]

        fa_resp = llm.complete(FA_PROMPT, fa_msgs, [], vision=False)
        cc_resp = llm.complete(CC_PROMPT, cc_msgs, [], vision=False)

        fa_lines = [l.strip() for l in fa_resp.text.strip().split("\n") if l.strip()]
        cc_lines = [l.strip() for l in cc_resp.text.strip().split("\n") if l.strip()]

        results.append({
            "goal": goal,
            "fastaget": {"text": fa_resp.text.strip(), "lines": len(fa_lines)},
            "cc_style": {"text": cc_resp.text.strip(), "lines": len(cc_lines)},
        })

    # ── 汇总 ──
    print(f"{'Goal':<40} {'FA'} {'CC'}")
    print("-" * 50)
    for r in results:
        goal_short = r["goal"][:38]
        print(f"{goal_short:<40} {r['fastaget']['lines']:>2} {r['cc_style']['lines']:>2}")

    fa_total = sum(r["fastaget"]["lines"] for r in results)
    cc_total = sum(r["cc_style"]["lines"] for r in results)
    print(f"{'':-<50}")
    print(f"{'TOTAL':<40} {fa_total:>2} {cc_total:>2}")
    print(f"{'AVG':<40} {fa_total/len(results):.1f} {cc_total/len(results):.1f}")

    # ── 详细输出 ──
    print(f"\n{'='*60}")
    print("逐条对比")
    print(f"{'='*60}")
    for r in results:
        print(f"\n{'─'*50}")
        print(f"【{r['goal']}】")
        print(f"{'─'*50}")
        print(f"\n  fastaget ({r['fastaget']['lines']} 行):")
        print(textwrap.indent(r['fastaget']['text'], "    "))
        print(f"\n  CC-style ({r['cc_style']['lines']} 行):")
        print(textwrap.indent(r['cc_style']['text'], "    "))

    llm.close()

if __name__ == "__main__":
    run()
