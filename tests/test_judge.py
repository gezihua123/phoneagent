"""P0-5 回归：judge 文本回退不得默认 satisfied=True（评测层假 PASS）。

背景：LLM 未调 judge_result 工具时，旧回退只查否定词——
空文本/拒答（"I cannot determine..."）没有任何否定词 → satisfied=True，
评测层把"无法判定"记为 PASS，对比数据作废。
正确语义与 judge prompt 一致："信息不足以判断 → satisfied=false"。
"""
from __future__ import annotations

from fastaget.flow.judge import SemanticJudge
from fastaget.llm.delegate import LLMResponse, ToolCall

from tests.conftest import ScriptedResponseLLM


def _text_resp(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn",
                       cost_usd=0.0, raw={})


def _tool_resp(satisfied: bool) -> LLMResponse:
    return LLMResponse(
        text="", tool_calls=[ToolCall(
            name="judge_result",
            input={"satisfied": satisfied, "confidence": 0.9,
                   "evidence": "screen shows X", "reasoning": "..."},
            id="j1")],
        stop_reason="tool_use", cost_usd=0.0, raw={})


def _judge(llm) -> SemanticJudge:
    return SemanticJudge(llm)  # type: ignore[arg-type]


# ---- 文本回退（无 tool_call）----

def test_fallback_empty_text_is_not_satisfied():
    """空白响应（协议违规）不得判 PASS——这是 P0-5 的核心回归。"""
    j = _judge(ScriptedResponseLLM([_text_resp("")]))
    r = j.judge("Wi-Fi 已关闭", "screen text")
    assert not r.satisfied, "空文本回退必须 satisfied=False（无法判定 ≠ 满足）"
    assert r.confidence <= 0.3


def test_fallback_refusal_text_is_not_satisfied():
    """拒答/不确定文本不得判 PASS。"""
    j = _judge(ScriptedResponseLLM([_text_resp("I cannot determine this from the screen.")]))
    r = j.judge("Wi-Fi 已关闭", "screen text")
    assert not r.satisfied


def test_fallback_negative_text_is_not_satisfied():
    """含否定词的文本判 False（修复前后都应成立）。"""
    j = _judge(ScriptedResponseLLM([_text_resp("预期不满足，屏幕还停留在首页")]))
    r = j.judge("Wi-Fi 已关闭", "screen text")
    assert not r.satisfied


def test_fallback_positive_text_is_satisfied():
    """明确肯定且无否定的文本仍可判 True——不得过度修正成恒 False。"""
    j = _judge(ScriptedResponseLLM([_text_resp("预期已满足，屏幕上可以看到 Wi-Fi 处于关闭状态")]))
    r = j.judge("Wi-Fi 已关闭", "screen text")
    assert r.satisfied


def test_fallback_negation_containing_positive_word():
    """'不满足' 含子串 '满足'——必须先判否定，防止误判 True。"""
    j = _judge(ScriptedResponseLLM([_text_resp("不满足")]))
    r = j.judge("Wi-Fi 已关闭", "screen text")
    assert not r.satisfied


# ---- 正常路径回归保护 ----

def test_tool_call_path_unaffected():
    """正常 tool-calling 路径：satisfied 取自工具参数。"""
    j = _judge(ScriptedResponseLLM([_tool_resp(True), _tool_resp(False)]))
    assert j.judge("d", "s").satisfied is True
    assert j.judge("d", "s").satisfied is False


def test_llm_exception_is_not_satisfied():
    """LLM 调用异常 → satisfied=False（已有行为，防回归）。"""
    class _BoomLLM:
        def complete(self, *a, **k):
            raise RuntimeError("api down")
        def close(self):
            pass

    r = _judge(_BoomLLM()).judge("d", "s")
    assert not r.satisfied
    assert r.confidence == 0.0
