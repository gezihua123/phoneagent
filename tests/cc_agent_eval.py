"""Claude Code Agent 评测 —— 通过 claude_agent_sdk 编程调用 CC 执行测试用例。

宪法第四条：CC 交互模式，只给 goal + phonefast 工具，CC 自主 observe→决策→执行→验证。

使用 claude_agent_sdk.query() → CC 多轮 tool calling → 捕获结果 → 同 fastaget verify。

Usage:
    python3 tests/cc_agent_eval.py \\
        --cases meta/eval_cases_aw_filled.yml \\
        --serial emulator-5554 \\
        --report /tmp/cc_eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import yaml

# ── SDK setup ──
# Token / Base URL 由调用方通过环境变量注入，不写死默认值
if not os.environ.get("ANTHROPIC_AUTH_TOKEN") and not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError("未配置模型凭证，请设置 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY")
os.environ.setdefault("ANTHROPIC_CUSTOM_HEADERS", f"X-Working-Dir: {os.getcwd()}")
os.environ.setdefault("DISABLE_COST_WARNINGS", "1")

from claude_agent_sdk import ClaudeAgentOptions, query, AssistantMessage, ResultMessage

SERIAL = ""
REPORT_DIR = ""


# ── CC Agent 单个 case 执行 ──

@dataclass
class CCAgentResult:
    name: str
    success: bool
    verified: bool | None
    steps: int          # CC tool calls
    elapsed_ms: int
    llm_calls: int = 0       # LLM API 调用次数
    input_tokens: int = 0    # 总输入 token
    output_tokens: int = 0   # 总输出 token
    summary: str = ""
    error: str = ""


def _build_prompt(goal: str, serial: str) -> str:
    """构建给 CC Agent 的 prompt——只给 goal + 工具，要求简洁执行。"""
    return f"""Execute this task on the Android device {serial}. Do NOT read skill docs. Do NOT explain your plan. Just execute step by step and output the final result.

GOAL: {goal}

TOOLS (use via Bash):
  phonefast --daemon --serial {serial} observe
  phonefast --daemon --serial {serial} tap <x> <y>
  phonefast --daemon --serial {serial} swipe <x1> <y1> <x2> <y2> [ms]
  phonefast --daemon --serial {serial} type <text>
  phonefast --daemon --serial {serial} launch <pkg>
  phonefast --daemon --serial {serial} back / home
  adb -s {serial} shell <cmd>

