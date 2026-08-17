#!/usr/bin/env python3
"""Evaluate how well different UI-hierarchy formats let an LLM locate elements.

For each XML dump and each converted format (yml, jsonl, flattext, simplexml,
flatref), we ask the LLM tricky-but-precise questions and check whether the
returned bounds match the ground truth parsed from the original XML.

Usage::

    export DEEPSEEK_API_KEY=sk-xxx
    python3 eval_formats.py
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import string
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ---------------------------------------------------------------------------
# Ground-truth questions
# ---------------------------------------------------------------------------


@dataclass
class Question:
    file_stem: str
    question: str
    match_text: str = ""
    match_desc: str = ""
    match_id: str = ""
    use_clickable_parent: bool = False
    pick_last: bool = False  # when multiple matches, pick the one with largest top
    match_index: int = 0  # 1-based: pick the Nth match (0 = disabled)
    note: str = ""


QUESTIONS: List[Question] = [
    # ── wd.xml: Google Play Store (99 nodes) ─────────────────────────────
    Question(
        file_stem="wd",
        question="我想安装小红书，找到小红书应用卡片整体可点击的区域，返回bounds",
        match_desc="小红书",
        use_clickable_parent=True,
        note="desc含'已安装'非'安装'，需理解卡片整体可点击",
    ),
    Question(
        file_stem="wd",
        question="找到语音搜索按钮的可点击位置，返回bounds",
        match_desc="语音搜索",
        use_clickable_parent=True,
        note="语音搜索是desc不是text，嵌套在View里",
    ),
    Question(
        file_stem="wd",
        question="找到搜索输入框的位置，返回bounds",
        match_text="搜索应用和游戏",
        use_clickable_parent=True,
        note="搜索框是EditText，hint文字在子TextView里",
    ),
    Question(
        file_stem="wd",
        question="找到'为您推荐'这个标题文字的位置，返回bounds",
        match_text="为您推荐",
        note="页面上有多个标题，需精确匹配",
    ),
    Question(
        file_stem="wd",
        question="找到'最近的搜索'这个区域标题的位置，返回bounds",
        match_text="最近的搜索",
        note="需区分其他标题",
    ),

    # ── ui.xml: Chrome on Google Groups (65 nodes) ───────────────────────
    Question(
        file_stem="ui",
        question="我想加入这个Google群组，找到'加入群组'按钮的位置，返回bounds",
        match_desc="加入群组",
        note="按钮通过desc标识",
    ),
    Question(
        file_stem="ui",
        question="我想举报这个群组，找到'举报'按钮的位置，返回bounds",
        match_desc="举报",
        note="举报按钮在页面右上角",
    ),
    Question(
        file_stem="ui",
        question="找到Chrome浏览器地址栏（显示URL的输入框）的位置，返回bounds",
        match_id="com.android.chrome:id/url_bar",
        note="需通过resource-id定位",
    ),
    Question(
        file_stem="ui",
        question="找到Chrome浏览器的主页按钮位置，返回bounds",
        match_id="com.android.chrome:id/home_button",
        note="通过resource-id定位",
    ),
    Question(
        file_stem="ui",
        question="找到显示'目前没有任何对话'这段文字的元素位置，返回bounds",
        match_text="目前没有任何对话",
        note="文字在WebView深处",
    ),

    # ── ui_dump.xml: Fortune app history (42 nodes) ──────────────────────
    Question(
        file_stem="ui_dump",
        question="找到第二条历史记录中'姻缘'对应的分数数字的位置，返回bounds",
        match_text="75",
        note="需区分第一二条记录，75是第二行姻缘分",
    ),
    Question(
        file_stem="ui_dump",
        question="找到第一条历史记录中'事业'对应的分数数字的位置，返回bounds",
        match_text="26",
        note="26是第一行事业分",
    ),
    Question(
        file_stem="ui_dump",
        question="找到第一条记录中'学业'对应的分数数字的位置，返回bounds",
        match_text="32",
        note="32是第一行学业分",
    ),
    Question(
        file_stem="ui_dump",
        question="找到页面标题'历史记录'的位置，返回bounds",
        match_text="历史记录",
        note="基准题",
    ),
    Question(
        file_stem="ui_dump",
        question="找到第二条历史记录的出生日期文字的位置，返回bounds",
        match_text="出生：1990-01-01",
        pick_last=True,
        note="两条记录有相同文字，需找第二条",
    ),

    # ── window_dump.xml: Fortune reading page (50 nodes) ─────────────────
    Question(
        file_stem="window_dump",
        question="我想返回上一页，找到返回按钮的位置，返回bounds",
        match_desc="返回",
        note="返回按钮通过desc标识",
    ),
    Question(
        file_stem="window_dump",
        question="我想保存当前页面到相册，找到保存按钮的位置，返回bounds",
        match_desc="保存到相册",
        note="保存按钮在右上角",
    ),
    Question(
        file_stem="window_dump",
        question="在五行分布中，找到'金'这个文字元素的位置，返回bounds",
        match_text="金",
        note="只有一个'金'字",
    ),
    Question(
        file_stem="window_dump",
        question="在五行分布中，找到'金'对应的百分比数值的位置，返回bounds",
        match_text="0%",
        note="金的百分比是0%",
    ),
    Question(
        file_stem="window_dump",
        question="找到'四柱八字'这个标题文字的位置，返回bounds",
        match_text="四柱八字",
        note="页面有两个'命理解读'但'四柱八字'只有一个",
    ),

    # ── wd2.xml: Google Play search result (xiaohongshu + Lemon8) ──────
    Question(
        file_stem="wd2",
        question="我想下载那个生活兴趣社区app，返回下载按钮的位置",
        match_desc="安装",
        use_clickable_parent=True,
        match_index=1,
        note="模糊描述，3个安装按钮交替排列，需理解'生活兴趣社区'是小红书第1个",
    ),
    Question(
        file_stem="wd2",
        question="那个分享生活方式的app怎么下载，找一下",
        match_desc="安装",
        use_clickable_parent=True,
        match_index=2,
        note="模糊描述，需理解'分享生活方式'对应Lemon8标签，选第2个",
    ),
    Question(
        file_stem="wd2",
        question="我搜的是什么词来着，找一下搜索记录",
        match_text="xiaohongshu",
        note="模糊描述，需理解顶部文字是搜索关键词",
    ),

    # ── wd3.xml: Play Store search "社交" → 5 app cards (79 nodes) ─────
    # 5 identical "安装" buttons — extreme ambiguity
    Question(
        file_stem="wd3",
        question="页面有5个应用的安装按钮，找到第1个小红书应用的安装按钮可点击区域，返回bounds",
        match_desc="安装",
        use_clickable_parent=True,
        match_index=1,
        note="5个安装按钮中选第1个(小红书)，极高歧义",
    ),
    Question(
        file_stem="wd3",
        question="找到第3个应用Lemon8的安装按钮可点击区域，返回bounds",
        match_desc="安装",
        use_clickable_parent=True,
        match_index=3,
        note="5个安装按钮中选第3个(Lemon8)，需计数定位",
    ),
    Question(
        file_stem="wd3",
        question="找到最后一个应用Instagram的安装按钮可点击区域，返回bounds",
        match_desc="安装",
        use_clickable_parent=True,
        pick_last=True,
        note="5个安装按钮中选最后一个(Instagram)",
    ),
    Question(
        file_stem="wd3",
        question="找到TikTok应用的评价信息区域（显示评分和评价数量），返回bounds",
        match_desc="有 500万 条评价",
        note="5个应用各有评价信息，需根据500万定位TikTok",
    ),
    Question(
        file_stem="wd3",
        question="找到微博应用的标签文字'随时随地发现新鲜事'的位置，返回bounds",
        match_text="随时随地发现新鲜事",
        note="5个应用各有不同标签文字，需精确匹配微博的",
    ),
    Question(
        file_stem="wd3",
        question="找到页面顶部的语音搜索按钮可点击位置，返回bounds",
        match_desc="语音搜索",
        use_clickable_parent=True,
        note="顶部搜索栏右侧，需区分文字搜索",
    ),

    # ── wd4.xml: System Settings page (132 nodes, 18 items) ───────────
    # Many similar list items + switches
    Question(
        file_stem="wd4",
        question="找到蓝牙设置的开关按钮位置（当前已开启），返回bounds",
        match_desc="蓝牙开关",
        note="18个设置项中3个有开关，需精确定位蓝牙开关",
    ),
    Question(
        file_stem="wd4",
        question="找到位置信息的开关按钮位置（当前已开启），返回bounds",
        match_desc="位置信息开关",
        note="需区分蓝牙开关和位置信息开关",
    ),
    Question(
        file_stem="wd4",
        question="找到'电池'设置项的标题文字位置，返回bounds",
        match_text="电池",
        note="18个设置项标题之一，需精确匹配",
    ),
    Question(
        file_stem="wd4",
        question="找到'关于手机'设置项的标题文字位置，返回bounds",
        match_text="关于手机",
        note="列表最后一项",
    ),
    Question(
        file_stem="wd4",
        question="我想返回上一页，找到返回按钮的可点击位置，返回bounds",
        match_desc="返回",
        use_clickable_parent=True,
        note="左上角返回按钮",
    ),
    Question(
        file_stem="wd4",
        question="找到搜索设置的按钮位置，返回bounds",
        match_desc="搜索设置",
        use_clickable_parent=True,
        note="右上角搜索按钮",
    ),
    Question(
        file_stem="wd4",
        question="找到'存储'设置项的摘要文字（显示已用空间）的位置，返回bounds",
        match_text="已使用 128 GB / 256 GB",
        note="需通过摘要文字定位特定设置项",
    ),

    # ── ui2.xml: News article + comments (58 nodes) ───────────────────
    # Nested content, multiple similar action buttons, comments with replies
    Question(
        file_stem="ui2",
        question="找到这篇文章的标题位置，返回bounds",
        match_text="2024年最值得关注的10款AI工具：从代码生成到图像创作",
        note="长标题，需精确匹配完整文字",
    ),
    Question(
        file_stem="ui2",
        question="找到关注作者按钮的位置，返回bounds",
        match_text="关注",
        use_clickable_parent=True,
        note="关注按钮在作者信息右侧",
    ),
    Question(
        file_stem="ui2",
        question="找到第一条评论的点赞按钮位置（给用户_科技爱好者的评论点赞），返回bounds",
        match_desc="给用户_科技爱好者的评论点赞",
        use_clickable_parent=True,
        note="5条评论各有点赞按钮，需定位第一条评论的",
    ),
    Question(
        file_stem="ui2",
        question="找到文章中的配图位置（AI工具对比图表），返回bounds",
        match_desc="AI工具对比图表",
        note="文章中间的图片占位符",
    ),
    Question(
        file_stem="ui2",
        question="我想返回上一页，找到返回按钮的可点击位置，返回bounds",
        match_desc="返回",
        use_clickable_parent=True,
        note="顶部导航栏左侧",
    ),
    Question(
        file_stem="ui2",
        question="找到评论区中'用户_设计师小王'发布的评论文字位置，返回bounds",
        match_text="作为一个设计师，我每天都在用Midjourney和Stable Diffusion。两者各有优势，Midjourney的艺术感更强，SD的可控性更好。",
        note="5条评论之一，需根据用户名定位对应评论内容",
    ),
]


# ---------------------------------------------------------------------------
# Ground-truth extraction
# ---------------------------------------------------------------------------


def _parse_bool(val: str) -> bool:
    return val.strip().lower() == "true"


def _all_nodes(root: ET.Element) -> List[Tuple[ET.Element, List[ET.Element]]]:
    result: List[Tuple[ET.Element, List[ET.Element]]] = []

    def walk(elem: ET.Element, ancestors: List[ET.Element]) -> None:
        if elem.tag == "node":
            result.append((elem, ancestors[:]))
        for child in elem:
            walk(child, ancestors + [elem])

    walk(root, [])
    return result


def find_ground_truth(
    xml_path: Path, q: Question
) -> Optional[Tuple[int, int, int, int]]:
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    nodes = _all_nodes(root)

    matches: List[Tuple[ET.Element, List[ET.Element]]] = []
    for elem, ancestors in nodes:
        text = elem.get("text", "")
        desc = elem.get("content-desc", "")
        rid = elem.get("resource-id", "")
        matched = False
        if q.match_text and q.match_text == text:
            matched = True
        if q.match_desc and q.match_desc in desc:
            matched = True
        if q.match_id and q.match_id == rid:
            matched = True
        if matched:
            matches.append((elem, ancestors))

    if not matches:
        return None

    if q.match_index and len(matches) >= q.match_index:
        # Pick the Nth match (1-based), sorted by vertical position
        def get_top(item):
            b = item[0].get("bounds", "[0,0][0,0]")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
            return int(m.group(2)) if m else 0
        matches.sort(key=get_top)
        elem, ancestors = matches[q.match_index - 1]
    elif len(matches) > 1 and q.pick_last:
        def get_top(item):
            b = item[0].get("bounds", "[0,0][0,0]")
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
            return int(m.group(2)) if m else 0
        matches.sort(key=get_top)
        elem, ancestors = matches[-1]
    else:
        elem, ancestors = matches[0]

    if q.use_clickable_parent:
        if not _parse_bool(elem.get("clickable", "false")):
            for ancestor in reversed(ancestors):
                if _parse_bool(ancestor.get("clickable", "false")):
                    elem = ancestor
                    break

    bounds_str = elem.get("bounds", "")
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


# ---------------------------------------------------------------------------
# Bounds matching
# ---------------------------------------------------------------------------


def parse_bounds_from_response(text: str) -> Optional[Tuple[int, int, int, int]]:
    m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", text)
    if m:
        return tuple(int(x) for x in m.groups())
    numbers = re.findall(r"\d+", text)
    if len(numbers) >= 4:
        return tuple(int(x) for x in numbers[:4])
    return None


def bounds_match(
    predicted: Tuple[int, int, int, int],
    ground_truth: Tuple[int, int, int, int],
    tolerance: int = 20,
) -> Tuple[bool, str]:
    if predicted == ground_truth:
        return True, "exact"
    pl, pt, pr, pb = predicted
    gl, gt, gr, gb = ground_truth
    if (abs(pl - gl) <= tolerance and abs(pt - gt) <= tolerance and
            abs(pr - gr) <= tolerance and abs(pb - gb) <= tolerance):
        return True, "near"
    pcx, pcy = (pl + pr) // 2, (pt + pb) // 2
    if gl <= pcx <= gr and gt <= pcy <= gb:
        return True, "center_in"
    gcx, gcy = (gl + gr) // 2, (gt + gb) // 2
    if pl <= gcx <= pr and pt <= gcy <= pb:
        return True, "contains_gt"
    return False, "miss"


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


PROMPT_TEMPLATE = """\
你是一个Android UI分析专家。下面是某个Android界面的UI层级数据，采用{format_name}格式表示。

