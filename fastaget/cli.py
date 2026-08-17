"""fastaget CLI 入口。

命令：
  fastaget devices          列出已连接设备
  fastaget observe          observe 一次并打印 UI 元素
  fastaget run "<goal>"     用 LLM agent 执行测试目标
  fastaget doctor           诊断执行器 + 模型配置
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from fastaget.device.phonefast import Phonefast, PhonefastError
from fastaget.device.uiprocessor import processor
from fastaget.format.console import Console
from fastaget.tools import build_registry
from fastaget.tools.credential import CredentialManager


# ── reset 配置常量 ──
_RESET_HOME_WAIT_SEC = 0.6          # home 后等待 launcher 渲染
_RESET_MIN_ELEMENTS = 3             # 正常桌面至少有几个图标/文字
_RESET_MAX_RETRIES = 2              # 重试次数


def _reset_device(pf: Phonefast, verbose: bool = False) -> None:
    """重置设备到桌面，确保 a11y 元素可读。

    问题背景：国产 ROM（TECNO 等）home() 后 launcher 可能未立即
    渲染 a11y 树，导致 initial observe 返回 0 元素，agent 误判
    屏幕状态。此外前置 case 可能把设备留在 a11y 阻塞的界面
    （如 Google Play 主页）。

    策略：home → wait → observe 验证 → 元素不足时 force-stop
    前台 app + 重试 home，最多 2 轮。
    """
    for attempt in range(1, _RESET_MAX_RETRIES + 1):
        try:
            pf.home()
        except PhonefastError:
            if verbose:
                print(Console.reset_step(f"home() 失败 (attempt {attempt})"))
        time.sleep(_RESET_HOME_WAIT_SEC)

        # 验证 a11y 树是否有元素
        try:
            raw = pf.observe(max_elements=40)
            # 去除尾部空行再计数，防止 trailing newline 虚增元素数
            element_count = raw.elements_text.strip().count("\n") + 1 if raw.elements_text and raw.elements_text.strip() else 0
        except PhonefastError:
            element_count = 0

        if element_count >= _RESET_MIN_ELEMENTS:
            if verbose and attempt > 1:
                print(Console.reset_step(f"a11y OK ({element_count} 元素, attempt {attempt})"))
            return

        # 元素不足 → 尝试 force-stop 前台 app 后重试
        if verbose:
            print(Console.reset_step(f"observe 仅 {element_count} 元素（需 "
                  f">= {_RESET_MIN_ELEMENTS} ），attempt {attempt}"))
        try:
            current_pkg = pf.shell(
                "dumpsys activity activities 2>/dev/null | "
                "grep -E 'mResumedActivity|mFocusedActivity' | "
                "tail -1 | awk '{print $4}' | cut -d'/' -f1"
            ).strip()
            if current_pkg and current_pkg not in ("", "com.android.launcher", "com.android.systemui"):
                pf.shell(f"am force-stop {current_pkg}")
                if verbose:
                    print(Console.reset_step(f"force-stop {current_pkg}"))
        except PhonefastError:
            pass

    # 最终验证（静默，不阻断 case）
    try:
        raw = pf.observe(max_elements=40)
        final_count = raw.elements_text.count("\n") + 1 if raw.elements_text else 0
    except PhonefastError:
        final_count = 0
    if verbose and final_count < _RESET_MIN_ELEMENTS:
        print(Console.warn(f"重试 {_RESET_MAX_RETRIES} 次后仍有仅 "
              f"{final_count} 个 a11y 元素，继续执行"))


def _load_credentials() -> CredentialManager | None:
    """加载 meta/credentials.yml（不存在则返回 None，不炸 agent）。"""
    from pathlib import Path
    default = Path(__file__).resolve().parent / "meta" / "credentials.yml"
    if not default.is_file():
        return None
    cm = CredentialManager()
    n = cm.load_yaml(default)
    if n == 0:
        return None
    return cm


def _check_token() -> int:
    """检查 ANTHROPIC_AUTH_TOKEN 环境变量，未设置打印错误返回 2。"""
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    if not token:
        print("未配置模型凭证。请设置环境变量 "
              "ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY", file=sys.stderr)
        return 2
    return 0


def _save_report(suite, report_dir: str, prefix: str = "") -> None:
    """统一报告落盘：创建目录 + 保存 text/json。"""
    d = Path(report_dir)
    d.mkdir(parents=True, exist_ok=True)
    suite.save(d / f"{prefix}report.txt" if prefix else d / "report.txt",
               d / f"{prefix}report.json" if prefix else d / "report.json")
    print(f"\n报告已写入 {d}/")


def cmd_devices(pf: Phonefast) -> int:
    # 设备列表是 CLI 管理功能，不属于 Phonefast RPC 客户端
    import subprocess
    binary = os.environ.get("PHONEFAST_BINARY", "phonefast")
    proc = subprocess.run([binary, "devices"], capture_output=True, text=True, timeout=10)
    print(proc.stdout.strip())
    return 0


def cmd_observe(pf: Phonefast) -> int:
    raw = pf.observe()
    _, elements_text = processor.process(raw.elements_text)
    print(elements_text)
    return 0


def cmd_doctor(pf: Phonefast, args: argparse.Namespace) -> int:
    from rich.console import Console as RichConsole
    from rich.panel import Panel
    rc = RichConsole(highlight=False)

    all_ok = True

    # ── Section 1: phonefast daemon ──
    try:
        st = pf.status()
        text = (f"[bold]pid[/] {st.get('pid')}    "
                f"[bold]device[/] {st.get('serial')}    "
                f"[bold]resolution[/] {st.get('device_width')}x{st.get('device_height')}")
        rc.print(Panel(text, title="[bold]Phonefast Daemon[/]",
                       border_style="green", padding=(1, 2)))
    except PhonefastError as e:
        all_ok = False
        rc.print(Panel(f"[bold red]{e}[/]",
                       title="[bold]Phonefast Daemon[/]",
                       border_style="red", padding=(1, 2)))

    # ── Section 2: device observe ──
    try:
        raw = pf.observe()
        state, _ = processor.process(raw.elements_text)
        rc.print(Panel(f"[bold]{len(state.elements)}[/] interactive elements detected",
                       title="[bold]Device Observe[/]",
                       border_style="green", padding=(1, 2)))
    except PhonefastError as e:
        all_ok = False
        rc.print(Panel(f"[bold red]{e}[/]",
                       title="[bold]Device Observe[/]",
                       border_style="red", padding=(1, 2)))

    # ── Section 3: LLM delegate ──
    try:
        from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate
        d = AnthropicHTTPDelegate(model=args.model)
        d._require_token()
        rc.print(Panel(f"Model [bold cyan]{args.model}[/]  →  [dim]{d._base_url}[/]",
                       title="[bold]LLM Delegate[/]",
                       border_style="green", padding=(1, 2)))
        d.close()
    except Exception as e:
        all_ok = False
        rc.print(Panel(f"[bold red]{e}[/]",
                       title="[bold]LLM Delegate[/]",
                       border_style="red", padding=(1, 2)))

    return 0 if all_ok else 1


def cmd_flow_run(pf: Phonefast, args: argparse.Namespace) -> int:
    from fastaget.flow.case import load_flow_cases
    from fastaget.flow.report import FlowSuiteReport
    from fastaget.flow.runner import FlowRunner
    from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate
    from fastaget.llm.delegate import LLMDelegate
    from fastaget.tools import build_registry

    if rc := _check_token():
        return rc

    cases = load_flow_cases(args.file)
    if not cases:
        print(f"flow 文件 {args.file} 无用例", file=sys.stderr)
        return 2

    suite = FlowSuiteReport()
    _delegate_cache: dict[str, LLMDelegate] = {}

    def _get_delegate(model: str) -> LLMDelegate:
        if model not in _delegate_cache:
            _delegate_cache[model] = AnthropicHTTPDelegate(model=model)
        return _delegate_cache[model]

    for i, case in enumerate(cases, 1):
        exec_model = case.model or args.model
        judge_model = case.judge_model or args.judge_model or exec_model
        print(Console.case_banner(i, len(cases), case.name,
                                  exec_model, 0,
                                  f"judge={judge_model}" if judge_model != exec_model else ""))

        exec_llm = _get_delegate(exec_model)
        judge_llm = _get_delegate(judge_model) if judge_model != exec_model else None
        cred_mgr = _load_credentials()
        registry = build_registry(capabilities=pf.FULL_CAPABILITIES, credential_manager=cred_mgr)

        try:
            runner = FlowRunner(
                execute_llm=exec_llm, judge_llm=judge_llm,
                phonefast=pf, registry=registry,
                verbose=True, verbose_timing=not args.no_timing,
                trace=args.trace, trace_dir=args.trace_dir,
                auto_observe=args.trace_auto_observe,
            )
            result = runner.run(case)
        except Exception as e:
            import traceback
            print(f"  [ERROR] flow 执行异常: {e}", file=sys.stderr)
            traceback.print_exc()
            from fastaget.flow.runner import FlowResult
            result = FlowResult(
                case_name=case.name, success=False,
                summary=f"执行异常: {e}", precondition_passed=True,
            )
        suite.add(result)

    for d in _delegate_cache.values():
        d.close()
    print("\n" + suite.to_text())

    if args.report_dir:
        _save_report(suite, args.report_dir, prefix="flow_")

    return 0 if suite.passed == suite.total else 1


def cmd_run(pf: Phonefast, args: argparse.Namespace) -> int:
    from fastaget.agent.fast_agent import Capabilities, FastAgent, AgentResult
    from fastaget.agent.session import Session
    from fastaget.cases import Case
    from fastaget.report import CaseReport, SuiteReport
    from fastaget.llm.delegate import LLMDelegate

    if rc := _check_token():
        return rc

    def _make_delegate(model: str) -> LLMDelegate:
        from fastaget.llm.anthropic_http_delegate import AnthropicHTTPDelegate
        if args.verbose_timing:
            print(Console.delegate(model))
        return AnthropicHTTPDelegate(model=model)

    cases: list[Case]
    if args.file:
        from fastaget.cases import load_cases
        cases = load_cases(args.file)
        if not cases:
            print(f"用例文件 {args.file} 无用例", file=sys.stderr)
            return 2
    elif args.goal:
        short = args.goal[:16].replace("\n", " ")
        cases = [Case(name=short, goal=args.goal)]
    else:
        print("错误：需要提供测试目标，或用 -f 指定用例文件", file=sys.stderr)
        return 2

    suite = SuiteReport()
    _delegate_cache: dict[str, LLMDelegate] = {}
    for i, case in enumerate(cases, 1):
        model = case.model or args.model
        max_steps = case.max_steps or args.max_steps
        thresh = case.error_thresh if case.error_thresh is not None else args.error_thresh

        # 构建 capabilities——error_thresh 注入 FaultTolerance.limit
        # 注意：thresh 允许为 0（禁用容错），None 表示不注入此 capability
        from fastaget.agent.capabilities import FaultTolerance
        llm_failure_caps = [FaultTolerance(limit=thresh)] if thresh is not None else None

        if case.reset:
            _reset_device(pf, verbose=args.verbose_timing)

        # ── 事前初始化：AndroidWorld 式 initialize_task —— 预置文件/数据/状态 ──
        for init in (case.initialize or []):
            try:
                cmd = init.get('command', '')
                if cmd:
                    pf.shell(cmd)
                    if args.verbose_timing:
                        print(Console.init_step(cmd))
            except Exception as e:
                import logging
                _log = logging.getLogger(__name__)
                _log.warning("Case init command failed [%s]: %s", case.name, e)
                if args.verbose_timing:
                    print(Console.warn(f"init 失败 [{cmd[:50]}]: {e}"))

        mode_tags = []
        if args.vision:
            mode_tags.append("视觉")
        mode_tags.append("直接")
        mode_str = "，".join(mode_tags)
        print(Console.case_banner(i, len(cases), case.name, model, max_steps, mode_str))

        llm = _delegate_cache.get(model)
        if llm is None:
            llm = _make_delegate(model)
            _delegate_cache[model] = llm
        cred_mgr = _load_credentials()
        registry = build_registry(capabilities=pf.FULL_CAPABILITIES, credential_manager=cred_mgr)

        try:
            # ── 前置条件门控（PI before_task 模式）──
            precondition_caps = None
            if case.precondition:
                from fastaget.agent.precondition import PreconditionGate
                from fastaget.flow.expectation import Expectation, ExpectationEvaluator
                from fastaget.flow.condition import ConditionEvaluator
                expectations = [Expectation.from_dict(p) for p in case.precondition]
                evaluator = ExpectationEvaluator(
                    condition_eval=ConditionEvaluator(), phonefast=pf,
                )
                precondition_caps = [PreconditionGate(
                    expectations=expectations, evaluator=evaluator, phonefast=pf,
                )]
                if args.verbose_timing:
                    print(Console.precondition(len(expectations)))

            caps = Capabilities(pre_run=precondition_caps, llm_failure=llm_failure_caps) if (precondition_caps or llm_failure_caps) else None
            hooks = None
            if args.verbose_timing:
                from fastaget.agent.hooks import ConsoleHook
                hooks = [ConsoleHook()]
            agent = FastAgent(llm, pf, registry, max_steps=max_steps,
                              capabilities=caps, hooks=hooks,
                              credential_manager=cred_mgr)
            session = Session(agent=agent, trace=args.trace)
            result = session.run(case.goal)
            session.flush()
            report = CaseReport.build(case, result)
            # ── 市后验证：AndroidWorld 式独立判定（agent 不知道、不受影响）──
            if case.verifications:
                from fastaget.verify import VerificationSpec, run_verification
                specs = [VerificationSpec.from_dict(v) for v in case.verifications]
                v_results = run_verification(specs, pf)
                all_ok = all(r.passed for r in v_results)
                failures = [r for r in v_results if not r.passed]
                report.verified = all_ok
                if failures:
                    report.verify_detail = "; ".join(
                        f"[{f.spec.command[:40]}] {f.reason()}" for f in failures
                    )
                # AW 式判定：设备验证是唯一真相
                # agent 声称成功但设备验证失败 → 修正为失败（false positive）
                if report.success and not all_ok:
                    report.success = False
                    report.summary = f"{report.summary} [VERIFY_FAIL: {report.verify_detail}]"
                    print(Console.warn(f"设备验证失败: {report.verify_detail}"))
                # agent 声称失败但设备验证通过 → 修正为通过（false negative）
                # 防 LLM 失败误判：0 步 $0 成本 → agent 根本没执行，不修正
                if not report.success and all_ok and result.steps > 0:
                    report.success = True
                    report.summary = f"【验证覆盖】{report.summary}"
                    print(Console.warn("验证覆盖: agent 声称失败但设备验证通过 → 修正为 PASS"))

        except Exception as e:
            import traceback
            print(Console.error(str(e)), file=sys.stderr)
            traceback.print_exc()
            report = CaseReport.build(case, AgentResult(
                session_id="error",
                success=False, summary=f"执行异常: {e}", steps=0,
                total_cost_usd=0.0, steps_detail=[],
            ))
        suite.add(report)

    for d in _delegate_cache.values():
        d.close()
    if len(cases) > 1 or not args.verbose_timing:
        # 单 case + verbose：逐步输出已是报告，不重复打印卡片
        print(suite.to_text())

    if args.report_dir:
        _save_report(suite, args.report_dir)

    return 0 if suite.passed == suite.total else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="fastaget", description="快速、自愈的 Android 测试 Agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="列出已连接设备")
    sub.add_parser("observe", help="observe 一次并打印 UI 元素")
    p_doc = sub.add_parser("doctor", help="诊断执行器与模型配置")
    p_doc.add_argument("--model", default="deepseek-v4-pro", help="模型名")

    p_run = sub.add_parser("run", help="用 LLM agent 执行测试目标")
    p_run.add_argument("goal", nargs="?", default="", help="测试目标（自然语言）；与 -f 二选一")
    p_run.add_argument("-f", "--file", help="用例 YAML 文件（可批量）")
    p_run.add_argument("--model", default="deepseek-v4-pro", help="模型名（默认 deepseek-v4-pro）")
    p_run.add_argument("--serial", default="", help="目标设备 serial（多设备时必须指定，防止连错；单设备自动检测）")
    p_run.add_argument("--max-steps", type=int, default=15, help="最大步数（默认 15）")
    p_run.add_argument("--error-thresh", type=int, default=3, help="连续失败阈值（默认 3）")
    p_run.add_argument("--report-dir", help="报告写入目录")
    p_run.add_argument("--vision", action="store_true", help="视觉模式：截图喂多模态模型")
    p_run.add_argument("--verbose-timing", action="store_true", help="打印每步耗时、LLM 决策、工具执行详情")
    p_run.add_argument("--trace", action="store_true",
                       help="为每个 run 产出 LLM 动作重放日志（build/traces/<run_id>.*）")
    p_run.add_argument("--trace-dir", default="build/traces", help="重放日志输出目录")
    p_run.add_argument("--trace-auto-observe", action="store_true",
                       help="富模式：每个操作类工具后额外 observe（会改变运行行为，仅重放场景用）")

    p_flow = sub.add_parser("flow", help="声明式流程图测试")
    flow_sub = p_flow.add_subparsers(dest="flow_cmd", required=True)
    p_flow_run = flow_sub.add_parser("run", help="执行 flow YAML")
    p_flow_run.add_argument("-f", "--file", required=True, help="flow YAML 文件")
    p_flow_run.add_argument("--serial", default="", help="目标设备 serial（多设备时必须指定，防止连错；单设备自动检测）")
    p_flow_run.add_argument("--model", default="deepseek-v4-pro", help="执行模型（默认 deepseek-v4-pro）")
    p_flow_run.add_argument("--judge-model", default="", help="判定模型（默认与执行模型相同）")
    p_flow_run.add_argument("--report-dir", help="报告写入目录")
    p_flow_run.add_argument("--no-timing", action="store_true", help="关闭每步耗时打印（默认开启）")
    p_flow_run.add_argument("--trace", action="store_true",
                            help="为每个 node 的 run 产出 LLM 动作重放日志（build/traces/<run_id>.*）")
    p_flow_run.add_argument("--trace-dir", default="build/traces", help="重放日志输出目录")
    p_flow_run.add_argument("--trace-auto-observe", action="store_true",
                            help="富模式：每个操作类工具后额外 observe（会改变运行行为，仅重放场景用）")

    args = parser.parse_args(argv)
    pf = Phonefast(serial=getattr(args, "serial", "") or None)

    if args.cmd == "devices":
        return cmd_devices(pf)
    if args.cmd == "observe":
        return cmd_observe(pf)
    if args.cmd == "doctor":
        return cmd_doctor(pf, args)
    if args.cmd == "run":
        return cmd_run(pf, args)
    if args.cmd == "flow":
        if args.flow_cmd == "run":
            return cmd_flow_run(pf, args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
