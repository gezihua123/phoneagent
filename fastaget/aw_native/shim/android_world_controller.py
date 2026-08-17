"""AndroidWorldController 的 phonefast 实现。

task 代码经 env.controller 用到的方法（统计自 vendored AW 代码）：
- pull_file / push_file —— DB 拉取/推送（sqlite_utils 用）
- click_element(text)  —— app 引导页点击（apps.py/contacts_utils 用）
- send_sms(number, message) —— SMS 预置消息（sms.py 用）
- get_ui_elements() —— UI 元素（actuation.find_and_click_element 间接用）

实现约定：设备访问全部走 pf（shell/tap/observe），零 adb 直调。
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import tempfile
import time
from typing import Iterator, Optional

from fastaget.aw_native.shim import adb_utils
from fastaget.aw_native.shim import interface as shim_interface
from fastaget.aw_native.vendor.env import representation_utils

logger = logging.getLogger(__name__)

_A11Y_TIMEOUT = 5.0  # 引导页元素等待轮询（秒）


class AndroidWorldController:
    """phonefast 后端的 AW controller。"""

    def __init__(self, pf):
        self._pf = pf

    @property
    def env(self):
        # AW 代码里有 controller.env 反向引用（返回 AsyncEnv）——shim 里提供自身即可
        return self

    # ── shell 直通 ──

    def execute_adb_call(self, *args, **kwargs):
        return shim_interface.execute_adb_call(*args, **kwargs)

    def shell(self, cmd: str, timeout: float = 15.0) -> str:
        return shim_interface.shell(cmd, timeout)

    # ── 文件 ──

    @contextlib.contextmanager
    def pull_file(self, remote_db_file_path: str, timeout_sec: Optional[float] = None) -> Iterator[str]:
        """把设备文件拉到临时目录（context manager，退出即删）——对齐 AW 原语义。"""
        remote_dir = os.path.dirname(remote_db_file_path)
        file_name = os.path.basename(remote_db_file_path)
        # sqlite WAL 适配：pull 前强制 checkpoint，把 -wal 未合并数据并入主
        # 文件（adb pull 只拿主文件，AW 原版靠 close_app 触发 checkpoint）
        shim_interface.shell(
            f'sqlite3 "{remote_db_file_path}" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true',
            timeout=timeout_sec or 30.0,
        )
        tmp_dir = shim_interface.shell("mktemp -d /sdcard/aw_pull.XXXX 2>/dev/null || echo /sdcard/aw_pull").strip()
        # mktemp 在 Android toybox 存在；否则退回固定目录
        if not tmp_dir.startswith("/"):
            tmp_dir = f"/sdcard/aw_pull_{int(time.time())}"
        try:
            ok = shim_interface.shell(
                f'mkdir -p "{tmp_dir}" && cp "{remote_db_file_path}" "{tmp_dir}/{file_name}" 2>/dev/null && echo OK',
                timeout=timeout_sec or 60.0,
            )
            if "OK" not in ok:
                raise FileNotFoundError(f"pull 失败: {remote_db_file_path}")
            from fastaget.aw_native.shim import interface as iface

            content = iface._read_device_file(f"{tmp_dir}/{file_name}")
            local_tmp = tempfile.mkdtemp(prefix="aw_pull_")
            with open(os.path.join(local_tmp, file_name), "wb") as f:
                f.write(content)
            yield local_tmp
        finally:
            shim_interface.shell(f'rm -rf "{tmp_dir}" 2>/dev/null')
            try:
                if "local_tmp" in dir():
                    import shutil as _sh
                    _sh.rmtree(local_tmp, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

    def push_file(
        self,
        local_db_file_path: str,
        remote_db_file_path: str,
        timeout_sec: Optional[float] = None,
    ) -> None:
        """把本地文件推到设备（原子替换：先写临时文件再 mv，
        写入失败不破坏设备上原文件——AW 原语义是直接覆盖）。"""
        from fastaget.aw_native.shim import interface as iface

        remote_dir = os.path.dirname(remote_db_file_path)
        shim_interface.shell(f'mkdir -p "{remote_dir}" 2>/dev/null')
        with open(local_db_file_path, "rb") as f:
            content = f.read()
        tmp_path = f"{remote_db_file_path}.fastaget_tmp"
        shim_interface.shell(f'rm -f "{tmp_path}" 2>/dev/null')
        if not iface._write_device_file(tmp_path, content):
            logger.warning("push_file 写入失败（原文件保留）: %s", remote_db_file_path)
            return
        # 清旧 wal/shm（旧 DB 日志会覆盖新数据）
        shim_interface.shell(
            f'rm -f "{remote_db_file_path}-wal" "{remote_db_file_path}-shm" 2>/dev/null'
        )
        # 截断写回原文件（保持 inode——app 打开的文件描述符能看到新内容；
        # mv 替换 inode 会被 app 后续 checkpoint 用旧 inode 覆盖丢失），
        # 并把属主恢复为 app 数据目录 owner（root shell 写入会变成 root 所有，
        # Room app 打不开 root 属主的 DB → 建库失败）
        ok = shim_interface.shell(
            f'cat "{tmp_path}" > "{remote_db_file_path}" 2>/dev/null && '
            f'rm -f "{tmp_path}" && '
            f'chown $(stat -c %u "{remote_dir}") "{remote_db_file_path}" 2>/dev/null; '
            f'chmod 660 "{remote_db_file_path}" 2>/dev/null; echo OK',
            timeout=timeout_sec or 60.0,
        )
        if "OK" not in ok:
            logger.warning("push_file 写回失败: %s", remote_db_file_path)

    # ── UI ──

    def get_ui_elements(self) -> list:
        """observe(jsonl) 路径——uiautomator dump 在本模拟器上被杀（'Killed'），
        phonefast daemon 的 a11y 树通道稳定。返回 AW UIElement 列表。"""
        import json as _json

        from fastaget.aw_native.vendor.env.representation_utils import BoundingBox, UIElement

        try:
            r = self._pf.observe(format="jsonl")
            lines = (r.elements_text or "").strip().split("\n")
        except Exception as e:  # noqa: BLE001
            logger.warning("get_ui_elements observe 失败: %s", e)
            return []
        els = []
        for line in lines:
            try:
                d = _json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", d.get("bounds", "") or "")
            if not m:
                continue
            l, t, r_, b = (int(x) for x in m.groups())
            els.append(
                UIElement(
                    text=d.get("text") or None,
                    content_description=d.get("content_desc") or None,
                    class_name=d.get("class") or None,
                    bbox_pixels=BoundingBox(l, r_, t, b),
                    is_clickable=bool(d.get("clickable")),
                )
            )
        return els

    def click_element(self, element_text: str, case_sensitive: bool = False) -> bool:
        """按文本找元素并点击中心——app 引导页用。带轮询（UI 加载需要时间）。"""
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            elements = self.get_ui_elements()
            target = None
            needle = element_text if case_sensitive else element_text.lower()
            for el in elements:
                text = (el.text or "").strip()
                desc = (el.content_description or "").strip()
                if (text if case_sensitive else text.lower()) == needle or (
                    desc if case_sensitive else desc.lower()
                ) == needle:
                    target = el
                    break
            if target is not None and target.bbox_pixels is not None:
                bb = target.bbox_pixels  # BoundingBox(x_min, x_max, y_min, y_max)
                cx, cy = (bb.x_min + bb.x_max) // 2, (bb.y_min + bb.y_max) // 2
                try:
                    self._pf.tap(cx, cy)
                    return True
                except Exception as e:  # noqa: BLE001
                    logger.warning("click_element tap 失败: %s", e)
                    return False
            time.sleep(1.5)
        logger.warning("click_element 超时未找到: %s", element_text)
        return False

    # ── 其它 ──

    def send_sms(self, number: str, message: str) -> None:
        """向设备发短信（对齐 AW tools.AndroidToolController.send_sms——emu 通道 shim）。"""
        shim_interface._emu_sms_send(number, message)

    def get_current_activity(self) -> str:
        out = shim_interface.shell(
            "dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity' | head -1",
            timeout=15.0,
        )
        m = re.search(r"([\w.]+/[\w.]+)", out)
        return m.group(1) if m else ""
