#!/usr/bin/env python3
"""fastaget 评测运行器——每 case 刷新进度文件。

用法:
  python3 scripts/run_eval.py --smoke         # 先跑 4 个 case 验证
  python3 scripts/run_eval.py                 # 全量 116 case

tail -f build/eval/fa_run01/report.txt     # 实时看进度
"""
from __future__ import annotations

import os, re, sys, time, argparse, json, subprocess
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

# ── LLM 端点常量（构造函数直传，不依赖 env）──
LLM_BASE_URL = "https://api.deepseek.com/anthropic"
LLM_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY") or ""
DEVICE_SERIAL = "emulator-5554"
SMOKE_CASES = ["AW-CameraTakePhoto", "AW-CameraTakeVideo",
               "AW-SystemBluetoothTurnOn", "AW-SystemWifiTurnOff"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="fastaget 评测运行器")
    p.add_argument("--file", "-f", default=str(PROJ / "fastaget/meta/eval_cases_aw_aligned.yml"))
    p.add_argument("--model", "-m", default="deepseek-v4-pro")
    p.add_argument("--temperature", type=float, default=0.0,
                   help="LLM 采样温度（默认 0=确定性，消除评测方差）")
    p.add_argument("--max-steps", default=30, type=int)
    p.add_argument("--run-id", default="run01")
    p.add_argument("--report-dir", default=str(PROJ / "build/eval"))
    p.add_argument("--smoke", action="store_true", help="只跑 smoke 用例（4 个）")
    p.add_argument("--only", default="", help="只跑名称含此子串的 case（逗号分隔多个）")
    return p.parse_args()


def _run_init(pf: "Phonefast", cmd: str) -> None:
    """执行一条 initialize 命令。

    设备内命令走 pf.shell（adb shell）。`adb ...` 前缀命令是 HOST 侧命令
    （如 `adb emu sms send`）——设备内没有 adb 二进制，必须在宿主上执行，
    并注入评测 serial。
    """
    cmd = (cmd or "").strip()
    if not cmd:
        return
    if cmd.startswith("adb "):
        # cwd=PROJ：host 侧命令里引用的相对路径（如 adb push fastaget/meta/assets/...）
        # 一律相对 repo 根解析——与启动目录无关（CWD 健壮性）
        subprocess.run(
            f"adb -s {pf.serial} {cmd[len('adb '):]}",
            shell=True, capture_output=True, text=True, timeout=60,
            cwd=str(PROJ),
        )
    else:
        pf.shell(cmd)


