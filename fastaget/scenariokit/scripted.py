"""scripted: PromptAwareScriptedLLM — deterministic A/B test scripted LLM.

Detects prompt quality by keyword-matching the system prompt content, simulating how
a real LLM would behave with vs. without certain guidance. Enables deterministic
measurement of prompt optimization effects without real LLM randomness.
"""
from __future__ import annotations

from typing import Any

from fastaget.llm.delegate import LLMDelegate, LLMResponse, ToolCall

from fastaget.scenariokit.scenarios import (
    Scenario,
    _find_clickable_ancestor,
    _find_node_by_desc,
    _find_node_by_text,
)


class PromptAwareScriptedLLM(LLMDelegate):
    """Scripted LLM that selects element quality based on system prompt content.

    - Prompt contains "Switch" guidance → toggle task selects Switch element (correct)
    - Prompt lacks it → toggle task selects item title text (wrong)
    - Prompt contains "clickable container" guidance → list task selects clickable container (correct)
    - Prompt lacks it → selects internal text node (wrong)

    Enables deterministic measurement of prompt quality improvements.
    """

    def __init__(self, scenario: Scenario, nodes: list[dict]) -> None:
        self._scenario = scenario
        self._nodes = nodes
        self._call_count = 0
        self._system_prompt = ""
        self._responses: list[LLMResponse] = []

    @property
    def context_window(self) -> int:
        return 128_000

    def _build_responses(self) -> list[LLMResponse]:
        """Build response sequence from scenario + current system prompt."""
        s = self._scenario
        p = self._system_prompt.lower()
        has_switch_guidance = "switch" in p
        has_container_guidance = "clickable=true" in p or "clickable container" in p
        has_self_heal = "available" in p or "self-heal" in p  # matches "Stagnation Self-Healing"

        responses: list[LLMResponse] = []

        # ---- toggle tasks ----
        if s.kind == "switch":
            switch_node = _find_node_by_desc(self._nodes, s.target_desc)
            if switch_node is None:
                responses.append(self._tool_use("observe", {}))
                responses.append(self._tool_use("complete", {
                    "result": f"not found: {s.target_desc}", "success": False,
                }))
                return responses
            if has_switch_guidance:
                responses.append(self._tool_use("tap_element", {"index": switch_node["idx"]}))
                responses.append(self._tool_use("assert", {
                    "description": f"{s.target_desc} state flipped", "passed": True,
                }))
                responses.append(self._tool_use("complete", {
                    "result": f"toggled {s.target_desc}", "success": True,
                }))
            else:
                label = _find_node_by_text(self._nodes, s.label_text or "")
                wrong_idx = label["idx"] if label else 0
                responses.append(self._tool_use("tap_element", {"index": wrong_idx}))
                responses.append(self._tool_use("complete", {
                    "result": f"tapped {s.label_text}", "success": True,
                }))

        # ---- list-item navigation tasks ----
        elif s.kind == "navigate":
            target = _find_node_by_text(self._nodes, s.target_text or "")
            if target is None:
                responses.append(self._tool_use("observe", {}))
                responses.append(self._tool_use("complete", {
                    "result": f"not found: {s.target_text}", "success": False,
                }))
                return responses
            if has_container_guidance and not target["clickable"]:
                ancestor = _find_clickable_ancestor(self._nodes, target)
                tap_idx = ancestor["idx"] if ancestor else target["idx"]
            else:
                tap_idx = target["idx"]
            responses.append(self._tool_use("tap_element", {"index": tap_idx}))
            responses.append(self._tool_use("complete", {
                "result": f"entered {s.target_text}", "success": True,
            }))

        # ---- back tasks ----
        elif s.kind == "back":
            responses.append(self._tool_use("back", {}))
            responses.append(self._tool_use("complete", {
                "result": "went back", "success": True,
            }))

        # ---- error recovery tasks (tests agent self-healing) ----
        elif s.kind == "self_heal":
            wrong_idx = 9999
            responses.append(self._tool_use("tap_element", {"index": wrong_idx}))
            if has_self_heal:
                switch_node = _find_node_by_desc(self._nodes, s.target_desc)
                correct_idx = switch_node["idx"] if switch_node else 0
                responses.append(self._tool_use("observe", {}))
                responses.append(self._tool_use("tap_element", {"index": correct_idx}))
                responses.append(self._tool_use("complete", {
                    "result": f"self-healed to {s.target_desc}", "success": True,
                }))
            else:
                responses.append(self._tool_use("complete", {
                    "result": "element not found", "success": False,
                }))

        # ---- unresponsive screen (loading/empty) ----
        elif s.kind == "unresponsive":
            has_unresponsive_guidance = "unresponsive" in p or "loading" in p
            if has_unresponsive_guidance:
                responses.append(self._tool_use("complete", {
                    "result": "screen unresponsive, cannot operate", "success": False,
                }))
            else:
                responses.append(self._tool_use("observe", {}))
                responses.append(self._tool_use("complete", {
                    "result": "cannot complete task", "success": False,
                }))

        # ---- state awareness: toggle already off, don't toggle again ----
        elif s.kind == "verify_state":
            has_state_guidance = "already off" in p or "checked" in p or "already satisfied" in p
            if has_state_guidance:
                responses.append(self._tool_use("observe", {}))
                responses.append(self._tool_use("complete", {
                    "result": f"confirmed {s.target_desc} already at target state", "success": True,
                }))
            else:
                switch_node = _find_node_by_desc(self._nodes, s.target_desc)
                wrong_idx = switch_node["idx"] if switch_node else 0
                responses.append(self._tool_use("tap_element", {"index": wrong_idx}))
                responses.append(self._tool_use("complete", {
                    "result": "toggled switch", "success": True,
                }))

        # ---- input flow: type + key(enter) ----
        elif s.kind == "input_flow":
            has_enter_guidance = "enter" in p or "search" in p or "enter key" in p
            responses.append(self._tool_use("type", {"text": "bluetooth"}))
            if has_enter_guidance:
                responses.append(self._tool_use("key", {"name": "enter"}))
                responses.append(self._tool_use("observe", {}))
                responses.append(self._tool_use("complete", {
                    "result": "searched and found results", "success": True,
                }))
            else:
                responses.append(self._tool_use("complete", {
                    "result": "typed search term", "success": True,
                }))

        # ---- error recovery: back + retry ----
        elif s.kind == "recover":
            responses.append(self._tool_use("back", {}))
            responses.append(self._tool_use("observe", {}))
            switch_node = _find_node_by_desc(self._nodes, s.target_desc)
            if switch_node:
                responses.append(self._tool_use("tap_element", {"index": switch_node["idx"]}))
            responses.append(self._tool_use("complete", {
                "result": f"went back and toggled {s.target_desc}", "success": True,
            }))

        # ---- max_steps exhaustion: target missing, tap repeatedly without completing ----
        elif s.kind == "exhaustion":
            indices = [n["idx"] for n in self._nodes[:3]] or [0, 1, 2]
            for i in range(20):
                responses.append(self._tool_use("tap_element", {"index": indices[i % len(indices)]}))
                responses.append(self._tool_use("observe", {}))

        # ---- tool chain failure: tap keeps failing ----
        elif s.kind == "tool_failure":
            for i in range(3):
                responses.append(self._tool_use("tap_element", {"index": i}))
            if has_self_heal:
                responses.append(self._tool_use("observe", {}))
            responses.append(self._tool_use("complete", {
                "result": "tools continuously failed, cannot complete", "success": False,
            }))

        return responses

    @staticmethod
    def _tool_use(name: str, inp: dict) -> LLMResponse:
        return LLMResponse(
            text="",
            tool_calls=[ToolCall(name=name, input=inp, id=f"call_{name}_{abs(hash(name + str(inp)))}")],
            stop_reason="tool_use",
            cost_usd=0.0,
        )

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        vision: bool = False,
        tool_choice: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if self._call_count == 0:
            self._system_prompt = system
            self._responses = self._build_responses()
        idx = self._call_count
        self._call_count += 1
        if idx < len(self._responses):
            return self._responses[idx]
        return LLMResponse(
            text="task ended", tool_calls=[], stop_reason="end_turn", cost_usd=0.0,
        )

    def close(self) -> None:
        pass
