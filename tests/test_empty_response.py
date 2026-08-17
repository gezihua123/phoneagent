"""P0-2 回归：空 LLM 响应（无 text 无 tool_calls）不得毒化消息历史。

背景：_llm_turn 曾把 {'role':'assistant','content':[]} 追加进 messages——
Anthropic API 拒绝空 content 数组，下次调用 HTTP 400 → FaultTolerance 杀 run。
正确行为（与 max_tokens 分支一致）：不追加空消息，注入 empty_response
反馈，主循环 _last_is_assistant 检查跳过本轮、下轮重试。
"""
from __future__ import annotations

from fastaget.agent.fast_agent import FastAgent
from fastaget.llm.delegate import LLMResponse, ToolCall
from fastaget.tools import build_registry

from fastaget.scenariokit import MockPhonefast

from tests.conftest import FLATREF_SCREEN


class _EmptyThenCompleteLLM:
    """第 1 次返回空响应，之后返回 complete——模拟 API 间歇性空应答。"""

    model = "test-model"

    def __init__(self, empty_rounds: int = 1):
        self.calls = 0
        self._empty_rounds = empty_rounds
        self.user_msg_counts: list[int] = []  # 每次调用时 messages 中 user 消息数

    def complete(self, system, messages, tools, *, vision=False, **_):
        self.calls += 1
        self.user_msg_counts.append(
            sum(1 for m in messages if m.get("role") == "user"))
        if self.calls <= self._empty_rounds:
            return LLMResponse(
                text="", tool_calls=[], stop_reason="end_turn", cost_usd=0.001,
                raw={"usage": {"input_tokens": 100, "output_tokens": 0}},
            )
        return LLMResponse(
            text="done", tool_calls=[
                ToolCall(name="complete", input={"result": "ok", "success": True}, id="t1")],
            stop_reason="tool_use", cost_usd=0.003,
            raw={"usage": {"input_tokens": 100, "output_tokens": 5}},
        )

    def close(self):
        pass


def _agent(llm) -> FastAgent:
    return FastAgent(llm, MockPhonefast(FLATREF_SCREEN), build_registry())


def test_empty_response_does_not_poison_history():
    """空响应后 run 必须自愈完成，且历史中无空 assistant 消息。"""
    llm = _EmptyThenCompleteLLM(empty_rounds=1)
    agent = _agent(llm)
    result = agent.run("task")

    assert result.success, f"空响应后应自愈完成，got: {result.summary}"
    assert llm.calls == 2, "空响应后应重试 LLM 调用"
    empties = [
        m for m in agent._context.messages
        if m.get("role") == "assistant" and not m.get("content")
    ]
    assert not empties, f"历史中不得有空 assistant 消息（毒化源）: {empties}"


def test_empty_response_injects_feedback():
    """空响应必须触发 empty_response 反馈注入（下轮随 _drain_pending 送达）。

    结构化断言（不钉模板措辞）：空响应那轮没有追加任何 assistant/tool 消息，
    因此两次 LLM 调用间新增的 user 消息只能是注入的反馈。"""
    llm = _EmptyThenCompleteLLM(empty_rounds=1)
    agent = _agent(llm)
    agent.run("task")

    assert llm.calls == 2
    assert llm.user_msg_counts[1] > llm.user_msg_counts[0], \
        "空响应后应注入一条 user 反馈消息再重试 LLM"


def test_repeated_empty_responses_eventually_succeed():
    """连续多轮空响应也不追加空消息，LLM 恢复后照常完成。"""
    llm = _EmptyThenCompleteLLM(empty_rounds=3)
    agent = _agent(llm)
    result = agent.run("task")

    assert result.success
    assert llm.calls == 4
    assert all(
        m.get("content") for m in agent._context.messages
        if m.get("role") == "assistant"
    )
