"""FlowRunner：声明式流程图执行器。

核心职责：
  1. precondition 校验 → 不满足则跳过用例
  2. DAG 遍历（含 loop 回边）
  3. 每步执行后 expect 校验（critical 失败终止 flow）
  4. teardown 清理（无论成功失败都执行）
  5. 用例级 expect 最终校验

执行模式：
  guided     — 调 FastAgent.run(goal)，max_steps=1（单步）
  autonomous — 调 FastAgent.run(goal)，max_steps=node.max_steps（多步）
  wait       — 轮询 observe，检查 success_when，不调 LLM
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from fastaget.agent.fast_agent import AgentResult, FastAgent
from fastaget.device.phonefast import Phonefast, PhonefastError
from fastaget.device.uiprocessor import processor
from fastaget.flow.case import FlowCase, FlowNode
from fastaget.flow.condition import ConditionEvaluator
from fastaget.flow.context import ExpectRecord, FlowContext, StepResult
from fastaget.flow.expectation import ExpectationEvaluator
from fastaget.flow.judge import SemanticJudge
from fastaget.format.console import Console
from fastaget.llm.delegate import LLMDelegate
from fastaget.tools.registry import ToolRegistry


@dataclass
class FlowResult:
    """一个 flow case 的执行结果。"""
    case_name: str
    success: bool
    summary: str
    precondition_passed: bool
    precondition_detail: list[ExpectRecord] = field(default_factory=list)
    path: list[str] = field(default_factory=list)          # 走过的 node id 序列
    branches_hit: list[dict] = field(default_factory=list)  # 分支命中记录
    branches_missed: list[str] = field(default_factory=list)
    step_results: list[StepResult] = field(default_factory=list)
    expect_records: list[ExpectRecord] = field(default_factory=list)
    teardown_results: list[StepResult] = field(default_factory=list)
    cost_usd: float = 0.0
    elapsed: float = 0.0
    coverage: float = 0.0

    @property
    def critical_fails(self) -> list[ExpectRecord]:
        return [e for e in self.expect_records if not e.passed and e.severity == "critical"]


class FlowRunner:
    """声明式流程图执行器。"""

    # 防止无限循环的最大遍历步数
    _MAX_TRAVERSAL = 200

    def __init__(
        self,
        execute_llm: LLMDelegate,
        judge_llm: LLMDelegate | None,
        phonefast: Phonefast,
        registry: ToolRegistry,
        verbose: bool = True,
        verbose_timing: bool = False,
        trace: bool = False,
        trace_dir: str = "build/traces",
        auto_observe: bool = False,
    ) -> None:
        self._exec_llm = execute_llm
        self._phonefast = phonefast
        self._registry = registry
        self._verbose = verbose
        self._verbose_timing = verbose_timing
        self._exec_model = getattr(execute_llm, "model", None)

        # 判定 LLM（隔离），默认回退到执行 LLM
        judge = SemanticJudge(judge_llm or execute_llm)
        self._cond_eval = ConditionEvaluator(semantic_judge=judge)
        self._expect_eval = ExpectationEvaluator(
            condition_eval=self._cond_eval,
            judge=judge,
            phonefast=phonefast,
        )
        self._last_branch_info: dict = {}

        # 可选重放日志：SessionReplay 以 session 为维度聚合，每个 node 调 begin_run
        self._replay = None
        self._trace_seq = 0
        if trace:
            from fastaget.agent.trace import SessionReplay
            import uuid
            self._replay = SessionReplay(
                session_id=uuid.uuid4().hex[:12],
                output_dir=trace_dir,
                action_tool_names=registry.action_tool_names(),
            )
            self._replay.configure(
                phonefast=phonefast, processor=processor,
                action_tool_names=registry.action_tool_names(),
            )

        # 复用 FastAgent 实例：避免每个 node 重建 tools 定义 + ActionContext
        hooks_list = [self._replay] if self._replay is not None else None
        self._agent: FastAgent = FastAgent(
            execute_llm, phonefast, registry,
            max_steps=4,
            hooks=hooks_list,
        )  # type: ignore[assignment]

    def run(self, case: FlowCase) -> FlowResult:
        """执行一个 flow case。"""
        t_start = time.time()
        ctx = FlowContext(phonefast=self._phonefast)
        total_cost = 0.0
        path: list[str] = []
        branches_hit: list[dict] = []
        branches_missed: list[str] = []

        # ── Phase 1: Precondition 校验 ──
        if self._verbose and case.precondition:
            print(Console.flow_phase("precondition", len(case.precondition)))
        self._refresh_screen(ctx)
        pre_records = self._expect_eval.check_all(case.precondition, ctx, "_precondition")
        ctx._expects.extend(pre_records)
        pre_critical_fails = [r for r in pre_records if not r.passed and r.severity == "critical"]

        if pre_critical_fails:
            # 前置条件不满足 → 跳过用例（不是 FAIL，是 SKIP）
            summary = f"前置条件不满足: {pre_critical_fails[0].description}"
            if self._verbose:
                print(Console.skip(summary))
            return FlowResult(
                case_name=case.name, success=False, summary=summary,
                precondition_passed=False, precondition_detail=pre_records,
                expect_records=pre_records, elapsed=time.time() - t_start,
            )

        # ── Phase 2: Flow 遍历 ──
        summary = "flow 完成"
        if not case.flow:
            summary = "flow 为空"
        else:
            current = case.flow[0]
            traversal_count = 0
            loop_counters: dict[str, int] = {}  # node_id → 当前迭代次数

            while current and traversal_count < self._MAX_TRAVERSAL:
                traversal_count += 1
                path.append(current.id)

                # loop 计数器初始化
                if current.loop and current.loop.counter_var:
                    if current.id not in loop_counters:
                        loop_counters[current.id] = 0
                    loop_counters[current.id] += 1
                    ctx.set_var(current.loop.counter_var, loop_counters[current.id])

                # 执行 node
                step_result = self._execute_node(current, ctx)
                ctx.record_step(step_result)
                total_cost += step_result.cost_usd
                if self._verbose:
                    print(Console.flow_step(
                        step_result.success, current.id, step_result.summary,
                        step_result.elapsed, step_result.cost_usd))

                # 步骤级 expect 校验
                if current.expect or current.assert_:
                    expects = current.expect or current.assert_
                    self._refresh_screen(ctx)
                    exp_records = self._expect_eval.check_all(expects, ctx, current.id)
                    ctx._expects.extend(exp_records)
                    for r in exp_records:
                        if self._verbose:
                            print(Console.flow_expect(r.passed, r.severity, r.description, r.judge))

                    # critical 失败 → 终止 flow
                    critical_fails = [r for r in exp_records if not r.passed and r.severity == "critical"]
                    if critical_fails:
                        summary = f"步骤 {current.id} 预期失败: {critical_fails[0].description}"
                        break

                # 执行失败 + on_fail 跳转
                if not step_result.success and current.on_fail:
                    current = case.get_node(current.on_fail)
                    continue

                # ── 决定下一个节点 ──
                target = self._decide_next(current, case, ctx, loop_counters)

                # 记录分支命中/未覆盖
                if current.branches:
                    hit_info = self._last_branch_info
                    if hit_info.get("matched") and hit_info.get("source") != "default":
                        branches_hit.append({
                            "node": current.id, "branch": hit_info.get("detail", "")[:80],
                            "to": target or "",
                        })
                    for b in current.branches:
                        if b.when != "default" and b.to != target:
                            branches_missed.append(f"{current.id}:{b.when[:40]}")

                if target is None:
                    summary = step_result.summary or f"flow 结束于 {current.id}"
                    break

                next_node = case.get_node(target)
                if next_node is None:
                    summary = f"目标节点 {target} 不存在"
                    break
                current = next_node
            else:
                summary = f"遍历上限 {self._MAX_TRAVERSAL} 达到"

        # ── Phase 3: 用例级 expect 校验 ──
        if case.expect:
            self._refresh_screen(ctx)
            final_records = self._expect_eval.check_all(case.expect, ctx, "_case")
            ctx._expects.extend(final_records)
            for r in final_records:
                if self._verbose:
                    print(Console.flow_expect(r.passed, r.severity, r.description, r.judge))

        success = ctx.all_critical_passed

        # ── Phase 4: Teardown（无论成功失败都执行）──
        teardown_results: list[StepResult] = []
        if case.teardown:
            if self._verbose:
                print(Console.flow_phase("teardown", len(case.teardown)))
            for node in case.teardown:
                self._refresh_screen(ctx)
                tr = self._execute_node(node, ctx)
                teardown_results.append(tr)
                ctx.record_step(tr)
                if self._verbose:
                    print(Console.flow_step(
                        tr.success, f"teardown:{node.id}", tr.summary, 0, 0))

        elapsed = time.time() - t_start
        coverage = self._calc_coverage(branches_hit, branches_missed)

        # flush session 级 trace
        if self._replay is not None:
            try:
                self._replay.flush()
            except Exception as e:
                import logging
                _log = logging.getLogger(__name__)
                _log.warning("SessionReplay.flush() failed for [%s]: %s", case.name, e)

        return FlowResult(
            case_name=case.name, success=success,
            summary=summary if not success else "全部预期通过",
            precondition_passed=True, precondition_detail=pre_records,
            path=path, branches_hit=branches_hit, branches_missed=branches_missed,
            step_results=ctx.all_steps, expect_records=ctx.all_expects,
            teardown_results=teardown_results, cost_usd=round(total_cost, 4),
            elapsed=elapsed, coverage=coverage,
        )

    # ---- 节点执行 ----

    def _decide_next(
        self, current: FlowNode, case: FlowCase,
        ctx: FlowContext, loop_counters: dict[str, int],
    ) -> str | None:
        """决定下一个要执行的 node id。

        规则：
          1. 无分支 → 顺序流到 flow 列表中的下一个节点（末尾则 None）
          2. 有 loop 且 break_when 满足 → 走分支（跳出 loop）
          3. 有 loop 且迭代次数到上限 → 走 default 分支（跳出 loop）
          4. 有 loop 且未到上限 → 重新执行当前 node（继续 loop）
          5. 无 loop → 求值分支
        """
        self._last_branch_info = {}

        # 无分支 → 顺序流
        if not current.branches:
            idx = case.flow.index(current)
            if idx + 1 < len(case.flow):
                return case.flow[idx + 1].id
            return None

        # loop 处理
        if current.loop:
            # break_when 满足 → 跳出
            if current.loop.break_when:
                br = self._cond_eval.eval(current.loop.break_when, ctx)
                if br.matched:
                    target, hit = self._cond_eval.eval_branches(
                        [{"when": b.when, "to": b.to} for b in current.branches], ctx
                    )
                    self._last_branch_info = {
                        "matched": hit.matched, "source": hit.source, "detail": hit.detail,
                    }
                    return target
            # 迭代上限 → 跳出（走 default）
            iters = loop_counters.get(current.id, 0)
            if iters >= current.loop.max_iterations:
                target, hit = self._cond_eval.eval_branches(
                    [{"when": b.when, "to": b.to} for b in current.branches], ctx
                )
                self._last_branch_info = {
                    "matched": hit.matched, "source": hit.source, "detail": hit.detail,
                }
                return target
            # 未到上限 → 继续 loop
            return current.id

        # 普通分支求值
        target, hit = self._cond_eval.eval_branches(
            [{"when": b.when, "to": b.to} for b in current.branches], ctx
        )
        self._last_branch_info = {
            "matched": hit.matched, "source": hit.source, "detail": hit.detail,
        }
        return target

    def _execute_node(self, node: FlowNode, ctx: FlowContext) -> StepResult:
        """执行单个 node，根据 mode 分发。"""
        t_start = time.time()
        try:
            if node.mode == "wait":
                result = self._execute_wait(node, ctx)
            elif node.mode == "autonomous":
                result = self._execute_autonomous(node, ctx)
            else:
                result = self._execute_guided(node, ctx)
            elapsed = time.time() - t_start
            return StepResult(
                node_id=node.id, success=result.success,
                summary=result.summary, cost_usd=result.total_cost_usd,
                elapsed=elapsed,
            )
        except Exception as e:
            return StepResult(
                node_id=node.id, success=False,
                summary=f"node error: {e}", elapsed=time.time() - t_start,
            )

    def _execute_guided(self, node: FlowNode, ctx: FlowContext) -> AgentResult:
        """guided 模式：FastAgent 单步执行。"""
        self._agent.max_steps = 4
        self._begin_trace_run(node, max_steps=4)
        result = self._agent.run(node.goal)
        # FastAgent 内部已 observe，直接同步其 ctx 到 FlowContext，省一次重复 observe
        self._sync_ctx_from_agent(ctx)
        return result

    def _execute_autonomous(self, node: FlowNode, ctx: FlowContext) -> AgentResult:
        """autonomous 模式：FastAgent 多步执行。"""
        self._agent.max_steps = node.max_steps
        self._begin_trace_run(node, max_steps=node.max_steps)
        result = self._agent.run(node.goal)
        self._sync_ctx_from_agent(ctx)
        return result

    def _execute_wait(self, node: FlowNode, ctx: FlowContext) -> AgentResult:
        """wait 模式：轮询 observe 检查 success_when，不调 LLM。"""
        deadline = time.time() + node.timeout
        while time.time() < deadline:
            self._refresh_screen(ctx)
            if node.success_when:
                result = self._cond_eval.eval(node.success_when, ctx)
                if result.matched:
                    return AgentResult(
                        session_id="flow-wait",
                        success=True, summary=f"wait condition met: {node.success_when}",
                        steps=0, total_cost_usd=0.0, steps_detail=[],
                    )
            time.sleep(node.poll_interval)

        # 超时
        if node.on_timeout and node.on_timeout != "fail":
            return AgentResult(
                session_id="flow-wait",
                success=True, summary=f"timeout, continue to {node.on_timeout}",
                steps=0, total_cost_usd=0.0, steps_detail=[],
            )
        return AgentResult(
            session_id="flow-wait",
            success=False, summary=f"wait timeout after {node.timeout}s: {node.success_when}",
            steps=0, total_cost_usd=0.0, steps_detail=[],
        )

    # ---- 辅助 ----

    def _begin_trace_run(self, node: FlowNode, *, max_steps: int) -> None:
        """每个 node 的 agent.run 前，给复用的 SessionReplay 开一个新 run。"""
        if self._replay is None:
            return
        self._trace_seq += 1
        self._replay.begin_run(
            node.goal, scenario=node.id, variant="",
            prompt="flow", fmt="", max_steps=max_steps, vision=False,
            model=self._exec_model,
        )

    def _sync_ctx_from_agent(self, ctx: FlowContext) -> None:
        """从复用的 FastAgent.ctx 同步屏幕状态到 FlowContext。

        FastAgent.run 首步已 observe 并刷新了自身 ctx，
        直接复用其 UIState，省掉一次重复 observe（~500ms/node）。
        """
        agent_ui = self._agent.ctx.ui
        if agent_ui is not None:
            ctx.update_screen(agent_ui, processor.format(agent_ui))

    def _refresh_screen(self, ctx: FlowContext) -> None:
        """observe 并更新 ctx 屏幕状态。"""
        try:
            raw = self._phonefast.observe()
            ui, screen_text = processor.process(raw.elements_text)
            ctx.update_screen(ui, screen_text)
        except PhonefastError:
            pass

    def _calc_coverage(self, hit: list[dict], missed: list[str]) -> float:
        """计算分支覆盖率。"""
        total = len(hit) + len(missed)
        if total == 0:
            return 1.0
        return round(len(hit) / total, 2)
