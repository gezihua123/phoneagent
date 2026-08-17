"""Expectation：预期数据结构 + 求值器。

judge 三档：
  rule     — 纯规则，复用 ConditionEvaluator，0ms
  semantic — 纯 LLM 语义判定，复用 SemanticJudge
  hybrid   — 先查规则，规则不过时 LLM 语义兜底

expect 可带 wait（秒）：最多轮询等待 N 秒，每秒重新 observe + 求值。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from fastaget.flow.condition import ConditionEvaluator, ConditionResult
from fastaget.flow.context import ExpectRecord, FlowContext
from fastaget.flow.judge import SemanticJudge


@dataclass
class Expectation:
    """一条预期。"""
    description: str
    check: str = ""              # rule 条件表达式（judge=rule/hybrid 时用）
    judge: str = "rule"          # rule | semantic | hybrid
    severity: str = "critical"   # critical | warn
    wait: float = 0              # 最多等待秒数（0=立即求值）
    hints: list[str] | None = None  # semantic 时的提示线索

    @classmethod
    def from_dict(cls, d: dict) -> "Expectation":
        return cls(
            description=d.get("description", ""),
            check=d.get("check", ""),
            judge=d.get("judge", "rule"),
            severity=d.get("severity", "critical"),
            wait=float(d.get("wait", 0)),
            hints=d.get("hints"),
        )


class ExpectationEvaluator:
    """预期求值器。复用 ConditionEvaluator + SemanticJudge。"""

    def __init__(
        self,
        condition_eval: ConditionEvaluator,
        judge: SemanticJudge | None = None,
        phonefast: Any = None,
    ) -> None:
        self._cond = condition_eval
        self._judge = judge
        self._pf = phonefast

    def check(self, expect: Expectation, ctx: FlowContext, node_id: str = "") -> ExpectRecord:
        """校验单条 expectation，支持 wait 轮询。"""
        deadline = time.time() + expect.wait if expect.wait > 0 else 0
        t_start = time.time()

        while True:
            # wait 模式下每轮重新 observe
            if expect.wait > 0 and self._pf is not None:
                self._refresh_screen(ctx)

            rec = self._check_once(expect, ctx, node_id)
            if rec.passed:
                rec.elapsed = time.time() - t_start
                return rec

            # 无 wait 或超时
            if expect.wait <= 0 or time.time() >= deadline:
                rec.elapsed = time.time() - t_start
                return rec

            time.sleep(1)

    def check_all(
        self, expects: list[Expectation], ctx: FlowContext, node_id: str = ""
    ) -> list[ExpectRecord]:
        """校验一组 expectation。"""
        return [self.check(e, ctx, node_id) for e in expects]

    def _check_once(self, expect: Expectation, ctx: FlowContext, node_id: str) -> ExpectRecord:
        """单次求值（不轮询）。"""
        if expect.judge == "semantic":
            return self._check_semantic(expect, ctx, node_id)
        if expect.judge == "hybrid":
            return self._check_hybrid(expect, ctx, node_id)
        # 默认 rule
        return self._check_rule(expect, ctx, node_id)

    def _check_rule(self, expect: Expectation, ctx: FlowContext, node_id: str) -> ExpectRecord:
        """规则型：复用 ConditionEvaluator。"""
        result = self._cond.eval(expect.check, ctx)
        return ExpectRecord(
            node_id=node_id, description=expect.description,
            passed=result.matched, severity=expect.severity,
            judge="rule", detail=result.detail,
        )

    def _check_semantic(self, expect: Expectation, ctx: FlowContext, node_id: str) -> ExpectRecord:
        """语义型：调 SemanticJudge。"""
        if self._judge is None:
            return ExpectRecord(
                node_id=node_id, description=expect.description,
                passed=False, severity=expect.severity, judge="semantic",
                detail="no semantic judge configured",
            )
        screen_text = ctx.current_screen_text or "(no screen)"
        result = self._judge.judge(expect.description, screen_text, expect.hints)
        return ExpectRecord(
            node_id=node_id, description=expect.description,
            passed=result.satisfied, severity=expect.severity, judge="semantic",
            detail=f"conf={result.confidence:.1f} evidence={result.evidence[:120]}",
            confidence=result.confidence,
        )

    def _check_hybrid(self, expect: Expectation, ctx: FlowContext, node_id: str) -> ExpectRecord:
        """混合型：规则快速通过，规则不过时 LLM 兜底。"""
        # 先查规则
        rule_result = self._cond.eval(expect.check, ctx)
        if rule_result.matched:
            return ExpectRecord(
                node_id=node_id, description=expect.description,
                passed=True, severity=expect.severity, judge="hybrid",
                detail=f"rule passed: {rule_result.detail}",
            )
        # 规则不过 → LLM 语义兜底
        sem_rec = self._check_semantic(expect, ctx, node_id)
        sem_rec.judge = "hybrid"
        sem_rec.detail = f"rule failed({rule_result.detail}) → semantic: {sem_rec.detail}"
        return sem_rec

    def _refresh_screen(self, ctx: FlowContext) -> None:
        """重新 observe 并更新 ctx 屏幕状态。"""
        if self._pf is None:
            return
        try:
            from fastaget.device.uiprocessor import processor
            raw = self._pf.observe()
            ui, screen_text = processor.process(raw.elements_text)
            ctx.update_screen(ui, screen_text)
        except Exception:
            pass
