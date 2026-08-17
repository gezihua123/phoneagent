"""标准动作集：每个动作是一个可调用类，携带自身的描述、参数和注册元数据。

Action 接口:
  - name: str            — 工具名（LLM 看到的名称）
  - description: str     — LLM 可读的描述文本
  - params: dict         — 参数 schema {name: {type, desc, required?}}
  - is_action: bool      — 是否改变设备状态（操作类工具）
  - is_observation: bool — 是否为感知类（刷新屏幕状态，如 observe）
  - is_assert: bool      — 是否为断言类（验证预期，如 assert）
  - is_retryable: bool   — 是否允许 L1 自愈层重试（wait 等副作用不可重放的工具应设 False）
  - __call__(ctx, **kwargs) → ActionResult  — 执行逻辑

build_registry() 自动发现并注册所有 Action 子类，不集中硬编码。
各 is_* 标记通过 ToolRegistry.mark_*() 收集为工具名集合，agent 循环
据此查询判断（如 registry.observation_tool_names()），不在 agent 代码里
硬编码任何具体工具名字符串（complete 除外，属于协议级概念）。
"""
from __future__ import annotations

import re as _re
import shlex as _shlex
import time as _time
from typing import Any, ClassVar

from fastaget.tools.context import ActionContext
from fastaget.tools.registry import ActionResult


def _load_feedback(name: str, fallback: str) -> str:
    from fastaget.meta.feedback import load_feedback
    return load_feedback(name, fallback)


_FB_STALE_INDEX_FALLBACK = "{error} | available indices: {avail}. Call observe to refresh the screen and reselect by index."
_FB_STALE_ELEMENT_FALLBACK = "Call observe to refresh the screen and reselect."

# Shared swipe geometry ratios (used by ScrollToFindAction + FillFieldsAction)
_SWIPE_FRAC_TOP: float = 0.75   # swipe start at 75% of screen height
_SWIPE_FRAC_BOTTOM: float = 0.25  # swipe end at 25% of screen height
# Shared label display truncation limit (used by ScrollToFindAction, TapElementAction, LongPressAction)
_LABEL_DISPLAY_LIMIT: int = 60


# ═══════════════════════════════════════════════════════════
# 感知类
# ═══════════════════════════════════════════════════════════

class ObserveAction:
    name: ClassVar[str] = "observe"
    description: ClassVar[str] = (
        "Refresh the screen by capturing current UI element list. Call when the element "
        "list is stale or a target element cannot be found. "
        "concise=true returns compact format (default), false returns verbose format "
        "(use when there are many elements on screen). "
        "max_elements caps the element count returned (default 200, increase for dense screens)."
    )
    params: ClassVar[dict] = {
        "concise": {"type": "boolean", "desc": "Compact mode (default true)"},
        "max_elements": {"type": "integer", "desc": "Max element count (default 200)"},
    }
    is_action: ClassVar[bool] = False
    is_observation: ClassVar[bool] = True

    # 与 phonefast._DEFAULT_MAX_ELEMENTS 对齐：80 会截掉密集列表视口尾部行
    _DEFAULT_MAX_ELEMENTS: ClassVar[int] = 200

    def __call__(self, *, ctx: ActionContext, concise: bool = True,
                 max_elements: int = _DEFAULT_MAX_ELEMENTS) -> ActionResult:
        raw = ctx.phonefast.observe(concise=concise, max_elements=max_elements)
        # max_elements 透传：LLM 要多少、daemon 出多少、processor 放行多少（防截留）
        state, screen_text = ctx._processor.process(
            raw.elements_text, max_elements=max_elements)
        ctx.ui = state
        ctx._last_screen_text = screen_text
        return ActionResult.ok(
            f"observed screen, {len(state.elements)} elements",
            count=len(state.elements), elements=screen_text,
        )


class CurrentAppAction:
    name: ClassVar[str] = "current_app"
    description: ClassVar[str] = "Query foreground Activity (device-level fact). Returns current foreground package and Activity."
    params: ClassVar[dict] = {}
    is_action: ClassVar[bool] = False

    def __call__(self, *, ctx: ActionContext) -> ActionResult:
        activity = ctx.phonefast.current_activity()
        pkg = ctx.phonefast.current_package()
        return ActionResult.ok(f"current: {activity}", activity=activity, package=pkg)


class CheckPackageAction:
    name: ClassVar[str] = "check_package"
    description: ClassVar[str] = (
        "Check if a package is installed on the device (device-level fact, not screen text). "
        "Use this to query device state when determining whether an app is installed — "
        "do not rely solely on what the screen shows."
    )
    params: ClassVar[dict] = {
        "package": {"type": "string", "desc": "Package name, e.g. com.android.settings", "required": True},
    }
    is_action: ClassVar[bool] = False

    def __call__(self, *, ctx: ActionContext, package: str) -> ActionResult:
        installed = ctx.phonefast.is_package_installed(package)
        return ActionResult.ok(f"package {package} installed={installed}", package=package, installed=installed)


class WaitAction:
    name: ClassVar[str] = "wait"
    description: ClassVar[str] = "Wait N seconds before continuing. Use when waiting for downloads, page loads, or animations to complete."
    params: ClassVar[dict] = {"seconds": {"type": "number", "desc": "Seconds to wait, default 1", "required": False}}
    is_action: ClassVar[bool] = False
    # 重试会导致重复等待（语义上不安全：多睡了几秒 != 幂等），L1 自愈层跳过重试
    is_retryable: ClassVar[bool] = False

    _DEFAULT_WAIT_SEC: ClassVar[float] = 1.0

    def __call__(self, *, ctx: ActionContext, seconds: float | int = _DEFAULT_WAIT_SEC) -> ActionResult:
        actual = float(seconds)
        _time.sleep(actual)
        return ActionResult.ok(f"waited {actual:.1f}s", seconds=actual)


class PollUntilAction:
    name: ClassVar[str] = "poll_until"
    description: ClassVar[str] = (
        "Poll until a condition is met (more efficient than wait; returns as soon as satisfied). "
        "Supports package_installed: periodically checks package manager until the package is "
        "installed or timeout is reached. Prefer this over wait for async operations (install/download)."
    )
    params: ClassVar[dict] = {
        "condition": {"type": "string", "desc": "Condition type, currently supports package_installed", "required": True},
        "package": {"type": "string", "desc": "Package name, e.g. com.android.settings (required when condition=package_installed)"},
        "timeout": {"type": "integer", "desc": "Max seconds to wait, default 120, cap 120"},
        "interval": {"type": "number", "desc": "Poll interval in seconds, default 1"},
    }
    is_action: ClassVar[bool] = False

    _MAX_TIMEOUT: ClassVar[int] = 120
    _DEFAULT_TIMEOUT: ClassVar[int] = 120
    _DEFAULT_POLL_INTERVAL_SEC: ClassVar[float] = 1.0
    _SUPPORTED: ClassVar[tuple] = ("package_installed",)

    def __call__(self, *, ctx: ActionContext, condition: str,
                 package: str = "", timeout: int = _DEFAULT_TIMEOUT,
                 interval: float = _DEFAULT_POLL_INTERVAL_SEC) -> ActionResult:
        deadline = _time.monotonic() + min(timeout, self._MAX_TIMEOUT)
        if condition in self._SUPPORTED:
            if not package:
                return ActionResult.fail("poll_until package_installed needs package param")
            while _time.monotonic() < deadline:
                if ctx.phonefast.is_package_installed(package):
                    return ActionResult.ok(
                        f"package {package} installed",
                        condition=condition, package=package, installed=True,
                    )
                _time.sleep(interval)
            installed = ctx.phonefast.is_package_installed(package)
            return ActionResult.ok(
                f"timeout after {timeout}s, package {package} installed={installed}",
                condition=condition, package=package, installed=installed, timeout=True,
            )
        return ActionResult.fail(
            f"unsupported condition '{condition}', supported: {list(self._SUPPORTED)}"
        )


