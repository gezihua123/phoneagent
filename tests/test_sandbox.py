"""Sandbox 安全测试 + ToolProxy 测试 + 集成测试。

验证：
1. 安全边界：import/open/getattr/globals 全部被封
2. 自由度：json/re/math/try-except 正常工作
3. ToolProxy：observe/tap/current_app 通过 mock 验证
4. 集成：多步脚本组合
"""
from __future__ import annotations

from fastaget.tools.sandbox import execute_python, ToolProxy, SANDBOX_BUILTINS
from fastaget.tools.context import ActionContext

from fastaget.scenariokit import MockPhonefast


# ---- helpers ----

def _result(output: str) -> str:
    """Extract the 'result:' value from the new trace+result output format."""
    for line in output.splitlines():
        if line.startswith("result: "):
            return line[len("result: "):]
    raise ValueError(f"no 'result:' line found in output:\n{output}")


# ---- 测试夹具 ----

class _FakePhonefast(MockPhonefast):
    """MockPhonefast + tap/swipe 元组追踪 + shell/ocr/包状态桩。

    设备操作（back/home/key/launch/type_text 等）直接继承 MockPhonefast。
    """

    def __init__(self, screen=None):
        super().__init__(screen or _SCREEN)
        self.tapped: list[tuple] = []
        self.swiped: list[tuple] = []
        self.set_installed("com.test.app")

    def tap(self, x, y):
        self.tapped.append((x, y))
        return super().tap(x, y)

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.swiped.append((x1, y1, x2, y2))
        return super().swipe(x1, y1, x2, y2, duration_ms)

    def shell(self, command, timeout=10): return "shell output: " + command
    def current_package(self): return "com.test.app"
    def current_activity(self): return "com.test.app/.MainActivity"
    def ocr(self): return {"items": [{"text": "Hello", "center": [50, 50], "confidence": 0.95}]}


_SCREEN = (
    '[0] text="WiFi" (TextView) [clickable] bounds=[50,150][150,250]\n'
    '[1] text="Bluetooth" (TextView) [clickable] bounds=[50,250][150,350]\n'
    '[2] text="Storage" (TextView) [clickable] bounds=[50,350][150,450]'
)


def _ctx():
    pf = _FakePhonefast()
    ctx = ActionContext(phonefast=pf)
    return ctx, pf


# ═══════════════════════════════════════════════════════════
# 安全边界测试
# ═══════════════════════════════════════════════════════════

