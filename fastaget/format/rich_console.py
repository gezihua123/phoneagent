"""Rich-based terminal output formatting.

Migrated from hand-rolled ANSI (terminal.py) to Rich for professional
terminal styling — Panel, Rule, markup colors, CJK support out of box.

Style reference: mobilerun (emoji-prefixed + Rich Console style= coloring).
New API (v2) produces cleaner, more scannable output with visual hierarchy.

Usage::

    from fastaget.format.rich_console import RichConsole

    # Inline (returns strings, compatible with print())
    print(RichConsole.case_banner(1, 5, "test", "deepseek-v4-pro", 15))

    # Report (returns Rich-rendered strings; auto-strips colors when piped)
    card = RichConsole.case_card(success=True, name="test", goal="go",
                                  steps=3, cost=0.0012)
    print(card)  # colored in TTY, plain in pipe

RichConsole delegates to a module-level `_console` instance that auto-detects
TTY.  Callers that produce plain-text output (e.g. report save to file) can
force non-TTY by setting `force_terminal=False`.
"""
from __future__ import annotations

import io
from typing import Any

from rich.console import Console as RichConsoleLib
from rich.markup import escape as _escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text


# ═══════════════════════════════════════════════════════
# Module-level Rich Console (auto-detect TTY)
# ═══════════════════════════════════════════════════════

_console = RichConsoleLib(highlight=False)
"""Rich Console instance for rendering. Auto-detects TTY for color output."""


def _render(renderable, *, force_terminal: bool | None = None) -> str:
    """Render a Rich object to string, with TTY-awareness.

    When force_terminal=False or stdout is not a TTY, strips ANSI codes
    automatically (Rich Console does this). Useful for file output.
    """
    if force_terminal is False:
        buf = io.StringIO()
        c = RichConsoleLib(file=buf, force_terminal=False, highlight=False)
        c.print(renderable)
        return buf.getvalue().rstrip("\n")
    with _console.capture() as capture:
        _console.print(renderable)
    return capture.get().rstrip("\n")


# ═══════════════════════════════════════════════════════
# Emoji constants
# ═══════════════════════════════════════════════════════

# ── 核心表情符号（精简到 8 个）──
LLM = "🤖"
LLM_TURN = "🎉"        # 轮次分隔
ACTION = "🎯"
STEERING = "📢"
PASS_EMOJI = "✅"
FAIL_EMOJI = "❌"
WARN_EMOJI = "⚠️"
INIT_EMOJI = "⚙️"

# ── 排版符号（非 emoji，单字符）──
OK = "✓"
BAD = "✗"
PASS_MARK = "✔"       # 加重对勾，用于醒目的 PASS 显示
FAIL_MARK = "✘"       # 加重叉号，用于醒目的 FAIL 显示

# ── 已删除的策略性常量（保留下划线占位以便 grep/code search 回溯）──
# OBSERVE / AUTO_OBSERVE / WAIT / COMPLETE / ASSERT / SEARCH / PACKAGE
# FALLBACK / ERROR_EMOJI / CASE / DELEGATE / PRECONDITION / REPORT / RESET / SKIP_EMOJI
# 上述旧 emoji (📷📱⏳🏁✔️🔍📦🔧💥📋🔌🚧📊🔄⏭️) 已替换为纯文本标签

# ═══════════════════════════════════════════════════════
# Tool -> emoji mapping
# ═══════════════════════════════════════════════════════

_TOOL: dict[str, str] = {
    "tap": ACTION,
    "tap_element": ACTION,
    "tap_by_text": ACTION,
    "long_press": ACTION,
    "long_press_at": ACTION,
    "type": ACTION,
    "type_secret": ACTION,
    "fill_fields": ACTION,
    "swipe": ACTION,
    "key": ACTION,
    "back": ACTION,
    "home": ACTION,
    "launch": ACTION,
    "navigate_to": ACTION,
    "shell": ACTION,
    # observe / wait / complete / assert 等工具无前缀，由 tool_line 直接打印工具名
}


def _render_markup(markup: str) -> str:
    """Render Rich markup text to ANSI (TTY) or plain (piped)."""
    return _render(Text.from_markup(markup))

