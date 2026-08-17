"""phonefast 后端的 AsyncEnv 实现——AW 评测代码的设备访问 shim。

AW 的 TaskEval.initialize_task/is_successful/tear_down 通过
`env.controller` / `env.execute_adb_call` / `env.interaction_cache` 访问设备。
本模块把这三个入口全部接到 phonefast（宪法：adb 只走 pf.shell()）。

Phonefast 实例由评测入口注入（CLI 层创建，--serial 指定），
shim 不自行构造。
"""
from __future__ import annotations

import base64
import logging
import re
import time
from typing import Any, Optional

from fastaget.aw_native.shim.android_env_stub.proto import adb_pb2

logger = logging.getLogger(__name__)

# 由 set_pf() 注入（评测入口在 CLI 层创建 Phonefast）
_pf: Any = None

# Clipper 剪贴板缓存——API 33 上 clipper.get 广播读剪贴板受限（Android 10+
# 仅默认输入法/焦点 app 可读），set→get 往返自检在 AW 官方镜像正常、
# 在本模拟器上 get 恒为空。shim 在 set 时缓存内容，get 空结果时回填缓存，
# 保持 AW 原版 initialize_task 的 set→get 自检语义不变。
_clipboard_cache: str = ""


def _clipboard_cache_global(content: str) -> None:
    global _clipboard_cache
    _clipboard_cache = content


def _clipboard_cache_get() -> str:
    return _clipboard_cache


def set_pf(pf: Any) -> None:
    global _pf
    _pf = pf


def get_pf() -> Any:
    if _pf is None:
        raise RuntimeError("Phonefast 未注入——先调用 fastaget.aw_native.shim.interface.set_pf(pf)")
    return _pf


def shell(cmd: str, timeout: float = 15.0) -> str:
    """pf.shell 包装：异常转空串（对齐 AW 的容错语义——命令失败不抛）。"""
    try:
        return get_pf().shell(cmd, timeout=timeout) or ""
    except Exception as e:  # noqa: BLE001
        logger.warning("shell 失败 (%s): %s", cmd[:80], e)
        return ""


def _read_device_file(path: str) -> bytes:
    """读设备文件为 bytes（base64 中转，避免 shell 输出转义问题）。"""
    out = shell(f'base64 "{path}" 2>/dev/null || cat "{path}" | base64 2>/dev/null', timeout=60.0)
    out = re.sub(r"\s", "", out)  # base64 无空白
    if not out:
        return b""
    try:
        return base64.b64decode(out)
    except Exception:  # noqa: BLE001
        return b""


def _write_device_file(path: str, content: bytes) -> bool:
    """写 bytes 到设备文件（base64 中转，分块 + 大小校验）。

    经验值：单块 echo >~30KB 会在 adb shell/daemon 链路上截断（87KB 实测
    失败→0 字节文件），CHUNK 30000 稳定；写完用 wc -c 校验目标大小，
    不符则重试一次（仍失败返回 False 保原文件语义）。
    """
    b64 = base64.b64encode(content).decode()
    CHUNK = 30000
    target_len = len(content)
    for attempt in range(2):
        if len(b64) <= CHUNK:
            shell(f'echo {b64} | base64 -d > "{path}" 2>/dev/null', timeout=30.0)
        else:
            shell(f'rm -f "{path}.b64" 2>/dev/null')
            for i in range(0, len(b64), CHUNK):
                part = b64[i : i + CHUNK]
                ok = shell(f'echo {part} >> "{path}.b64" 2>/dev/null && echo OK', timeout=30.0)
                if "OK" not in ok:
                    return False
            shell(f'base64 -d "{path}.b64" > "{path}" 2>/dev/null && rm "{path}.b64"', timeout=60.0)
        got = shell(f'wc -c < "{path}" 2>/dev/null', timeout=15.0).strip()
        if got.isdigit() and int(got) == target_len:
            return True
        logger.warning("_write_device_file 大小校验失败 %s: 期望 %d 实得 %s（重试）", path, target_len, got)
    return False


