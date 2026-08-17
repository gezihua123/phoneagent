"""用例 DSL：YAML 数据结构 + 加载器。

一个 YAML 文件可含单个用例（顶层是 dict）或多个用例（顶层是 list，或顶层 cases: 列表）。

用例结构：
  name: 打开设置验证
  goal: 启动设置应用，确认进入设置页，然后 complete
  model: glm-5.2          # 可选，覆盖默认
  max_steps: 10           # 可选
  error_thresh: 2         # 可选
  asserts:                # 可选，最终断言（描述 + 期望通过）
    - description: 设置标题可见
      expected: true

goal 是给 agent 的自然语言目标（agent 自主 ReAct 完成并自主 assert/complete）。
asserts 是 QA 的人工预期，用于报告里和 agent 的 assert 结果对照。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 包名提示：goal 中括号内的小写点分 token（如 "(com.android.camera2)"）。
# 宪法第一条禁止向 agent 注入包名——加载时从 goal 剥离，转入 target_packages。
_PACKAGE_HINT_RE = re.compile(r"\s*\(\s*[a-z][a-z0-9_.]*\.[a-z0-9_.]+\s*\)")


@dataclass
class Assert:
    description: str
    expected: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "Assert":
        return cls(description=d.get("description", ""), expected=d.get("expected", True))


@dataclass
class Case:
    name: str
    goal: str
    model: str | None = None
    max_steps: int | None = None
    error_thresh: int | None = None
    reset: bool = True  # 用例前是否 home 复位（状态隔离）
    asserts: list[Assert] = field(default_factory=list)
    verifications: list[dict] = field(default_factory=list)  # 事后验证 spec 列表
    initialize: list[dict] = field(default_factory=list)  # 事前初始化（AW 式 initialize_task）
    precondition: list[dict] = field(default_factory=list)  # 前置条件（PI before_task 检查）
    target_packages: list[str] = field(default_factory=list)  # 从 goal 剥离的包名（仅评测层用，不进 agent）

    @classmethod
    def from_dict(cls, d: dict) -> "Case":
        goal = d.get("goal", "") or ""
        target_packages: list[str] = []
        for m in _PACKAGE_HINT_RE.finditer(goal):
            token = m.group(0).strip()
            target_packages.append(token.strip("()").strip())
        if target_packages:
            goal = re.sub(r"\s{2,}", " ", _PACKAGE_HINT_RE.sub("", goal)).strip()
        return cls(
            name=d.get("name", "(unnamed)"),
            goal=goal,
            model=d.get("model"),
            max_steps=d.get("max_steps"),
            error_thresh=d.get("error_thresh"),
            reset=d.get("reset", True),
            asserts=[Assert.from_dict(a) for a in d.get("asserts", []) or []],
            verifications=d.get("verify", []) or [],
            initialize=d.get("initialize", []) or [],
            precondition=d.get("precondition", []) or [],
            target_packages=target_packages,
        )


def load_cases(path: str | Path) -> list[Case]:
    """从 YAML 文件加载用例列表。支持单用例、列表、cases: 键三种形态。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if data is None:
        return []
    if isinstance(data, dict):
        if "cases" in data and isinstance(data["cases"], list):
            return [Case.from_dict(c) for c in data["cases"]]
        return [Case.from_dict(data)]
    if isinstance(data, list):
        return [Case.from_dict(c) for c in data]
    raise ValueError(f"无法解析用例文件 {path}：顶层应为 dict 或 list")