class TestSecurityBoundary:
    """验证 4 条逃逸路径全部被封。"""

    def test_no_import(self):
        ctx, _ = _ctx()
        result = execute_python("import os\nresult='imported'", ctx)
        assert "NameError" in result or "import" in result.lower()

    def test_no_open(self):
        ctx, _ = _ctx()
        result = execute_python("open('/etc/passwd')\nresult='opened'", ctx)
        assert "NameError" in result or "open" in result.lower()

    def test_no_getattr(self):
        ctx, _ = _ctx()
        result = execute_python("getattr(tools, '_ctx')\nresult='got'", ctx)
        assert "NameError" in result or "getattr" in result.lower()

    def test_no_globals(self):
        ctx, _ = _ctx()
        result = execute_python("globals()['result'] = 'hacked'\n", ctx)
        assert "NameError" in result or "globals" in result.lower()

    def test_no_import_via_exec(self):
        """exec 在 sandbox 内仍用受限 builtins——import os 也逃不出去。"""
        ctx, _ = _ctx()
        result = execute_python("exec('import os')\nresult='escaped'", ctx)
        assert "NameError" in result or "import" in result.lower()

    def test_no_getattr_via_exec(self):
        ctx, _ = _ctx()
        result = execute_python("exec('x = getattr(tools, \"_ctx\")')\nresult='got'", ctx)
        assert "NameError" in result or "getattr" in result.lower()

    # ---- P0-6 回归：AST 级逃逸（属性语法不走 getattr builtin）----

    def test_dunder_subclasses_chain_blocked(self):
        """().__class__.__bases__[0].__subclasses__() 链必须被拒——
        旧代码 _DANGEROUS_ATTRS 是死代码，此链直达 host os.system。"""
        ctx, _ = _ctx()
        result = execute_python(
            "result = str(len(().__class__.__bases__[0].__subclasses__()))", ctx)
        assert "SandboxError" in result or "blocked" in result.lower(), \
            f"dunder 逃逸链未被拦截: {result}"

    def test_dunder_class_attr_blocked(self):
        """任何 dunder 属性访问（x.__class__）都必须被拒。"""
        ctx, _ = _ctx()
        result = execute_python("result = str((1).__class__)", ctx)
        assert "SandboxError" in result or "blocked" in result.lower()

    def test_private_attr_ctx_blocked(self):
        """tools._ctx → phonefast 私有访问必须被拒（下划线属性规则）。"""
        ctx, _ = _ctx()
        result = execute_python("result = str(type(tools._ctx).__name__)", ctx)
        assert "SandboxError" in result or "blocked" in result.lower()

    def test_eval_blocked(self):
        """eval 必须被封——eval 字符串绕过 AST 静态校验。"""
        ctx, _ = _ctx()
        result = execute_python("result = eval('1+1')", ctx)
        assert "NameError" in result or "eval" in result.lower()
        assert "eval" not in SANDBOX_BUILTINS

    def test_exec_compile_blocked(self):
        """exec/compile 同理被封。"""
        ctx, _ = _ctx()
        result = execute_python("exec('result = 42')", ctx)
        assert "NameError" in result or "exec" in result.lower()
        assert "exec" not in SANDBOX_BUILTINS
        assert "compile" not in SANDBOX_BUILTINS

    def test_fstring_dunder_blocked(self):
        """f-string 内的 dunder 属性也在 AST 中——必须被拒。"""
        ctx, _ = _ctx()
        result = execute_python("result = f'{(1).__class__}'", ctx)
        assert "SandboxError" in result or "blocked" in result.lower()

    def test_exception_dunder_blocked(self):
        """异常对象的 __traceback__/__context__ 链同样被拒。"""
        ctx, _ = _ctx()
        code = """
try:
    1/0
except Exception as e:
    result = str(e.__traceback__)
"""
        result = execute_python(code, ctx)
        assert "SandboxError" in result or "blocked" in result.lower()


# ═══════════════════════════════════════════════════════════
# 自由度测试
# ═══════════════════════════════════════════════════════════

class TestFreedom:
    """验证安全模块 + builtins 正常工作。"""

    def test_json_works(self):
        ctx, _ = _ctx()
        result = execute_python("result = json.loads('{\"a\": 1}')[\"a\"]", ctx)
        assert _result(result) == "1"

    def test_re_works(self):
        ctx, _ = _ctx()
        result = execute_python("m = re.search(r'\\d+', 'abc123'); result = m.group()", ctx)
        assert _result(result) == "123"

    def test_math_works(self):
        ctx, _ = _ctx()
        result = execute_python("result = str(math.ceil(3.2))", ctx)
        assert _result(result) == "4"

    def test_try_except_works(self):
        ctx, _ = _ctx()
        code = """
try:
    x = 1 / 0
    result = "no error"
except Exception as e:
    result = "caught: " + str(type(e).__name__)
"""
        result = execute_python(code, ctx)
        assert "caught: ZeroDivisionError" in _result(result)

    def test_list_comprehension(self):
        ctx, _ = _ctx()
        result = execute_python("result = str([x*2 for x in range(3)])", ctx)
        assert _result(result) == "[0, 2, 4]"

    def test_print_captured(self):
        ctx, _ = _ctx()
        result = execute_python("print('hello world')", ctx)
        assert _result(result) == "hello world"

    def test_result_overrides_stdout(self):
        ctx, _ = _ctx()
        result = execute_python("print('stdout'); result = 'result_var'", ctx)
        assert _result(result) == "result_var"

    def test_no_result_uses_stdout(self):
        ctx, _ = _ctx()
        result = execute_python("print('only stdout')", ctx)
        assert _result(result) == "only stdout"

    def test_empty_script(self):
        ctx, _ = _ctx()
        result = execute_python("pass", ctx)
        assert _result(result) == "ok"

    def test_non_main_thread_no_stdout_hijack(self):
        """P1-17 回归：非主线程调用不得永久劫持 sys.stdout。

        signal.signal 在非主线程抛 ValueError——旧代码在 try/finally 外安装，
        异常时 sys.stdout 已重定向到死 StringIO，进程后续 print 静默消失。
        """
        import sys
        import threading
        ctx, _ = _ctx()
        errors, results = [], []
        real_stdout = sys.stdout

        def worker():
            try:
                results.append(execute_python("result = 'from-thread'", ctx))
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=20)
        assert not t.is_alive()
        assert sys.stdout is real_stdout, "sys.stdout 被永久劫持"
        assert not errors, f"非主线程执行不应抛异常: {errors}"
        assert results == ["[trace] 0 steps:\nresult: from-thread"]


