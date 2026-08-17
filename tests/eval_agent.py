#!/usr/bin/env python3
"""用真实 LLM 驱动 FastAgent 跑自动化场景，评测成功率。

参照 eval_formats.py 的结构，但把「单次 LLM 调用定位元素」升级为
「FastAgent 完整 tool-calling 循环」，验证 agent 在真实模型下的端到端成功率。

评测维度（A/B 矩阵）：
  - prompt:  baseline (_SYSTEM_PROMPT) vs optimized (OPTIMIZED_SYSTEM_PROMPT)
  - format:  region / jsonl / flattext / compact / simplexml / flatref
  - variant: baseline / bt_off / loc_off / scrolled / truncated / noisy

成功标准：
  - tap_in_gt:  agent 的 tap 坐标落在 ground-truth bounds 内 + complete(success=True)
  - action_match: actions 日志含指定动作（如 back）+ complete(success=True)

Usage::

    # DeepSeek（OpenAI 兼容 API + function calling）
    export DEEPSEEK_API_KEY=sk-xxx
    python3 eval_agent.py --quick

    export ANTHROPIC_AUTH_TOKEN=xxx
    python3 eval_agent.py --delegate anthropic --quick

    # 完整矩阵（慢，~400 次 LLM 调用）
    python3 eval_agent.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# 确保项目根在 sys.path（tests/ → 项目根）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastaget.agent.fast_agent import FastAgent
from fastaget.agent.prompts import (
    OPTIMIZED_SYSTEM_PROMPT,
    SYSTEM_PROMPT as _SYSTEM_PROMPT,
)
from fastaget.device.uistate import Element, UIState
from fastaget.llm.delegate import LLMDelegate, LLMResponse, ToolCall
from fastaget.tools import build_registry

# 复用 tests/meta_infra.py 的共享基础设施（XML 转换器、变体生成器、MockPhonefast、场景定义）
from fastaget.scenariokit import (
    MockPhonefast,
    Scenario,
    Screen,
    WD4_XML,
    _build_scenarios,
    _find_clickable_ancestor,
    _find_node_by_desc,
    _find_node_by_text,
    _point_in_bounds,
    _resolve_gt_bounds,
    evaluate_scenario_outcome,
    load_device_graph,
    make_stateful_phonefast,
    make_variants,
    parse_meaningful_nodes,
    parse_meaningful_nodes_from_text,
    xml_to_phonefast_text,
)

import fastaget.device.uiprocessor as up_module


# ---------------------------------------------------------------------------
# 一、DeepSeek tool-calling delegate（OpenAI 兼容 API → LLMDelegate）
# ---------------------------------------------------------------------------


class DeepSeekToolDelegate(LLMDelegate):
    """DeepSeek OpenAI 兼容 API 的 tool-calling delegate。

    FastAgent 内部用 Anthropic 消息格式（content blocks），这里做一层转换：
      Anthropic messages → OpenAI messages → DeepSeek API → LLMResponse
    """

    def __init__(
        self,
        model: str = "deepseek-v4-flash",
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self._base_url = (
            base_url
            or os.environ.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com/v1"
        ).rstrip("/")
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._client = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0))

    @property
    def context_window(self) -> int:
        return 128_000

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        vision: bool = False,
        tool_choice: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")

        oai_messages = self._convert_messages(system, messages)
        oai_tools = self._convert_tools(tools)

        body: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "temperature": 0.0,
            "stream": False,
        }
        if oai_tools:
            body["tools"] = oai_tools
            body["tool_choice"] = self._map_tool_choice(tool_choice)

        try:
            resp = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code}: {e.response.text[:300]}")
        except httpx.RequestError as e:
            raise RuntimeError(f"HTTP request failed: {e}")

        return self._parse_response(resp.json())

    @staticmethod
    def _map_tool_choice(tc: dict[str, Any] | None) -> Any:
        """Anthropic tool_choice → OpenAI tool_choice 格式映射。"""
        if tc is None:
            return "auto"
        t = tc.get("type")
        if t == "any":
            return "required"
        if t == "tool":
            return {"type": "function", "function": {"name": tc.get("name", "")}}
        if t == "none":
            return "none"
        return "auto"

    def _convert_messages(
        self, system: str, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Anthropic 消息格式 → OpenAI 消息格式。"""
        oai: list[dict[str, Any]] = [{"role": "system", "content": system}]

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            # 纯文本消息
            if isinstance(content, str):
                oai.append({"role": role, "content": content})
                continue

            # content blocks 列表
            if role == "assistant":
                text_parts: list[str] = []
                tool_calls: list[dict] = []
                for block in content:
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(
                                    block.get("input", {}), ensure_ascii=False
                                ),
                            },
                        })
                oai_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": "\n".join(text_parts) if text_parts else None,
                }
                if tool_calls:
                    oai_msg["tool_calls"] = tool_calls
                oai.append(oai_msg)

            elif role == "user":
                # user content 可能含 text blocks 和 tool_result blocks
                for block in content:
                    btype = block.get("type")
                    if btype == "text":
                        oai.append({"role": "user", "content": block.get("text", "")})
                    elif btype == "tool_result":
                        oai.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": str(block.get("content", "")),
                        })
        return oai

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Anthropic tool definitions → OpenAI function definitions。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {
                        "type": "object", "properties": {},
                    }),
                },
            }
            for t in tools
        ]

    @staticmethod
    def _parse_response(data: dict) -> LLMResponse:
        """解析 OpenAI 响应 → LLMResponse。"""
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(text="(empty)", stop_reason="end_turn")
        choice = choices[0]
        message = choice.get("message", {})

        text = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []):
            fn = tc.get("function", {})
            args_str = fn.get("arguments", "{}")
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(
                name=fn.get("name", ""),
                input=args,
                id=tc.get("id", ""),
            ))

        finish = choice.get("finish_reason", "stop")
        stop_reason = "tool_use" if finish == "tool_calls" else "end_turn"

        # 成本估算（DeepSeek pricing ≈ $0.27/M input, $1.10/M output）
        cost = None
        usage = data.get("usage", {})
        if usage:
            inp = usage.get("prompt_tokens", 0)
            out = usage.get("completion_tokens", 0)
            cost = round(inp * 0.27 / 1e6 + out * 1.10 / 1e6, 6)

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            cost_usd=cost,
            raw=data,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()


