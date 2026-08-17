"""Python REPL sandbox——LLM 写脚本，FastAgent 执行。

自由度：预注入安全模块（json/re/math/time 等）+ 几乎全量 builtins。
控制边界（双层）：
  1. builtins 层：封 __import__/open/getattr/eval/exec/compile 等（见 _BLOCKED）
  2. AST 层：拒绝 import 语句 + 一切下划线属性访问（x.__class__ / tools._ctx）
     ——dunder 链（__class__.__bases__.__subclasses__）不经过 getattr builtin，
     必须在 AST 静态校验层切断；eval/exec/compile 会产生未校验代码，一并封禁

ToolProxy 暴露 15 个设备操作（有限集合），脚本只能调这些 + 安全模块。
"""
from __future__ import annotations

import ast
import io
import json
import re
import math
import sys
import threading
import time
import datetime
import string
import collections
import itertools
import functools
import signal
import builtins as _builtins_mod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastaget.tools.context import ActionContext


# ═══════════════════════════════════════════════════════════
# 预注入安全模块——脚本直接用，不需要 import
# ═══════════════════════════════════════════════════════════

SAFE_MODULES: dict[str, Any] = {
    "json": json,
    "re": re,
    "math": math,
    "time": time,
    "datetime": datetime,
    "string": string,
    "collections": collections,
    "itertools": itertools,
    "functools": functools,
}


# ═══════════════════════════════════════════════════════════
# 受限 builtins——全量减去逃逸路径
# ═══════════════════════════════════════════════════════════

_BLOCKED = frozenset({
    "__import__",    # 不能 import 新模块（安全模块已预注入）
    "open",          # 不能读写文件
    "getattr",       # 不能访问 proxy 内部 / phonefast 私有
    "setattr",       # 同上
    "delattr",       # 同上
    "globals",       # 不能改 sandbox 作用域
    "locals",        # 同上
    "vars",          # 同上
    "eval",          # eval 字符串绕过 AST 静态校验——必须封死
    "exec",          # 同上
    "compile",       # 同上
    "input",         # 不能阻塞等待输入
    "breakpoint",    # 不能触发调试器
    "exit",          # SystemExit 是 BaseException，逃出 except Exception 杀进程
    "quit",          # 同上
})


# 白名单：纯数据 dunder（只读字符串），无法构成逃逸链
_ALLOWED_DUNDER_ATTRS = frozenset({"__name__"})


