"""FlowRunner 集成测试：mock LLM，真机 observe。

验证：
  1. precondition 闭环
  2. DAG 遍历 + 分支命中
  3. expect rule 求值
  4. teardown 执行
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastaget.agent.fast_agent import AgentResult
from fastaget.agent.types import Step
from fastaget.flow.case import FlowCase
from fastaget.flow.runner import FlowRunner


def _mock_agent_result(success: bool, summary: str = "ok") -> AgentResult:
    return AgentResult(
        success=success, summary=summary, steps=1,
        total_cost_usd=0.001, steps_detail=[
            Step(index=1, thought="", action="observe", args={},
                 result=summary, success=success, elapsed=0.1)
        ],
    )


def _make_screen(text: str) -> str:
    """生成 UIState 可解析的屏幕文本。"""
    return f'[0] text="{text}" (TextView) bounds=[0,0][100,50]'


def test_flow_runner_precondition_fail_skip():
    """precondition 不满足 → SKIP 用例。"""
    case = FlowCase.from_dict({
        "name": "pre_fail",
        "precondition": [{
            "description": "屏幕必须有不存在文本",
            "check": "{screen.has_text:ZZZZZ_NOT_EXIST}",
            "judge": "rule",
            "severity": "critical",
        }],
        "flow": [{"id": "a", "goal": "test", "mode": "guided"}],
    })

    pf = MagicMock()
    pf.observe.return_value = MagicMock(elements_text=_make_screen("hello"), image_b64="")

    runner = FlowRunner(
        execute_llm=MagicMock(), judge_llm=None,
        phonefast=pf, registry=MagicMock(),
        verbose=False,
    )
    result = runner.run(case)
    assert not result.precondition_passed
    assert not result.success
    assert result.path == []  # 没执行 flow


def test_flow_runner_basic_traversal():
    """基本 DAG 遍历：precondition 过 → 执行 node → expect 通过。"""
    case = FlowCase.from_dict({
        "name": "basic",
        "precondition": [{
            "description": "屏幕有 hello",
            "check": "{screen.has_text:hello}",
            "judge": "rule",
            "severity": "critical",
        }],
        "flow": [
            {"id": "a", "goal": "do A", "mode": "guided"},
            {"id": "b", "goal": "do B", "mode": "guided"},
        ],
        "expect": [{
            "description": "屏幕有 hello",
            "check": "{screen.has_text:hello}",
            "judge": "rule",
            "severity": "critical",
        }],
    })

    pf = MagicMock()
    pf.observe.return_value = MagicMock(elements_text=_make_screen("hello world"), image_b64="")

    runner = FlowRunner(
        execute_llm=MagicMock(), judge_llm=None,
        phonefast=pf, registry=MagicMock(),
        verbose=False,
    )

    # mock _execute_node 返回成功
    from fastaget.flow.context import StepResult
    runner._execute_node = MagicMock(return_value=StepResult(
        node_id="a", success=True, summary="ok",
    ))

    result = runner.run(case)
    assert result.precondition_passed
    assert result.success
    assert result.path == ["a", "b"]


def test_flow_runner_branch_routing():
    """分支路由：node A 根据屏幕条件跳到 B 或 C。"""
    case = FlowCase.from_dict({
        "name": "branch",
        "flow": [
            {
                "id": "a", "goal": "do A", "mode": "guided",
                "branches": [
                    {"when": "{screen.has_text:GO_B}", "to": "b"},
                    {"when": "{screen.has_text:GO_C}", "to": "c"},
                    {"when": "default", "to": "b"},
                ],
            },
            {"id": "b", "goal": "do B", "mode": "guided"},
            {"id": "c", "goal": "do C", "mode": "guided"},
        ],
    })

    pf = MagicMock()
    pf.observe.return_value = MagicMock(elements_text=_make_screen("GO_C"), image_b64="")

    runner = FlowRunner(
        execute_llm=MagicMock(), judge_llm=None,
        phonefast=pf, registry=MagicMock(),
        verbose=False,
    )
    from fastaget.flow.context import StepResult
    runner._execute_node = MagicMock(return_value=StepResult(
        node_id="x", success=True, summary="ok",
    ))

    result = runner.run(case)
    assert result.path == ["a", "c"]


def test_flow_runner_expect_critical_fail_stops():
    """expect critical 失败 → 终止 flow。"""
    case = FlowCase.from_dict({
        "name": "expect_fail",
        "flow": [
            {
                "id": "a", "goal": "do A", "mode": "guided",
                "expect": [{
                    "description": "必须有特定文本",
                    "check": "{screen.has_text:SPECIAL}",
                    "judge": "rule",
                    "severity": "critical",
                }],
            },
            {"id": "b", "goal": "do B", "mode": "guided"},
        ],
    })

    pf = MagicMock()
    pf.observe.return_value = MagicMock(elements_text=_make_screen("hello"), image_b64="")

    runner = FlowRunner(
        execute_llm=MagicMock(), judge_llm=None,
        phonefast=pf, registry=MagicMock(),
        verbose=False,
    )
    from fastaget.flow.context import StepResult
    runner._execute_node = MagicMock(return_value=StepResult(
        node_id="a", success=True, summary="ok",
    ))

    result = runner.run(case)
    assert not result.success
    assert result.path == ["a"]  # b 没执行
    assert len(result.expect_records) == 1
    assert not result.expect_records[0].passed


def test_flow_runner_teardown_always_runs():
    """teardown 无论成功失败都执行。"""
    case = FlowCase.from_dict({
        "name": "teardown_test",
        "flow": [
            {
                "id": "a", "goal": "do A", "mode": "guided",
                "expect": [{
                    "description": "必须失败的条件",
                    "check": "{screen.has_text:NOT_EXIST}",
                    "judge": "rule",
                    "severity": "critical",
                }],
            },
        ],
        "teardown": [
            {"id": "cleanup", "goal": "cleanup", "mode": "guided"},
        ],
    })

    pf = MagicMock()
    pf.observe.return_value = MagicMock(elements_text=_make_screen("hello"), image_b64="")

    runner = FlowRunner(
        execute_llm=MagicMock(), judge_llm=None,
        phonefast=pf, registry=MagicMock(),
        verbose=False,
    )
    from fastaget.flow.context import StepResult
    runner._execute_node = MagicMock(return_value=StepResult(
        node_id="x", success=True, summary="ok",
    ))

    result = runner.run(case)
    assert not result.success  # expect 失败
    assert len(result.teardown_results) == 1  # teardown 仍执行
    # teardown 的 StepResult node_id 来自 _execute_node 的返回值（mock 固定 "x"）


def test_flow_runner_loop_iteration():
    """loop 结构：最多迭代 N 次。"""
    case = FlowCase.from_dict({
        "name": "loop_test",
        "flow": [
            {
                "id": "retry", "goal": "retry", "mode": "guided",
                "loop": {
                    "max_iterations": 3,
                    "break_when": "{screen.has_text:DONE}",
                    "counter_var": "attempt",
                },
                "branches": [
                    {"when": "default", "to": "end"},
                ],
            },
            {"id": "end", "goal": "end", "mode": "guided"},
        ],
    })

    pf = MagicMock()
    pf.observe.return_value = MagicMock(elements_text=_make_screen("NOT_DONE"), image_b64="")

    runner = FlowRunner(
        execute_llm=MagicMock(), judge_llm=None,
        phonefast=pf, registry=MagicMock(),
        verbose=False,
    )
    from fastaget.flow.context import StepResult
    runner._execute_node = MagicMock(return_value=StepResult(
        node_id="retry", success=True, summary="ok",
    ))

    result = runner.run(case)
    # 应该迭代 3 次后走 default 分支到 retry... 实际上 default 分支 to=retry 会无限循环
    # 但 max_iterations 到了之后会走 default 分支
    # path 应该包含 retry 多次 + end
    assert "end" in result.path
    # retry 出现次数 <= 3
    assert result.path.count("retry") <= 3
