"""OcrAction 回归测试——ctx.memory 为 AgentMemory（生产路径）时不得崩（P0-1）。

背景：FastAgent.__init__ 总是 ctx.set_agent_memory(AgentMemory(), ns)，
而 OcrAction 曾调用 ctx.memory.get()——AgentMemory 只有 recall/__getitem__，
AttributeError 逃逸 except (TypeError, ValueError) → ocr 工具 100% 报失败。
"""
from unittest.mock import MagicMock

from fastaget.agent.memory import AgentMemory
from fastaget.tools.actions import OcrAction
from fastaget.tools.context import ActionContext


def _ctx_with_agent_memory(ocr_result: dict) -> ActionContext:
    pf = MagicMock()
    pf.ocr.return_value = ocr_result
    ctx = ActionContext(phonefast=pf)
    ctx.set_agent_memory(AgentMemory(), "test")  # 生产路径：总是 AgentMemory
    return ctx


def test_ocr_with_agent_memory_succeeds():
    """绑定 AgentMemory 时 ocr 必须成功返回（不得抛 AttributeError）。"""
    ctx = _ctx_with_agent_memory(
        {"items": [{"text": "Wi-Fi", "center": [100, 200], "confidence": 0.9}]}
    )
    ar = OcrAction()(ctx=ctx)
    assert ar.success, f"ocr should succeed with AgentMemory bound, got: {ar.summary}"
    assert "1 text regions" in ar.summary


def test_ocr_empty_is_still_success():
    """OCR 空返回不算失败——报告现状，由 agent 层 Guards 处理停滞。"""
    ctx = _ctx_with_agent_memory({"items": []})
    ar = OcrAction()(ctx=ctx)
    assert ar.success
    assert "NO text" in ar.summary


def test_ocr_does_not_mutate_ctx_memory():
    """OCR 为无状态工具，不写 ctx.memory（状态机纪律）。"""
    ctx = _ctx_with_agent_memory({"items": []})
    facts_before = dict(ctx.memory.facts)
    OcrAction()(ctx=ctx)
    OcrAction()(ctx=ctx)
    assert ctx.memory.facts == facts_before, (
        f"OCR mutated memory: {set(ctx.memory.facts) - set(facts_before)}")


def test_ocr_with_plain_dict_memory_also_works():
    """旧 dict 回退路径（未绑定 AgentMemory）同样可用。"""
    pf = MagicMock()
    pf.ocr.return_value = {"items": [{"text": "OK", "center": [1, 2], "confidence": 0.8}]}
    ctx = ActionContext(phonefast=pf)  # 不绑定 AgentMemory → dict 回退
    ar = OcrAction()(ctx=ctx)
    assert ar.success
