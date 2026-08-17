"""SemanticJudge：语义判定器（原生 tool-calling，协议级结构化输入输出）。

与执行 LLM 隔离——用独立的 LLMDelegate 实例，避免"学生批改自己作业"的同源偏差。
判定时不喂执行历史，只给 LLM：预期描述 + 当前屏幕，让它独立判断。

结构化保证：
  - 输入：Anthropic 原生 messages（user content blocks）
  - 输出：LLM 调用 judge_result 工具，参数即结构化字段（satisfied/confidence/evidence/reasoning）
  - 零文本解析：从 resp.tool_calls[0].input 直接取 dict，无正则/JSON 解析失败
  - 与 agent 工具链一致：都用原生 tool-calling，全系统协议级结构化

judge prompt 外置于 meta/prompts/judge.txt，支持非开发人员迭代。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastaget.llm.delegate import LLMDelegate


def _judge_prompts_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / "meta" / "prompts"
    return d if d.is_dir() else d


def _load_judge_prompt() -> str:
    fpath = _judge_prompts_dir() / "judge.txt"
    if fpath.is_file():
        return fpath.read_text(encoding="utf-8").strip()
    return _JUDGE_SYSTEM_FALLBACK


_JUDGE_SYSTEM_FALLBACK = """You are a test assertion judge. Determine whether the current phone screen satisfies the given expectation.

You MUST call the judge_result tool to output your verdict, with these parameters:
- satisfied: boolean, whether the screen satisfies the expectation
- confidence: 0.0-1.0, your confidence in the verdict
- evidence: string, specific evidence seen on the screen (quoting actual element text)
- reasoning: string, reasoning process

Rules:
- satisfied=true only when you actually saw evidence on the screen supporting the expectation
- if the screen information is insufficient to judge, use satisfied=false, confidence=0.3
- evidence must quote element text that actually exists on the screen, never fabricate it
- always call the judge_result tool, never output plain text"""

_JUDGE_SYSTEM = _load_judge_prompt()


# judge_result 工具定义（Anthropic Messages API input_schema 格式）
# LLM 通过调用此工具输出结构化判定，零文本解析
_JUDGE_TOOL: dict[str, Any] = {
    "name": "judge_result",
    "description": "Output the assertion verdict. You MUST call this tool after judging whether the screen satisfies the expectation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "satisfied": {
                "type": "boolean",
                "description": "Whether the screen satisfies the expected description",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence 0.0-1.0",
            },
            "evidence": {
                "type": "string",
                "description": "Specific evidence seen on the screen, quoting actual element text",
            },
            "reasoning": {
                "type": "string",
                "description": "Reasoning process",
            },
        },
        "required": ["satisfied", "confidence", "evidence", "reasoning"],
    },
}


@dataclass
class JudgeResult:
    """语义判定结果。"""
    satisfied: bool
    confidence: float
    evidence: str
    reasoning: str


class SemanticJudge:
    """语义判定器（独立 LLM 实例，原生 tool-calling 输出）。"""

    # 文本回退的关键词表（LLM 未调工具时的降级推断）
    _NEGATIVE_WORDS = ("不满足", "未满足", "失败", "not satisfied", "false")
    _POSITIVE_WORDS = ("满足", "satisfied", "true")

    def __init__(self, llm: LLMDelegate) -> None:
        self._llm = llm

    def judge(self, description: str, screen_text: str, hints: list[str] | None = None) -> JudgeResult:
        """判定屏幕是否满足预期描述。

        LLM 通过调用 judge_result 工具输出结构化结果，从 tool_calls 直接取参数，
        无文本解析（零解析失败）。
        """
        hint_text = ""
        if hints:
            hint_text = f"\nHint clues (reference only, not hard conditions): {hints}"

        user = (
            f"Expected goal: {description}{hint_text}\n\n"
            f"Current screen elements:\n{screen_text}\n\n"
            f"Judge whether the expectation is satisfied and call the judge_result tool."
        )
        try:
            resp = self._llm.complete(
                _JUDGE_SYSTEM,
                [{"role": "user", "content": user}],
                [_JUDGE_TOOL],
            )
            return self._extract(resp)
        except Exception as e:
            return JudgeResult(
                satisfied=False, confidence=0.0,
                evidence="", reasoning=f"judge error: {e}",
            )

    def _extract(self, resp: Any) -> JudgeResult:
        """从 LLM 响应的 tool_calls 提取结构化判定结果。

        协议级结构化：tool_calls[0].input 已是 dict，无需 JSON 解析。
        兜底：LLM 未调工具（end_turn）时，从文本推断或返回低置信默认。
        """
        # 优先：LLM 调用了 judge_result 工具
        if resp.tool_calls:
            for tc in resp.tool_calls:
                if tc.name == "judge_result":
                    inp = tc.input
                    return JudgeResult(
                        satisfied=bool(inp.get("satisfied", False)),
                        confidence=float(inp.get("confidence", 0.0)),
                        evidence=str(inp.get("evidence", "")),
                        reasoning=str(inp.get("reasoning", "")),
                    )
            # 调了其他工具（不应发生），取第一个的 input 兜底
            inp = resp.tool_calls[0].input
            return JudgeResult(
                satisfied=bool(inp.get("satisfied", False)),
                confidence=float(inp.get("confidence", 0.0)),
                evidence=str(inp.get("evidence", "")),
                reasoning=str(inp.get("reasoning", "")),
            )
        # 兜底：LLM 未调工具（end_turn）——协议违规，无法可靠判定。
        # 默认 satisfied=False（与 judge prompt "信息不足以判断 → false" 一致；
        # 评测层宁可 false FAIL 不可 fake PASS——空文本/拒答不含否定词，
        # 旧逻辑会把"无法判定"误判为满足）。
        # 仅当文本含明确肯定且无否定时才采信；否定优先（"不满足"含子串"满足"）
        text = (resp.text or "").lower()
        negative = any(w in text for w in self._NEGATIVE_WORDS)
        positive = any(w in text for w in self._POSITIVE_WORDS)
        satisfied = positive and not negative
        return JudgeResult(
            satisfied=satisfied, confidence=0.3,
            evidence="", reasoning=f"LLM 未调用 judge_result 工具，从文本推断: {resp.text[:100]}",
        )
