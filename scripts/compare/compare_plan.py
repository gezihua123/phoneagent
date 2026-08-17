#!/usr/bin/env python3
"""对比 fastaget plan 分解 vs Claude Code 分解样式，仅分析不执行。"""
import sys, textwrap
sys.path.insert(0, '.')

from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate

# ── Claude Code 的 style reference ──
# install_rednote.md 中的分解：
CLAUDE_PLAN_STYLE = """Claude Code Phase 0 特征:
  1. 4行子任务，不超5行
  2. 每个是状态描述（"启动Google Play"而非"点击图标"）
  3. 不指定工具名、不指定index
  4. 不用括号、不用解释
  5. 粒度：一次有意义的页面跳转=一个子任务"""

# ── 测试用例 ──
TEST_CASES = [
    ("install",  "打开 Google Play，安装小红书"),
    ("toggle",   "打开设置，关闭蓝牙"),
    ("send_msg", "打开微信，发送你好给张三"),
    ("photo",    "打开相机，拍一张照片"),
    ("calendar", "打开日历，查看今天日程"),
    ("wifi",     "打开设置，连接WiFi名为Office的网络"),
    ("uninstall","打开设置，卸载微信"),
    ("navigate", "打开地图，导航到天安门"),
    ("music",    "打开网易云音乐，播放每日推荐"),
    ("mail",     "打开邮件，查看最新未读邮件"),
]

def run():
    llm = AnthropicHTTPDelegate(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/anthropic",
        token=os.environ["ANTHROPIC_AUTH_TOKEN"],
    )

    # fastaget 当前 plan prompt（来自 _generate_plan）
    FA_PLAN = (
        "将目标分解为 3-5 个中间状态。每个状态是从上一状态到目标终点的必经点。\n"
        "只描述状态，不描述动作、工具或方法。\n"
        "不要写初始条件（如'设备已解锁''处于桌面'），从第一个实际操作后的状态开始。\n"
        "格式：子目标N：<当前应处于什么状态>"
    )

    # Claude Code 风格 simulation——更接近 CC 原始 system prompt 效果
    CC_SIM = (
        "你是一个操控 Android 手机的自动化测试 Agent。\n\n"
        "## 任务拆解\n"
        "将用户目标分解为 3-4 个子任务。每个子任务描述一个要达成的中间状态。\n"
        "只描述状态，不描述具体的工具调用、坐标或编号。"
    )

    print("=" * 70)
    print("fastaget plan prompt vs Claude-Code-style plan prompt")
    print("=" * 70)

    for tag, goal in TEST_CASES:
        print(f"\n{'─' * 60}")
        print(f"【{tag}】{goal}")
        print(f"{'─' * 60}")

        # fastaget plan
        fa_msgs = [{"role": "user", "content": [{"type": "text", "text": goal}]}]
        fa_resp = llm.complete(FA_PLAN, fa_msgs, [], vision=False)
        fa_text = fa_resp.text.strip()

        # Claude-Code-style plan
        cc_msgs = [{"role": "user", "content": [{"type": "text", "text": goal}]}]
        cc_resp = llm.complete(CC_SIM, cc_msgs, [], vision=False)
        cc_text = cc_resp.text.strip()

        print(f"\n  fastaget:\n{textwrap.indent(fa_text, '    ')}")
        print(f"\n  Claude-Code-style:\n{textwrap.indent(cc_text, '    ')}")

        fa_lines = [l.strip() for l in fa_text.split("\n") if l.strip()]
        cc_lines = [l.strip() for l in cc_text.split("\n") if l.strip()]
        print(f"\n  → fastaget: {len(fa_lines)} 行 | CC-style: {len(cc_lines)} 行")

    # ── 汇总对比 ──
    print(f"\n{'=' * 70}")
    print("汇总")
    print(f"{'=' * 70}")
    print(f"fastaget prompt ({len(FA_PLAN)} chars):")
    print(textwrap.indent(FA_PLAN, "  "))
    print(f"\nClaude-Code-style prompt ({len(CC_SIM)} chars):")
    print(textwrap.indent(CC_SIM, "  "))
    print(f"\n{CLAUDE_PLAN_STYLE}")

    llm.close()

if __name__ == "__main__":
    run()
