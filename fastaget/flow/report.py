"""Flow 报告生成。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastaget.flow.runner import FlowResult


@dataclass
class FlowSuiteReport:
    cases: list[FlowResult] = field(default_factory=list)

    def add(self, r: FlowResult) -> None:
        self.cases.append(r)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.success)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def skipped(self) -> int:
        return sum(1 for c in self.cases if not c.precondition_passed)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.cases), 4)

    def to_text(self) -> str:
        from fastaget.format.console import Console

        lines = [Console.report_header(self.total)]
        lines.append("")
        for c in self.cases:
            # 构建 detail dicts
            precondition_detail = [
                {"passed": r.passed, "description": r.description, "judge": r.judge}
                for r in (c.precondition_detail or [])
            ]
            step_expects_data = [
                {
                    "passed": r.passed,
                    "node_id": r.node_id,
                    "description": r.description,
                    "judge": r.judge,
                    "severity": r.severity,
                }
                for r in c.expect_records
                if r.node_id not in ("_case", "_precondition")
            ]
            case_expects_data = [
                {
                    "passed": r.passed,
                    "node_id": r.node_id,
                    "description": r.description,
                    "judge": r.judge,
                    "severity": r.severity,
                }
                for r in c.expect_records
                if r.node_id == "_case"
            ]
            teardown_data = [
                {"success": tr.success, "node_id": tr.node_id, "summary": tr.summary}
                for tr in (c.teardown_results or [])
            ]

            lines.append(Console.case_card_flow(
                success=(c.precondition_passed and c.success),
                name=c.case_name,
                elapsed=c.elapsed,
                cost=c.cost_usd,
                coverage=c.coverage,
                summary=c.summary,
                path=c.path,
                precondition_detail=precondition_detail,
                step_expects=step_expects_data,
                case_expects=case_expects_data,
                teardown_results=teardown_data,
                branches_missed=c.branches_missed,
            ))
            lines.append("")  # case 间空一行

        lines.append(Console.suite_summary_section(
            self.passed, self.total, cost=self.cost_usd,
            skipped=self.skipped,
        ))
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "passed": self.passed,
                "total": self.total,
                "skipped": self.skipped,
                "cost_usd": self.cost_usd,
                "cases": [asdict(c) for c in self.cases],
            },
            ensure_ascii=False, indent=2, default=str,
        )

    def save(self, text_path: str | Path | None = None, json_path: str | Path | None = None) -> None:
        if text_path:
            Path(text_path).write_text(self.to_text(), encoding="utf-8")
        if json_path:
            Path(json_path).write_text(self.to_json(), encoding="utf-8")