# ---------------------------------------------------------------------------
# 二、UI 格式函数（UIState → LLM 可读文本）
# ---------------------------------------------------------------------------


def _compute_hierarchy(elements: list[Element]) -> tuple[dict[int, int | None], dict[int, int]]:
    """基于 bounds 包含关系计算每个元素的 parent 和 depth。"""
    parents: dict[int, int | None] = {}
    for e in elements:
        best_parent: int | None = None
        best_area = float("inf")
        for other in elements:
            if other.index == e.index:
                continue
            if other.contains(e):
                area = other.area()
                if area < best_area:
                    best_parent = other.index
                    best_area = area
        parents[e.index] = best_parent

    depths: dict[int, int] = {}

    def get_depth(idx: int) -> int:
        if idx in depths:
            return depths[idx]
        p = parents.get(idx)
        depths[idx] = 0 if p is None else get_depth(p) + 1
        return depths[idx]

    for e in elements:
        get_depth(e.index)
    return parents, depths


def _bstr(e: Element) -> str:
    return f"[{e.bounds[0]},{e.bounds[1]}][{e.bounds[2]},{e.bounds[3]}]"


def _flags(e: Element) -> str:
    """从 Element.flags 还原 phonefast 格式的标记文本。"""
    parts = []
    if e.clickable:
        parts.append("[clickable]")
    for flag in sorted(e.flags - {"clickable"}):
        parts.append(f"[{flag}]")
    return " ".join(parts)


def _label(e: Element) -> str:
    parts = []
    if e.text:
        parts.append(f'text="{e.text}"')
    if e.desc and e.desc != e.text:
        parts.append(f'desc="{e.desc}"')
    if e.id:
        parts.append(f'id="{e.id}"')
    return " ".join(parts)