def main() -> int:
    args = parse_args()

    # ── 导入（env 无关，构造函数直传参数）──
    from fastaget.cases import load_cases
    from fastaget.device.phonefast import Phonefast, PhonefastError
    from fastaget.tools import build_registry
    from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate
    from fastaget.agent.fast_agent import Capabilities, FastAgent
    from fastaget.agent.session import Session
    from fastaget.verify import VerificationSpec, run_verification
    from fastaget.flow.expectation import Expectation, ExpectationEvaluator
    from fastaget.flow.condition import ConditionEvaluator
    from fastaget.agent.precondition import PreconditionGate

    # ── 报告目录 ──
    report_dir = Path(args.report_dir) / f"fa_{args.run_id}"
    report_dir.mkdir(parents=True, exist_ok=True)
    progress_path = report_dir / "report.txt"
    json_path = report_dir / "report.json"

    # ── 连接设备 ──
    pf = Phonefast(serial=DEVICE_SERIAL)
    # 评测前强制重启 daemon：长跑（2h+）中 UI 子进程会失联（observe 报
    # "connect ui socket: connection refused"），主进程无自愈。干净 daemon 防退化。
    # （SimpleCalendar 集群 8/8 失败即此根因）
    try:
        pf.restart_daemon()
    except PhonefastError:
        pass  # 重启失败不阻塞——ctx.observe 还有运行时自愈
    st = pf.status()
    dev_name = st.get("devices", ["?"])[0] if st.get("devices") else "?"
    print(f"[Env] device={dev_name} model={pf.shell('getprop ro.product.model')}")
    print(f"[Env] endpoint={LLM_BASE_URL} model={args.model}")
    print(f"[Env] report={report_dir}")
    print(f"[TIPS] tail -f {progress_path}\n")

    # ── LLM（构造函数直传，零 env 依赖）──
    # temperature 默认 0：确定性采样，消除 LLM 采样方差对评测的干扰
    # （同一 case 两次跑结果应可复现——fa_final_0813 中 13 个上轮 PASS 的 case 因方差反转失败）
    llm = AnthropicHTTPDelegate(
        model=args.model,
        base_url=LLM_BASE_URL,
        token=LLM_TOKEN,
        temperature=args.temperature,
    )
    registry = build_registry(capabilities=pf.FULL_CAPABILITIES)

    # ── 加载用例 ──
    all_cases = load_cases(args.file)
    if args.smoke:
        cases = [c for c in all_cases if c.name in SMOKE_CASES]
        print(f"[Load] SMOKE: {len(cases)}/{len(all_cases)} cases")
    elif args.only:
        subs = [s.strip() for s in args.only.split(",") if s.strip()]
        cases = [c for c in all_cases if any(s in c.name for s in subs)]
        print(f"[Load] ONLY {subs}: {len(cases)}/{len(all_cases)} cases")
    else:
        cases = all_cases
        print(f"[Load] {len(cases)} cases")

    # ── 统计 ──
    total = len(cases)
    passed_verify = 0; verify_total = 0; llm_failures = 0
    total_cost = 0.0; total_steps = 0
    case_records: list[dict] = []
    t_start = time.time()

    for i, case in enumerate(cases, 1):
        goal = case.goal
        max_steps = case.max_steps or args.max_steps

        # reset + init — always press Home to start from clean state
        try: pf.home()
        except PhonefastError: pass
        # 状态隔离：从 initialize 命令提取涉及的包（/data/data/<pkg>/ 或 /Android/data/<pkg>/）
        # 并 force-stop——防止上一 case 的 UI 残留状态（对话框/编辑页）污染本 case
        # （OsmAnd Favorite 曾因残留 "Edit Favorite" 页导致收藏保存无效）
        _PKG_RE = re.compile(r"(?:/data/data/|/Android/data/)([a-zA-Z][a-zA-Z0-9_.]+)")
        init_pkgs = set()
        for init in (case.initialize or []):
            init_pkgs.update(_PKG_RE.findall(init.get("command", "") or ""))
        for pkg in sorted(init_pkgs):
            try:
                pf.shell(f"am force-stop {pkg}")
            except Exception:
                pass
        for init in (case.initialize or []):
            try:
                _run_init(pf, init.get("command", ""))
            except Exception: pass

        # ── Precondition Gate ──
        precondition_caps = None
        if case.precondition:
            exps = [Expectation.from_dict(p) for p in case.precondition]
            ev = ExpectationEvaluator(condition_eval=ConditionEvaluator(), phonefast=pf)
            precondition_caps = [PreconditionGate(
                expectations=exps, evaluator=ev, phonefast=pf)]
            print(f"    precondition: {len(exps)} 项")

        caps = Capabilities(pre_run=precondition_caps) if precondition_caps else None
        agent = FastAgent(llm, pf, registry, max_steps=max_steps, capabilities=caps)
        session = Session(agent=agent, trace=True)

        # ── 执行 ──
        try:
            result = session.run(goal)
            session.flush()
        except Exception as e:
            import traceback; traceback.print_exc()
            result = type("R", (), {"success":False, "summary":f"异常:{e}",
                "steps":0, "total_cost_usd":0.0, "steps_detail":[], "session_id":""})()
            result = _fake_result(f"异常: {e}")

        # ── Verify ──
        verified = None; verify_detail = ""
        if case.verifications:
            specs = [VerificationSpec.from_dict(v) for v in case.verifications]
            v_results = run_verification(specs, pf)
            all_ok = all(r.passed for r in v_results)
            failures = [r for r in v_results if not r.passed]
            verified = all_ok
            if failures:
                verify_detail = "; ".join(
                    f"[{f.spec.command[:40]}] {f.reason()}" for f in failures)
            verify_total += 1

            # false positive → override
            if result.success and not all_ok:
                result = _override_result(result, False,
                    f"{result.summary} [VERIFY_FAIL: {verify_detail}]")
            # false negative → override (防线: LLM 0步 $0 不修正)
            if not result.success and all_ok:
                is_hard_fail = (result.steps == 0 and result.total_cost_usd == 0.0)
                if not is_hard_fail:
                    result = _override_result(result, True,
                        f"【验证覆盖】{result.summary}")

        # ── 统计 ──
        is_hard_fail = (result.steps == 0 and result.total_cost_usd == 0.0)
        if is_hard_fail: llm_failures += 1
        if verified: passed_verify += 1
        total_cost += result.total_cost_usd; total_steps += result.steps

        tag = "PASS" if result.success else "FAIL"
        v_tag = "✓" if verified else ("✗" if verified is False else "·")
        print(f"[{i}/{total}] {tag} {case.name} — {result.steps}步 "
              f"${result.total_cost_usd:.4f} | verify: {v_tag}")
        if result.summary:
            print(f"    {result.summary[:120]}")

        case_records.append(dict(name=case.name, goal=goal,
            success=result.success, summary=result.summary,
            steps=result.steps, cost_usd=round(result.total_cost_usd, 4),
            verified=verified, verify_detail=verify_detail))

        _flush(case_records, total, passed_verify, verify_total,
               llm_failures, total_cost, progress_path, json_path,
               time.time() - t_start)

    # ── 最终 ──
    elapsed = time.time() - t_start
    _flush(case_records, total, passed_verify, verify_total,
           llm_failures, total_cost, progress_path, json_path, elapsed,
           final=True)
    llm.close()
    print(f"\nDone. {total_steps}步 ${total_cost:.4f} {elapsed/60:.1f}min → {progress_path}")
    return 0 if (verify_total == 0 or passed_verify == verify_total) else 1


