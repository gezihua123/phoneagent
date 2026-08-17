#!/usr/bin/env python3
"""大样本 Plan 分解对比：fastaget vs Claude-Code-style，30+ 用例。"""
import sys, json, textwrap
sys.path.insert(0, '.')

from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate

# ── 30+ 测试用例，覆盖 6 大类 ──
CASES = [
    # 应用安装
    ("install_1",  "打开 Google Play，安装小红书"),
    ("install_2",  "打开应用商店，安装微信"),
    ("install_3",  "打开华为应用市场，下载抖音"),
    ("install_4",  "打开 Play 商店，更新已安装的应用"),

    # 开关控制
    ("toggle_1",   "打开设置，关闭蓝牙"),
    ("toggle_2",   "打开快捷设置，开启飞行模式"),
    ("toggle_3",   "打开设置，开启WiFi"),
    ("toggle_4",   "打开设置，关闭NFC"),
    ("toggle_5",   "打开设置，开启手电筒"),

    # 消息发送
    ("msg_1",      "打开微信，发送你好给张三"),
    ("msg_2",      "打开短信，给10086发送查询流量"),
    ("msg_3",      "打开微信，发送图片给李四"),
    ("msg_4",      "打开QQ，发送文件给王五"),

    # 内容浏览
    ("browse_1",   "打开日历，查看今天日程"),
    ("browse_2",   "打开相册，查看最近一张照片"),
    ("browse_3",   "打开文件管理，查看下载文件夹"),
    ("browse_4",   "打开浏览器，查看浏览历史"),
    ("browse_5",   "打开设置，查看存储空间使用情况"),

    # 导航
    ("nav_1",      "打开地图，导航到天安门"),
    ("nav_2",      "打开高德地图，搜索最近的加油站"),
    ("nav_3",      "打开地图，查看实时路况"),

    # 媒体
    ("media_1",    "打开相机，拍一张照片"),
    ("media_2",    "打开相机，切换到视频模式开始录制"),
    ("media_3",    "打开网易云音乐，播放每日推荐"),
    ("media_4",    "打开抖音，点赞第一条视频"),
    ("media_5",    "打开相册，删除最近一张照片"),

    # 系统设置
    ("sys_1",      "打开设置，查看电池使用情况"),
    ("sys_2",      "打开设置，修改屏幕超时为5分钟"),
    ("sys_3",      "打开设置，查看已安装应用列表"),
    ("sys_4",      "打开设置，卸载微信"),
    ("sys_5",      "打开设置，清除浏览器缓存"),
]

FA_PROMPT = (
    "你是一个手机自动化 Agent。将目标分解为 3-5 个中间状态。\n"
    "每个状态是从上一状态到目标终点的必经点。\n"
    "只描述界面状态，不描述动作、工具或方法。\n"
    "不要写初始条件（如'设备已解锁''处于桌面'），从第一个操作后的状态开始。\n"
    "格式：子目标N：<当前应处于什么界面状态>"
)

CC_SYS = (
    "你是一个操控 Android 手机的自动化测试 Agent。\n\n"
    "## 任务拆解\n"
    "将用户目标分解为子任务。每个子任务描述一个要达成的中间状态。\n"
    "只描述状态，不描述具体的工具调用、坐标或编号。"
)