RULES:
- System settings (wifi/bt/brightness) → adb shell svc/settings directly
- App launch → adb shell pm list packages | grep <keyword> → launch <pkg>
- Tap center = (bounds_left+bounds_right)/2, (bounds_top+bounds_bottom)/2
- No observe verification needed for shell-only operations
- FINAL OUTPUT: single line starting with RESULT: PASS or RESULT: FAIL"""


async def _run_cc_case(name: str, goal: str, serial: str, timeout: int = 120) -> CCAgentResult:
    """调用 CC Agent 执行单个 case。"""
    prompt = _build_prompt(goal, serial)
    t0 = time.time()
    steps = 0; llm_calls = 0; total_in = 0; total_out = 0
    output_parts: list[str] = []
    error = ""

    try:
        async with asyncio.timeout(timeout):
            async for msg in query(prompt=prompt, options=ClaudeAgentOptions()):
                if isinstance(msg, AssistantMessage):
                    usage = getattr(msg, "usage", None) or {}
                    total_in += usage.get("input_tokens", 0)
                    total_out += usage.get("output_tokens", 0)
                    llm_calls += 1
                    for block in msg.content:
                        if hasattr(block, "text") and block.text:
                            output_parts.append(block.text)
                        if hasattr(block, "name"):  # tool_use block
                            steps += 1
                elif isinstance(msg, ResultMessage):
                    output_parts.append(str(msg.result))
    except asyncio.TimeoutError:
        error = f"Timeout after {timeout}s"
    except Exception as e:
        error = str(e)[:200]

    elapsed = int((time.time() - t0) * 1000)
    summary = " ".join(output_parts)[:500]

    # 判断 success——从输出中找 RESULT: PASS/FAIL
    full_output = " ".join(output_parts)
    success = "RESULT: PASS" in full_output or "RESULT: SUCCESS" in full_output

    return CCAgentResult(
        name=name, success=success, verified=None,
        steps=steps, elapsed_ms=elapsed,
        llm_calls=llm_calls, input_tokens=total_in, output_tokens=total_out,
        summary=summary, error=error,
    )


# ── 验证（同 fastaget verify rules）──

def run_verification(verify_specs: list[dict]) -> tuple[bool | None, str]:
    """执行验证 shell 命令。返回 (passed, detail)。"""
    for vfy in verify_specs:
        cmd = vfy.get("command", "")
        if not cmd:
            continue
        try:
            r = subprocess.run(
                ["adb", "-s", SERIAL, "shell", cmd],
                capture_output=True, text=True, timeout=10,
            )
            output = (r.stdout + r.stderr).strip()
        except Exception:
            output = ""

        if vfy.get("min_lines", 0) > 0:
            lines = len([l for l in output.split("\n") if l.strip()])
            passed = lines >= vfy["min_lines"]
            return passed, f"lines={lines}/{vfy['min_lines']}"
        elif vfy.get("expect"):
            passed = output == vfy["expect"]
            return passed, f"got={output[:30]} exp={vfy['expect']}"
        elif vfy.get("expect_re"):
            passed = bool(re.search(vfy["expect_re"], output))
            return passed, f"re={vfy['expect_re'][:20]}"
    return None, ""


# ── 批量执行 ──

async def run_all(cases_path: str, serial: str, max_cases: int = 0) -> list[CCAgentResult]:
    """批量执行所有 case。"""
    global SERIAL
    SERIAL = serial

    with open(cases_path) as f:
        data = yaml.safe_load(f)
    all_cases = data.get("cases", data if isinstance(data, list) else [])
    if max_cases > 0:
        all_cases = all_cases[:max_cases]

    results = []
    for i, c in enumerate(all_cases, 1):
        name = c.get("name", f"case_{i}")
        goal = c.get("goal", "")
        verify_specs = c.get("verify", []) or []

        # ── 事前 init（同 fastaget）──
        for init in (c.get("initialize") or []):
            cmd = init.get("command", "")
            if cmd:
                subprocess.run(["adb", "-s", serial, "shell", cmd],
                             capture_output=True, timeout=10)

        print(f"[{i}/{len(all_cases)}] {name}: ", end="", flush=True)

        # ── CC Agent 执行 ──
        r = await _run_cc_case(name, goal, serial)

        # ── 事后验证 ──
        v_passed, v_detail = run_verification(verify_specs)
        r.verified = v_passed
        if v_passed is not None and not v_passed:
            r.success = False

        status = "PASS" if r.success else "FAIL"
        v_str = "✓" if v_passed else ("✗" if v_passed is False else "·")
        print(f"{status} v={v_str} {r.steps}steps {r.elapsed_ms}ms")
        if r.error:
            print(f"  ERROR: {r.error}")
        if r.summary:
            print(f"  {r.summary[:150]}")

        results.append(r)

    return results


def print_report(results: list[CCAgentResult]) -> None:
    """打印评测报告（含 token 统计）。"""
    passed = sum(1 for r in results if r.success)
    total = len(results)
    total_ms = sum(r.elapsed_ms for r in results)
    total_steps = sum(r.steps for r in results)
    total_llm = sum(r.llm_calls for r in results)
    total_in = sum(r.input_tokens for r in results)
    total_out = sum(r.output_tokens for r in results)
    verified = sum(1 for r in results if r.verified is True)

    print("\n" + "=" * 65)
    print("  CC Agent Eval — claude_agent_sdk, 宪法第四条")
    print("=" * 65)
    print(f"  Cases:       {total}")
    print(f"  Agent Pass:  {passed}/{total} ({100 * passed // total}%)")
    print(f"  Verify Pass: {verified}/{total} ({100 * verified // total}%)")
    print(f"  LLM Calls:   {total_llm} total, avg {total_llm / total:.1f}/case")
    print(f"  Input Tok:   {total_in} total, avg {total_in / total:.0f}/case")
    print(f"  Output Tok:  {total_out} total, avg {total_out / total:.0f}/case")
    print(f"  Steps:       {total_steps} total, avg {total_steps / total:.1f}/case")
    print(f"  Time:        {total_ms}ms total, avg {total_ms / total:.0f}ms/case")
    print()

    print("  Detail:")
    for r in results:
        s = "PASS" if r.success else "FAIL"
        v = "✓" if r.verified else ("✗" if r.verified is False else "·")
        print(f"  [{s}] {r.name:45s} v={v}  steps={r.steps:2d}  LLM={r.llm_calls:2d}  in={r.input_tokens:5d}  out={r.output_tokens:5d}  {r.elapsed_ms//1000}s")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--report", default="/tmp/cc_eval_report.json")
    args = parser.parse_args()

    results = await run_all(args.cases, args.serial, args.max_cases)

    # Save report
    report = {
        "results": [{"name": r.name, "success": r.success, "verified": r.verified,
                      "steps": r.steps, "elapsed_ms": r.elapsed_ms} for r in results],
        "total": len(results),
        "passed": sum(1 for r in results if r.success),
        "verified": sum(1 for r in results if r.verified is True),
    }
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print_report(results)


if __name__ == "__main__":
    asyncio.run(main())
