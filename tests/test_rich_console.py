"""P1-16 回归：动态文本进 Rich markup 必须转义。

背景：LLM 输出 / 工具摘要 / 判定理由等动态文本直接拼进 markup 模板——
文本中的 "[/]" 抛 MarkupError 崩 CLI，"[word]" 被当样式标签静默吞掉
（元素 dump 里的 "[0] text=..."、verify_detail 里的 "[command]" 正撞枪口）。
契约：动态内容渲染后必须逐字保留，不抛异常。
"""
from __future__ import annotations

import pytest

from fastaget.format.rich_console import RichConsole

# (测试名, 调用, 必须逐字保留的子串)
_CASES = [
    ("llm_text-closing-tag", lambda: RichConsole.llm_text("tap [/] then done"), ("[/]",)),
    ("llm_text-word-brackets", lambda: RichConsole.llm_text("found [command] in output"), ("[command]",)),
    # 工具摘要常含元素 dump '[0] text="WiFi"'——必须逐字保留
    ("tool_done-element-dump",
     lambda: RichConsole.tool_done(0.3, True, '[0] text="WiFi" [clickable]'),
     ('[0] text="WiFi"', "[clickable]")),
    ("tool_line-args",
     lambda: RichConsole.tool_line("tap", "bounds=[0,100][200,200]", step=1),
     ("bounds=[0,100][200,200]",)),
    ("case_result-summary",
     lambda: RichConsole.case_result(True, 3, 0.01, "verify [command] ok"),
     ("[command]",)),
    # node_id 被 '[...]' 包裹——未转义时整段被当标签吞掉
    ("flow_step-node-id", lambda: RichConsole.flow_step(True, "install_1", "done ok"), ("install_1",)),
    ("flow_step-summary",
     lambda: RichConsole.flow_step(False, "n1", "err at [line 3]", elapsed=1.2),
     ("[line 3]",)),
    ("flow_expect-desc",
     lambda: RichConsole.flow_expect(False, "fail", "wifi [x] off", "saw [maybe]"),
     ("[x]", "[maybe]")),
    ("steering-text", lambda: RichConsole.steering("user", "pls check [wifi] now"), ("[wifi]",)),
    ("case_banner-name", lambda: RichConsole.case_banner(1, 5, "T01 [baseline]"), ("[baseline]",)),
    ("error", lambda: RichConsole.error("boom [/] at [step 2]"), ("[step 2]",)),
    ("warn", lambda: RichConsole.warn("boom [/] at [step 2]"), ("[step 2]",)),
    ("skip", lambda: RichConsole.skip("boom [/] at [step 2]"), ("[step 2]",)),
    ("reset_step", lambda: RichConsole.reset_step("boom [/] at [step 2]"), ("[step 2]",)),
]


class TestDynamicTextEscaped:
    """动态文本中的方括号序列：不崩 + 不丢字。"""

    @pytest.mark.parametrize("name,call,needles", _CASES, ids=[c[0] for c in _CASES])
    def test_brackets_preserved_verbatim(self, name, call, needles):
        out = call()
        for needle in needles:
            assert needle in out, f"{name}: {needle!r} 未逐字保留于输出"

    def test_tool_done_failed_prefix_still_stripped(self):
        """既有 [FAILED] 前缀剥离行为不受转义影响。"""
        out = RichConsole.tool_done(0.1, False, "[FAILED] no element")
        assert "[FAILED]" not in out
        assert "no element" in out
