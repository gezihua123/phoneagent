"""FlowNode + FlowCase 数据结构 + YAML 加载器。

FlowNode mode:
  guided     — 单步执行，LLM 只做一件事
  autonomous — LLM 自主多步，分支命中即中断
  wait       — 轮询等待 success_when，不调 LLM

loop 结构（P0-3）：
  loop:
    max_iterations: 3      — 最多循环 3 次
    break_when: "{expr}"   — 满足条件时跳出
    counter_var: retry     — 计数器存入 var.retry
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from fastaget.flow.expectation import Expectation


@dataclass
class Branch:
    """分支：条件 → 目标节点。"""
    when: str       # 条件表达式或 "default"
    to: str         # 目标 node id

    @classmethod
    def from_dict(cls, d: dict) -> "Branch":
        return cls(when=d.get("when", "default"), to=d.get("to", d.get("target", "")))


@dataclass
class LoopSpec:
    """循环节点配置。"""
    max_iterations: int = 1
    break_when: str = ""       # 满足条件跳出循环
    continue_when: str = ""    # 满足条件继续循环（与 break_when 互斥，优先 break）
    counter_var: str = ""      # 计数器变量名

    @classmethod
    def from_dict(cls, d: dict | None) -> "LoopSpec | None":
        if not d:
            return None
        return cls(
            max_iterations=int(d.get("max_iterations", 1)),
            break_when=d.get("break_when", ""),
            continue_when=d.get("continue_when", ""),
            counter_var=d.get("counter_var", ""),
        )


@dataclass
class FlowNode:
    """流程节点。"""
    id: str
    goal: str = ""
    mode: str = "guided"        # guided | autonomous | wait
    max_steps: int = 5          # autonomous 模式的 LLM 步数上限
    branches: list[Branch] = field(default_factory=list)
    expect: list[Expectation] = field(default_factory=list)
    assert_: list[Expectation] = field(default_factory=list)  # 显式断言节点
    loop: LoopSpec | None = None
    # wait 模式专属
    timeout: float = 60.0
    poll_interval: float = 3.0
    success_when: str = ""
    on_timeout: str = ""        # 超时后的行为: "fail" | node_id
    on_fail: str = ""           # 执行失败后跳转的 node id

    @classmethod
    def from_dict(cls, d: dict) -> "FlowNode":
        return cls(
            id=d.get("id", ""),
            goal=d.get("goal", ""),
            mode=d.get("mode", "guided"),
            max_steps=int(d.get("max_steps", 5)),
            branches=[Branch.from_dict(b) for b in d.get("branches", []) or []],
            expect=[Expectation.from_dict(e) for e in d.get("expect", []) or []],
            assert_=[Expectation.from_dict(e) for e in d.get("assert", []) or []],
            loop=LoopSpec.from_dict(d.get("loop")),
            timeout=float(d.get("timeout", 60.0)),
            poll_interval=float(d.get("poll_interval", 3.0)),
            success_when=d.get("success_when", ""),
            on_timeout=d.get("on_timeout", "fail"),
            on_fail=d.get("on_fail", ""),
        )


@dataclass
class FlowCase:
    """声明式测试用例（flow 版）。"""
    name: str
    flow: list[FlowNode] = field(default_factory=list)
    precondition: list[Expectation] = field(default_factory=list)
    expect: list[Expectation] = field(default_factory=list)
    teardown: list[FlowNode] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    model: str | None = None
    judge_model: str | None = None  # 判定模型（隔离执行模型）
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "FlowCase":
        return cls(
            name=d.get("name", "(unnamed)"),
            flow=[FlowNode.from_dict(n) for n in d.get("flow", []) or []],
            precondition=[Expectation.from_dict(e) for e in d.get("precondition", []) or []],
            expect=[Expectation.from_dict(e) for e in d.get("expect", []) or []],
            teardown=[FlowNode.from_dict(n) for n in d.get("teardown", []) or []],
            tags=d.get("tags", []) or [],
            model=d.get("model"),
            judge_model=d.get("judge_model"),
            params=d.get("params", {}) or {},
        )

    def get_node(self, node_id: str) -> FlowNode | None:
        for n in self.flow:
            if n.id == node_id:
                return n
        return None


def load_flow_case(path: str | Path) -> FlowCase:
    """从 YAML 文件加载单个 flow case。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"flow case 文件 {path} 顶层应为 dict")
    case = FlowCase.from_dict(data)
    # 参数替换：{var.xxx} → params 中的值
    if case.params:
        _apply_params(case, case.params)
    return case


def load_flow_cases(path: str | Path) -> list[FlowCase]:
    """加载 flow cases（单个或列表）。

    无论哪种 YAML 结构，都统一走 _apply_params 做占位符替换。
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if data is None:
        return []
    if isinstance(data, dict):
        if "cases" in data and isinstance(data["cases"], list):
            cases = [FlowCase.from_dict(c) for c in data["cases"]]
        else:
            cases = [FlowCase.from_dict(data)]
    elif isinstance(data, list):
        cases = [FlowCase.from_dict(c) for c in data]
    else:
        raise ValueError(f"无法解析 flow 文件 {path}")
    for case in cases:
        if case.params:
            _apply_params(case, case.params)
    return cases


def _apply_params(case: FlowCase, params: dict[str, Any]) -> None:
    """递归替换 {var.xxx} 占位符为 params 中的值。"""
    for node in case.flow + case.teardown:
        node.goal = _substitute(node.goal, params)
        node.success_when = _substitute(node.success_when, params)
        for b in node.branches:
            b.to = _substitute(b.to, params)
        for e in node.expect + node.assert_:
            e.description = _substitute(e.description, params)
            e.check = _substitute(e.check, params)
    for e in case.precondition + case.expect:
        e.description = _substitute(e.description, params)
        e.check = _substitute(e.check, params)


def _substitute(text: str, params: dict[str, Any]) -> str:
    """替换 {var.xxx} 为 params[xxx]。"""
    for k, v in params.items():
        text = text.replace(f"{{var.{k}}}", str(v))
    return text
