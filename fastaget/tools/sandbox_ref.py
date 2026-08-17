"""自动从 ToolProxy 生成 run_script 可用方法清单——注入系统 prompt。

保证 prompt 里的方法列表和 ToolProxy 实际代码一致——改 ToolProxy 自动反映到 prompt。
"""
from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastaget.tools.sandbox import ToolProxy


def generate_sandbox_reference() -> str:
    """从 ToolProxy 类签名自动生成方法清单文本。"""
    from fastaget.tools.sandbox import ToolProxy, SAFE_MODULES

    lines = ["## run_script sandbox available methods (auto-generated, synced with code)", ""]

    # ── tools 方法 ──
    # 先收集方法列表再生成，计数自动同步
    tool_methods = []
    for name in sorted(dir(ToolProxy)):
        if name.startswith("_"):
            continue
        method = getattr(ToolProxy, name, None)
        if not callable(method) or isinstance(method, type):
            continue
        try:
            sig = inspect.signature(method)
        except (ValueError, TypeError):
            continue
        params = []
        for pname, param in sig.parameters.items():
            if pname == "self":
                continue
            if param.default is not param.empty:
                params.append(f"{pname}={param.default!r}")
            else:
                params.append(pname)
        doc = (method.__doc__ or "").strip().split("\n")[0]
        ret_hint = ""
        if "→" in doc:
            ret_hint = " " + doc[doc.index("→"):].split(".")[0]
        elif doc:
            ret_hint = f"  # {doc[:60]}"
        tool_methods.append(f"- tools.{name}({', '.join(params)}){ret_hint}")

    lines.append(f"### tools object (device operations, {len(tool_methods)} methods)")
    lines.append("")
    lines.extend(tool_methods)
    lines.append("")

    # ── 预注入模块 ──
    lines.append("### pre-injected safe modules (use directly, no import needed)")
    lines.append("")
    lines.append("⚠️ `import` / `from ... import` statements are AST-banned — all imports raise SandboxError directly.")
    lines.append("   Use the modules below to call methods directly: `json.loads(...)` ✓  |  `import json; json.loads(...)` ✗")
    lines.append("")
    for mod_name in sorted(SAFE_MODULES.keys()):
        mod = SAFE_MODULES[mod_name]
        # 列几个常用函数
        common = [a for a in dir(mod) if not a.startswith("_")][:5]
        lines.append(f"- `{mod_name}`: {', '.join(common)}...")
    lines.append("")

    # ── builtins ──
    from fastaget.tools.sandbox import SANDBOX_BUILTINS, _BLOCKED
    lines.append(f"### Python builtins ({len(SANDBOX_BUILTINS)} available)")
    lines.append("")
    # 分类列出
    types_ = [k for k in SANDBOX_BUILTINS if k[0].isupper() or k in ("str", "int", "float", "bool", "list", "dict", "set", "tuple", "frozenset")]
    funcs = [k for k in SANDBOX_BUILTINS if k not in types_ and k not in ("True", "False", "None")]
    lines.append(f"- Types: {', '.join(sorted(types_))}")
    lines.append(f"- Functions: {', '.join(sorted(funcs))}")
    lines.append(f"- Blocked (unavailable): {', '.join(sorted(_BLOCKED))}")
    lines.append("")

    # ── 返回值 ──
    lines.append("### Return value")
    lines.append("Set the `result = '...'` variable to return the result to the agent. If unset, stdout is used.")
    lines.append("")

    return "\n".join(lines)