class ScrollToFindAction:
    name: ClassVar[str] = "scroll_to_find"
    description: ClassVar[str] = (
        "Scroll the current page while searching for target text (exploratory navigation). "
        "Observes after each swipe; stops at first match, returning the latest element list. "
        "Use this when the target element is not on the current screen — do not keep "
        "retrying a fixed index. "
        "* Substring match — may hit non-interactive text (comments/descriptions). After finding, "
        "check whether flags contain 'clickable' before tapping; do not tap plain text labels."
    )
    params: ClassVar[dict] = {
        "text": {"type": "string", "desc": "Target text to find (partial match supported), e.g. 'Battery', 'Bluetooth'", "required": True},
        "direction": {"type": "string", "desc": "Scroll direction: up or down, default down"},
        "max_swipes": {"type": "integer", "desc": "Max swipe count, default 5"},
    }
    is_action: ClassVar[bool] = False

    # 滑动参数
    _SWIPE_DURATION_MS: ClassVar[int] = 300
    _SWIPE_INTERVAL_SEC: ClassVar[float] = 0.3
    _CANDIDATE_LIMIT: ClassVar[int] = 15          # max candidate labels in not-found summary
    _DEFAULT_MAX_SWIPES: ClassVar[int] = 5        # default max swipe count
    _DEFAULT_DEVICE_WIDTH: ClassVar[int] = 1080   # fallback device width (consistent with other actions)
    _DEFAULT_DEVICE_HEIGHT: ClassVar[int] = 2400  # fallback device height

    def __call__(self, *, ctx: ActionContext, text: str,
                 direction: str = "down", max_swipes: int = _DEFAULT_MAX_SWIPES) -> ActionResult:
        status = ctx.phonefast.status()
        w, h = status.get("device_width", self._DEFAULT_DEVICE_WIDTH), status.get("device_height", self._DEFAULT_DEVICE_HEIGHT)
        y_top = int(h * _SWIPE_FRAC_TOP)
        y_bot = int(h * _SWIPE_FRAC_BOTTOM)
        y1, y2 = (y_top, y_bot) if direction == "down" else (y_bot, y_top)

        for attempt in range(1, max_swipes + 1):
            state = ctx.require_ui() if (attempt == 1 and ctx.ui is not None) else ctx.observe()

            found = [el for el in state.elements if text in (el.text or "") or text in (el.desc or "")]
            if found:
                el = found[0]
                label = el.label() or "(no label)"
                return ActionResult.ok(
                    f"found '{text}' at element[{el.index}] label='{label[:_LABEL_DISPLAY_LIMIT]}' after {attempt-1} swipes",
                    text=text, index=el.index, swipes=attempt - 1,
                    elements=ctx.observe_text(), count=len(state.elements),
                )

            if attempt < max_swipes:
                ctx.phonefast.swipe(w // 2, y1, w // 2, y2, self._SWIPE_DURATION_MS)
                _time.sleep(self._SWIPE_INTERVAL_SEC)

        # 耗尽所有滑动——把最后屏幕的元素列表回传给 LLM 自主判断
        state = ctx.observe()
        screen_text = ctx.observe_text()
        candidates = [f"[{el.index}] {el.label()}" for el in state.elements[:self._CANDIDATE_LIMIT]]
        candidates_str = ", ".join(candidates) if candidates else "(none)"
        return ActionResult.ok(
            f"'{text}' not found after {max_swipes} swipes. "
            f"Screen has {len(state.elements)} elements: {candidates_str}",
            text=text, found=False, swipes=max_swipes,
            elements=screen_text, count=len(state.elements),
        )


class WaitAndObserveAction:
    name: ClassVar[str] = "wait_and_observe"
    description: ClassVar[str] = (
        "Wait N seconds then auto-observe screen (recommended; one-turn wait+observe). "
        "Use this instead of separate wait + observe calls when unsure of an action's outcome."
    )
    params: ClassVar[dict] = {"seconds": {"type": "number", "desc": "Seconds to wait", "required": False}}
    is_action: ClassVar[bool] = False

    _DEFAULT_WAIT_SEC: ClassVar[float] = 2.0

    def __call__(self, *, ctx: ActionContext, seconds: float | int = _DEFAULT_WAIT_SEC) -> ActionResult:
        actual = float(seconds)
        _time.sleep(actual)
        state = ctx.observe()
        return ActionResult.ok(
            f"waited {actual:.1f}s, observed {len(state.elements)} elements",
            seconds=actual, count=len(state.elements), elements=ctx.observe_text(),
        )


class AssertAction:
    name: ClassVar[str] = "assert"
    description: ClassVar[str] = "Assert: describe an expected condition and report whether it passed. Use to verify test expectations."
    params: ClassVar[dict] = {
        "description": {"type": "string", "desc": "Assertion description", "required": True},
        "passed": {"type": "boolean", "desc": "Whether the assertion passed", "required": True},
    }
    is_action: ClassVar[bool] = False
    is_assert: ClassVar[bool] = True

    def __call__(self, *, ctx: ActionContext, description: str, passed: bool) -> ActionResult:
        return ActionResult(success=passed, summary=f"assert: {description}",
                          data={"description": description, "passed": passed})


class CompleteAction:
    name: ClassVar[str] = "complete"
    description: ClassVar[str] = (
        "Finish the test case. Must only be called after assert has verified the outcome; "
        "do not call complete without verification. Set success=true when the goal is achieved. "
        "evidence: key observed facts supporting the judgment (e.g. 'page title=Settings'), used for failure attribution audit."
    )
    params: ClassVar[dict] = {
        "result": {"type": "string", "desc": "Test case result summary", "required": True},
        "success": {"type": "boolean", "desc": "Goal achieved? Default true", "required": False},
        "evidence": {"type": "string", "desc": "Supporting evidence: key observed facts (optional, for attribution audit)", "required": False},
    }
    is_action: ClassVar[bool] = False

    def __call__(self, *, ctx: ActionContext, result: str, success: bool = True,
                 evidence: str = "") -> ActionResult:
        # 效果即数据：通过 data 声明终结，agent 主循环统一解释，零 ctx 副作用
        # evidence 并入 result——随 CompleteVerify 进入 state.summary，报告层可见
        full = f"{result} | evidence: {evidence}" if evidence else result
        return ActionResult.complete(result=full, success=success)


# ═══════════════════════════════════════════════════════════
# 操作类（改变设备状态）
# ═══════════════════════════════════════════════════════════

class TapAction:
    name: ClassVar[str] = "tap"
    description: ClassVar[str] = "Tap the screen at coordinates (x,y). Use when the target element is not in the a11y tree (custom View/RecyclerView items) — compute Y from container bounds obtained via observe."
    params: ClassVar[dict] = {
        "x": {"type": "integer", "desc": "X coordinate", "required": True},
        "y": {"type": "integer", "desc": "Y coordinate", "required": True},
    }
    is_action: ClassVar[bool] = True

    def __call__(self, *, ctx: ActionContext, x: int, y: int) -> ActionResult:
        ctx.phonefast.tap(x, y)
        return ActionResult.ok(f"tapped ({x},{y})", x=x, y=y)


class TapElementAction:
    name: ClassVar[str] = "tap_element"
    description: ClassVar[str] = (
        "Tap an element by index (precise, recommended) or text (stable but may have duplicates). "
        "After tapping, check the returned label to confirm you hit the right target; "
        "if not, retry with different parameters."
    )
    params: ClassVar[dict] = {
        "index": {"type": "integer", "desc": "Element index from observe output (precise, recommended)"},
        "text": {"type": "string", "desc": "Element text (exact match; refuses if multiple elements match)"},
    }
    is_action: ClassVar[bool] = True

    # Config constants (hardcode zero tolerance)
    _MAX_RETRIES: ClassVar[int] = 3           # max attempts including initial one
    _COORD_BOUND_FALLBACK: ClassVar[tuple[int, int]] = (3000, 3000)
    _COORD_BOUND_SAFETY_FACTOR: ClassVar[float] = 1.5
    _CANDIDATE_LIMIT: ClassVar[int] = 15      # max candidate labels in not-found error
    _MAX_DUP_DISPLAY: ClassVar[int] = 5       # max duplicate-element entries to show in refusal message
    _DEFAULT_DEVICE_WIDTH: ClassVar[int] = 1080   # fallback device width when status() lacks it
    _DEFAULT_DEVICE_HEIGHT: ClassVar[int] = 2400  # fallback device height

    def __call__(self, *, ctx: ActionContext, index: int | None = None, text: str | None = None) -> ActionResult:
        if index is None and text is None:
            return ActionResult.fail("tap_element needs index or text")

        for attempt in range(1, self._MAX_RETRIES + 1):
            ui = ctx.require_ui()

            if index is not None:
                try:
                    x, y = ui.get_coords(index)
                except ValueError as e:
                    if attempt < self._MAX_RETRIES:
                        ctx.observe()
                        continue
                    fb = _load_feedback("stale_index", _FB_STALE_INDEX_FALLBACK)
                    return ActionResult.fail(fb.format(error=str(e), avail=""))

                # Out-of-bounds safety net — use device screen size, not hardcoded dimensions
                try:
                    status = ctx.phonefast.status()
                    max_x = status.get("device_width", self._DEFAULT_DEVICE_WIDTH) * self._COORD_BOUND_SAFETY_FACTOR
                    max_y = status.get("device_height", self._DEFAULT_DEVICE_HEIGHT) * self._COORD_BOUND_SAFETY_FACTOR
                except Exception:
                    max_x, max_y = self._COORD_BOUND_FALLBACK
                if y < 0 or x < 0 or y > max_y or x > max_x:
                    label = next((el.label() for el in ui.elements if el.index == index), "(no label)") or "(no label)"
                    return ActionResult.fail(
                        f"element[{index}] label='{label[:_LABEL_DISPLAY_LIMIT]}' coordinate ({x},{y}) out of bounds, cannot tap", index=index)

                ctx.phonefast.tap(x, y)
                label = next((el.label() for el in ui.elements if el.index == index), "(no label)") or "(no label)"
                tag = f" [retry {attempt}]" if attempt > 1 else ""
                return ActionResult.ok(
                    f"tapped element[{index}] label='{label[:_LABEL_DISPLAY_LIMIT]}' at ({x},{y}){tag}", index=index)

            # text matching
            el = ui.find_by_text(text)
            if el is None:
                if attempt < self._MAX_RETRIES:
                    ctx.observe()
                    continue
                labels = [e.label() for e in ui.elements if (e.text or e.desc)][:self._CANDIDATE_LIMIT]
                fb = _load_feedback("stale_index", _FB_STALE_ELEMENT_FALLBACK)
                return ActionResult.fail(f"element text='{text}' not found | visible labels: {labels}. {fb}")

            dups = ui.find_all_by_text(text)
            if len(dups) > 1:
                dup_info = ", ".join(f"[{e.index}]@{e.bounds}" for e in dups[:self._MAX_DUP_DISPLAY])
                return ActionResult.fail(
                    f"refusing to tap: {len(dups)} elements match text='{text}' ({dup_info}). "
                    f"Re-tap with index=<index of the intended element> instead.",
                    text=text,
                )

            x, y = el.center()
            ctx.phonefast.tap(x, y)
            tag = f" [retry {attempt}]" if attempt > 1 else ""
            return ActionResult.ok(
                f"tapped element by text='{text}' at ({x},{y}){tag}", text=text)


class LongPressAction:
    """长按元素（按 index）：触发上下文菜单、复制/粘贴、卸载等。"""

    name: ClassVar[str] = "long_press"
    description: ClassVar[str] = (
        "Long-press (press and hold) an element by index. Triggers context menus "
        "(copy/paste/uninstall/share etc.). duration_ms defaults to 1000ms (1 second)."
    )
    params: ClassVar[dict] = {
        "index": {"type": "integer", "desc": "Element index (from observe output)", "required": True},
        "duration_ms": {"type": "integer", "desc": "Press duration in ms, default 1000"},
    }
    is_action: ClassVar[bool] = True

    _LONGPRESS_RETRY_COUNT: ClassVar[int] = 3  # max attempts including initial one
    _DEFAULT_DURATION_MS: ClassVar[int] = 1000

    def __call__(self, *, ctx: ActionContext, index: int, duration_ms: int = _DEFAULT_DURATION_MS) -> ActionResult:
        # 硬校验纯数字：registry 强转失败会静默透传原值，此处兜底防 shell 注入
        duration_ms = int(duration_ms)
        for attempt in range(1, self._LONGPRESS_RETRY_COUNT + 1):
            ui = ctx.require_ui()
            try:
                x, y = ui.get_coords(index)
            except ValueError as e:
                if attempt < self._LONGPRESS_RETRY_COUNT:
                    ctx.observe()
                    continue
                fb = _load_feedback("stale_index", _FB_STALE_INDEX_FALLBACK)
                return ActionResult.fail(fb.format(error=str(e), avail=""))
            # 长按：swipe 起点=终点 + 长 duration
            ctx.phonefast.shell(f"input swipe {x} {y} {x} {y} {duration_ms}")
            label = next((el.label() for el in ui.elements if el.index == index), "(no label)") or "(no label)"
            tag = f" [retry {attempt}]" if attempt > 1 else ""
            return ActionResult.ok(
                f"long-pressed element[{index}] label='{label[:_LABEL_DISPLAY_LIMIT]}' ({duration_ms}ms){tag}",
                index=index, x=x, y=y,
            )


class LongPressAtAction:
    """长按坐标 (x,y)：用于自定义 View 条目不在 a11y 树时触发上下文菜单。"""

    name: ClassVar[str] = "long_press_at"
    description: ClassVar[str] = (
        "Long-press at coordinates (x,y). Use for RecyclerView/custom View items not in "
        "the a11y tree to trigger context menus (delete/move/share etc.). Compute Y from "
        "container bounds obtained via observe. duration_ms defaults to 1000ms."
    )
    params: ClassVar[dict] = {
        "x": {"type": "integer", "desc": "X coordinate", "required": True},
        "y": {"type": "integer", "desc": "Y coordinate", "required": True},
        "duration_ms": {"type": "integer", "desc": "Long-press duration in ms, default 1000"},
    }
    is_action: ClassVar[bool] = True

    _DEFAULT_DURATION_MS: ClassVar[int] = 1000

    def __call__(self, *, ctx: ActionContext, x: int, y: int, duration_ms: int = _DEFAULT_DURATION_MS) -> ActionResult:
        # x/y/duration_ms 全部来自 LLM 参数。registry 强转失败会静默透传原值
        # （registry.py 强转 except pass），非数字会进 shell 字符串被 adb 按分号
        # 拆成多条命令执行。此处硬校验纯数字，非法输入抛 ValueError → ActionResult.fail。
        x, y, duration_ms = int(x), int(y), int(duration_ms)
        ctx.phonefast.shell(f"input swipe {x} {y} {x} {y} {duration_ms}")
        return ActionResult.ok(
            f"long-pressed at ({x},{y}) ({duration_ms}ms)",
            x=x, y=y,
        )


class SwipeAction:
    name: ClassVar[str] = "swipe"
    description: ClassVar[str] = "Swipe from (x1,y1) to (x2,y2)."
    params: ClassVar[dict] = {
        "x1": {"type": "integer", "required": True}, "y1": {"type": "integer", "required": True},
        "x2": {"type": "integer", "required": True}, "y2": {"type": "integer", "required": True},
        "duration_ms": {"type": "integer", "desc": "Swipe duration in ms, default 300"},
    }
    is_action: ClassVar[bool] = True

    _SWIPE_DURATION_MS: ClassVar[int] = 300

    def __call__(self, *, ctx: ActionContext, x1: int, y1: int, x2: int, y2: int,
                 duration_ms: int = _SWIPE_DURATION_MS) -> ActionResult:
        ctx.phonefast.swipe(x1, y1, x2, y2, duration_ms)
        return ActionResult.ok(f"swiped ({x1},{y1})->({x2},{y2})")


class TypeAction:
    name: ClassVar[str] = "type"
    description: ClassVar[str] = (
        "Type text into the currently focused input field. ASCII only (letters/digits/pinyin); "
        "Chinese characters are not supported. For Chinese app search, use pinyin "
        "(e.g. xiaohongshu for Xiaohongshu). Tap the input field with tap_element first to focus it."
    )
    params: ClassVar[dict] = {"text": {"type": "string", "required": True}}
    is_action: ClassVar[bool] = True

    def __call__(self, *, ctx: ActionContext, text: str) -> ActionResult:
        ctx.phonefast.type_text(text)
        return ActionResult.ok(f"typed {len(text)} chars", length=len(text))


class FillFieldsAction:
    """批量填表单——一步完成多字段「定位→聚焦→输入」。

    把 N 个 (tap_element+type) 工具调用压缩为 1 步，避免表单填充时的逐字段
    循环。通用工具，适配任意多字段表单，非场景特判。

    两种字段布局均支持（按 label 定位输入框的通用模式，不限特定 app）：
      - 模式 1（自标签输入框）：空字段 text=hint 标签，直接按 label 子串匹配
        EditText 本身（常见于 Material TextInputLayout 包裹的输入框）。
      - 模式 2（独立 label 文本）：字段名是独立 Text 元素，先定位 label，再取
        其下方或同行的可输入元素（覆盖 label 在上 / label 在左两种布局）。
    """
    name: ClassVar[str] = "fill_fields"
    description: ClassVar[str] = (
        "Batch-fill multiple form fields in ONE step. For each field: observe -> "
        "locate by label -> tap to focus -> type value. Use for forms with 2+ fields "
        "(recipe/contact/expense add). Replaces repeated tap_element+type pairs and "
        "avoids run_script form-fill loops. Labels matched case-insensitively against "
        "element text/desc/id (empty-field hint). Fields filled top-to-bottom; "
        "auto-scrolls to off-screen fields."
    )
    params: ClassVar[dict] = {
        "fields": {
            "type": "array", "required": True,
            "desc": ("List of {label, value} pairs, e.g. "
                     "[{label:'Title',value:'Cake'},{label:'Servings',value:'8'}]. "
                     "Order = fill order (top-to-bottom recommended)."),
        },
    }
    is_action: ClassVar[bool] = True
    # 多步聚合工具，外层 L1 不重试（部分字段已填，重放会重复输入）
    is_retryable: ClassVar[bool] = False

    # 配置化时序常量（宪法：硬编码零容忍）
    _FOCUS_WAIT_SEC: ClassVar[float] = 0.3   # tap 后等输入框聚焦
    _SCROLL_WAIT_SEC: ClassVar[float] = 0.3  # swipe 后等渲染
    _SWIPE_DURATION_MS: ClassVar[int] = 300
    _SUMMARY_VAL_LIMIT: ClassVar[int] = 30   # 摘要里 value 截断长度
    # 字段不在首屏时，最多滚动多少次寻找（与 scroll_to_find 同模式）
    _MAX_FIELD_SCROLLS: ClassVar[int] = 3
    # label↔input 关联的 y 区间重叠阈值（同行判定）：重叠 >= 该比例算同行
    _SAMEROW_OVERLAP_RATIO: ClassVar[float] = 0.5
    # _is_input widget-class detection heuristic (extensible, no inline magic strings)
    _INPUT_CLASS_INCLUDES: ClassVar[tuple[str, ...]] = ("edittext", "autocompletetextview", "searchview", "autocomplete")
    _INPUT_CLASS_CONTAINS: ClassVar[tuple[str, ...]] = ("input",)
    _INPUT_CLASS_EXCLUDES: ClassVar[tuple[str, ...]] = ("button", "switch", "checkbox", "radio", "inputlayout")
    _DEFAULT_DEVICE_WIDTH: ClassVar[int] = 1080   # fallback device width when status() lacks it
    _DEFAULT_DEVICE_HEIGHT: ClassVar[int] = 2400  # fallback device height

    def __call__(self, *, ctx: ActionContext, fields: list) -> ActionResult:
        if not fields:
            return ActionResult.fail("fill_fields needs a non-empty 'fields' list")
        results: list[str] = []
        filled = 0
        for f in fields:
            label = str(f.get("label", "")).strip()
            value = str(f.get("value", ""))
            if not label:
                results.append("SKIP (no label)")
                continue
            # 1. 定位字段：当前屏找；找不到则滚动寻找（最多 _MAX_FIELD_SCROLLS 次，
            #    处理屏幕外字段——长表单可能需多次滚动）
            el = self._find_field(ctx, label)
            scrolls = 0
            while el is None and scrolls < self._MAX_FIELD_SCROLLS:
                self._scroll_down(ctx)
                scrolls += 1
                el = self._find_field(ctx, label)
            if el is None:
                # 未找到：回滚滚动距离，恢复视口，避免后续字段因视口偏移而漏判
                for _ in range(scrolls):
                    self._scroll_up(ctx)
                results.append(f"FAIL '{label}': not found")
                continue
            # 2. 字段已有值（text 非空且 != label hint）→ 跳过，不重复输入
            cur = (el.text or "").strip()
            if cur and cur.lower() != label.lower():
                results.append(f"SKIP '{label}' (already has value)")
                continue
            # 3. tap 聚焦 + type 输入（坐标 tap 对非 clickable 输入框同样有效）
            cx, cy = el.center()
            ctx.phonefast.tap(x=cx, y=cy)
            _time.sleep(self._FOCUS_WAIT_SEC)
            ctx.phonefast.type_text(value)
            results.append(f"OK '{label}'='{value[:self._SUMMARY_VAL_LIMIT]}'")
            filled += 1
        summary = f"filled {filled}/{len(fields)} fields: " + "; ".join(results)
        # 返回最终屏幕（供 executor 同步指纹 + LLM 看填充结果）
        ui = ctx.observe()
        return ActionResult.ok(
            summary, filled=filled, total=len(fields),
            elements=ctx.observe_text(), count=len(ui.elements),
        )

    # ── 字段定位 ──────────────────────────────────────────────────

    def _find_field(self, ctx: ActionContext, label: str):
        """按 label 定位输入框。两种布局模式都支持，返回最靠上的命中。

        模式 1：输入框自身标签 == hint → 直接匹配输入框。
        模式 2：label 是独立文本元素 → 取其下方或同行的可输入元素（覆盖
                label 在上 / label 在左两种布局）。
        """
        ui = ctx.observe()
        target = label.lower()

        def _is_input(el):
            cls_l = (el.cls or "").lower()
            if any(b in cls_l for b in self._INPUT_CLASS_EXCLUDES):
                return False
            if any(inc in cls_l for inc in self._INPUT_CLASS_INCLUDES):
                return True
            return any(c in cls_l for c in self._INPUT_CLASS_CONTAINS)

        def _matches(el):
            combined = ((el.text or "") + " " + (el.desc or "") + " " + (el.id or "")).lower()
            return target in combined

        def _same_row(a, b) -> bool:
            """两元素 y 区间重叠 >= 阈值算同行（label 在左、input 在右布局）。"""
            ay1, ay2 = a.bounds[1], a.bounds[3]
            by1, by2 = b.bounds[1], b.bounds[3]
            overlap = max(0, min(ay2, by2) - max(ay1, by1))
            taller = max(1, min(ay2 - ay1, by2 - by1))
            return overlap / taller >= self._SAMEROW_OVERLAP_RATIO

        def _dist_from_label(lab, el) -> tuple[int, int]:
            """到 label 的距离：(垂直距离, 水平距离)。下方优先，同行其次。"""
            _, ly1, _, _ = lab.bounds
            _, ey1, _, _ = el.bounds
            vdist = max(0, ey1 - ly1)  # 下方为正，上方（不应出现）为 0
            hdist = abs(el.center()[0] - lab.center()[0])
            return (vdist, hdist)

        # 模式 1：输入框自身标签 == hint → 直接匹配输入框
        cands = [el for el in ui.elements if _is_input(el) and _matches(el)]
        if cands:
            return min(cands, key=lambda e: e.bounds[1])  # 最靠上

        # 模式 2：label 是独立文本元素 → 取其下方或同行的可输入元素（取最近）
        label_els = [el for el in ui.elements if _matches(el) and not _is_input(el)]
        best = None
        best_key = None
        for lab in label_els:
            for el in ui.elements:
                if not _is_input(el) or el is lab:
                    continue
                # 下方（el.y1 >= lab.y1）或同行（y 重叠足够）
                if el.bounds[1] >= lab.bounds[1] or _same_row(lab, el):
                    key = _dist_from_label(lab, el)
                    if best_key is None or key < best_key:
                        best, best_key = el, key
        return best

    # ── 向下滚动（复用 scroll_to_find 的 swipe 参数）──────────────

    def _scroll_down(self, ctx: ActionContext) -> None:
        status = ctx.phonefast.status()
        w = status.get("device_width", self._DEFAULT_DEVICE_WIDTH)
        h = status.get("device_height", self._DEFAULT_DEVICE_HEIGHT)
        y_top = int(h * _SWIPE_FRAC_TOP)
        y_bot = int(h * _SWIPE_FRAC_BOTTOM)
        ctx.phonefast.swipe(w // 2, y_top, w // 2, y_bot, self._SWIPE_DURATION_MS)
        _time.sleep(self._SCROLL_WAIT_SEC)

    def _scroll_up(self, ctx: ActionContext) -> None:
        """Reverse of _scroll_down: swipes downward on screen (content scrolls up)."""
        status = ctx.phonefast.status()
        w = status.get("device_width", self._DEFAULT_DEVICE_WIDTH)
        h = status.get("device_height", self._DEFAULT_DEVICE_HEIGHT)
        y_top = int(h * _SWIPE_FRAC_TOP)
        y_bot = int(h * _SWIPE_FRAC_BOTTOM)
        ctx.phonefast.swipe(w // 2, y_bot, w // 2, y_top, self._SWIPE_DURATION_MS)
        _time.sleep(self._SCROLL_WAIT_SEC)


class KeyAction:
    name: ClassVar[str] = "key"
    description: ClassVar[str] = (
        "Press a hardware/system key (e.g. enter to trigger search, back to go back, search, "
        "home, power). After enter, waits 1.5s for search results to load, then auto-observes "
        "and returns the updated screen. Always press enter after typing a search query — "
        "without enter only search suggestions are shown, not actual results. "
        "Text-editing aliases: clear (empties the focused text field), copy/cut/paste "
        "(clipboard operations, need an active selection), del (backspace)."
    )
    params: ClassVar[dict] = {
        "name": {"type": "string", "desc": "Key name or keycode, e.g. enter/66/back/search", "required": True}
    }
    is_action: ClassVar[bool] = True

    # enter 后等待秒数（搜索/加载等异步操作需要时间）
    _ENTER_DELAY_SEC: ClassVar[float] = 1.5
    # 触发异步操作后等待+自动 observe 的按键名/keycode
    _ENTER_KEYS: ClassVar[frozenset[str]] = frozenset({"enter", "66"})

    # 名称别名 → Android keycode。daemon 只认少量名称，但透传数字 keycode；
    # 文本编辑原语（clear/copy/paste）让 agent 不再依赖 OCR 盲点或不可靠的
    # select-all 长按菜单（Clipboard/AudioRecorder 改名等场景）。
    _KEY_ALIASES: ClassVar[dict[str, str]] = {
        "clear": "28",   # KEYCODE_CLEAR：清空聚焦的文本字段
        "copy": "278",   # KEYCODE_COPY：复制当前选区（需先有选区）
        "cut": "277",    # KEYCODE_CUT
        "paste": "279",  # KEYCODE_PASTE
        "del": "67",     # KEYCODE_DEL：退格
    }

    def __call__(self, *, ctx: ActionContext, name: str) -> ActionResult:
        resolved = self._KEY_ALIASES.get((name or "").strip().lower(), name)
        ctx.phonefast.key(resolved)
        if resolved in self._ENTER_KEYS:
            _time.sleep(self._ENTER_DELAY_SEC)
            state = ctx.observe()
            return ActionResult.ok(
                f"pressed key {resolved}, observed {len(state.elements)} elements",
                name=resolved, elements=ctx.observe_text(), count=len(state.elements),
            )
        return ActionResult.ok(f"pressed key {resolved}", name=resolved)


class LaunchAction:
    name: ClassVar[str] = "launch"
    description: ClassVar[str] = (
        "Launch an app. Prefer 'app' (common display name, e.g. clock/settings/calendar); "
        "use 'package' as fallback (Android package name)."
    )
    params: ClassVar[dict] = {
        "app": {"type": "string", "required": False,
                "desc": "App display name, e.g. clock, settings, calendar"},
        "package": {"type": "string", "required": False,
                    "desc": "Android package name, e.g. com.android.settings"},
    }
    is_action: ClassVar[bool] = True
    # Package-name filtering: prefer non-vendor packages when resolving app name
    _VENDOR_WORDS: ClassVar[frozenset[str]] = frozenset({
        "transsion", "miui", "vivo", "oppo", "vendor"})
    _LAUNCH_SETTLE_SEC: ClassVar[float] = 1.0   # wait after launch before checking foreground
    _DUMPSYS_TIMEOUT: ClassVar[float] = 10.0     # dumpsys package timeout
    _LABEL_LOOKBACK_LINES: ClassVar[int] = 7     # Package [xxx] appears within 6 lines before the label line

    # 不预置包名映射——一律通过 shell(pm list packages | grep) 搜索设备实际安装的应用

    def __call__(self, *, ctx: ActionContext, package: str = "", app: str = "") -> ActionResult:
        if not package and not app:
            return ActionResult.fail("launch needs 'app' or 'package' param")
        resolved_from_app = False
        if not package:
            package = self._resolve_app(app, ctx)
            if not package:
                return ActionResult.fail(
                    f"cannot resolve '{app}' to a package — "
                    f"try shell(pm list packages | grep {app}) to find it"
                )
            resolved_from_app = True
        ctx.phonefast.launch(package)
        _time.sleep(self._LAUNCH_SETTLE_SEC)
        # Confirm foreground app
        try:
            activity = ctx.phonefast.current_activity()
            current_pkg = ctx.phonefast.current_package()
        except Exception:
            activity = ""; current_pkg = ""
        verified = (current_pkg == package) or (package in (activity or ""))
        note = "" if verified else " (foreground unconfirmed)"
        # ── PI 风格 auto-memory：解析成功自动记入跨步记忆，后续 run 免重复搜索 ──
        # remember/mark_visited 标记 dirty，由 _build_result 统一持久化——无需显式 save
        if verified and hasattr(ctx.memory, 'mark_visited'):
            try:
                ctx.memory.mark_visited(package)
            except Exception:
                pass
        if resolved_from_app and verified:
            try:
                mem_key = f"app_{app.replace(' ', '_')}"
                ctx.memory[mem_key] = package
            except Exception:
                pass
        return ActionResult.ok(
            f"launched {package}{note}" + (f" (resolved from '{app}')" if app else ""),
            package=package, current_app=current_pkg or activity, verified=verified,
        )

    def _resolve_app(self, app: str, ctx: ActionContext) -> str:
        """解析 app 名 → 包名：多策略回退——先 grep 包名（快），再搜显示标签（兜底）。"""
        # ── 策略 1：grep 包名（fast path，保持原逻辑）──
        # 多词 app 名（"Arduia Expense"）拆 token 做 OR 匹配——包名用点不用空格，
        # 整串 -F 匹配必败。歧义结果优选段数最少（最规范）的包名。
        try:
            tokens = [_re.escape(t) for t in _re.split(r"\s+", app.strip()) if t]
            if not tokens:
                tokens = [_re.escape(app)]
            pattern = "|".join(tokens)
            result = ctx.phonefast.shell(
                f"pm list packages | grep -iE {_shlex.quote(pattern)}")
            if result:
                lines = [l.strip() for l in result.split("\n") if l.startswith("package:")]
                if lines:
                    # 优先选非厂商包；同非厂商多个时选点段最少（最规范）的
                    cands = [l.replace("package:", "").strip() for l in lines]
                    non_vendor = [p for p in cands
                                  if not any(v in p for v in self._VENDOR_WORDS)]
                    pool = non_vendor or cands
                    return min(pool, key=lambda p: p.count("."))
        except Exception:
            pass

        # ── 策略 2：dumpsys package 搜 Application Label（Python 侧匹配，消除 shell 注入）──
        try:
            # 将 app 名拆分为 token 构建模糊正则：Google Play → application label.*google.*play
            tokens = [_re.escape(t) for t in app.split() if t.strip()]
            if not tokens:
                tokens = [_re.escape(app)]
            label_re = _re.compile(
                r'application\s+label\s*:.*' + '.*'.join(tokens),
                _re.IGNORECASE,
            )
            raw = ctx.phonefast.shell("dumpsys package", timeout=self._DUMPSYS_TIMEOUT)
            if raw:
                all_lines = raw.split("\n")
                for i, line in enumerate(all_lines):
                    if label_re.search(line):
                        # Package [xxx] 行出现在 label 行之前 6 行内——从近到远扫描，
                        # 避免错取前一个包（e.g. WeChat label 匹配到 android.vending）
                        for j in range(i - 1, max(-1, i - self._LABEL_LOOKBACK_LINES), -1):
                            m = _re.search(r'Package \[([^\]]+)\]', all_lines[j])
                            if m:
                                pkg = m.group(1).strip()
                                if not any(v in pkg for v in self._VENDOR_WORDS):
                                    return pkg
                                break  # matched vendor package → keep scanning
        except Exception:
            pass

        return ""


class NavigateToAction:
    """在已打开的应用内切换 Tab（底部导航栏）或导航到指定文本页面。"""

    name: ClassVar[str] = "navigate_to"
    description: ClassVar[str] = (
        "Navigate to a specific page within the current app. Supports 'tab' param "
        "(bottom/top navigation bar text, e.g. timer/stopwatch/alarm/photo/video) "
        "and 'target' param (any visible text element match). "
        "Auto-observes before tapping to confirm target element is on screen."
    )
    params: ClassVar[dict] = {
        "tab": {"type": "string", "required": False,
                "desc": "Text of a bottom/top navigation tab, e.g. timer/stopwatch/all recipes/contacts"},
        "target": {"type": "string", "required": False,
                   "desc": "Any text visible on screen; taps the first element matching it"},
    }
    is_action: ClassVar[bool] = True
    _TAB_REGION_RATIO: ClassVar[float] = 0.65  # bottom tab region starts at this fraction of screen height
    _NAV_SETTLE_SEC: ClassVar[float] = 0.8     # wait after navigation tap before confirming
    _VISIBLE_TEXTS_LIMIT: ClassVar[int] = 30   # max visible text labels in error message
    _DEFAULT_DEVICE_HEIGHT: ClassVar[int] = 2400  # fallback device height

    def __call__(self, *, ctx: ActionContext, tab: str = "", target: str = "") -> ActionResult:
        search_text = (tab or target).strip()
        if not search_text:
            return ActionResult.fail("navigate_to needs 'tab' or 'target' param")

        ui = ctx.observe()
        search_lower = search_text.lower()

        # 获取设备尺寸用于底部 tab 区域计算
        status = ctx.phonefast.status()
        h = status.get("device_height", self._DEFAULT_DEVICE_HEIGHT)

        # 找匹配文本的可交互元素（优先底部 tab 区域）
        best_index = -1
        best_y = -1
        for el in ui.elements:
            if not el.clickable:
                continue
            text_match = search_lower in (el.text or "").lower() or search_lower in (el.desc or "").lower()
            if not text_match:
                continue
            y = el.bounds[1]
            min_tab_y = int(h * self._TAB_REGION_RATIO)
            if y > min_tab_y and y > best_y:
                best_index = el.index; best_y = y
            elif best_index < 0:
                best_index = el.index; best_y = y

        if best_index < 0:
            visible = [el.text for el in ui.elements if el.text][:self._VISIBLE_TEXTS_LIMIT]
            return ActionResult.fail(
                f"navigate_to: '{search_text}' not found on screen. "
                f"Try scrolling or using back to go up a level.",
                available_texts=", ".join(visible),
            )

        cx, cy = ui.get_coords(best_index)
        ctx.phonefast.tap(x=cx, y=cy)

        _time.sleep(self._NAV_SETTLE_SEC)
        return ActionResult.ok(
            f"navigated to '{search_text}'", target=search_text, index=best_index,
        )



class TapByTextAction:
    """在屏幕上搜索文本并点击——一步完成 observe+搜索+tap。"""

    name: ClassVar[str] = "tap_by_text"
    description: ClassVar[str] = (
        "Search the screen for text and tap the first matching element. "
        "Auto observe→search→tap in one step. Must pass 'text' param (partial match supported)."
    )
    params: ClassVar[dict] = {
        "text": {"type": "string", "required": True,
                 "desc": "Text to tap (e.g. Save/Done/Allow/Create), partial match supported"},
    }
    is_action: ClassVar[bool] = True
    _VISIBLE_TEXTS_LIMIT: ClassVar[int] = 30   # max visible text labels in error message

    def __call__(self, *, ctx: ActionContext, text: str) -> ActionResult:
        if not text.strip():
            return ActionResult.fail("tap_by_text needs 'text' param")
        ui = ctx.observe()
        target = text.strip().lower()
        for el in ui.elements:
            if not el.clickable:
                continue
            combined = ((el.text or "") + " " + (el.desc or "")).lower()
            if target in combined:
                cx, cy = el.center()
                ctx.phonefast.tap(x=cx, y=cy)
                return ActionResult.ok(f"tapped '{text}' (index={el.index})", text=text, index=el.index)
        visible = [el.text for el in ui.elements if el.text][:self._VISIBLE_TEXTS_LIMIT]
        return ActionResult.fail(
            f"tap_by_text: '{text}' not found on screen",
            available_texts=", ".join(visible),
        )




class CurrentStateAction:
    """返回当前屏幕状态摘要——agent 用来确认"我现在在哪"。"""

    name: ClassVar[str] = "current_state"
    description: ClassVar[str] = (
        "Get current screen state summary: foreground app, visible text labels, "
        "interactive element count. No params needed. Use after actions to confirm "
        "which page you are on."
    )
    params: ClassVar[dict] = {}
    is_action: ClassVar[bool] = False  # 感知类，不改变设备状态
    _VISIBLE_TEXTS_LIMIT: ClassVar[int] = 30   # max visible texts returned

    def __call__(self, *, ctx: ActionContext) -> ActionResult:
        ui = ctx.observe()
        texts = [el.text for el in ui.elements if el.text]
        interactive = sum(1 for el in ui.elements if el.clickable)
        scrollable = any("scrollable" in (el.flags or []) for el in ui.elements)

        # 获取当前 app
        try:
            activity = ctx.phonefast.current_activity()
            pkg = ctx.phonefast.current_package()
        except Exception:
            activity = "unknown"
            pkg = "unknown"

        return ActionResult.ok(
            f"app={pkg} interactive={interactive} scrollable={scrollable}",
            app=pkg, activity=activity, visible_texts=texts[:self._VISIBLE_TEXTS_LIMIT],
            interactive_count=interactive, scrollable=scrollable,
        )


class BackAction:
    name: ClassVar[str] = "back"
    description: ClassVar[str] = "Press the back button."
    params: ClassVar[dict] = {}
    is_action: ClassVar[bool] = True

    def __call__(self, *, ctx: ActionContext) -> ActionResult:
        ctx.phonefast.back()
        return ActionResult.ok("pressed back")


class HomeAction:
    name: ClassVar[str] = "home"
    description: ClassVar[str] = "Press the Home key to return to the launcher/desktop."
    params: ClassVar[dict] = {}
    is_action: ClassVar[bool] = True

    def __call__(self, *, ctx: ActionContext) -> ActionResult:
        ctx.phonefast.home()
        return ActionResult.ok("pressed home")


class ScreenshotAction:
    name: ClassVar[str] = "screenshot"
    description: ClassVar[str] = (
        "Capture a screenshot and save it to the execution trace for post-hoc review/debugging. "
        "NOTE: the screenshot image is NOT visible to you — there is no vision channel, so you "
        "cannot interpret screenshot output. Do NOT call this to 'see' or confirm the screen. "
        "To determine screen state, use observe (element list) or ocr (text recognition). "
        "Call screenshot only to record evidence for later review."
    )
    params: ClassVar[dict] = {}
    is_action: ClassVar[bool] = False

    def __call__(self, *, ctx: ActionContext) -> ActionResult:
        b64 = ctx.phonefast.screenshot()
        return ActionResult.ok("screenshot captured", image_b64=b64)


class ShellAction:
    name: ClassVar[str] = "shell"
    description: ClassVar[str] = (
        "Execute an adb shell command. Provides flexible device-level access "
        "(e.g. pm list packages, settings get, cat, ls). "
        "Use as a last resort — prefer dedicated tools (launch/tap_element/check_package) first. "
        "NEVER use shell to write task content (no echo>/mkdir/content insert); shell is read-only "
        "plus system toggles (svc/settings put) and app launching (am start -n)."
    )
    params: ClassVar[dict] = {
        "command": {"type": "string", "desc": "adb shell command, e.g. 'pm list packages | grep xingin'", "required": True},
        "timeout": {"type": "number", "desc": "Timeout in seconds (default 10)"},
    }
    is_action: ClassVar[bool] = True  # shell changes device state, triggers auto-observe fingerprint update

    _SHELL_OUTPUT_LIMIT: ClassVar[int] = 4000  # max chars of output shown in LLM-facing summary
    _SUMMARY_CMD_LIMIT: ClassVar[int] = 60     # max chars of command shown in summary
    _SHELL_TIMEOUT_SEC: ClassVar[float] = 10.0  # default shell command timeout

    def __call__(self, *, ctx: ActionContext, command: str,
                 timeout: float | None = None) -> ActionResult:
        timeout = timeout if timeout is not None else self._SHELL_TIMEOUT_SEC
        output = ctx.phonefast.shell(command, timeout=timeout)
        # Output must reach the LLM via summary; truncate only at generous limits with a marker
        truncated = output[:self._SHELL_OUTPUT_LIMIT]
        marker = f" [...truncated, {len(output) - len(truncated)} more chars]" if len(output) > self._SHELL_OUTPUT_LIMIT else ""
        return ActionResult.ok(
            f"shell '{command[:self._SUMMARY_CMD_LIMIT]}' → {truncated}{marker}", command=command, output=output,
        )


class DeviceStatusAction:
    """查设备状态：daemon 连接、屏幕尺寸、UI 可用性等。"""

    name: ClassVar[str] = "device_status"
    description: ClassVar[str] = (
        "Query device status: daemon connection, screen dimensions, UI availability, serial. "
        "Use to diagnose device issues (broken UI tree, daemon disconnect) or get screen size."
    )
    params: ClassVar[dict] = {}
    is_action: ClassVar[bool] = False
    is_retryable: ClassVar[bool] = True

    def __call__(self, *, ctx: ActionContext) -> ActionResult:
        status = ctx.phonefast.status()
        parts = [f"{k}={v}" for k, v in (status or {}).items()]
        return ActionResult.ok(
            f"device status: {', '.join(parts)}",
            **(status or {}),
        )


class OcrAction:
    """OCR: read text from screenshot via image recognition.

    Fallback when observe returns too few elements (broken accessibility tree).
    Returns indexed text with center coordinates — use tap(x,y) to interact.
    """

    name: ClassVar[str] = "ocr"
    description: ClassVar[str] = (
        "Read text from the screen via OCR (image recognition). "
        "Fallback when observe returns too few elements (broken accessibility "
        "tree on real devices/custom ROMs). Returns indexed text with center "
        "coordinates: [N] 'text' at (x,y). Use tap(x=x, y=y) to interact with "
        "OCR-found text. Workflow: observe (few elements) → ocr → find target "
        "→ tap(x, y).\n\n"
        "⚠️ If OCR returns 0 results or only garbled noise (low-confidence "
        "random characters), the screen likely has NO readable text. Do NOT "
        "retry OCR — switch to shell verification, back/home relaunch the app, "
        "or complete(success=false) if truly stuck."
    )
    params: ClassVar[dict] = {}
    is_action: ClassVar[bool] = False
    is_observation: ClassVar[bool] = True
    _MIN_CONFIDENCE: ClassVar[float] = 0.3  # 低于此置信度的 OCR 结果视为噪声
    _LOW_CONFIDENCE_MAX_COUNT: ClassVar[int] = 3  # 低置信度 fragment 数 ≤ 此值视为噪声

    def __call__(self, *, ctx: ActionContext) -> ActionResult:
        result = ctx.phonefast.ocr()
        items = result.get("items", []) if isinstance(result, dict) else []
        lines: list[str] = []
        conf_sum: float = 0.0
        valid_count = 0
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            text = item.get("text", "")
            center = item.get("center", [0, 0])
            cx = int(center[0]) if len(center) > 0 else 0
            cy = int(center[1]) if len(center) > 1 else 0
            conf = item.get("confidence", 0)
            try:
                conf_f = float(conf)
            except (TypeError, ValueError):
                conf_f = 0.0
            conf_sum += conf_f
            valid_count += 1
            lines.append(f"[{valid_count - 1}] '{text}' at ({cx},{cy}) conf={conf_f:.2f}")
        text_out = "\n".join(lines)
        count = valid_count
        avg_conf = conf_sum / count if count > 0 else 0.0

        # 每条 OCR 调用独立判定——不做跨调用状态计数（归 agent 层 Guard 管）
        if count == 0:
            msg = ("OCR found NO text on this screen. "
                   "The screen likely has no readable content — "
                   "try shell verification or back/home to navigate away.")
        elif avg_conf < self._MIN_CONFIDENCE and count <= self._LOW_CONFIDENCE_MAX_COUNT:
            msg = (
                f"OCR returned {count} very-low-confidence fragments "
                f"(avg conf={avg_conf:.2f}). These are likely noise — "
                "NOT usable for navigation. Use shell or back/home instead."
            )
        else:
            msg = f"OCR: {count} text regions found"

        return ActionResult.ok(msg, count=count, elements=text_out)


class PythonExecAction:
    """Python REPL：LLM 写脚本，FastAgent sandbox 执行。

    脚本可调 tools.xxx()（15 个设备操作）+ json/re/math 等安全模块。
    一次调用完成多步工具组合，替代多轮 ReAct。
    """

    name: ClassVar[str] = "run_script"
    description: ClassVar[str] = (
        "Run a Python script to compose multiple tool calls with logic in ONE step. "
        "Every tools.xxx() call auto-logs to a step trace — returned alongside the "
        "result so you see every intermediate effect (observe snapshots, tap/swipe "
        "outcomes) without guessing.\n\n"
        "**When to use run_script:**\n"
        "- State-changing actions that need verification → observe→tap→observe in one go\n"
        "- Any workflow where you need to perceive UI changes mid-way\n"
        "- Parse shell output + conditionally act on it\n"
        "- Scroll-until-found loops with per-scroll observe\n\n"
        "**When NOT to use run_script:**\n"
        "- Single-step actions (back/home/launch/known tap) → call the tool directly\n"
        "- Two-step batches that don't need intermediate perception → just batch them\n\n"
        "Available: tools (observe/tap/swipe/type/shell/ocr/current_app/check_package/"
        "wait/back/home/key/launch/device_status/screenshot), "
        "json, re, math, time, datetime, collections, itertools, functools, "
        "and most Python builtins. Set `result = '...'` to return a summary.\n\n"
        "Example (switch to video mode and confirm):\n"
        "screen = tools.observe()\n"
        "targets = [e for e in screen if 'video' in e['text'].lower()]\n"
        "if targets:\n"
        "    t = targets[0]; tools.tap(t['center'][0], t['center'][1])\n"
        "    tools.wait(0.3)\n"
        "    screen2 = tools.observe()\n"
        "    result = f'after tap: {[e[\"text\"] for e in screen2]}'\n"
        "else:\n"
        "    result = 'no video option found'"
    )
    params: ClassVar[dict] = {
        "code": {"type": "string", "desc": "Python code to execute", "required": True},
    }
    is_action: ClassVar[bool] = True
    is_retryable: ClassVar[bool] = False

    _RUNSCRIPT_OUTPUT_LIMIT: ClassVar[int] = 8000  # max chars shown in LLM-facing summary

    def __call__(self, *, ctx: ActionContext, code: str) -> ActionResult:
        from fastaget.tools.sandbox import execute_python
        output = execute_python(code, ctx)
        truncated = output[:self._RUNSCRIPT_OUTPUT_LIMIT]
        marker = f" [...truncated, {len(output) - len(truncated)} more chars]" if len(output) > self._RUNSCRIPT_OUTPUT_LIMIT else ""
        return ActionResult.ok(f"{truncated}{marker}", output=output)


class AddMemoryAction:
    """跨步记忆：LLM 离开屏幕前存入关键数据，后续每步注入到上下文。

    典型用法：observe 看到目标包名 → add_memory(key="pkg", value="com.xingin.xhs")
    → 离开当前页 → 后续每步看到 <memory> 块，不用回翻历史。
    """

    name: ClassVar[str] = "add_memory"
    description: ClassVar[str] = (
        "Store a key-value memory entry that is automatically shown in every subsequent step. "
        "Use to remember critical info across pages (e.g. discovered package names, target "
        "names from search results, confirmed state values). "
        "Pick short, meaningful keys (e.g. pkg/text/step_done)."
    )
    params: ClassVar[dict] = {
        "key": {"type": "string", "desc": "Memory key (short and meaningful, e.g. pkg/text/installed)", "required": True},
        "value": {"type": "string", "desc": "Memory value", "required": True},
    }
    is_action: ClassVar[bool] = False  # 不改变设备状态

    def __call__(self, *, ctx: ActionContext, key: str, value: str) -> ActionResult:
        ctx.memory[key] = value  # 标记 dirty，由 _build_result 统一持久化
        ns = ctx.memory_namespace
        return ActionResult.ok(
            f"memory stored [{ns}]: {key}='{value}'", key=key, value=value, namespace=ns,
        )


# ═══════════════════════════════════════════════════════════
# 自动发现所有 Action 类（供 build_registry 使用）
# ═══════════════════════════════════════════════════════════

def _all_actions() -> list:
    """返回所有 Action 类的实例列表。新增 Action 只需加一个类，无需改注册逻辑。"""
    return [
        ObserveAction(), CurrentAppAction(), CheckPackageAction(),
        WaitAction(), PollUntilAction(), ScrollToFindAction(),
        AddMemoryAction(), WaitAndObserveAction(), AssertAction(), CompleteAction(),
        TapAction(), TapElementAction(), LongPressAction(), LongPressAtAction(), SwipeAction(),
        TypeAction(), FillFieldsAction(), KeyAction(), LaunchAction(), NavigateToAction(),
        TapByTextAction(), CurrentStateAction(),
        BackAction(), HomeAction(), ScreenshotAction(), ShellAction(), DeviceStatusAction(),
        OcrAction(), PythonExecAction(),
    ]