def score_decomposition(text: str) -> dict:
    """对分解质量打分。"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # 去掉 "好的"/"已拆解" 等前缀行
    clean = [l for l in lines if not l.startswith(("好的", "已拆", "根据", "我将", "{" , "}"))]
    clean = [l for l in clean if len(l) > 5]

    issues = []
    score = 10

    # 1. 行数检查 (3-5 最优)
    n = len(clean)
    if n < 2:   score -= 3; issues.append("too_few")
    elif n > 6: score -= 2; issues.append("too_many")

    # 2. 动作动词检查（不应有"点击""输入""打开"）
    action_words = ["点击", "输入", "按下", "滑动", "tap", "type", "swipe", "launch"]
    for l in clean:
        for w in action_words:
            if w in l:
                score -= 1
                issues.append(f"action_word:{w}")
                break

    # 3. 前置条件检查
    precond_words = ["解锁", "主屏幕", "桌面可见", "设备已"]
    for l in clean[:1]:  # 只检查第一行
        for w in precond_words:
            if w in l:
                score -= 1
                issues.append(f"precond:{w}")
                break

    # 4. 工具名检查
    tool_names = ["launch", "tap_element", "check_package", "observe"]
    for l in clean:
        for t in tool_names:
            if t in l:
                score -= 2
                issues.append(f"tool:{t}")
                break

    return {"score": max(0, score), "lines": n, "issues": issues}

def run():
    llm = AnthropicHTTPDelegate(
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com/anthropic",
        token=os.environ["ANTHROPIC_AUTH_TOKEN"],
    )

    results = []
    for tag, goal in CASES:
        fa_msgs = [{"role": "user", "content": [{"type": "text", "text": goal}]}]
        cc_msgs = [{"role": "user", "content": [{"type": "text", "text": goal}]}]

        fa_resp = llm.complete(FA_PROMPT, fa_msgs, [], vision=False)
        cc_resp = llm.complete(CC_SYS, cc_msgs, [], vision=False)

        fa_score = score_decomposition(fa_resp.text)
        cc_score = score_decomposition(cc_resp.text)

        results.append({
            "tag": tag, "goal": goal,
            "fa": {"text": fa_resp.text.strip(), **fa_score},
            "cc": {"text": cc_resp.text.strip(), **cc_score},
        })

    # ── 排名表 ──
    print(f"{'#':<3} {'Case':<30} {'goal':<45} {'FA':>3} {'CC':>3} {'Δ':>4}")
    print("-" * 95)
    for i, r in enumerate(results, 1):
        tag = r["tag"]
        goal = r["goal"][:43]
        fa_s = r["fa"]["score"]
        cc_s = r["cc"]["score"]
        delta = fa_s - cc_s
        bar = "◆" if delta > 0 else ("◇" if delta < 0 else "=")
        print(f"{i:<3} {tag:<30} {goal:<45} {fa_s:>3} {cc_s:>3} {delta:>+4} {bar}")

    # ── 统计 ──
    fa_scores = [r["fa"]["score"] for r in results]
    cc_scores = [r["cc"]["score"] for r in results]
    fa_lines = [r["fa"]["lines"] for r in results]
    cc_lines = [r["cc"]["lines"] for r in results]

    print(f"\n{'='*60}")
    print(f"{'Metric':<20} {'fastaget':>12} {'CC-style':>12}")
    print(f"{'-'*44}")
    print(f"{'Avg Score':<20} {sum(fa_scores)/len(fa_scores):>12.1f} {sum(cc_scores)/len(cc_scores):>12.1f}")
    print(f"{'Avg Lines':<20} {sum(fa_lines)/len(fa_lines):>12.1f} {sum(cc_lines)/len(cc_lines):>12.1f}")
    print(f"{'Score >=8':<20} {sum(1 for s in fa_scores if s>=8):>12} {sum(1 for s in cc_scores if s>=8):>12}")
    print(f"{'Score <=5':<20} {sum(1 for s in fa_scores if s<=5):>12} {sum(1 for s in cc_scores if s<=5):>12}")

    # ── 常见问题 ──
    fa_issues = {}
    cc_issues = {}
    for r in results:
        for iss in r["fa"]["issues"]:
            fa_issues[iss] = fa_issues.get(iss, 0) + 1
        for iss in r["cc"]["issues"]:
            cc_issues[iss] = cc_issues.get(iss, 0) + 1

    print(f"\n{'Issue':<25} {'FA':>5} {'CC':>5}")
    print(f"{'-'*35}")
    for iss in sorted(set(list(fa_issues) + list(cc_issues))):
        print(f"{iss:<25} {fa_issues.get(iss,0):>5} {cc_issues.get(iss,0):>5}")

    # ── 逐条详情 ──
    print(f"\n{'='*70}")
    print("逐条详情")
    print(f"{'='*70}")
    for r in results:
        print(f"\n{'─'*50}")
        print(f"【{r['tag']}】{r['goal']}")
        print(f"{'─'*50}")
        fa = r["fa"]
        cc = r["cc"]
        print(f"  FA [{fa['score']}分 {fa['lines']}行]:")
        print(textwrap.indent(fa['text'], "    "))
        print(f"  CC [{cc['score']}分 {cc['lines']}行]:")
        print(textwrap.indent(cc['text'], "    "))

    llm.close()

if __name__ == "__main__":
    run()
