"""tests/conftest.py — 共享测试辅助（pytest 自动加载，亦可显式 import）。

- FLATREF_SCREEN: 单元素 flatref 屏幕字面量（原在 3 个文件中逐字重复）
- make_llm_response: LLMResponse 构造便捷函数（统一默认值）
- OneTurnCompleteLLM: 首轮即 complete(success=True) 的确定性 LLM
- ScriptedResponseLLM: 按队列回放 LLMResponse，耗尽后返回无工具文本（优雅终止）
- scenario_run / variant_materials: wd4 场景运行 lru_cache——
  矩阵测试与单点测试间同一 (场景,变体,prompt) 只跑一次 FastAgent.run()
  （输入纯函数：MockPhonefast 静态屏 + PromptAwareScriptedLLM 确定性脚本）。
"""
from __future__ import annotations

import functools

from fastaget.llm.delegate import LLMResponse, ToolCall
from fastaget.scenariokit import (
    WD4_XML,
    _build_scenarios,
    make_variants,
    parse_meaningful_nodes,
    xml_to_phonefast_text,
)

from tests.meta_infra import RunOutcome, _run_scenario


# ---- 共享字面量 ----

FLATREF_SCREEN = '[0] text="设置" (TextView) [clickable] bounds=[0,100][200,200]'


# ---- LLM 响应/替身 ----

def make_llm_response(text: str = "", tool_calls=None, cost: float = 0.001,
                      usage: dict | None = None) -> LLMResponse:
    tcs = tool_calls or []
    return LLMResponse(
        text=text, tool_calls=tcs,
        stop_reason="tool_use" if tcs else "end_turn",
        cost_usd=cost,
        raw={"usage": usage or {"input_tokens": 100, "output_tokens": 5}},
    )


class OneTurnCompleteLLM:
    """一次调用就 complete(success=True)。"""
    model = "test-model"

    def __init__(self, cost_usd: float = 0.001):
        self._cost = cost_usd

    def complete(self, system, messages, tools, *, vision=False, **_):
        return make_llm_response(
            text="done",
            tool_calls=[ToolCall(name="complete", input={"result": "ok", "success": True}, id="t1")],
            cost=self._cost,
        )

    def close(self):
        pass


class ScriptedResponseLLM:
    """按队列返回预设 LLMResponse；耗尽后返回无工具文本（管道自然终止）。"""
    model = "test-model"

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)

    def complete(self, system, messages, tools, *, vision=False, **_):
        if self._responses:
            return self._responses.pop(0)
        return make_llm_response(text="(script exhausted)", cost=0.0, usage={})

    def close(self):
        pass


# ---- wd4 场景运行缓存（同一 (场景,变体,prompt) 组合只跑一次）----


@functools.lru_cache(maxsize=1)
def _wd4_raw_xml() -> str:
    return WD4_XML.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def wd4_variants() -> dict[str, str]:
    return make_variants(_wd4_raw_xml())


@functools.lru_cache(maxsize=1)
def wd4_scenarios() -> list:
    return _build_scenarios(parse_meaningful_nodes(_wd4_raw_xml()))


@functools.lru_cache(maxsize=None)
def variant_materials(variant_name: str) -> tuple[str, list[dict]]:
    """(screen_text, nodes)——变体解析结果缓存（nodes 只读共享）。"""
    xml = wd4_variants()[variant_name]
    return xml_to_phonefast_text(xml), parse_meaningful_nodes(xml)


@functools.lru_cache(maxsize=None)
def scenario_run(scenario_name: str, variant_name: str, prompt: str) -> RunOutcome:
    """跑一次 (场景,变体,prompt) 并缓存结果（variant 字段已填充）。"""
    sc = next(s for s in wd4_scenarios() if s.name == scenario_name)
    text, nodes = variant_materials(variant_name)
    outcome = _run_scenario(sc, text, nodes, prompt)
    outcome.variant = variant_name
    return outcome
