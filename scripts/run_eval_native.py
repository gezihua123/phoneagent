#!/usr/bin/env python3
"""AW 原生评测运行器——评测层完全采用 AndroidWorld 的 TaskEval 体系。

流程（与 AW run.py 对齐）：
  random.seed(固定) → cls.generate_random_params() → task 实例化
  → task.initialize_task(env)（AW 原生 Python 逻辑，经 phonefast shim）
  → fastaget agent 执行 goal
  → env.interaction_cache = agent 答案（IR 类校验用）
  → score = task.is_successful(env)   # 0.0~1.0，AW 原生判定（可部分分）
  → task.tear_down(env)

成功率定义（AW 同款）：score ≥ 1.0 / 总 case 数。
报告同时给出 agent 自报成功率（result.success）做误报对照。

用法:
  python3 scripts/run_eval_native.py --only CameraTakePhoto,SmsSend   # 子集
  python3 scripts/run_eval_native.py                                  # 全量 116
  tail -f build/eval_aw_native/run01/report.txt
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

# ── LLM 端点常量（构造函数直传，不依赖 env）──
LLM_BASE_URL = "https://api.deepseek.com/anthropic"
LLM_TOKEN = __import__("os").environ.get("ANTHROPIC_AUTH_TOKEN") or __import__("os").environ.get("ANTHROPIC_API_KEY") or ""
DEVICE_SERIAL = "emulator-5554"
FIXED_SEED = 42  # AW 的固定任务种子（零随机可重复评测）


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AW 原生评测运行器")
    p.add_argument("--model", "-m", default="deepseek-v4-flash")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-steps", default=30, type=int)
    p.add_argument("--seed", type=int, default=FIXED_SEED)
    p.add_argument("--run-id", default="run01")
    p.add_argument("--report-dir", default=str(PROJ / "build/eval_aw_native"))
    p.add_argument("--only", default="", help="只跑名称含此子串的 case（逗号分隔）")
    p.add_argument("--list", action="store_true", help="只列出可评测 task，不执行")
    return p.parse_args()


def _task_registry() -> dict:
    from fastaget.aw_native.vendor.registry import TaskRegistry

    r = TaskRegistry()
    reg = {}
    reg.update(r.get_registry(family="android"))
    reg.update(r.get_registry(family="information_retrieval"))
    return reg


def _build_task(cls, seed: int):
    random.seed(seed)
    params = cls.generate_random_params()
    if params is None:
        params = {}
    task = cls(params) if params is not None else cls({})
    return task


def _agent_answer(result) -> str:
    """从 AgentResult 提取 agent 的最终答案（IR 类 goal 要求文字回答）。"""
    summary = getattr(result, "summary", "") or ""
    # session 记录的完整答案优先（complete 的 summary）
    return summary.strip()


def main() -> int:
    args = parse_args()

    reg = _task_registry()
    if args.list:
        for name in sorted(reg):
            print(name)
        print(f"\n{len(reg)} tasks")
        return 0

    # ── 导入（env 无关，构造函数直传参数）──
    from fastaget.device.phonefast import Phonefast, PhonefastError
    from fastaget.tools import build_registry
    from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate
    from fastaget.agent.fast_agent import FastAgent
    from fastaget.agent.session import Session
    from fastaget.aw_native.shim import interface as shim_iface

    report_dir = Path(args.report_dir) / args.run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    progress_path = report_dir / "report.txt"

    # ── 连接设备（CLI 层创建 Phonefast——宪法：子模块不得自行构造）──
    pf = Phonefast(serial=DEVICE_SERIAL)
    try:
        pf.restart_daemon()
    except PhonefastError:
        pass
    shim_iface.set_pf(pf)
    from fastaget.aw_native.shim.interface import AsyncEnv

    env = AsyncEnv(pf)
    st = pf.status()
    dev_name = st.get("devices", ["?"])[0] if st.get("devices") else "?"
    print(f"[Env] device={dev_name} model={pf.shell('getprop ro.product.model')}")
    print(f"[Env] endpoint={LLM_BASE_URL} model={args.model} seed={args.seed}")
    print(f"[Env] report={report_dir}")
    print(f"[TIPS] tail -f {progress_path}\n")

    llm = AnthropicHTTPDelegate(
        model=args.model,
        base_url=LLM_BASE_URL,
        token=LLM_TOKEN,
        temperature=args.temperature,
    )
    registry = build_registry(capabilities=pf.FULL_CAPABILITIES)

    # ── case 清单（116 = 91 android + 25 IR）──
    if args.only:
        subs = [s.strip() for s in args.only.split(",") if s.strip()]
        names = [n for n in sorted(reg) if any(s in n for s in subs)]
        print(f"[Load] ONLY {subs}: {len(names)} cases")
    else:
        names = sorted(reg)
        print(f"[Load] {len(names)} cases")

    # ── 统计 ──
    total = len(names)
    passed_verify = 0
    agent_pass = 0
    total_cost = 0.0
    total_steps = 0
    case_records: list[dict] = []
    t_start = time.time()

    for i, name in enumerate(names, 1):
        cls = reg[name]
        try:
            task = _build_task(cls, args.seed)
            goal = task.goal
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{total}] {name} — 参数生成失败: {e}")
            case_records.append({"name": name, "error": f"build: {e}", "score": 0.0})
            continue

        # ── initialize_task（AW 原生）──
        init_err = ""
        try:
            pf.home()
        except PhonefastError:
            pass
        try:
            task.initialize_task(env)
        except Exception as e:  # noqa: BLE001
            init_err = f"init: {e}"

        # ── agent 执行 ──
        max_steps = args.max_steps
        agent = FastAgent(llm, pf, registry, max_steps=max_steps)
        session = Session(agent=agent, trace=True)
        t0 = time.time()
        try:
            result = session.run(goal)
            session.flush()
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            result = None
            print(f"    agent 异常: {e}")

        elapsed = time.time() - t0
        steps = getattr(result, "steps", 0) or 0
        cost = getattr(result, "total_cost_usd", 0.0) or 0.0
        total_steps += steps
        total_cost += cost

        # ── 答案写入 interaction_cache（IR 校验）──
        env.interaction_cache = _agent_answer(result) if result is not None else ""

        # ── is_successful（AW 原生，0.0~1.0）──
        score = 0.0
        verify_err = ""
        try:
            score = float(task.is_successful(env))
        except Exception as e:  # noqa: BLE001
            verify_err = f"verify: {e}"

        # ── tear_down（AW 原生）──
        try:
            task.tear_down(env)
        except Exception:  # noqa: BLE001
            pass

        passed = score >= 1.0
        if passed:
            passed_verify += 1
        if result is not None and getattr(result, "success", False):
            agent_pass += 1

        rec = {
            "name": name,
            "score": score,
            "passed": passed,
            "agent_success": bool(result and getattr(result, "success", False)),
            "agent_summary": _agent_answer(result)[:120] if result else "",
            "steps": steps,
            "cost_usd": round(cost, 4),
            "elapsed_s": round(elapsed, 1),
            "init_err": init_err,
            "verify_err": verify_err,
        }
        case_records.append(rec)

        line = (
            f"[{i}/{total}] {name} — score={score:.1f} {'✓' if passed else '✗'} "
            f"| agent={'✓' if rec['agent_success'] else '✗'} | {steps}步 "
            f"${cost:.4f} | {elapsed:.0f}s"
            + (f" | ⚠ {init_err}" if init_err else "")
            + (f" | ⚠ {verify_err}" if verify_err else "")
        )
        print(line)
        with open(progress_path, "a") as f:
            f.write(line + "\n")
        _flush_report(report_dir, case_records, total, passed_verify, agent_pass,
                      total_steps, total_cost, t_start)

    success_rate = passed_verify / total if total else 0.0
    agent_rate = agent_pass / total if total else 0.0
    print(f"\n═══ 完成 ═══")
    print(f"设备验证通过率: {passed_verify}/{total} = {success_rate:.1%}  (AW 原生 is_successful ≥ 1.0)")
    print(f"agent 自报通过率: {agent_pass}/{total} = {agent_rate:.1%}")
    print(f"误报（自报✓设备✗）: {agent_pass - passed_verify}  漏报（自报✗设备✓）: {passed_verify - agent_pass}")
    print(f"总步数 {total_steps} | 总成本 ${total_cost:.2f} | 耗时 {(time.time()-t_start)/60:.0f}min")

    _flush_report(report_dir, case_records, total, passed_verify, agent_pass,
                  total_steps, total_cost, t_start, done=True)
    return 0


def _flush_report(report_dir, records, total, passed_verify, agent_pass,
                  total_steps, total_cost, t_start, done: bool = False) -> None:
    summary = {
        "total": total,
        "passed_verify": passed_verify,
        "success_rate": round(passed_verify / total, 4) if total else 0.0,
        "agent_pass": agent_pass,
        "agent_rate": round(agent_pass / total, 4) if total else 0.0,
        "total_steps": total_steps,
        "total_cost_usd": round(total_cost, 2),
        "elapsed_min": round((time.time() - t_start) / 60, 1),
        "done": done,
        "cases": records,
    }
    with open(report_dir / "report.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