class RichConsole:
    """Terminal output formatting backed by Rich.

    All methods return strings. Rich markup is used internally — the
    module-level `_console` renders with TTY auto-detection.

    v2 API (new):
      - case_banner, llm_header, llm_text, tool_line, tool_done, case_result
      - flow_step, flow_expect, flow_phase, skip, warn, reset, init_step
      - auto_observe, steering, delegate, precondition, error

    v1 API (deprecated, kept for compat):
      - case_header, llm_turn, tool_line (old), tool_result, result

    Report API (unchanged):
      - report_header, section, case_card, case_card_flow, suite_summary_section
    """

    # Re-export emoji as class attributes for backward compat
    LLM = LLM
    LLM_TURN = LLM_TURN
    ACTION = ACTION
    STEERING = STEERING
    PASS = PASS_EMOJI
    FAIL = FAIL_EMOJI
    WARN = WARN_EMOJI
    OK = OK
    BAD = BAD
    PASS_MARK = PASS_MARK
    FAIL_MARK = FAIL_MARK

    # ── Rich styling helpers ──
    _PASS_BORDER = "green"
    _FAIL_BORDER = "red"
    _SKIP_BORDER = "yellow"
    _NEUTRAL_BORDER = "bright_black"

    @classmethod
    def tool_emoji(cls, name: str) -> str:
        return _TOOL.get(name, "")

    # ═══════════════════════════════════════════════════
    # v2 Inline API — clean, scannable, mobilerun-inspired
    # ═══════════════════════════════════════════════════

    @staticmethod
    def case_banner(i: int, total: int, name: str, model: str = "",
                    max_steps: int = 0, mode: str = "") -> str:
        """Case banner with Rich Rule separator.

        Example:
            ━━ [case] Case 1/5 · 打开设置 ━━  deepseek-v4-pro · 15 steps · direct
        """
        left = f"[bold bright_white]\\[case] Case {i}/{total}[/]"
        if name:
            left += f"[bright_white] · {_escape(name)}[/]"
        right_parts = []
        if model:
            right_parts.append(f"[dim]{_escape(model)}[/]")
        if max_steps:
            right_parts.append(f"[dim]{max_steps} steps[/]")
        if mode and mode != "direct":
            right_parts.append(f"[dim]{_escape(mode)}[/]")
        if right_parts:
            left += "  " + " · ".join(right_parts)
        rule = Rule(title=Text.from_markup(left), style="bright_black")
        return _render(rule)

    @staticmethod
    def llm_header(call: int, elapsed: float, *, cost: float | None = None,
                   inp_tok: int = 0, out_tok: int = 0, cache_tok: int = 0) -> str:
        """LLM turn header line — rendered with Rich for color.

        Example:
            ▶ #1  5.5s · $0.0004
            ▶ #2  2.2s · $0.0001 · tok 1928→253
        """
        parts = [f"{LLM_TURN} [bold cyan]#{call}[/]  [dim]{elapsed:.1f}s[/]"]
        if cost is not None and cost > 0:
            parts.append(f"[dim yellow]${cost:.4f}[/]")
        if inp_tok or out_tok:
            parts.append(f"[dim]tok {inp_tok}→{out_tok}[/]")
            if cache_tok:
                parts.append(f"[dim]cache:{cache_tok}[/]")
        return _render_markup(" · ".join(parts))

    @staticmethod
    def llm_text(preview: str, max_len: int = 100) -> str:
        """LLM text preview line — dim italic, clipped for scanning."""
        if not preview:
            return ""
        text = preview.replace("\n", " ").strip()
        if len(text) > max_len:
            text = text[:max_len] + "…"
        return _render_markup(f"  [dim italic]\"{_escape(text)}\"[/]")

    @staticmethod
    def tool_line(name: str, args: str = "", step: int = 0) -> str:
        """Tool execution line start (inline, no newline — pair with tool_done).

        Example:
            🎯 tap_element "更多选项"
        """
        emoji = RichConsole.tool_emoji(name)
        markup = f"  {emoji} [bold]{_escape(name)}[/]"
        if args:
            markup += f" [dim]{_escape(args)}[/]"
        return _render_markup(markup)

    @staticmethod
    def tool_done(elapsed: float, success: bool, summary: str) -> str:
        """Inline tool result — completes the line started by tool_line."""
        tag = f"[green]{OK}[/]" if success else f"[red]{BAD}[/]"
        clean = (summary or "").replace("\n", " ").strip()
        if clean.startswith("[OK] "):
            clean = clean[5:]
        elif clean.startswith("[FAILED] "):
            clean = clean[9:]
        return _render_markup(f"  [dim]{elapsed:.1f}s[/] {tag}  {_escape(clean[:80])}")

    @staticmethod
    def case_result(success: bool, steps: int, cost: float, summary: str) -> str:
        """Case final result line.

        Example:
            ✔ PASS  7 steps · $0.0021  Instagram 已是最新版本
        """
        mark = f"[bold green]{PASS_MARK} PASS[/]" if success else f"[bold red]{FAIL_MARK} FAIL[/]"
        parts = [mark, f"[dim]{steps} steps[/]"]
        if cost > 0:
            parts.append(f"[dim yellow]${cost:.4f}[/]")
        line = "  " + " · ".join(parts)
        if summary:
            short = str(summary).replace("\n", " ")[:80]
            line += f"  [bright_black]{_escape(short)}[/]"
        return _render_markup(line)

    @staticmethod
    def auto_observe(n: int) -> str:
        return _render_markup(f"  [dim]\\[auto] {n} elements[/]")

    @staticmethod
    def steering(source: str, preview: str) -> str:
        text = (preview or "").replace("\n", " ")[:100]
        return _render_markup(f"  [yellow]{STEERING} {_escape(source)}[/]: [dim]{_escape(text)}[/]")

    @staticmethod
    def delegate(model: str) -> str:
        return _render_markup(f"  [dim]\\[delegate] AnthropicHTTPDelegate (model={_escape(model)})[/]")

    @staticmethod
    def precondition(count: int) -> str:
        return _render_markup(f"  [dim]\\[precondition] {count} preconditions[/]")

    @staticmethod
    def error(msg: str) -> str:
        return _render_markup(f"  [bold red]{FAIL_EMOJI} {_escape(msg)}[/]")

    @staticmethod
    def warn(msg: str) -> str:
        return _render_markup(f"  [yellow]{WARN_EMOJI} {_escape(msg)}[/]")

    @staticmethod
    def skip(msg: str) -> str:
        return _render_markup(f"  [yellow]\\[skip] {_escape(msg)}[/]")

    @staticmethod
    def reset_step(msg: str) -> str:
        return _render_markup(f"  [dim]\\[reset] {_escape(msg)}[/]")

    @staticmethod
    def init_step(cmd: str) -> str:
        return _render_markup(f"  [dim]{INIT_EMOJI} {_escape(cmd[:60])}[/]")

    # ── Flow runner methods ──

    @staticmethod
    def flow_phase(phase: str, count: int) -> str:
        return _render_markup(f"  [bold cyan]\\[{_escape(phase)}][/] [dim]· {count} items[/]")

    @staticmethod
    def flow_step(success: bool, node_id: str, summary: str,
                  elapsed: float = 0.0, cost: float = 0.0) -> str:
        """Flow node execution result line."""
        tag = f"[green]{OK}[/]" if success else f"[red]{BAD}[/]"
        clean = (summary or "").replace("\n", " ")[:70]
        # node_id 外层的方括号是要显示的字符——必须写成转义形式，
        # 否则 [{node_id}] 整体被当样式标签静默吞掉
        line = f"  {tag} [bold]\\[{_escape(node_id)}][/] {_escape(clean)}"
        if elapsed > 0:
            line += f" [dim]({elapsed:.1f}s[/]"
            if cost > 0:
                line += f" [dim yellow]${cost:.4f}[/]"
            line += "[dim])[/]"
        return _render_markup(line)

    @staticmethod
    def flow_expect(passed: bool, severity: str, description: str,
                    judge: str = "") -> str:
        """Flow expectation check result."""
        if severity == "warn":
            tag = "~" if not passed else OK
            tag_markup = f"[yellow]{tag}[/]"
        elif passed:
            tag_markup = f"[green]{OK}[/]"
        else:
            tag_markup = f"[red]{BAD}[/]"
        desc = (description or "")[:60]
        line = f"    {tag_markup} [dim]expect:[/] {_escape(desc)}"
        if judge:
            line += f" [dim]({_escape(judge)})[/]"
        return _render_markup(line)


    # ═══════════════════════════════════════════════════
    # Report API (unchanged)
    # ═══════════════════════════════════════════════════

    WIDTH = 72

    @classmethod
    def _panel(cls, content: str | Text | Table, *,
               title: str | None = None,
               border_style: str = "bright_black",
               padding: tuple[int, int] = (1, 2)) -> str:
        """Render content inside a Rich Panel."""
        panel = Panel(content, title=title, border_style=border_style,
                      padding=padding, expand=False)
        return _render(panel)

    @classmethod
    def _rule(cls, title: str = "", style: str = "bright_black") -> str:
        """Render a Rich horizontal rule."""
        rule = Rule(title=title, style=style)
        return _render(rule)

    @staticmethod
    def _tag_pass() -> str:
        return "[bold white on green] PASS [/bold white on green]"

    @staticmethod
    def _tag_fail() -> str:
        return "[bold white on red] FAIL [/bold white on red]"

    @staticmethod
    def _tag_skip() -> str:
        return "[black on yellow] SKIP [/black on yellow]"

    @classmethod
    def _result_tag(cls, success: bool) -> str:
        return cls._tag_pass() if success else cls._tag_fail()

    @classmethod
    def report_header(cls, total: int) -> str:
        left = f"[bold bright_white]\\[Report] Test Suite Report[/]"
        right = f"[dim]{total} cases[/]"
        rule = Rule(title=Text.from_markup(f"{left}  {right}"),
                    style="bright_black")
        return _render(rule)

    @classmethod
    def section(cls, label_text: str) -> str:
        return f"[bold cyan]{label_text}[/]"

    @classmethod
    def case_card(cls, success: bool, name: str, goal: str, steps: int, cost: float,
                  *, summary: str = "", healed: int = 0, verify_tag: str = "",
                  verify_detail: str = "",
                  agent_asserts: list[dict[str, object]] | None = None,
                  expected_asserts: list[dict[str, object]] | None = None,
                  skipped: bool = False) -> str:
        """Render a single case as a Rich Panel."""
        lines: list[str] = []

        if skipped:
            icon = f"[bold yellow]{WARN_EMOJI}[/]"
            badge = cls._tag_skip()
        elif success:
            icon = f"[bold green]{OK}[/]"
            badge = cls._tag_pass()
        else:
            icon = f"[bold red]{BAD}[/]"
            badge = cls._tag_fail()

        lines.append(f"{icon} [bold white]{name}[/]  {badge}")
        lines.append("[dim]" + "-" * (cls.WIDTH - 4) + "[/]")
        lines.append(f"[dim]Goal[/]      {goal}")

        metric_parts = [f"{steps} steps", f"[dim]cost[/] ${cost:.4f}"]
        if healed:
            metric_parts.append(f"[dim]healed[/] x{healed}")
        lines.append(f"[dim]Steps[/]     {'    '.join(metric_parts)}")

        if summary:
            lines.append(f"[dim]Summary[/]   {summary}")

        if verify_tag:
            if verify_tag == OK:
                v_text = f"[bold green]{OK} Device verify PASS[/]"
            elif verify_tag == BAD:
                v_text = f"[bold red]{BAD} Device verify FAIL[/]"
            else:
                v_text = "[dim]· No verify[/]"
            if verify_detail:
                v_text += f"  [dim]— {verify_detail}[/]"
            lines.append(f"[dim]Verify[/]    {v_text}")

        if agent_asserts:
            lines.append(f"[bold cyan]  Asserts[/]")
            for a in agent_asserts:
                passed = a.get("passed", False)
                desc = str(a.get("description", ""))
                icon_a = f"[green]{OK}[/]" if passed else f"[red]{BAD}[/]"
                tag = "[green]PASS[/]" if passed else "[red]FAIL[/]"
                lines.append(f"    {icon_a} {tag}  {desc}")

        if expected_asserts:
            lines.append(f"[dim]  Expected[/]")
            for a in expected_asserts:
                desc = str(a.get("description", a.get("expected", "")))
                lines.append(f"    [dim]· {desc}[/]")

        border = cls._PASS_BORDER if success else cls._FAIL_BORDER
        if skipped:
            border = cls._SKIP_BORDER

        content = "\n".join(lines)
        return cls._panel(content, border_style=border)

    @classmethod
    def case_card_flow(cls, success: bool, name: str, elapsed: float, cost: float,
                       coverage: float, *, summary: str = "",
                       path: list[str] | None = None,
                       precondition_detail: list[dict[str, object]] | None = None,
                       step_expects: list[dict[str, object]] | None = None,
                       case_expects: list[dict[str, object]] | None = None,
                       teardown_results: list[dict[str, object]] | None = None,
                       branches_missed: list[str] | None = None) -> str:
        """Render a flow case as a Rich Panel."""
        lines: list[str] = []

        if success:
            icon = f"[bold green]{OK}[/]"
            badge = cls._tag_pass()
        else:
            icon = f"[bold red]{BAD}[/]"
            badge = cls._tag_fail()

        lines.append(f"{icon} [bold white]{name}[/]  {badge}")
        lines.append("[dim]" + "-" * (cls.WIDTH - 4) + "[/]")

        pct = f"{coverage * 100:.0f}%"
        lines.append(
            f"[dim]Elapsed[/]   {elapsed:.1f}s    "
            f"[dim]cost[/] ${cost:.4f}    "
            f"[dim]cover[/] {pct}"
        )

        if summary:
            lines.append(f"[dim]Summary[/]   {summary}")
        if path:
            lines.append(f"[dim]Path[/]      {' → '.join(path)}")

        if precondition_detail:
            lines.append(f"[bold cyan]  Precondition[/]")
            for r in precondition_detail:
                passed = r.get("passed", False)
                desc = str(r.get("description", ""))
                judge = str(r.get("judge", ""))
                sym = f"[green]{OK}[/]" if passed else f"[red]{BAD}[/]"
                lines.append(f"    {sym} {desc}  [dim]({judge})[/]")

        if step_expects:
            lines.append(f"[bold cyan]  Step Expects[/]")
            for r in step_expects:
                passed = r.get("passed", False)
                severity = str(r.get("severity", ""))
                node = str(r.get("node_id", ""))
                desc = str(r.get("description", ""))[:50]
                judge = str(r.get("judge", ""))
                if severity == "warn":
                    sym = f"[yellow]{WARN_EMOJI}[/]"
                elif passed:
                    sym = f"[green]{OK}[/]"
                else:
                    sym = f"[red]{BAD}[/]"
                lines.append(f"    {sym} [dim][{node}][/] {desc}  [dim]({judge})[/]")

        if case_expects:
            lines.append(f"[bold cyan]  Case Expects[/]")
            for r in case_expects:
                passed = r.get("passed", False)
                severity = str(r.get("severity", ""))
                desc = str(r.get("description", ""))[:50]
                judge = str(r.get("judge", ""))
                if severity == "warn":
                    sym = f"[yellow]{WARN_EMOJI}[/]"
                elif passed:
                    sym = f"[green]{OK}[/]"
                else:
                    sym = f"[red]{BAD}[/]"
                lines.append(f"    {sym} {desc}  [dim]({judge})[/]")

        if branches_missed:
            lines.append(f"[bold yellow]  Missed Branches[/]  {len(branches_missed)}")
            for b in branches_missed[:5]:
                lines.append(f"    [dim]- {b}[/]")

        if teardown_results:
            lines.append(f"[bold cyan]  Teardown[/]")
            for tr in teardown_results:
                ok = tr.get("success", False)
                node = str(tr.get("node_id", ""))
                s = str(tr.get("summary", ""))[:50]
                sym = f"[green]{OK}[/]" if ok else f"[red]{BAD}[/]"
                lines.append(f"    {sym} [dim][{node}][/] {s}")

        border = cls._PASS_BORDER if success else cls._FAIL_BORDER
        content = "\n".join(lines)
        return cls._panel(content, border_style=border)

    @classmethod
    def suite_summary_section(cls, agent_pass: int, total: int, *, cost: float,
                              verify_pass: int = 0, verify_total: int = 0,
                              false_pos: int = 0, false_neg: int = 0,
                              skipped: int = 0) -> str:
        """Render suite summary section."""
        rate = agent_pass / total * 100 if total > 0 else 0
        lines: list[str] = []

        lines.append(f"[bold white]\\[Report] Summary[/]")
        lines.append("")

        lines.append(f"  [dim]Pass Rate[/]     "
                     f"{agent_pass}/{total} passed  "
                     f"[bold yellow]{rate:.1f}%[/]")

        if verify_total > 0:
            v_rate = verify_pass / verify_total * 100 if verify_total > 0 else 0
            lines.append(f"  [dim]Device Verify[/] "
                         f"{verify_pass}/{verify_total} passed  "
                         f"[bold yellow]{v_rate:.1f}%[/]")

        lines.append("")

        bottom: list[str] = []
        fp_text = str(false_pos) if false_pos > 0 else "—"
        bottom.append(f"[bold red]False Pos: {fp_text}[/]" if false_pos > 0
                      else f"[dim]False Pos: {fp_text}[/]")
        fn_text = str(false_neg) if false_neg > 0 else "—"
        bottom.append(f"[bold yellow]False Neg: {fn_text}[/]" if false_neg > 0
                      else f"[dim]False Neg: {fn_text}[/]")
        if skipped > 0:
            bottom.append(f"[yellow]Skipped: {skipped}[/]")
        bottom.append(f"[dim]Total Cost[/] [bold yellow]${cost:.4f}[/]")
        lines.append("  " + "    ".join(bottom))

        content = "\n".join(lines)
        return cls._panel(content, border_style="bright_black")