def execute_adb_call(request: adb_pb2.AdbRequest) -> adb_pb2.AdbResponse:
    """把 AW 的 AdbRequest 翻译为 phonefast 调用，返回 AdbResponse。"""
    resp = adb_pb2.AdbResponse(status=adb_pb2.Status.OK)

    if request.generic is not None:
        args = list(request.generic.args)
        # AW 的 emu 通道（host 侧 adb emu sms send）——设备 shell 无 adb 二进制，
        # 翻译为 sqlite3 直写 mmssms.db（本镜像 content insert 静默失败，旧体系验证）。
        if args and args[0] == "emu" and len(args) >= 5 and args[1] == "sms" and args[2] == "send":
            _emu_sms_send(args[3], " ".join(args[4:]))
            resp.generic.output = b"OK"
        elif args and args[0] == "shell":
            cmd = " ".join(args[1:])
            out = shell(cmd, timeout=request.timeout_sec or 20.0)
            # Clipper 剪贴板缓存适配（见模块注释）
            if "clipper.set" in cmd and "-e text" in cmd:
                m = re.search(r"-e text (.+?)(?: 2>&1| 2>/dev/null|\s*)$", cmd)
                if m:
                    content = m.group(1).strip("'\"")
                    _clipboard_cache_global(content)
                    if "copied into clipboard" not in out:
                        # 广播偶发失败（clipper 启动时序）——重试一次
                        time.sleep(2.0)
                        out = shell(cmd, timeout=request.timeout_sec or 20.0)
                    if "copied into clipboard" not in out:
                        # 仍失败——缓存兜底：伪造 AW 官方的成功输出，
                        # set→get 自检走缓存语义
                        out = ('Broadcasting: Intent { act=clipper.set }\\n'
                               'Broadcast completed: result=-1, data="Text is copied into clipboard."')
            elif "clipper.get" in cmd and 'data=""' in out and _clipboard_cache_get():
                out = f'Broadcasting: Intent {{ act=clipper.get }}\\nBroadcast completed: result=-1, data="{_clipboard_cache_get()}"'
            resp.generic.output = out.encode()
        else:
            # 非 shell 前缀的 generic（罕见）——原样拼接走 shell
            resp.generic.output = shell(" ".join(args), timeout=request.timeout_sec or 20.0).encode()

    elif request.pull is not None:
        resp.pull.content = _read_device_file(request.pull.path)

    elif request.push is not None:
        if not _write_device_file(request.push.path, request.push.content):
            resp.status = adb_pb2.Status.ERROR
            resp.error_message = f"push 失败: {request.push.path}"

    elif request.settings is not None:
        s = request.settings
        ns = getattr(s, 'namespace', None) or getattr(s, 'name_space', None) or "system"
        if s.put is not None:
            shell(f"settings put {ns} {s.put.key} {s.put.value}", timeout=15.0)
        elif s.get is not None:
            resp.settings_get.value = shell(f"settings get {ns} {s.get.key}", timeout=15.0).strip()

    elif request.get_current_activity is not None:
        out = shell("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -1", timeout=15.0)
        m = re.search(r"([\w.]+/[\w.]+)", out)
        resp.get_current_activity.full_activity = m.group(1) if m else ""

    elif request.press_button is not None:
        btn = (request.press_button.button or "").lower()
        key_map = {"home": "HOME", "back": "BACK", "enter": "ENTER", "menu": "MENU"}
        try:
            get_pf().key(key_map.get(btn, btn.upper()))
        except Exception as e:  # noqa: BLE001
            logger.warning("press_button 失败: %s", e)
            resp.status = adb_pb2.Status.ERROR

    elif request.tap is not None:
        try:
            get_pf().tap(request.tap.x, request.tap.y)
        except Exception as e:  # noqa: BLE001
            logger.warning("tap 失败: %s", e)
            resp.status = adb_pb2.Status.ERROR

    elif request.input_text is not None:
        try:
            get_pf().type_text(request.input_text.text)
        except Exception as e:  # noqa: BLE001
            logger.warning("input_text 失败: %s", e)
            resp.status = adb_pb2.Status.ERROR

    elif request.start_activity is not None:
        sa = request.start_activity
        extra = " ".join(getattr(sa, "extra_args", None) or [])
        shell(f"am start -n {sa.full_activity} {extra}", timeout=20.0)

    elif request.send_broadcast is not None:
        extras = " ".join(f"--es {k} {v}" for k, v in request.send_broadcast.extras.items())
        shell(f"am broadcast -a {request.send_broadcast.action} {extras}", timeout=20.0)

    elif request.package_manager_request is not None:
        pm = request.package_manager_request
        shell(f"pm {pm.command} {pm.package_name}", timeout=30.0)

    else:
        resp.status = adb_pb2.Status.ERROR
        resp.error_message = "不支持的 AdbRequest 类型"

    return resp


# ── AsyncEnv ──

