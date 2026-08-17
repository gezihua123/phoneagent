"""市后独立验证——仿 AndroidWorld `is_successful(env)` 模式。

验证层与 agent 工具能力完全解耦：
  - agent 不知道、不调用、不受影响
  - 验证命令通过 phonefast.shell() 直发
  - UI 树验证通过 phonefast.observe() 获取（AndroidWorld env.get_state().ui_elements 对齐）
  - 仅用于评测结果判定，不是 agent tool

两种验证路径：
  shell 路径:  command + expect/expect_re/not_contain/min_lines → pf.shell()
  UI 路径:     ui_contains/ui_not_contains → pf.observe() 取 elements_text 子串匹配

Usage:
    from fastaget.verify import VerificationSpec, run_verification

    # shell 验证
    specs = [VerificationSpec(command="settings get global wifi_on", expect="0")]
    # UI 树验证（AndroidWorld 式——扫 accessibility tree 找文本）
    specs = [VerificationSpec(ui_contains="Success!")]
    results = run_verification(specs, phonefast)
    all_passed = all(r.passed for r in results)
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

# 哨兵：区分"YAML 没写 expect 键"（None=不检查）和"expect: ''"（期望空输出）
_NO_EXPECT = object()

# sqlite3_cat 宿主查询超时（秒）
_SQLITE3_CAT_TIMEOUT: float = 15.0


@dataclass
class VerificationSpec:
    """单条验证规格——从 YAML verify: 块解析而来。

    --- shell 路径 ---
    command:    shell 命令，如 "settings get global wifi_on"
    expect:     精确匹配（strip 后比对）。None=不做精确匹配，""=期望空输出（文件不存在等）
    expect_re:  正则匹配（re.search），None=不做正则匹配
    not_contain: 不应包含此文本，空字符串表示不检查
    min_lines:  最少输出行数，0 表示不检查（用于"至少要有输出"的场景）
    timeout:    shell 命令超时秒数，默认 20.0

    --- UI 路径（AndroidWorld env.get_state().ui_elements 对齐）---
    ui_contains:     UI accessibility tree 中必须包含此文本（走 pf.observe() 而非 pf.shell()）
    ui_not_contains: UI accessibility tree 中不得包含此文本
    """

    command: str = ""
    expect: str | None = None
    expect_re: str | None = None
    not_contain: str = ""
    min_lines: int = 0
    timeout: float = 20.0
    ui_contains: str = ""
    ui_not_contains: str = ""

    @property
    def is_ui_spec(self) -> bool:
        """是否走 UI 路径（observe）而非 shell 路径。"""
        return bool(self.ui_contains or self.ui_not_contains)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerificationSpec":
        # expect: 缺键→None（不检查），expect: ''→''（期望空输出）
        expect_val = d.get("expect", _NO_EXPECT)
        expect_re_val = d.get("expect_re", _NO_EXPECT)
        return cls(
            command=d.get("command", ""),
            expect=None if expect_val is _NO_EXPECT else str(expect_val),
            expect_re=None if expect_re_val is _NO_EXPECT else str(expect_re_val),
            not_contain=str(d.get("not_contain", "")),
            min_lines=int(d.get("min_lines", 0)),
            timeout=float(d.get("timeout", 20.0)),
            ui_contains=str(d.get("ui_contains", "")),
            ui_not_contains=str(d.get("ui_not_contains", "")),
        )


@dataclass
class VerificationResult:
    """单条验证结果。"""

    passed: bool
    actual: str
    spec: VerificationSpec
    error: str = ""

    def reason(self) -> str:
        """失败原因（供报告展示）。"""
        if self.error:
            return f"执行失败: {self.error}"
        if self.spec.is_ui_spec:
            _passed, reasons = _evaluate_ui(self.actual, self.spec)
        else:
            _passed, reasons = _evaluate(self.actual, self.spec)
        return "; ".join(reasons) if reasons else ""


def run_verification(
    specs: list[VerificationSpec],
    phonefast: Any,  # Phonefast
) -> list[VerificationResult]:
    """执行验证规格列表，返回每条结果。

    两种路径：
    - UI 路径（ui_contains/ui_not_contains 非空）：调 phonefast.observe() 取 elements_text 子串匹配
    - shell 路径（command 非空）：调 phonefast.shell() 重试 2 次间隔 1s

    phonefast 超时/失败时：返回 passed=False + error 信息，不抛异常。
    """
    results: list[VerificationResult] = []
    for spec in specs:
        # UI 路径——AndroidWorld env.get_state().ui_elements 对齐
        if spec.is_ui_spec:
            try:
                obs = phonefast.observe()
                ui_text = getattr(obs, "elements_text", "") or ""
            except Exception as e:
                results.append(VerificationResult(
                    passed=False, actual="", spec=spec, error=f"observe() failed: {e}",
                ))
                continue
            passed, _reasons = _evaluate_ui(ui_text, spec)
            results.append(VerificationResult(
                passed=passed, actual=ui_text[:200], spec=spec,
            ))
            continue

        # shell 路径——跳过空 command
        if not spec.command:
            continue

        # sqlite3_cat 路径：设备 sqlite3 二进制过旧，无法解析新应用（如 VLC）的 DB schema。
        # 通过 cat 把 DB 拉到宿主临时文件，用宿主现代 sqlite3 执行查询。
        # 格式：sqlite3_cat:<设备db路径>::<SQL>（SQL 允许空格；:: 分隔）
        if spec.command.startswith("sqlite3_cat:"):
            try:
                _, rest = spec.command.split(":", 1)
                db_path, sql = rest.split("::", 1)
                # 二进制 DB 经 shell 文本通道必须 base64（text=True 的 UTF-8 解码会损坏字节）
                b64 = (phonefast.shell(f"cat '{db_path}' | base64") or "").strip()
                with tempfile.NamedTemporaryFile(
                        mode="wb", suffix=".db", delete=False) as tf:
                    tf.write(base64.b64decode(b64))
                    tmp_path = tf.name
                try:
                    output = subprocess.run(
                        ["sqlite3", tmp_path, sql],
                        capture_output=True, text=True, timeout=_SQLITE3_CAT_TIMEOUT,
                    ).stdout or ""
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                last_err = None
            except Exception as e:
                output = ""
                last_err = e
            if last_err is not None:
                results.append(VerificationResult(
                    passed=False, actual="", spec=spec, error=str(last_err),
                ))
                continue
        else:
            output = ""
            last_err = None
            for _attempt in range(2):
                try:
                    output = phonefast.shell(spec.command, timeout=spec.timeout) or ""
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if _attempt == 0:
                        time.sleep(1.0)  # 重试前等 1s，给 adb 恢复时间
                    continue
            if last_err is not None:
                results.append(VerificationResult(
                    passed=False, actual="", spec=spec, error=str(last_err),
                ))
                continue

        actual = output.strip()
        passed, _reasons = _evaluate(actual, spec)
        results.append(VerificationResult(
            passed=passed, actual=actual, spec=spec,
        ))
    return results


def _evaluate(actual: str, spec: VerificationSpec) -> tuple[bool, list[str]]:
    """统一比对 + 失败原因收集（_check_output 和 reason() 共用）。

    Returns (passed, reasons)。reasons 为空表示通过；非空为失败原因列表。
    """
    reasons: list[str] = []
    if spec.expect is not None and actual != spec.expect:
        reasons.append(f"期望 '{spec.expect}'，实际 '{actual}'")
    if spec.expect_re is not None and not re.search(spec.expect_re, actual):
        reasons.append(f"不匹配 /{spec.expect_re}/")
    if spec.not_contain and spec.not_contain in actual:
        reasons.append(f"不应包含 '{spec.not_contain}'")
    if spec.min_lines > 0:
        n_lines = len([l for l in actual.split("\n") if l.strip()])
        if n_lines < spec.min_lines:
            reasons.append(f"输出行数 {n_lines} < {spec.min_lines}")
    return (len(reasons) == 0, reasons)


def _evaluate_ui(ui_text: str, spec: VerificationSpec) -> tuple[bool, list[str]]:
    """UI 树文本比对——子串匹配（AndroidWorld env.get_state().ui_elements 对齐）。

    phonefast.observe() 返回 elements_text（flatref 格式 UI 树文本），
    对此文本做子串匹配——等价于 AndroidWorld 扫 ui_elements 的 text/content_description。
    """
    reasons: list[str] = []
    if spec.ui_contains and spec.ui_contains not in ui_text:
        reasons.append(f"UI 树未找到 '{spec.ui_contains}'")
    if spec.ui_not_contains and spec.ui_not_contains in ui_text:
        reasons.append(f"UI 树不应包含 '{spec.ui_not_contains}'")
    return (len(reasons) == 0, reasons)


def _check_output(actual: str, spec: VerificationSpec) -> bool:
    """逐条比对：expect / expect_re / not_contain / min_lines 任一不满足即 False。"""
    passed, _ = _evaluate(actual, spec)
    return passed
