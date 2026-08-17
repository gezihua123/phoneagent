"""meta_infra: 向后兼容 shim，全部逻辑已迁移到 scenariokit 包。

新代码请直接 `from fastaget.scenariokit import ...`，本模块仅为兼容旧 import 保留。
实际实现见：
  - scenariokit.xmltext     XML↔phonefast 文本 + 节点解析
  - scenariokit.variants    屏幕变体生成
  - scenariokit.device      MockPhonefast + Screen + TapZone
  - scenariokit.scenarios   Scenario + YAML 加载 + 字段推导
  - scenariokit.outcomes    判定器注册表 + evaluate_scenario_outcome
  - scenariokit.scripted    PromptAwareScriptedLLM

_run_scenario / RunOutcome 保留在此（依赖 fastaget 的场景运行器，不属于 scenariokit 纯域）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 从 scenariokit 重新导出全部公共 API（向后兼容旧 import）
from fastaget.scenariokit import (
    WD4_XML,
    SCENARIOS_YML,
    MockPhonefast,
    Screen,
    TapZone,
    TapRecord,
    Scenario,
    OutcomeContext,
    PromptAwareScriptedLLM,
    evaluate_scenario_outcome,
    register_outcome_checker,
    make_stateful_phonefast,
    load_device_graph,
    make_variants,
    xml_to_phonefast_text,
    parse_meaningful_nodes,
    parse_meaningful_nodes_from_text,
    _build_scenarios,
    _derive_scenario_fields,
    _resolve_gt_bounds,
    _find_node_by_desc,
    _find_node_by_text,
    _find_clickable_ancestor,
    _point_in_bounds,
)
from fastaget.scenariokit.outcomes import _OUTCOME_CHECKERS
from fastaget.scenariokit.device import _auto_derive_zones

from fastaget.agent.prompts import (
    SYSTEM_PROMPT as _SYSTEM_PROMPT,
    OPTIMIZED_SYSTEM_PROMPT,
)
from fastaget.agent.fast_agent import (
    FastAgent,
)
from fastaget.tools import build_registry


@dataclass
class RunOutcome:
    """一次场景运行的结果。"""
    scenario: str
    variant: str
    prompt: str  # "baseline" | "optimized"
    success: bool
    reason: str
    taps: list[TapRecord] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


def _run_scenario(
    scenario: Scenario,
    screen_text: str,
    nodes: list[dict],
    prompt: str,  # "baseline" | "optimized"
) -> RunOutcome:
    """用指定 prompt 跑一个场景，返回成功/失败及原因。"""
    pf = MockPhonefast(screen_text)
    llm = PromptAwareScriptedLLM(scenario, nodes)
    registry = build_registry()
    system_prompt = _SYSTEM_PROMPT if prompt == "baseline" else OPTIMIZED_SYSTEM_PROMPT

    agent = FastAgent(llm, pf, registry, max_steps=12, system_prompt=system_prompt)
    result = agent.run(scenario.goal)

    ok, reason = evaluate_scenario_outcome(scenario, nodes, pf, result)

    return RunOutcome(
        scenario=scenario.name,
        variant="",  # 由调用方填充
        prompt=prompt,
        success=ok,
        reason=reason,
        taps=list(pf.taps),
        actions=list(pf.actions),
    )