# ═══════════════════════════════════════════════════════════
# ToolProxy 测试
# ═══════════════════════════════════════════════════════════

class TestToolProxy:
    """验证 ToolProxy 的 15 个设备操作。"""

    def test_observe_returns_list_of_dicts(self):
        ctx, _ = _ctx()
        proxy = ToolProxy(ctx)
        # 需要 ctx.observe() 先填充 UIState
        ctx.observe()
        result = proxy.observe()
        assert isinstance(result, list)
        assert len(result) >= 1
        el = result[0]
        assert "index" in el
        assert "text" in el
        assert "center" in el
        assert isinstance(el["center"], list) and len(el["center"]) == 2

    def test_tap_calls_phonefast(self):
        ctx, pf = _ctx()
        proxy = ToolProxy(ctx)
        proxy.tap(100, 200)
        assert pf.tapped == [(100, 200)]

    def test_swipe_calls_phonefast(self):
        ctx, pf = _ctx()
        proxy = ToolProxy(ctx)
        proxy.swipe(360, 1000, 360, 400)
        assert pf.swiped == [(360, 1000, 360, 400)]

    def test_current_app_returns_dict(self):
        ctx, _ = _ctx()
        proxy = ToolProxy(ctx)
        app = proxy.current_app()
        assert app["package"] == "com.test.app"
        assert "MainActivity" in app["activity"]

    def test_check_package_returns_bool(self):
        ctx, _ = _ctx()
        proxy = ToolProxy(ctx)
        assert proxy.check_package("com.test.app") is True
        assert proxy.check_package("com.fake.nope") is False

    def test_shell_returns_output(self):
        ctx, _ = _ctx()
        proxy = ToolProxy(ctx)
        output = proxy.shell("getprop ro.build.version")
        assert "shell output" in output

    def test_ocr_returns_list(self):
        ctx, _ = _ctx()
        proxy = ToolProxy(ctx)
        items = proxy.ocr()
        assert len(items) == 1
        assert items[0]["text"] == "Hello"
        assert items[0]["confidence"] == 0.95


# ═══════════════════════════════════════════════════════════
# 集成测试——脚本组合多步
# ═══════════════════════════════════════════════════════════

class TestIntegration:
    """验证脚本能组合多步工具调用。"""

    def test_find_and_tap(self):
        """脚本：observe → 找 WiFi → tap → 验证。"""
        ctx, pf = _ctx()
        code = """
screen = tools.observe()
target = None
for el in screen:
    if "WiFi" in el["text"]:
        target = el
        break

if target:
    tools.tap(target["center"][0], target["center"][1])
    result = "tapped " + target["text"]
else:
    result = "not found"
"""
        result = execute_python(code, ctx)
        assert "tapped WiFi" in result
        assert pf.tapped == [(100, 200)]  # WiFi element's center

    def test_shell_plus_re_parsing(self):
        """脚本：shell → re 解析 → 条件判断。"""
        ctx, _ = _ctx()
        code = """
output = tools.shell("dumpsys wifi | grep state")
match = re.search(r"state", output)
if match:
    result = "found state in output"
else:
    result = "not found"
"""
        output = execute_python(code, ctx)
        assert _result(output) == "found state in output"

    def test_scroll_and_find(self):
        """脚本：observe → 没找到 → swipe → observe → 找到 → tap。"""
        ctx, pf = _ctx()
        code = """
# First observe: no "Storage" visible
screen = tools.observe()
target = None
for el in screen:
    if "Storage" in el["text"]:
        target = el
        break

if not target:
    # Scroll and retry
    tools.swipe(360, 1000, 360, 400)
    screen = tools.observe()
    for el in screen:
        if "Storage" in el["text"]:
            target = el
            break

if target:
    tools.tap(target["center"][0], target["center"][1])
    result = "found and tapped: " + target["text"]
else:
    result = "not found after scroll"
"""
        result = execute_python(code, ctx)
        assert "found and tapped: Storage" in result
        # mock 返回固定屏幕，Storage 在首次 observe 即可见，不需要 swipe
        assert len(pf.swiped) == 0
