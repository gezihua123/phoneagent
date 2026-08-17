"""报告生成测试。"""
from fastaget.agent.types import Step
from fastaget.agent.fast_agent import AgentResult
from fastaget.cases import Case, Assert
from fastaget.report import CaseReport, SuiteReport


def _step(idx: int, action: str, success: bool, args: dict | None = None) -> Step:
    return Step(
        index=idx, thought="", action=action, args=args or {},
        result=f"[{'OK' if success else 'FAIL'}] done",
        success=success, elapsed=0.1, cost_usd=None, healed=False,
    )


def _result(success: bool, detail: list[Step], cost: float = 0.05) -> AgentResult:
    return AgentResult(
        session_id="test",
        success=success, summary="done", steps=len(detail),
        total_cost_usd=cost, steps_detail=detail,
    )


def test_case_report_basic():
    case = Case(name="c", goal="g")
    detail = [
        _step(0, "observe", True),
        Step(
            index=1, thought="", action="assert",
            args={"description": "x visible", "passed": True},
            result="[OK] assert: x visible", success=True,
            elapsed=0.0, cost_usd=None, healed=False,
        ),
        _step(2, "complete", True),
    ]
    rep = CaseReport.build(case, _result(True, detail))
    assert rep.success
    assert len(rep.trajectory) == 3
    assert len(rep.agent_asserts) == 1
    assert rep.agent_asserts[0]["description"] == "x visible"
    assert rep.agent_asserts[0]["passed"] is True


def test_case_report_with_expected_asserts():
    case = Case(
        name="c", goal="g",
        asserts=[Assert(description="进入设置页", expected=True)],
    )
    rep = CaseReport.build(case, _result(True, [_step(0, "complete", True)]))
    assert len(rep.expected_asserts) == 1
    assert rep.expected_asserts[0]["description"] == "进入设置页"


def test_suite_report_text():
    case = Case(name="c", goal="g")
    suite = SuiteReport()
    suite.add(CaseReport.build(case, _result(True, [_step(0, "complete", True)])))
    suite.add(CaseReport.build(case, _result(False, [_step(0, "complete", False)])))
    text = suite.to_text()
    assert "PASS" in text
    assert "FAIL" in text
    assert "1/2" in text


def test_suite_report_json():
    case = Case(name="c", goal="g")
    suite = SuiteReport()
    suite.add(CaseReport.build(case, _result(True, [_step(0, "complete", True)])))
    j = suite.to_json()
    assert '"passed": 1' in j
    assert '"total": 1' in j