# ── helpers ──

class _FakeResult:
    def __init__(self, **kw): self.__dict__.update(kw)

def _fake_result(summary: str):
    return _FakeResult(success=False, summary=summary, steps=0,
                       total_cost_usd=0.0, steps_detail=[], session_id="")

def _override_result(r, success: bool, summary: str):
    return _FakeResult(
        success=success, summary=summary,
        steps=r.steps, total_cost_usd=r.total_cost_usd,
        steps_detail=getattr(r, "steps_detail", []),
        session_id=getattr(r, "session_id", ""),
    )

def _flush(records, total, pv, vt, lf, cost, tp, jp, elapsed, final=False):
    lines = [f"==== 进度：{len(records)}/{total} | verif: {pv}/{vt} "
             f"| LLM失败: {lf} | ${cost:.4f} | {elapsed/60:.1f}min ====\n"]
    for r in records:
        t = "PASS" if r["success"] else "FAIL"
        v = "✓" if r["verified"] else ("✗" if r["verified"] is False else "·")
        lines.append(f"[{t}] {r['name']} — {r['steps']}步 ${r['cost_usd']:.4f} | verify: {v}")
    if final:
        pa = sum(1 for r in records if r["success"])
        lines.append(f"\n==== 汇总：{pa}/{total} 通过（agent） | "
                     f"{pv}/{vt} 通过（验证） | {lf} LLM失败 "
                     f"| ${cost:.4f} | {elapsed/60:.1f}min ====")
    tp.write_text("\n".join(lines), encoding="utf-8")
    jp.write_text(json.dumps(dict(
        passed_agent=sum(1 for r in records if r["success"]),
        passed_verify=pv, verify_total=vt, llm_failures=lf,
        total=total, cost_usd=round(cost, 4),
        elapsed_min=round(elapsed/60, 1), cases=records,
    ), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
