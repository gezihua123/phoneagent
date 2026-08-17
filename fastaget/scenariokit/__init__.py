"""scenariokit — 场景生成与模拟测试工具包。

独立于 fastaget/ 主线（生产代码不依赖场景知识），提供：
  - xmltext:    XML ↔ phonefast 文本转换 + 节点解析
  - variants:   屏幕变体生成（shift/set_attr/strip/noise）
  - device:     MockPhonefast 状态机 + Screen + TapZone
  - scenarios:  Scenario + YAML 加载 + 字段推导
  - outcomes:   判定器注册表 + evaluate_scenario_outcome
  - scripted:   PromptAwareScriptedLLM（确定性 A/B 测试）

设计原则（agents.md）：
  - 与 fastaget/ 平级，不污染生产代码
  - 各模块单一职责，可独立单测
  - 稳定 API，供 tests/ / skill / CLI 调用
"""
from fastaget.scenariokit.xmltext import (
    xml_to_phonefast_text,
    parse_meaningful_nodes,
    parse_meaningful_nodes_from_text,
)
from fastaget.scenariokit.variants import make_variants
from fastaget.scenariokit.device import (
    MockPhonefast,
    Screen,
    TapZone,
    TapRecord,
    make_stateful_phonefast,
)
from fastaget.scenariokit.scenarios import (
    Scenario,
    load_device_graph,
    _build_scenarios,
    _derive_scenario_fields,
    _resolve_gt_bounds,
    _find_node_by_desc,
    _find_node_by_text,
    _find_clickable_ancestor,
    _point_in_bounds,
)
from fastaget.scenariokit.outcomes import (
    OutcomeContext,
    evaluate_scenario_outcome,
    register_outcome_checker,
)
from fastaget.scenariokit.scripted import PromptAwareScriptedLLM

__all__ = [
    # xmltext
    "xml_to_phonefast_text", "parse_meaningful_nodes", "parse_meaningful_nodes_from_text",
    # variants
    "make_variants",
    # device
    "MockPhonefast", "Screen", "TapZone", "TapRecord", "make_stateful_phonefast",
    # scenarios
    "Scenario", "load_device_graph", "_build_scenarios", "_derive_scenario_fields",
    "_resolve_gt_bounds", "_find_node_by_desc", "_find_node_by_text",
    "_find_clickable_ancestor", "_point_in_bounds",
    # outcomes
    "OutcomeContext", "evaluate_scenario_outcome", "register_outcome_checker",
    # scripted
    "PromptAwareScriptedLLM",
    # paths
    "WD4_XML", "SCENARIOS_YML",
]

from pathlib import Path
_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"
WD4_XML = _FIXTURES_DIR / "wd4.xml"
SCENARIOS_YML = Path(__file__).resolve().parent.parent / "meta" / "scenarios.yml"