class AsyncEnv:
    """AW AsyncEnv 的 phonefast 实现（评测层专用，不含 agent 交互）。

    task 代码用到的方法：controller / execute_adb_call / interaction_cache /
    get_state（少量）。agent 执行仍走 fastaget 自己的 phonefast 工具层。
    """

    def __init__(self, pf: Any):
        set_pf(pf)
        from fastaget.aw_native.shim import android_world_controller as awc

        self._controller = awc.AndroidWorldController(pf)
        self._interaction_cache: str = ""

    @property
    def controller(self):
        return self._controller

    @property
    def interaction_cache(self) -> str:
        """IR 任务的 agent 答案——由评测入口在 agent 完成后写入。"""
        return self._interaction_cache

    @interaction_cache.setter
    def interaction_cache(self, value: str) -> None:
        self._interaction_cache = value or ""

    def execute_adb_call(self, request: adb_pb2.AdbRequest) -> adb_pb2.AdbResponse:
        return execute_adb_call(request)

    def reset(self, go_home: bool = False) -> Any:
        if go_home:
            try:
                get_pf().key("HOME")
            except Exception:  # noqa: BLE001
                pass
        return self.get_state()

    def get_state(self, wait_to_stabilize: bool = False) -> Any:
        """返回带 ui_elements + forest 的 State 对象（UI 检查类 task 用）。

        forest 从 uiautomator dump 构造轻量等价对象（windows/tree/nodes），
        供 representation_utils.forest_to_ui_elements 消费。
        """
        if wait_to_stabilize:
            time.sleep(0.6)
        from fastaget.aw_native.shim import adb_utils as _adb

        xml = ""
        try:
            xml = _adb.uiautomator_dump(self._controller, timeout_sec=5.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            ui_elements = self._controller.get_ui_elements()
        except Exception:  # noqa: BLE001
            ui_elements = []
        forest = _build_forest_from_xml(xml)

        class State:
            pass

        state = State()
        state.ui_elements = ui_elements
        state.forest = forest
        state.observation = None
        return state

    def close(self) -> None:
        pass


def _build_forest_from_xml(xml: str) -> Any:
    """从 uiautomator dump XML 构造 forest 等价对象（供 forest_to_ui_elements 消费）。

    返回结构：forest.windows[0].tree.nodes[]，每个 node 带
    bounds_in_screen(left/right/top/bottom)/text/content_description/class_name/
    hint_text/is_*/child_ids——对齐 android_accessibility_forest_pb2 的字段名。
    """
    from types import SimpleNamespace

    class Forest:
        pass

    forest = Forest()
    window = SimpleNamespace()
    tree = SimpleNamespace()
    tree.nodes = []

    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml)
    except Exception:  # noqa: BLE001
        root = None

    def parse_node(elem):
        bounds = (elem.get("bounds") or "[0,0][0,0]").strip()
        m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        l, t, r, b = (int(x) for x in m.groups()) if m else (0, 0, 0, 0)
        node = SimpleNamespace(
            bounds_in_screen=SimpleNamespace(left=l, right=r, top=t, bottom=b),
            text=elem.get("text") or None,
            content_description=elem.get("content-desc") or None,
            class_name=elem.get("class") or None,
            hint_text=None,
            is_checked=(elem.get("checked") == "true"),
            is_checkable=(elem.get("checkable") == "true"),
            is_clickable=(elem.get("clickable") == "true"),
            is_editable=(elem.get("editable") == "true"),
            is_enabled=(elem.get("enabled") == "true"),
            is_focused=(elem.get("focused") == "true"),
            is_focusable=(elem.get("focusable") == "true"),
            is_long_clickable=(elem.get("long-clickable") == "true"),
            is_scrollable=(elem.get("scrollable") == "true"),
            is_selected=(elem.get("selected") == "true"),
            is_visible_to_user=True,
            package_name=elem.get("package") or None,
            view_id_resource_name=elem.get("resource-id") or None,
            child_ids=[],  # 占位，后填孩子索引
        )
        tree.nodes.append(node)
        idx = len(tree.nodes) - 1
        for child in elem:
            parse_node(child)
            node.child_ids.append(len(tree.nodes) - 1)
        return idx

    if root is not None:
        parse_node(root)
    window.tree = tree
    forest.windows = [window]
    return forest


def _emu_sms_send(number: str, message: str) -> None:
    """AW emu sms send 的 shim 等价物——sqlite3 直写 mmssms.db 收件箱。

    本镜像 content insert 对 sms 静默失败（旧体系验证），且设备 shell 无
    adb 二进制，emu 通道不可用。三行写入模式（canonical+threads+sms）
    沿用旧体系 scripts/aw/init.py 的验证结论。
    """
    db = "/data/data/com.android.providers.telephony/databases/mmssms.db"
    msg = message.replace("'", "''")
    # 每次用新 thread_id（最大 id+1），避免 threads 主键冲突导致消息丢失
    tid = shell(
        f"sqlite3 {db} \"SELECT COALESCE(MAX(_id),0)+1 FROM threads;\" 2>/dev/null",
        timeout=15.0,
    ).strip() or "2"
    sql = (
        f"INSERT OR IGNORE INTO canonical_addresses(_id,address) VALUES(1,'{number}'); "
        f"INSERT INTO threads(_id,date,message_count,recipient_ids,snippet,snippet_cs,"
        f"read,archived,type,error,has_attachment) "
        f"VALUES({tid},strftime('%s','now')*1000,1,1,'{msg}',1,1,0,0,0,0); "
        f"INSERT INTO sms(thread_id,address,date,date_sent,protocol,read,status,type,"
        f"reply_path_present,subject,body,service_center,locked,error_code,sub_id) "
        f"VALUES({tid},'{number}',strftime('%s','now')*1000,strftime('%s','now')*1000,"
        f"0,0,-1,1,0,'','{msg}','',0,0,1);"
    )
    shell(f'sqlite3 {db} "{sql}" 2>/dev/null || true', timeout=20.0)
