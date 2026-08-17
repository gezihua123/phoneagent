"""verify.py 单测——shell 路径 + UI 路径 + from_dict 解析。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from fastaget.verify import (
    VerificationSpec,
    VerificationResult,
    run_verification,
    _evaluate,
    _evaluate_ui,
    _check_output,
)


# ── Mock phonefast ──

@dataclass
class MockObserveResult:
    """phonefast.observe() 返回值的 mock。"""
    elements_text: str
    image_b64: str | None = None


class MockPhonefast:
    """Mock phonefast——shell 返回固定字符串，observe 返回固定 UI 文本。"""

    def __init__(self, shell_output: str = "", observe_text: str = ""):
        self._shell_output = shell_output
        self._observe_text = observe_text
        self.shell_calls: list[str] = []
        self.observe_calls: int = 0

    def shell(self, command: str, timeout: float = 20.0) -> str:
        self.shell_calls.append(command)
        return self._shell_output

    def observe(self, **kwargs: Any) -> MockObserveResult:
        self.observe_calls += 1
        return MockObserveResult(elements_text=self._observe_text)


class FailingPhonefast:
    """shell() 总是抛异常的 mock。"""

    def shell(self, command: str, timeout: float = 20.0) -> str:
        raise RuntimeError("adb timeout")

    def observe(self, **kwargs: Any) -> MockObserveResult:
        raise RuntimeError("observe failed")


# ── VerificationSpec.from_dict ──

class TestFromDict:
    def test_shell_spec(self):
        spec = VerificationSpec.from_dict({"command": "echo hi", "expect": "hi"})
        assert spec.command == "echo hi"
        assert spec.expect == "hi"
        assert not spec.is_ui_spec

    def test_ui_contains_spec(self):
        spec = VerificationSpec.from_dict({"ui_contains": "Success!"})
        assert spec.ui_contains == "Success!"
        assert spec.is_ui_spec
        assert spec.command == ""

    def test_ui_not_contains_spec(self):
        spec = VerificationSpec.from_dict({"ui_not_contains": "Error"})
        assert spec.ui_not_contains == "Error"
        assert spec.is_ui_spec

    def test_expect_empty_string(self):
        """expect: '' 应解析为空字符串（期望空输出），不是 None。"""
        spec = VerificationSpec.from_dict({"command": "ls", "expect": ""})
        assert spec.expect == ""
        assert spec.expect is not None

    def test_expect_missing_key(self):
        """缺 expect 键应解析为 None（不检查）。"""
        spec = VerificationSpec.from_dict({"command": "ls"})
        assert spec.expect is None

    def test_timeout_override(self):
        spec = VerificationSpec.from_dict({"command": "dumpsys", "timeout": 30.0})
        assert spec.timeout == 30.0


# ── _evaluate（shell 路径）──

class TestEvaluate:
    def test_exact_match(self):
        spec = VerificationSpec(command="x", expect="0")
        passed, _ = _evaluate("0", spec)
        assert passed

    def test_exact_mismatch(self):
        spec = VerificationSpec(command="x", expect="0")
        passed, reasons = _evaluate("1", spec)
        assert not passed
        assert len(reasons) == 1

    def test_expect_empty_match(self):
        """expect='' 应匹配空输出。"""
        spec = VerificationSpec(command="x", expect="")
        passed, _ = _evaluate("", spec)
        assert passed

    def test_expect_empty_mismatch(self):
        """expect='' 不应匹配非空输出。"""
        spec = VerificationSpec(command="x", expect="")
        passed, _ = _evaluate("some output", spec)
        assert not passed

    def test_regex(self):
        spec = VerificationSpec(command="x", expect_re=r"[1-9]")
        assert _evaluate("5", spec)[0]
        assert not _evaluate("0", spec)[0]

    def test_not_contain(self):
        spec = VerificationSpec(command="x", not_contain="error")
        assert _evaluate("ok", spec)[0]
        assert not _evaluate("error found", spec)[0]

    def test_min_lines(self):
        spec = VerificationSpec(command="x", min_lines=2)
        assert _evaluate("line1\nline2", spec)[0]
        assert not _evaluate("only one", spec)[0]


# ── _evaluate_ui（UI 路径）──

class TestEvaluateUI:
    def test_ui_contains_found(self):
        spec = VerificationSpec(ui_contains="Success!")
        passed, reasons = _evaluate_ui("some text Success! more", spec)
        assert passed
        assert reasons == []

    def test_ui_contains_missing(self):
        spec = VerificationSpec(ui_contains="Success!")
        passed, reasons = _evaluate_ui("no match here", spec)
        assert not passed
        assert "Success!" in reasons[0]

    def test_ui_not_contains_clean(self):
        spec = VerificationSpec(ui_not_contains="Error")
        passed, _ = _evaluate_ui("all good", spec)
        assert passed

    def test_ui_not_contains_violated(self):
        spec = VerificationSpec(ui_not_contains="Error")
        passed, reasons = _evaluate_ui("Error occurred", spec)
        assert not passed
        assert "Error" in reasons[0]

    def test_both_fields(self):
        spec = VerificationSpec(ui_contains="Pause", ui_not_contains="Start")
        # Has Pause, no Start → pass
        assert _evaluate_ui("Pause button here", spec)[0]
        # Has Pause AND Start → fail (ui_not_contains violated)
        assert not _evaluate_ui("Pause and Start", spec)[0]
        # Missing Pause → fail
        assert not _evaluate_ui("nothing here", spec)[0]


# ── run_verification ──

class TestRunVerification:
    def test_shell_path(self):
        pf = MockPhonefast(shell_output="0")
        spec = VerificationSpec(command="settings get global wifi_on", expect="0")
        results = run_verification([spec], pf)
        assert len(results) == 1
        assert results[0].passed
        assert pf.shell_calls == ["settings get global wifi_on"]

    def test_ui_path_observe(self):
        pf = MockPhonefast(observe_text="some UI text Success! end")
        spec = VerificationSpec(ui_contains="Success!")
        results = run_verification([spec], pf)
        assert len(results) == 1
        assert results[0].passed
        assert pf.observe_calls == 1
        assert pf.shell_calls == []  # 不走 shell

    def test_ui_path_missing(self):
        pf = MockPhonefast(observe_text="no success text")
        spec = VerificationSpec(ui_contains="Success!")
        results = run_verification([spec], pf)
        assert not results[0].passed

    def test_mixed_specs(self):
        """混合 shell + UI spec。"""
        pf = MockPhonefast(shell_output="0", observe_text="Success!")
        specs = [
            VerificationSpec(command="settings get wifi_on", expect="0"),
            VerificationSpec(ui_contains="Success!"),
        ]
        results = run_verification(specs, pf)
        assert len(results) == 2
        assert results[0].passed  # shell
        assert results[1].passed  # UI
        assert pf.shell_calls == ["settings get wifi_on"]
        assert pf.observe_calls == 1

    def test_empty_command_skipped(self):
        """空 command 且非 UI spec → 跳过。"""
        pf = MockPhonefast(shell_output="0")
        spec = VerificationSpec(command="", expect="0")
        results = run_verification([spec], pf)
        assert len(results) == 0

    def test_shell_failure_returns_error(self):
        pf = FailingPhonefast()
        spec = VerificationSpec(command="bad command", expect="0")
        results = run_verification([spec], pf)
        assert not results[0].passed
        assert "adb timeout" in results[0].error

    def test_ui_observe_failure_returns_error(self):
        pf = FailingPhonefast()
        spec = VerificationSpec(ui_contains="test")
        results = run_verification([spec], pf)
        assert not results[0].passed
        assert "observe" in results[0].error

    def test_result_reason_ui(self):
        """VerificationResult.reason() 对 UI spec 生成正确失败原因。"""
        spec = VerificationSpec(ui_contains="Pause")
        result = VerificationResult(
            passed=False, actual="no pause text", spec=spec,
        )
        reason = result.reason()
        assert "Pause" in reason

    def test_result_reason_shell(self):
        """VerificationResult.reason() 对 shell spec 生成正确失败原因。"""
        spec = VerificationSpec(command="x", expect="0")
        result = VerificationResult(
            passed=False, actual="1", spec=spec,
        )
        reason = result.reason()
        assert "0" in reason
        assert "1" in reason
