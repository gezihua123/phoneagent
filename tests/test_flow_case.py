"""FlowCase YAML 加载 + FlowRunner 单测。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastaget.flow.case import FlowCase, load_flow_case


_SAMPLE_YAML = """
name: sample
model: glm-5.2
judge_model: glm-5.2
params:
  app: xiaohongshu
precondition:
  - description: 屏幕可用
    check: "{screen.has_element:index=0}"
    judge: rule
    severity: critical
flow:
  - id: open
    goal: 打开应用 {var.app}
    mode: guided
    branches:
      - when: "{screen.has_text:Google Play}"
        to: search
      - when: default
        to: fail
  - id: search
    goal: 点击搜索框
    mode: guided
    loop:
      max_iterations: 3
      break_when: "{screen.has_text:Search}"
      counter_var: retry
  - id: fail
    goal: 失败结束
    mode: guided
expect:
  - description: 看到小红书
    check: "{screen.has_text:小红书}"
    judge: rule
    severity: critical
teardown:
  - id: home
    goal: 回到桌面
    mode: guided
tags: [smoke]
"""


def test_load_flow_case(tmp_path):
    p = tmp_path / "case.yaml"
    p.write_text(_SAMPLE_YAML, encoding="utf-8")
    case = load_flow_case(p)

    assert case.name == "sample"
    assert case.model == "glm-5.2"
    assert case.judge_model == "glm-5.2"
    assert len(case.flow) == 3
    assert len(case.precondition) == 1
    assert len(case.expect) == 1
    assert len(case.teardown) == 1

    # 参数替换
    assert case.flow[0].goal == "打开应用 xiaohongshu"

    # loop 解析
    assert case.flow[1].loop is not None
    assert case.flow[1].loop.max_iterations == 3
    assert case.flow[1].loop.break_when == "{screen.has_text:Search}"
    assert case.flow[1].loop.counter_var == "retry"

    # 分支解析
    assert len(case.flow[0].branches) == 2
    assert case.flow[0].branches[0].to == "search"
    assert case.flow[0].branches[1].to == "fail"

    # tags
    assert case.tags == ["smoke"]


def test_get_node():
    case = FlowCase.from_dict({
        "name": "t",
        "flow": [{"id": "a"}, {"id": "b"}],
    })
    assert case.get_node("a").id == "a"
    assert case.get_node("c") is None
