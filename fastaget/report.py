"""报告生成。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastaget.agent.types import Step
from fastaget.cases import Case
from fastaget.format.console import Console


@dataclass
class CaseReport:
    name: str
    goal: str
    success: bool
    summary: str
    steps: int
    cost_usd: float
    healed_count: int
    agent_asserts: list[dict[str, Any]] = field(default_factory=list)
    expected_asserts: list[dict[str, Any]] = field(default_factory=list)
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    # 市后验证（AndroidWorld 式独立判定）
    verified: bool | None = None        # None = 无验证规则，True/False = 验证结果
    verify_detail: str = ""             # 验证失败的原因描述
    agent_claimed_success: bool = False  # agent 原始声称（verify 修正前），用于误报统计

    @classmethod
    def build(cls, case: Case, result: "AgentResult") -> "CaseReport":  # noqa: F821
        healed = sum(1 for s in result.steps_detail if s.healed)
        agent_asserts = [
            {"description": s.args.get("description", ""), "passed": s.args.get("passed", False)}
            for s in result.steps_detail if s.action == "assert"
        ]
        expected_asserts = [
            {"description": a.description, "expected": a.expected}
            for a in case.asserts
        ]
        return cls(
            name=case.name,
            goal=case.goal,
            success=result.success,
            summary=result.summary,
            steps=result.steps,
            cost_usd=round(result.total_cost_usd, 4),
            healed_count=healed,
            agent_asserts=agent_asserts,
            expected_asserts=expected_asserts,
            trajectory=[_step_dict(s) for s in result.steps_detail],
            agent_claimed_success=result.success,  # 记录 agent 原始声称（verify 修正前）
        )


@dataclass
class SuiteReport:
    cases: list[CaseReport] = field(default_factory=list)

    def add(self, r: CaseReport) -> None:
        self.cases.append(r)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.success)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.cases), 4)

    def to_text(self) -> str:
        lines = [Console.report_header(self.total)]
        lines.append("")  # header 后空一行
        for c in self.cases:
            # 验证状态列
            if c.verified is None:
                v_tag = ""
            elif c.verified:
                v_tag = Console.OK
            else:
                v_tag = Console.BAD
            lines.append(Console.case_card(
                success=c.success,
                name=c.name,
                goal=c.goal,
                steps=c.steps,
                cost=c.cost_usd,
                summary=c.summary,
                healed=c.healed_count,
                verify_tag=v_tag,
                verify_detail=c.verify_detail,
                agent_asserts=c.agent_asserts,
                expected_asserts=c.expected_asserts,
            ))
            lines.append("")  # case 间空一行
        # 汇总：agent 声称 vs 设备验证
        agent_pass = sum(1 for c in self.cases if c.agent_claimed_success)
        verify_pass = sum(1 for c in self.cases if c.verified is True)
        verify_total = sum(1 for c in self.cases if c.verified is not None)
        false_pos = sum(1 for c in self.cases if c.agent_claimed_success and c.verified is False)
        false_neg = sum(1 for c in self.cases if not c.agent_claimed_success and c.verified is True)
        lines.append(Console.suite_summary_section(
            agent_pass, self.total, cost=self.cost_usd,
            verify_pass=verify_pass, verify_total=verify_total,
            false_pos=false_pos, false_neg=false_neg,
        ))
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "passed": self.passed,
                "total": self.total,
                "cost_usd": self.cost_usd,
                "verify_passed": sum(1 for c in self.cases if c.verified is True),
                "verify_total": sum(1 for c in self.cases if c.verified is not None),
                # 误报/漏报基于 agent 原始声称（修正前），反映 agent 自报可靠性
                "false_positives": sum(1 for c in self.cases if c.agent_claimed_success and c.verified is False),
                "false_negatives": sum(1 for c in self.cases if not c.agent_claimed_success and c.verified is True),
                "agent_claimed_passed": sum(1 for c in self.cases if c.agent_claimed_success),
                "cases": [asdict(c) for c in self.cases],
            },
            ensure_ascii=False, indent=2,
        )

    def save(self, text_path: str | Path | None = None, json_path: str | Path | None = None) -> None:
        if text_path:
            Path(text_path).write_text(self.to_text(), encoding="utf-8")
        if json_path:
            Path(json_path).write_text(self.to_json(), encoding="utf-8")


def _step_dict(s: Step) -> dict[str, Any]:
    return {
        "index": s.index,
        "action": s.action,
        "args": s.args,
        "result": s.result,
        "success": s.success,
        "elapsed": round(s.elapsed, 3),
        "cost_usd": s.cost_usd,
        "healed": s.healed,
    }
