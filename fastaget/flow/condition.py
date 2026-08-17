"""条件求值器：branch.when 和 expect.check 共用同一套条件语法。

三级条件（求值优先级从高到低）：
  1. rule     — 规则型，从 UIState / 上下文查，0ms，确定性
  2. context  — 上下文型，从执行历史查（step.success / var.xxx）
  3. semantic — 语义型，调 LLM 判断（只返回 bool）

语法：{prefix:args}
  {screen.has_text:小红书}        — 屏幕包含文本
  {screen.not_has_text:已停止}    — 屏幕不包含文本
  {screen.has_element:index=10}   — 屏幕有指定 index 元素
  {screen.package:com.xxx}        — 前台包名匹配
  {step.search.success}            — 某步骤成功
  {var.count>0}                    — 上下文变量比较
  {llm.judge:描述}                 — LLM 语义判断
  default                          — 默认分支
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from fastaget.device.uistate import UIState
    from fastaget.flow.context import FlowContext


@dataclass
class ConditionResult:
    """条件求值结果。"""
    matched: bool
    source: str = ""       # "rule" | "context" | "semantic" | "default"
    detail: str = ""       # 求值细节（失败时用于报告）


class ConditionEvaluator:
    """条件求值器。rule → context → semantic → default 依次尝试。"""

    def __init__(self, semantic_judge: Any = None) -> None:
        self._judge = semantic_judge  # SemanticJudge，可为 None

    def eval(self, expr: str, ctx: "FlowContext") -> ConditionResult:
        """求值单个条件表达式。"""
        expr = expr.strip()

        # default
        if expr == "default" or expr == "":
            return ConditionResult(matched=True, source="default")

        # 规则型：{screen.xxx:args}
        if expr.startswith("{screen."):
            return self._eval_screen(expr, ctx)

        # 设备级事实：{device.xxx:args}
        if expr.startswith("{device."):
            return self._eval_device(expr, ctx)

        # 上下文型：{step.xxx} / {var.xxx}
        if expr.startswith("{step.") or expr.startswith("{var."):
            return self._eval_context(expr, ctx)

        # 语义型：{llm.judge:描述}
        if expr.startswith("{llm.judge:"):
            return self._eval_semantic(expr, ctx)

        # 未知格式
        return ConditionResult(matched=False, source="unknown",
                               detail=f"unknown condition: {expr}")

    def eval_branches(
        self, branches: list[dict], ctx: "FlowContext"
    ) -> tuple[str | None, ConditionResult]:
        """求值分支列表，返回 (target_node_id, result)。

        branches: [{"when": expr, "to": target}, ...]
        依次求值，第一个命中的返回。default 永远最后。
        """
        # 先求值非 default 分支
        default_target: str | None = None
        for b in branches:
            when = b.get("when", "")
            target = b.get("to", b.get("target", ""))
            if when == "default" or when == "":
                if default_target is None:
                    default_target = target
                continue
            result = self.eval(when, ctx)
            if result.matched:
                return target, result

        # 回退 default
        if default_target is not None:
            return default_target, ConditionResult(matched=True, source="default")
        return None, ConditionResult(matched=False, source="none")

    # ---- 规则型：screen ----

    def _eval_screen(self, expr: str, ctx: "FlowContext") -> ConditionResult:
        """求值屏幕规则条件。"""
        m = re.match(r"\{screen\.(has_text|not_has_text|has_element|package):(.*)\}", expr)
        if not m:
            return ConditionResult(matched=False, source="rule",
                                   detail=f"bad screen expr: {expr}")

        op, arg = m.group(1), m.group(2).strip()
        ui = ctx.current_ui
        if ui is None:
            return ConditionResult(matched=False, source="rule", detail="no screen state")

        if op == "has_text":
            matched = any(e.text and arg in e.text for e in ui.elements)
            return ConditionResult(matched=matched, source="rule",
                                   detail=f"has_text '{arg}': {matched}")
        if op == "not_has_text":
            matched = not any(e.text and arg in e.text for e in ui.elements)
            return ConditionResult(matched=matched, source="rule",
                                   detail=f"not_has_text '{arg}': {matched}")
        if op == "has_element":
            # arg 格式: index=10 / text=xxx / any
            if arg == "any":
                matched = len(ui.elements) > 0
                return ConditionResult(matched=matched, source="rule",
                                       detail=f"has_element(any): {len(ui.elements)} elements")
            km = re.match(r"index=(\d+)", arg)
            if km:
                idx = int(km.group(1))
                matched = any(e.index == idx for e in ui.elements)
                return ConditionResult(matched=matched, source="rule",
                                       detail=f"has_element[{idx}]: {matched}")
            # 支持 text=xxx
            tm = re.match(r"text=(.*)", arg)
            if tm:
                txt = tm.group(1)
                matched = any(e.text and txt in e.text for e in ui.elements)
                return ConditionResult(matched=matched, source="rule",
                                       detail=f"has_element[text={txt}]: {matched}")
            return ConditionResult(matched=False, source="rule",
                                   detail=f"bad has_element arg: {arg}")
        if op == "package":
            pkg = ctx.current_package or ""
            matched = arg in pkg
            return ConditionResult(matched=matched, source="rule",
                                   detail=f"package '{arg}' in '{pkg}': {matched}")
        return ConditionResult(matched=False, source="rule", detail=f"unknown op: {op}")

    # ---- 设备级事实：device ----

    def _eval_device(self, expr: str, ctx: "FlowContext") -> ConditionResult:
        """求值设备级事实条件（ground truth，不依赖屏幕文本）。

        支持格式：
          {device.pkg_installed:com.xxx}   — 包是否已安装（查 pm list packages）
          {device.activity:com.xxx}        — 前台包名是否匹配（查 dumpsys）
          {device.not_pkg_installed:com.xxx} — 包未安装

        从原理上规避 LLM 幻觉：广告有"打开"按钮不代表应用已安装，
        必须用包管理器的事实交叉验证。
        """
        m = re.match(r"\{device\.(pkg_installed|not_pkg_installed|activity):(.*)\}", expr)
        if not m:
            return ConditionResult(matched=False, source="device",
                                   detail=f"bad device expr: {expr}")

        op, arg = m.group(1), m.group(2).strip()
        pf = ctx.phonefast
        if pf is None:
            return ConditionResult(matched=False, source="device",
                                   detail="no phonefast in context")

        if op == "pkg_installed":
            try:
                installed = pf.is_package_installed(arg)
                return ConditionResult(matched=installed, source="device",
                                       detail=f"pm list packages {arg}: installed={installed}")
            except Exception as e:
                return ConditionResult(matched=False, source="device",
                                       detail=f"pkg_installed error: {e}")

        if op == "not_pkg_installed":
            try:
                installed = pf.is_package_installed(arg)
                return ConditionResult(matched=not installed, source="device",
                                       detail=f"pm list packages {arg}: installed={installed}")
            except Exception as e:
                return ConditionResult(matched=False, source="device",
                                       detail=f"not_pkg_installed error: {e}")

        if op == "activity":
            try:
                pkg = pf.current_package()
                matched = arg in (pkg or "")
                return ConditionResult(matched=matched, source="device",
                                       detail=f"current_package='{pkg}', match '{arg}': {matched}")
            except Exception as e:
                return ConditionResult(matched=False, source="device",
                                       detail=f"activity error: {e}")

        return ConditionResult(matched=False, source="device", detail=f"unknown op: {op}")

    # ---- 上下文型：step / var ----

    def _eval_context(self, expr: str, ctx: "FlowContext") -> ConditionResult:
        """求值上下文条件。

        支持格式：
          {step.<node_id>.success}   — 步骤是否成功
          {step.<node_id>.failed}    — 步骤是否失败
          {var.<name>}               — 变量 truthy
          {var.<name>>0}             — 变量比较
        """
        m = re.match(
            r"\{(step|var)\.([a-zA-Z_][\w]*)(?:\.(success|failed))?([><=!]+.*)?\}",
            expr,
        )
        if not m:
            return ConditionResult(matched=False, source="context",
                                   detail=f"bad context expr: {expr}")

        kind, key, prop, cmp = m.group(1), m.group(2), m.group(3), m.group(4)

        if kind == "step":
            node_result = ctx.get_step_result(key)
            if node_result is None:
                return ConditionResult(matched=False, source="context",
                                       detail=f"step '{key}' not found")
            # 默认查 success 属性
            prop = prop or "success"
            if prop == "success":
                matched = node_result.success
            elif prop == "failed":
                matched = not node_result.success
            else:
                return ConditionResult(matched=False, source="context",
                                       detail=f"unknown step prop: {prop}")
            return ConditionResult(matched=matched, source="context",
                                   detail=f"step.{key}.{prop}: {matched}")

        if kind == "var":
            # {var.count>0} → 上下文变量比较
            val = ctx.get_var(key)
            if val is None:
                return ConditionResult(matched=False, source="context",
                                       detail=f"var '{key}' not found")
            if cmp:
                return self._compare(val, cmp, expr)
            # 无比较符 → truthy
            matched = bool(val)
            return ConditionResult(matched=matched, source="context",
                                   detail=f"var.{key}: {matched}")

        return ConditionResult(matched=False, source="context", detail="unknown kind")

    def _compare(self, val: Any, cmp: str, expr: str) -> ConditionResult:
        """比较 val 与 cmp 表达式。"""
        cmp = cmp.strip()
        for op in (">=", "<=", "!=", "==", ">", "<"):
            if cmp.startswith(op):
                operand = cmp[len(op):].strip()
                try:
                    if op == ">" and float(val) > float(operand):
                        return ConditionResult(matched=True, source="context")
                    if op == "<" and float(val) < float(operand):
                        return ConditionResult(matched=True, source="context")
                    if op == ">=" and float(val) >= float(operand):
                        return ConditionResult(matched=True, source="context")
                    if op == "<=" and float(val) <= float(operand):
                        return ConditionResult(matched=True, source="context")
                    if op == "==" and str(val) == operand:
                        return ConditionResult(matched=True, source="context")
                    if op == "!=" and str(val) != operand:
                        return ConditionResult(matched=True, source="context")
                except (ValueError, TypeError):
                    pass
                return ConditionResult(matched=False, source="context",
                                       detail=f"{val} {cmp} false")
        return ConditionResult(matched=False, source="context", detail=f"bad cmp: {cmp}")

    # ---- 语义型：llm.judge ----

    def _eval_semantic(self, expr: str, ctx: "FlowContext") -> ConditionResult:
        """求值语义条件：调 LLM 判断。"""
        m = re.match(r"\{llm\.judge:(.*)\}", expr)
        if not m:
            return ConditionResult(matched=False, source="semantic",
                                   detail=f"bad semantic expr: {expr}")
        description = m.group(1).strip()
        if self._judge is None:
            return ConditionResult(matched=False, source="semantic",
                                   detail="no semantic judge configured")
        screen_text = ctx.current_screen_text or "(no screen)"
        result = self._judge.judge(description, screen_text)
        return ConditionResult(
            matched=result.satisfied, source="semantic",
            detail=f"llm.judge '{description}': {result.satisfied} (conf={result.confidence:.1f})"
        )