def fmt_region(ui: UIState, max_elements: int = 60) -> str:
    """默认 UIProcessor 格式：顶部/中部/底部分区 + 父子缩进。"""
    # 直接委托给原 processor.format
    from fastaget.device.uiprocessor import UIProcessor
    return UIProcessor.format(UIProcessor(), ui, max_elements)


def fmt_jsonl(ui: UIState, max_elements: int = 60) -> str:
    """扁平 JSONL：每行一个节点，含 id/clickable/bounds/class。"""
    lines = []
    for e in ui.elements[:max_elements]:
        entry = {
            "id": e.index,
            "text": e.text or "",
            "content_desc": e.desc or "",
            "class": e.cls,
            "clickable": e.clickable,
            "bounds": _bstr(e),
        }
        if e.id:
            entry["resource_id"] = e.id
        lines.append(json.dumps(entry, ensure_ascii=False))
    return "\n".join(lines)


def fmt_flattext(ui: UIState, max_elements: int = 60) -> str:
    """缩进文本：depth 缩进 + [flags] + bounds。"""
    parents, depths = _compute_hierarchy(ui.elements)
    lines = [f"[index] label (Class) [flags] bounds  ({len(ui.elements)} nodes)"]
    for e in ui.elements[:max_elements]:
        indent = "  " * depths.get(e.index, 0)
        parts = [f"{indent}[{e.index}]"]
        lab = _label(e)
        if lab:
            parts.append(lab)
        parts.append(f"({e.cls})")
        fl = _flags(e)
        if fl:
            parts.append(fl)
        parts.append(f"bounds={_bstr(e)}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def fmt_compact(ui: UIState, max_elements: int = 60) -> str:
    """紧凑格式：▶ 标 clickable 容器。"""
    lines = [f"hierarchy ({len(ui.elements)} nodes)"]
    parents, depths = _compute_hierarchy(ui.elements)
    for e in ui.elements[:max_elements]:
        indent = "  " * depths.get(e.index, 0)
        click = "▶ " if e.clickable else ""
        flags = "+" if e.clickable else ""
        lab_parts = []
        if e.text:
            lab_parts.append(f'T"{e.text}"')
        if e.desc and e.desc != e.text:
            lab_parts.append(f'D<{e.desc}>')
        label = " ".join(lab_parts)
        parts = [indent, click, _bstr(e)]
        if flags:
            parts.append(flags)
        parts.append(e.cls)
        if label:
            parts.append(label)
        lines.append(" ".join(parts).strip())
    return "\n".join(lines)


def fmt_simplexml(ui: UIState, max_elements: int = 60) -> str:
    """简化 XML：只保留非空/true 属性。"""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    for e in ui.elements[:max_elements]:
        attrs = [f'index="{e.index}"']
        if e.text:
            attrs.append(f'text="{e.text}"')
        if e.desc:
            attrs.append(f'content-desc="{e.desc}"')
        if e.id:
            attrs.append(f'resource-id="{e.id}"')
        attrs.append(f'class="{e.cls}"')
        if e.clickable:
            attrs.append('clickable="True"')
        attrs.append(f'bounds="{_bstr(e)}"')
        lines.append(f'<node {" ".join(attrs)} />')
    return "\n".join(lines)


def fmt_flatref(ui: UIState, max_elements: int = 60) -> str:
    """扁平带引用：#id parent=#M depth=D。"""
    parents, depths = _compute_hierarchy(ui.elements)
    lines = [f"hierarchy ({len(ui.elements)} nodes)"]
    for e in ui.elements[:max_elements]:
        p = parents.get(e.index)
        p_str = f"parent=#{p}" if p is not None else "parent=None"
        parts = [f"#{e.index}", p_str, f"depth={depths.get(e.index, 0)}"]
        lab = _label(e)
        if lab:
            parts.append(lab)
        parts.append(f"({e.cls})")
        fl = _flags(e)
        if fl:
            parts.append(fl)
        parts.append(f"bounds={_bstr(e)}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


FORMATS: dict[str, Any] = {
    "region": fmt_region,
    "jsonl": fmt_jsonl,
    "flattext": fmt_flattext,
    "compact": fmt_compact,
    "simplexml": fmt_simplexml,
    "flatref": fmt_flatref,
}


@contextmanager
def patched_format(format_fn: Any):
    """临时替换 processor.format，使 agent 用指定格式喂 LLM。"""
    original = up_module.processor.format
    up_module.processor.format = lambda ui, max_elements=60: format_fn(ui, max_elements)
    try:
        yield
    finally:
        up_module.processor.format = original


# ---------------------------------------------------------------------------
# 三、用真实 LLM 跑场景
# ---------------------------------------------------------------------------


@dataclass
class AgentOutcome:
    """一次 agent 运行的结果。"""
    scenario: str
    variant: str
    prompt: str
    format: str
    success: bool
    reason: str
    taps: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    steps: int = 0
    cost_usd: float = 0.0
    duration: float = 0.0
    error: str = ""


def run_scenario(
    scenario: Scenario,
    screen_text: str,
    nodes: list[dict],
    prompt_name: str,
    format_name: str,
    delegate: LLMDelegate,
    max_steps: int = 10,
    *,
    screens: dict[str, Screen] | None = None,
    trace: bool = False,
    trace_dir: str = "build/traces",
    auto_observe: bool = False,
    variant: str = "",
    seq: int = 0,
) -> AgentOutcome:
    """用真实 LLM 跑一个场景，返回成功/失败及诊断信息。

    若提供 screens（状态机设备图），则使用状态机 MockPhonefast：
    tap 命中 zone 时屏幕会转换，agent 可 observe 到操作结果后调用 complete。
    否则使用静态 MockPhonefast（屏幕不变）。

    trace=True 时构造 ReplayLogger，按 run 产出 build/traces/<run_id>.{trace.jsonl,replay.json}。
    """
    if screens is not None:
        start_key = getattr(scenario, "start_screen", "settings_home")
        pf = make_stateful_phonefast(start_key, screens)
        # GT 从目标元素所在屏解析（默认起始屏；recover 类目标在 back 目的地屏）
        gt_screen_key = getattr(scenario, "gt_screen", "") or start_key
        gt_nodes = parse_meaningful_nodes_from_text(screens[gt_screen_key].text)
    else:
        pf = MockPhonefast(screen_text)
        gt_nodes = nodes
    registry = build_registry()
    system_prompt = _SYSTEM_PROMPT if prompt_name == "baseline" else OPTIMIZED_SYSTEM_PROMPT

    # 可选重放日志：构造 logger 并 begin_run（on_finish 自动落盘+reset）
    logger = None
    if trace:
        from fastaget.agent.trace import make_replay_logger
        from fastaget.device.uiprocessor import processor as _processor
        logger = make_replay_logger(
            enabled=True, output_dir=trace_dir,
            phonefast=pf, processor=_processor,
            action_tool_names=registry.action_tool_names(),
            auto_observe_after_action=auto_observe,
        )
        if logger is not None:
            logger.begin_run(
                scenario.goal, scenario=scenario.name, variant=variant,
                prompt=prompt_name, fmt=format_name, seq=seq,
                model=getattr(delegate, "model", None),
                max_steps=max_steps, vision=False,
            )

    t_start = time.time()
    try:
        with patched_format(FORMATS[format_name]):
            hooks_list = [logger] if logger is not None else None
            agent = FastAgent(
                delegate, pf, registry,
                max_steps=max_steps,
                system_prompt=system_prompt,
                hooks=hooks_list,
            )
            result = agent.run(scenario.goal)
    except Exception as e:
        if logger is not None:
            try:
                logger.flush()
            except Exception:
                pass
        return AgentOutcome(
            scenario=scenario.name, variant="", prompt=prompt_name,
            format=format_name, success=False, reason=f"exception: {e}",
            duration=time.time() - t_start, error=str(e)[:200],
        )
    duration = time.time() - t_start

    # 统一判定（消除重复 if/elif，复用 evaluate_scenario_outcome）
    ok, reason = evaluate_scenario_outcome(
        scenario, gt_nodes, pf, result,
        screens=screens, prompt_name=prompt_name,
    )

    return AgentOutcome(
        scenario=scenario.name, variant="", prompt=prompt_name,
        format=format_name, success=ok, reason=reason,
        taps=list(pf.taps), actions=list(pf.actions),
        steps=result.steps, cost_usd=result.total_cost_usd,
        duration=duration,
    )


# ---------------------------------------------------------------------------
# 四、矩阵执行
# ---------------------------------------------------------------------------


def run_matrix(
    scenarios: list[Scenario],
    variants: dict[str, str],
    prompts: list[str],
    formats: list[str],
    delegate: LLMDelegate,
    max_steps: int = 10,
    verbose: bool = True,
    screens: dict[str, Screen] | None = None,
    trace: bool = False,
    trace_dir: str = "build/traces",
    auto_observe: bool = False,
) -> list[AgentOutcome]:
    """跑 scenarios × variants × prompts × formats 全矩阵。

    若提供 screens，使用状态机设备图（tap 后屏幕变化）。
    """
    outcomes: list[AgentOutcome] = []
    total = len(scenarios) * len(variants) * len(prompts) * len(formats)
    done = 0

    for prompt_name in prompts:
        for format_name in formats:
            for vname, xml in variants.items():
                nodes = parse_meaningful_nodes(xml)
                text = xml_to_phonefast_text(xml)
                for sc in scenarios:
                    # self_heal 场景只跑 baseline 变体
                    if sc.kind == "self_heal" and vname != "baseline":
                        continue
                    # 状态机模式 + 无响应场景：只在 baseline 变体跑（loading/empty 与变体无关）
                    if screens is not None and sc.start_screen in ("loading", "empty") and vname != "baseline":
                        continue
                    # 状态机模式：跳过坐标偏移变体（scrolled/truncated/noisy）
                    # 原因：状态机 settings_home 屏幕固定用 baseline 变体构建，
                    # 但 GT bounds 从变体 nodes 解析，坐标偏移会导致 tap 必然不匹配。
                    # 坐标偏移变体在静态模式（无 --stateful）下测试才有意义。
                    if screens is not None and vname in ("scrolled", "truncated", "noisy"):
                        continue
                    done += 1
                    outcome = run_scenario(
                        sc, text, nodes, prompt_name, format_name, delegate, max_steps,
                        screens=screens, trace=trace, trace_dir=trace_dir,
                        auto_observe=auto_observe, variant=vname, seq=done,
                    )
                    outcome.variant = vname
                    outcomes.append(outcome)

                    if verbose:
                        icon = "✅" if outcome.success else "❌"
                        print(
                            f"  [{done:3d}/{total}] {icon} "
                            f"{scenario_short(sc.name):<20s} "
                            f"{vname:<12s} {prompt_name:<10s} {format_name:<12s} "
                            f"({outcome.steps}步, {outcome.duration:.1f}s, "
                            f"${outcome.cost_usd:.4f}) "
                            f"| {outcome.reason[:50]}"
                        )
    return outcomes


def scenario_short(name: str) -> str:
    return name[:20]


# ---------------------------------------------------------------------------
# 五、报告
# ---------------------------------------------------------------------------


def print_report(results: list[AgentOutcome], prompts: list[str], formats: list[str]) -> None:
    print("\n" + "=" * 100)
    print("  📊 FastAgent 真实 LLM 成功率报告")
    print("=" * 100)

    # --- 按 prompt 汇总 ---
    print(f"\n{'─' * 80}")
    print("  按 Prompt 汇总")
    print(f"{'─' * 80}")
    print(f"  {'Prompt':<14} {'Success':>8} {'Total':>6} {'Rate':>7} "
          f"{'AvgSteps':>8} {'AvgCost':>9} {'AvgTime':>8}")
    for p in prompts:
        pr = [r for r in results if r.prompt == p]
        if not pr:
            continue
        ok = sum(r.success for r in pr)
        total = len(pr)
        avg_steps = sum(r.steps for r in pr) / total
        avg_cost = sum(r.cost_usd for r in pr) / total
        avg_time = sum(r.duration for r in pr) / total
        print(f"  {p:<14} {ok:>8} {total:>6} {ok/total*100:>6.1f}% "
              f"{avg_steps:>8.1f} {avg_cost:>9.5f} {avg_time:>7.1f}s")

    # --- 按 format 汇总 ---
    print(f"\n{'─' * 80}")
    print("  按 UI 格式汇总")
    print(f"{'─' * 80}")
    print(f"  {'Format':<14} {'Success':>8} {'Total':>6} {'Rate':>7} "
          f"{'AvgSteps':>8} {'AvgCost':>9} {'AvgTime':>8}")
    for f in formats:
        fr = [r for r in results if r.format == f]
        if not fr:
            continue
        ok = sum(r.success for r in fr)
        total = len(fr)
        avg_steps = sum(r.steps for r in fr) / total
        avg_cost = sum(r.cost_usd for r in fr) / total
        avg_time = sum(r.duration for r in fr) / total
        print(f"  {f:<14} {ok:>8} {total:>6} {ok/total*100:>6.1f}% "
              f"{avg_steps:>8.1f} {avg_cost:>9.5f} {avg_time:>7.1f}s")

    # --- 按 scenario 汇总 ---
    print(f"\n{'─' * 80}")
    print("  按场景 × Prompt 汇总")
    print(f"{'─' * 80}")
    print(f"  {'Scenario':<22}", end="")
    for p in prompts:
        print(f" {p:>12}", end="")
    print()
    scenarios = sorted(set(r.scenario for r in results))
    for sc in scenarios:
        print(f"  {sc:<22}", end="")
        for p in prompts:
            sr = [r for r in results if r.scenario == sc and r.prompt == p]
            if sr:
                rate = sum(r.success for r in sr) / len(sr) * 100
                print(f" {rate:>11.0f}%", end="")
            else:
                print(f" {'N/A':>12}", end="")
        print()

    # --- 按 variant 汇总 ---
    print(f"\n{'─' * 80}")
    print("  按变体 × Prompt 汇总")
    print(f"{'─' * 80}")
    print(f"  {'Variant':<14}", end="")
    for p in prompts:
        print(f" {p:>12}", end="")
    print()
    variants = sorted(set(r.variant for r in results))
    for v in variants:
        print(f"  {v:<14}", end="")
        for p in prompts:
            vr = [r for r in results if r.variant == v and r.prompt == p]
            if vr:
                rate = sum(r.success for r in vr) / len(vr) * 100
                print(f" {rate:>11.0f}%", end="")
            else:
                print(f" {'N/A':>12}", end="")
        print()

    # --- format × prompt 交叉表 ---
    print(f"\n{'─' * 80}")
    print("  Format × Prompt 成功率交叉表")
    print(f"{'─' * 80}")
    print(f"  {'Format':<14}", end="")
    for p in prompts:
        print(f" {p:>12}", end="")
    print()
    for f in formats:
        print(f"  {f:<14}", end="")
        for p in prompts:
            fr = [r for r in results if r.format == f and r.prompt == p]
            if fr:
                rate = sum(r.success for r in fr) / len(fr) * 100
                print(f" {rate:>11.0f}%", end="")
            else:
                print(f" {'N/A':>12}", end="")
        print()

    # --- 总体 ---
    total_ok = sum(r.success for r in results)
    total = len(results)
    print(f"\n{'═' * 80}")
    print(f"  总体: {total_ok}/{total} = {total_ok/total*100:.1f}%")
    total_cost = sum(r.cost_usd for r in results)
    total_time = sum(r.duration for r in results)
    print(f"  总成本: ${total_cost:.4f} | 总耗时: {total_time:.0f}s")

    # --- 失败案例 ---
    fails = [r for r in results if not r.success]
    if fails:
        print(f"\n{'─' * 80}")
        print(f"  失败案例 ({len(fails)} 个)")
        print(f"{'─' * 80}")
        for r in fails[:20]:
            print(f"  ❌ {r.scenario:<20s} {r.variant:<12s} "
                  f"{r.prompt:<10s} {r.format:<12s} | {r.reason[:60]}")
        if len(fails) > 20:
            print(f"  ... 还有 {len(fails) - 20} 个")


# ---------------------------------------------------------------------------
# 六、Main
# ---------------------------------------------------------------------------


def make_delegate(args: argparse.Namespace) -> LLMDelegate:
    """根据 --delegate 选择 LLM delegate。"""
    if args.delegate == "deepseek":
        return DeepSeekToolDelegate(model=args.model)
    elif args.delegate == "anthropic":
        from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate
        return AnthropicHTTPDelegate(model=args.model)
    else:
        raise ValueError(f"Unknown delegate: {args.delegate}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="用真实 LLM 驱动 FastAgent 评测自动化成功率"
    )
    parser.add_argument("--delegate", default="deepseek",
                        choices=["deepseek", "anthropic"],
                        help="LLM delegate 类型")
    parser.add_argument("--model", default=None,
                        help="模型名（deepseek: deepseek-v4-flash; anthropic: glm-5.2）")
    parser.add_argument("--prompts", nargs="+",
                        default=["baseline", "optimized"],
                        help="要测试的 prompt 版本")
    parser.add_argument("--formats", nargs="+",
                        default=["region", "jsonl", "flattext", "compact",
                                 "simplexml", "flatref"],
                        help="要测试的 UI 格式")
    parser.add_argument("--variants", nargs="+",
                        default=None,
                        help="要测试的变体名（默认全部）")
    parser.add_argument("--scenarios", nargs="+", default=None,
                        help="要测试的场景名（默认全部）")
    parser.add_argument("--max-steps", type=int, default=10,
                        help="agent 最大步数")
    parser.add_argument("--quick", action="store_true",
                        help="快速模式：2 场景 × 1 变体 × 2 prompt × 2 格式")
    parser.add_argument("--no-report", action="store_true",
                        help="不打印报告")
    parser.add_argument("--stateful", action="store_true",
                        help="使用状态机设备图（tap 后屏幕变化，含成功/失败/无响应）")
    parser.add_argument("--yaml-scenarios", action="store_true",
                        help="从 meta/scenarios.yml 加载场景（含无响应场景）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅加载数据、打印矩阵，不实际调用 LLM（验证环境可用性）")
    parser.add_argument("--trace", action="store_true",
                        help="为每个 run 产出 LLM 动作重放日志（build/traces/<run_id>.*）")
    parser.add_argument("--trace-dir", default="build/traces",
                        help="重放日志输出目录（默认 build/traces）")
    parser.add_argument("--trace-auto-observe", action="store_true",
                        help="富模式：每个操作类工具后额外 observe（会改变运行行为，仅重放场景用）")
    args = parser.parse_args()

    # 默认模型
    if args.model is None:
        args.model = "deepseek-v4-flash" if args.delegate == "deepseek" else "glm-5.2"

    # 检查 API key（dry-run 模式跳过）
    if not args.dry_run:
        if args.delegate == "deepseek":
            key = os.environ.get("DEEPSEEK_API_KEY", "")
        else:
            key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            print(f"Error: 未配置 {args.delegate} API key", file=sys.stderr)
            return 1

    # 加载数据
    base_xml = WD4_XML.read_text(encoding="utf-8")
    nodes = parse_meaningful_nodes(base_xml)
    variants = make_variants(base_xml)

    # 场景来源: --yaml-scenarios 从 YAML 加载（含无响应场景），否则从 _build_scenarios
    screens = None
    if args.yaml_scenarios or args.stateful:
        screens, yaml_scenarios, _ = load_device_graph(base_xml, variants)
        scenarios = yaml_scenarios
    else:
        scenarios = _build_scenarios(nodes)

    # 过滤
    if args.scenarios:
        scenarios = [s for s in scenarios if s.name in args.scenarios]
    if args.variants:
        variants = {k: v for k, v in variants.items() if k in args.variants}

    # 快速模式
    if args.quick:
        scenarios = scenarios[:3]
        variants = {"baseline": variants["baseline"]}
        args.formats = args.formats[:2] if len(args.formats) > 2 else args.formats

    print(f"📁 XML: {WD4_XML}")
    print(f"🤖 Delegate: {args.delegate} (model={args.model})")
    if not args.dry_run:
        print(f"🔑 Key: {key[:8]}...")
    print(f"📋 Scenarios: {len(scenarios)} | Variants: {len(variants)}")
    print(f"🎨 Formats: {args.formats}")
    print(f"📝 Prompts: {args.prompts}")
    print(f"🔢 Max steps: {args.max_steps}")
    if args.stateful:
        print(f"🔌 模式: 状态机设备图 ({len(screens) if screens else 0} 屏幕)")
    total = len(scenarios) * len(variants) * len(args.prompts) * len(args.formats)
    print(f"📊 Total runs: {total}")
    print()

    # ---- dry-run：仅验证矩阵和基础设施，不调 LLM ----
    if args.dry_run:
        print("═══ DRY RUN ═══")
        print(f"✅ XML 数据加载成功 ({WD4_XML})")
        print(f"✅ YAML 场景加载: {len(scenarios)} 场景")
        print(f"✅ 变体生成: {len(variants)} 变体 ({list(variants.keys())})")
        print(f"✅ 格式函数: {len(args.formats)} 种 ({args.formats})")
        if args.stateful:
            loading = [s.name for s in scenarios if getattr(s, 'start_screen', '') == 'loading']
            empty = [s.name for s in scenarios if getattr(s, 'start_screen', '') == 'empty']
            print(f"✅ 状态机屏幕: {len(screens)} 个")
            print(f"✅ 无响应场景: loading={loading}, empty={empty}")
        # 验证每个 scenario 的字段推导
        for s in scenarios:
            print(f"   📋 {s.name}: kind={s.kind} check={s.check} "
                  f"target_desc={s.target_desc or '-'} start={getattr(s, 'start_screen', '-')}")
        # 预估成本
        est_input_tokens = total * 3000  # 平均每轮 system+user 约 3K tokens
        est_output_tokens = total * 500  # 平均每轮输出 500 tokens
        est_cost = est_input_tokens * 0.27 / 1e6 + est_output_tokens * 1.10 / 1e6
        print(f"\n💰 预估成本: ~${est_cost:.4f} ({total} 次调用 × ~3.5K tokens)")
        print(f"⏱  预估耗时: ~{total * 8}s (保守估计每次 8s)")
        print(f"\n✅ 基础设施就绪，可以开始真实 LLM 评测。")
        print(f"   去掉 --dry-run 即可正式运行。")
        return 0

    delegate = make_delegate(args)

    try:
        results = run_matrix(
            scenarios, variants, args.prompts, args.formats,
            delegate, max_steps=args.max_steps, verbose=True,
            screens=screens if args.stateful else None,
            trace=args.trace, trace_dir=args.trace_dir,
            auto_observe=args.trace_auto_observe,
        )
    finally:
        delegate.close()

    if not args.no_report:
        print_report(results, args.prompts, args.formats)

    # 写 JSON 结果
    out_path = Path("build/eval_agent_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = [
        {
            "scenario": r.scenario, "variant": r.variant,
            "prompt": r.prompt, "format": r.format,
            "success": r.success, "reason": r.reason,
            "steps": r.steps, "cost_usd": r.cost_usd,
            "duration": r.duration,
            "taps": [{"x": t.x, "y": t.y} for t in r.taps],
            "actions": r.actions,
        }
        for r in results
    ]
    out_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 结果已写入 {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