--- UI数据开始 ---
{content}
--- UI数据结束 ---

问题：{question}

要求：仔细分析UI层级数据，找到问题所指的UI元素。返回该元素的bounds坐标，格式为 [left,top][right,bottom]。
注意：
1. 只返回bounds坐标，不要返回任何其他文字。
2. bounds格式示例：[0,322][1080,508]
3. 如果有多个匹配，请根据问题语境选择最合适的一个。

bounds："""

FORMAT_NAMES = {
    ".yml": "YAML",
    ".jsonl": "JSONL（扁平化，每行一个节点，含id/parent/depth）",
    ".flattext": "缩进文本（phonefast风格）",
    ".simplexml": "简化XML（只保留有意义属性）",
    ".flatref": "扁平文本带引用（#id parent=#M depth=D）",
    ".compact": "紧凑格式（过滤噪声节点+折叠壳链+单字符标记）",
}


async def call_llm(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    api_key: str,
    messages: List[Dict[str, str]],
) -> Tuple[str, Dict[str, int]]:
    """Call LLM, return (content, usage_dict).

    usage_dict has keys: prompt_tokens, completion_tokens, total_tokens.
    Missing keys default to 0.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = await client.post(
        f"{base_url}/chat/completions",
        json={"model": model, "messages": messages,
              "stream": False, "temperature": 0.0},
        headers=headers, timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def _gen_nonce(n: int = 16) -> str:
    """Generate a random alphanumeric nonce to bust API prompt caching."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(n))


# Approximate token overhead added by cache-busting nonce per call.
# Measured: "<!-- ref:16chars -->" ≈ 8 tokens, "[sid:8chars]" ≈ 4 tokens,
# plus structural tokens ≈ 5. Total ≈ 17.
NONCE_TOKEN_OVERHEAD = 17


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass
class QResult:
    question: Question
    fmt: str
    predicted: Optional[Tuple[int, int, int, int]]
    gt: Tuple[int, int, int, int]
    correct: bool
    match_type: str
    raw: str
    duration: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


async def eval_one(
    client, base_url, model, api_key, q, fmt, content, gt, sem,
) -> QResult:
    async with sem:
        # Inject nonce to bust API prompt caching — content is NOT modified,
        # so the question↔input mapping stays strictly correct.
        nonce = _gen_nonce()
        prompt = PROMPT_TEMPLATE.format(
            format_name=FORMAT_NAMES.get(fmt, fmt),
            content=content, question=q.question,
        )
        prompt += f"\n<!-- ref:{nonce} -->"
        messages = [
            {"role": "system",
             "content": f"你是一个精确的Android UI元素定位助手。[sid:{_gen_nonce(8)}]"},
            {"role": "user", "content": prompt},
        ]
        start = time.monotonic()
        ptoks = ctoks = ttoks = 0
        try:
            resp, usage = await call_llm(client, base_url, model, api_key, messages)
            ptoks = usage["prompt_tokens"]
            ctoks = usage["completion_tokens"]
            ttoks = usage["total_tokens"]
            # Subtract nonce overhead so token stats reflect real content size
            ptoks = max(0, ptoks - NONCE_TOKEN_OVERHEAD)
            ttoks = max(0, ttoks - NONCE_TOKEN_OVERHEAD)
        except Exception as e:
            resp = f"ERROR: {e}"
        dur = time.monotonic() - start
        pred = parse_bounds_from_response(resp)
        if pred is None:
            correct, mt = False, "parse_fail"
        else:
            correct, mt = bounds_match(pred, gt)
        return QResult(q, fmt, pred, gt, correct, mt, resp.strip()[:200], dur,
                       ptoks, ctoks, ttoks)


async def run_eval(
    base_url, model, api_key, meta_dir, formats, questions, concurrency=5,
    shuffle_order=True,
):
    tasks = []
    sem = asyncio.Semaphore(concurrency)

    # Build all (question, format, content, gt) tuples.
    # Content is read as-is — never modified — so question↔input
    # mapping stays strictly correct for fair evaluation.
    pairs = []
    for q in questions:
        xml_path = meta_dir / f"{q.file_stem}.xml"
        gt = find_ground_truth(xml_path, q)
        if gt is None:
            print(f"  ⚠️  GT not found: {q.question[:60]}")
            continue
        for fmt in formats:
            fp = meta_dir / f"{q.file_stem}{fmt}"
            if not fp.exists():
                print(f"  ⚠️  Missing: {fp}")
                continue
            content = fp.read_text(encoding="utf-8")
            pairs.append((q, fmt, content, gt))

    # Shuffle execution order to avoid consecutive calls with similar
    # content hitting DeepSeek's prefix-cache. This only changes *when*
    # a pair runs, not *what* content it sees.
    if shuffle_order:
        random.shuffle(pairs)

    async with httpx.AsyncClient() as client:
        for q, fmt, content, gt in pairs:
            tasks.append(asyncio.create_task(
                eval_one(client, base_url, model, api_key,
                         q, fmt, content, gt, sem)
            ))
        total = len(tasks)
        print(f"🚀 {total} evaluations ({len(questions)} questions × "
              f"{len(formats)} formats) | model={model}")
        print("=" * 70)
        results = []
        done = 0
        for coro in asyncio.as_completed(tasks):
            r = await coro
            results.append(r)
            done += 1
            icon = "✅" if r.correct else "❌"
            gt_s = f"[{r.gt[0]},{r.gt[1]}][{r.gt[2]},{r.gt[3]}]"
            pr_s = (f"[{r.predicted[0]},{r.predicted[1]}]"
                    f"[{r.predicted[2]},{r.predicted[3]}]"
                    if r.predicted else "None")
            print(f"  [{done:3d}/{total}] {icon} {r.fmt:12s} "
                  f"GT={gt_s:25s} Pred={pr_s:25s} ({r.match_type}) "
                  f"| {r.question.question[:35]}")
        return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(results, formats):
    print("\n" + "=" * 110)
    print("  📊 FORMAT ACCURACY & TOKEN REPORT")
    print("=" * 110)

    # Strict = exact only; Precise = exact + near; Loose = all non-miss
    STRICT_TYPES = {"exact"}
    PRECISE_TYPES = {"exact", "near"}

    print(f"\n{'Format':<14} {'Strict':>7} {'Precise':>8} {'Loose':>7} "
          f"{'Total':>6} {'AvgTime':>8} {'AvgPrompt':>10} {'AvgCompl':>9} {'AvgTotal':>9}  Match Types")
    print("-" * 110)

    stats = {}
    for fmt in formats:
        fr = [r for r in results if r.fmt == fmt]
        if not fr:
            continue
        strict = sum(1 for r in fr if r.match_type in STRICT_TYPES)
        precise = sum(1 for r in fr if r.match_type in PRECISE_TYPES)
        loose = sum(1 for r in fr if r.correct)
        total = len(fr)
        s_acc = strict / total * 100 if total else 0
        p_acc = precise / total * 100 if total else 0
        l_acc = loose / total * 100 if total else 0
        avg_t = sum(r.duration for r in fr) / total
        avg_pt = sum(r.prompt_tokens for r in fr) / total
        avg_ct = sum(r.completion_tokens for r in fr) / total
        avg_tt = sum(r.total_tokens for r in fr) / total
        mts = {}
        for r in fr:
            mts[r.match_type] = mts.get(r.match_type, 0) + 1
        mt_s = ", ".join(f"{k}:{v}" for k, v in sorted(mts.items()))
        stats[fmt] = {"strict": strict, "precise": precise, "loose": loose,
                      "total": total, "s_acc": s_acc, "p_acc": p_acc,
                      "l_acc": l_acc,
                      "avg_pt": avg_pt, "avg_ct": avg_ct, "avg_tt": avg_tt}
        print(f"{fmt:<14} {s_acc:>6.1f}% {p_acc:>7.1f}% {l_acc:>6.1f}% "
              f"{total:>6} {avg_t:>7.1f}s {avg_pt:>10.0f} {avg_ct:>9.0f} {avg_tt:>9.0f}  {mt_s}")

    # Per-question (show strict / loose)
    print(f"\n{'Question':<50} {'Strict':>7}/{' Loose':>7}/{' Total':>6}")
    print("-" * 78)
    stems = sorted(set(r.question.file_stem for r in results))
    for fs in stems:
        fr = [r for r in results if r.question.file_stem == fs]
        qts = sorted(set(r.question.question for r in fr))
        print(f"\n  📄 {fs}.xml:")
        for qt in qts:
            qr = [r for r in fr if r.question.question == qt]
            sc = sum(1 for r in qr if r.match_type in STRICT_TYPES)
            lc = sum(1 for r in qr if r.correct)
            t = len(qr)
            icon = "✅" if sc == t else ("🔹" if lc == t else ("⚠️" if lc > 0 else "❌"))
            print(f"    {icon} {qt[:47]:<48} {sc}/{lc}/{t}")

    tsc = sum(1 for r in results if r.match_type in STRICT_TYPES)
    tpc = sum(1 for r in results if r.match_type in PRECISE_TYPES)
    tlc = sum(1 for r in results if r.correct)
    total = len(results)
    print(f"\n{'─' * 78}")
    print(f"  Overall Strict (exact only):  {tsc}/{total} = {tsc/total*100:.1f}%")
    print(f"  Overall Precise (±20px):      {tpc}/{total} = {tpc/total*100:.1f}%")
    print(f"  Overall Loose (any overlap):  {tlc}/{total} = {tlc/total*100:.1f}%")

    # Token summary
    print(f"\n{'─' * 100}")
    print("  💰 TOKEN CONSUMPTION SUMMARY")
    print(f"{'─' * 100}")
    print(f"\n  {'Format':<14} {'TotalPrompt':>12} {'TotalCompl':>12} {'TotalTokens':>12} "
          f"{'AvgPrompt':>10} {'AvgCompl':>9} {'AvgTotal':>9}")
    print("  " + "-" * 98)
    for fmt in formats:
        fr = [r for r in results if r.fmt == fmt]
        if not fr:
            continue
        s = stats[fmt]
        tot_pt = sum(r.prompt_tokens for r in fr)
        tot_ct = sum(r.completion_tokens for r in fr)
        tot_tt = sum(r.total_tokens for r in fr)
        print(f"  {fmt:<14} {tot_pt:>12,} {tot_ct:>12,} {tot_tt:>12,} "
              f"{s['avg_pt']:>10.0f} {s['avg_ct']:>9.0f} {s['avg_tt']:>9.0f}")

    grand_pt = sum(r.prompt_tokens for r in results)
    grand_ct = sum(r.completion_tokens for r in results)
    grand_tt = sum(r.total_tokens for r in results)
    print("  " + "-" * 98)
    print(f"  {'ALL':<14} {grand_pt:>12,} {grand_ct:>12,} {grand_tt:>12,}")

    print("\n  🏆 Format Ranking (by STRICT accuracy = exact only):")
    ranked = sorted(stats.items(), key=lambda x: -x[1]["s_acc"])
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣"]
    for i, (fmt, s) in enumerate(ranked):
        m = medals[min(i, 5)]
        print(f"    {m} {fmt:<14} strict {s['s_acc']:.1f}% ({s['strict']}/{s['total']})  "
              f"precise {s['p_acc']:.1f}%  loose {s['l_acc']:.1f}%  "
              f"avg {s['avg_tt']:.0f} tok")

    print("\n  💡 Token Efficiency Ranking (by avg total tokens):")
    token_ranked = sorted(stats.items(), key=lambda x: x[1]["avg_tt"])
    for i, (fmt, s) in enumerate(token_ranked):
        m = medals[min(i, 5)]
        print(f"    {m} {fmt:<14} {s['avg_tt']:.0f} tok/call  "
              f"(strict {s['s_acc']:.1f}% | precise {s['p_acc']:.1f}% | loose {s['l_acc']:.1f}%)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Evaluate UI hierarchy format accuracy with LLM."
    )
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--meta-dir",
                        default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--formats", nargs="+",
                        default=[".yml", ".jsonl", ".flattext",
                                 ".simplexml", ".flatref", ".compact"])
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--stems", nargs="+", default=None,
                        help="Only run questions for these file stems (e.g. wd2)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducible order shuffle (default: random)")
    parser.add_argument("--no-shuffle", action="store_true",
                        help="Disable execution order shuffle (may hit API cache)")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: set DEEPSEEK_API_KEY or use --api-key", file=sys.stderr)
        sys.exit(1)

    # Seed for reproducibility; default = random each run
    if args.seed is not None:
        random.seed(args.seed)
        seed_info = f" (seed={args.seed})"
    else:
        seed_info = f" (seed=random:{random.randint(0, 99999)})"
    shuffle_order = not args.no_shuffle

    meta_dir = Path(args.meta_dir).resolve()
    questions = list(QUESTIONS)
    if args.stems:
        questions = [q for q in questions if q.file_stem in args.stems]
    if args.quick:
        stems = sorted(set(q.file_stem for q in questions))
        questions = [q for fs in stems for q in
                     [x for x in questions if x.file_stem == fs][:2]]

    print(f"📁 Meta: {meta_dir}")
    print(f"🤖 Model: {args.model} @ {args.base_url}")
    print(f"🔑 Key: {api_key[:8]}...")
    print(f"📋 Formats: {args.formats}")
    print(f"❓ Questions: {len(questions)}")
    print(f"🎲 Order shuffle: {'ON' if shuffle_order else 'OFF'}{seed_info}")
    print(f"🔑 Nonce cache-bust: always ON")
    print()

    results = asyncio.run(run_eval(
        args.base_url, args.model, api_key, meta_dir,
        args.formats, questions, args.concurrency,
        shuffle_order=shuffle_order,
    ))
    print_report(results, args.formats)


if __name__ == "__main__":
    main()