def _validate_tree(tree: ast.AST) -> str | None:
    """AST 静态校验——返回 None 表示通过，否则返回拒绝原因。

    属性语法不走 getattr builtin，所以 dunder 逃逸链
    （`().__class__.__bases__[0].__subclasses__()`）只能在 AST 层切断。
    规则：拒绝 import 语句 + 一切下划线开头的属性访问（dunder 与私有全覆盖，
    含 tools._ctx），仅放行 _ALLOWED_DUNDER_ATTRS 中的纯数据 dunder。
    f-string/异常处理器中的属性节点同样在 AST 中，无处可藏。
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "import statements are blocked (safe modules are pre-injected)"
        if (isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and node.attr not in _ALLOWED_DUNDER_ATTRS):
            return f"underscore attribute access blocked: {node.attr}"
    return None

# 构建受限 builtins dict——从 builtins 模块取全量，减去逃逸路径
SANDBOX_BUILTINS: dict[str, Any] = {
    k: getattr(_builtins_mod, k)
    for k in dir(_builtins_mod)
    if (not k.startswith("_") or k in ("__name__", "__doc__"))
    and k not in _BLOCKED
}


# ═══════════════════════════════════════════════════════════
# ToolProxy——有限设备操作集
# ═══════════════════════════════════════════════════════════

class ToolProxy:
    """Sandbox-callable device operations — limited set of 15 methods.

    Depends only on ActionContext (phonefast + observe + ui), not registry.
    Each method returns simple Python types (str/bool/list/dict), not ActionResult.
    All method calls auto-log to trace — returned with result at script end so
    the LLM perceives every step's effect.
    """

    _MAX_TRACE_ELEMENTS: int = 12  # max element snapshot entries in trace

    def __init__(self, ctx: "ActionContext") -> None:
        self._ctx = ctx
        self._trace: list[dict] = []  # [{step, tool, args, summary, elements}]

    def _log(self, tool: str, args: dict, summary: str,
             elements: list[dict] | None = None) -> None:
        """Auto-log each tool call to trace (compact single-line + optional elements)."""
        self._trace.append({
            "step": len(self._trace) + 1,
            "tool": tool,
            "args": args,
            "summary": summary,
            "elements": elements,
        })

    # ── 感知 ──

    def observe(self, concise: bool = True, max_elements: int = 80) -> list[dict]:
        """Observe the screen and return the element list.

        Returns: [{index, text, center:[x,y], bounds:[l,t,r,b], clickable}]
        """
        state = self._ctx.observe()
        result: list[dict] = []
        for e in state.elements:
            result.append({
                "index": e.index,
                "text": e.text or e.label() or "",
                "center": list(e.center()),
                "bounds": list(e.bounds),
                "clickable": e.clickable,
            })
        # trace: 记录元素快照（紧凑格式）
        snapshot = []
        for e in state.elements[:self._MAX_TRACE_ELEMENTS]:
            label = (e.text or e.label() or "").strip()
            cx, cy = e.center()
            snapshot.append({"idx": e.index, "text": label[:50], "x": cx, "y": cy})
        self._log("observe", {"concise": concise},
                  f"{len(result)} elements", snapshot)
        return result

    def ocr(self) -> list[dict]:
        """Read screen text via OCR, returns text region list.

        Returns: [{text, center:[x,y], confidence}]
        """
        raw = self._ctx.phonefast.ocr()
        items = raw.get("items", []) if isinstance(raw, dict) else []
        result = [
            {"text": i.get("text", ""),
             "center": list(i.get("center", [0, 0])),
             "confidence": i.get("confidence", 0)}
            for i in items if isinstance(i, dict)
        ]
        texts = [r["text"] for r in result[:10]]
        self._log("ocr", {}, f"{len(result)} text regions ({', '.join(texts[:6])})")
        return result

    def screenshot(self) -> str:
        """Capture a screenshot, returns base64-encoded PNG."""
        b64 = self._ctx.phonefast.screenshot()
        self._log("screenshot", {}, f"PNG {len(b64)} chars base64")
        return b64

    def current_app(self) -> dict:
        """Query foreground Activity (device-level fact)."""
        pkg = self._ctx.phonefast.current_package()
        act = self._ctx.phonefast.current_activity()
        result = {"package": pkg, "activity": act}
        self._log("current_app", {}, f"{pkg}/{act}")
        return result

    def check_package(self, package: str) -> bool:
        """Check whether a package is installed (device-level fact)."""
        installed = self._ctx.phonefast.is_package_installed(package)
        self._log("check_package", {"package": package},
                  f"installed={installed}")
        return installed

    def device_status(self) -> dict:
        """Query device/daemon status."""
        status = self._ctx.phonefast.status()
        self._log("device_status", {},
                  f"width={status.get('device_width')}, height={status.get('device_height')}")
        return status

    # ── 操作 ──

    def tap(self, x: int, y: int) -> str:
        """Tap by coordinates."""
        self._ctx.phonefast.tap(int(x), int(y))
        summary = f"tapped ({x},{y})"
        self._log("tap", {"x": x, "y": y}, summary)
        return summary

    def tap_element(self, index: int) -> str:
        """Tap by element index — coordinates resolved from the current screen.

        先 observe 取屏幕元素 → 按 index 定位 → 点中心坐标。
        如果元素不存在则抛 ValueError。
        """
        state = self._ctx.observe()
        target = None
        for e in state.elements:
            if getattr(e, 'index', None) == int(index):
                target = e
                break
        if target is None:
            raise ValueError(f"element index {index} not found on current screen")
        cx, cy = target.center()
        self._ctx.phonefast.tap(cx, cy)
        summary = f"tapped element[{index}] label={target.text or target.label() or ''!r} at ({cx},{cy})"
        self._log("tap_element", {"index": index}, summary)
        return summary

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        """Swipe from (x1,y1) to (x2,y2)."""
        self._ctx.phonefast.swipe(int(x1), int(y1), int(x2), int(y2), int(duration_ms))
        summary = f"swiped ({x1},{y1})→({x2},{y2})"
        self._log("swipe", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "dur": duration_ms},
                  summary)
        return summary

    def type(self, text: str) -> str:
        """Type text (ASCII/pinyin)."""
        self._ctx.phonefast.type_text(str(text))
        summary = f"typed {len(str(text))} chars"
        self._log("type", {"text_len": len(str(text))}, summary)
        return summary

    def back(self) -> str:
        """Press the back key."""
        self._ctx.phonefast.back()
        self._log("back", {}, "back")
        return "back"

    def home(self) -> str:
        """Press the Home key."""
        self._ctx.phonefast.home()
        self._log("home", {}, "home")
        return "home"

    def key(self, name: str) -> str:
        """Press a system key (enter/back/home/search etc.)."""
        self._ctx.phonefast.key(str(name))
        summary = f"key({name})"
        self._log("key", {"name": name}, summary)
        return summary

    def launch(self, package: str) -> str:
        """Launch an app."""
        self._ctx.phonefast.launch(str(package))
        summary = f"launched {package}"
        self._log("launch", {"package": package}, summary)
        return summary

    def shell(self, command: str, timeout: float = 10.0) -> str:
        """Execute an adb shell command, returns stdout."""
        out = self._ctx.phonefast.shell(str(command), timeout=timeout)
        preview = (out or "").strip()[:120]
        self._log("shell", {"cmd": command[:60]}, preview or "(empty)")
        return out

    def wait(self, seconds: float) -> None:
        """Wait N seconds."""
        time.sleep(float(seconds))
        self._log("wait", {"seconds": seconds}, "done")


# ═══════════════════════════════════════════════════════════
# Sandbox 执行入口
# ═══════════════════════════════════════════════════════════

class _TimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise _TimeoutError("script execution timed out")


def _format_trace(trace_entries: list[dict]) -> list[str]:
    """Format trace entries into human-readable lines."""
    lines = [f"[trace] {len(trace_entries)} steps:"]
    for e in trace_entries:
        # main step line
        arg_str = ", ".join(f"{k}={v}" for k, v in e["args"].items())
        call = f"tools.{e['tool']}({arg_str})" if arg_str else f"tools.{e['tool']}()"
        lines.append(f"  {e['step']}. {call} → {e['summary']}")
        # element sub-lines (observe only)
        if e.get("elements"):
            for el in e["elements"]:
                lines.append(f"     [{el['idx']}] {el['text']} ({el['x']},{el['y']})")
    return lines


def execute_python(code: str, ctx: "ActionContext", timeout: int = 15) -> str:
    """Execute Python in restricted sandbox, returning trace + result.

    Dual-layer boundary: blocked builtins (_BLOCKED) + AST validation (_validate_tree).
    Result priority: `result` variable > stdout > "ok"
    """
    # AST 静态校验在 exec 之前——dunder 逃逸链在此切断
    try:
        tree = ast.parse(code, "<sandbox>", "exec")
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    rejection = _validate_tree(tree)
    if rejection:
        return f"SandboxError: blocked unsafe syntax ({rejection})"

    proxy = ToolProxy(ctx)
    stdout_buf = io.StringIO()

    g: dict[str, Any] = {
        **SAFE_MODULES,
        "__builtins__": SANDBOX_BUILTINS,
        "tools": proxy,
        "result": None,
    }

    # 超时保护（Unix SIGALRM）——仅主线程可装信号处理器；
    # 非主线程 signal.signal 抛 ValueError，若在 stdout 重定向后抛出会
    # 永久劫持 sys.stdout（P1-17），故 signal 安装必须早于重定向
    can_timeout = (hasattr(signal, "SIGALRM")
                   and threading.current_thread() is threading.main_thread())
    old_handler = signal.getsignal(signal.SIGALRM) if can_timeout else None
    if can_timeout:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout)

    old_real_stdout = sys.stdout
    try:
        sys.stdout = stdout_buf
        exec(compile(tree, "<sandbox>", "exec"), g)
    except _TimeoutError:
        return f"TimeoutError: script exceeded {timeout}s limit"
    except SystemExit:
        # exit()/quit() 抛 SystemExit(BaseException)——捕获防进程崩溃
        return "SystemExit: exit() called in sandbox (blocked)"
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    finally:
        sys.stdout = old_real_stdout
        if can_timeout:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    # 结果组装：trace + result
    trace_lines = _format_trace(proxy._trace)

    # result 优先级：result 变量 > stdout > "ok"
    result_val = g.get("result")
    if result_val is None:
        result_val = stdout_buf.getvalue().strip() or "ok"

    return "\n".join(trace_lines) + f"\nresult: {str(result_val)[:2000]}"
