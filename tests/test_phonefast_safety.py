"""P0-7 回归：phonefast 多设备三层防线（CLAUDE.md 硬性规范）。

背景：重构把 glob 放宽为 /tmp/phonefast-{uid}*.sock（前缀碰撞其他 uid：
501 匹配 5012 的 socket），daemon 启动不传 --serial，_ping 不校验 serial——
绑定真机的旧 daemon 会被静默复用，评测可能打到错手机。

防线契约（fastaget/device/phonefast.py）：
  L2   _ensure_daemon 始终 `phonefast daemon --serial <s>` 启动
  附加 _ping 校验 daemon 已绑定设备——serial 不匹配 → 拒绝复用
  附赠 socket 路径精确构造（无 glob 前缀碰撞）
"""
from __future__ import annotations

import os

import pytest

from fastaget.device import phonefast as pf_mod
from fastaget.device.phonefast import Phonefast, PhonefastError

_SERIAL = "emulator-5554"
_FOREIGN = "13709314CF044927"  # 真机


def _sock(serial: str | None = None) -> str:
    uid = os.getuid()
    return f"/tmp/phonefast-{uid}-{serial}.sock" if serial else f"/tmp/phonefast-{uid}.sock"


@pytest.fixture
def no_real_sockets(monkeypatch):
    """屏蔽机器上真实存在的 socket 文件——测试不依赖环境状态。"""
    monkeypatch.setattr(os.path, "exists", lambda p: False)


# ---- socket 发现：精确构造，无前缀碰撞 ----

def test_find_sockets_no_uid_prefix_collision(monkeypatch):
    """uid=501 时不得匹配 phonefast-5012-*.sock（其他用户的 daemon）。"""
    evil = f"/tmp/phonefast-{os.getuid()}2-{_FOREIGN}.sock"
    foreign_serial_sock = _sock(_FOREIGN)
    monkeypatch.setattr(os.path, "exists", lambda p: p in (evil, foreign_serial_sock))

    pf = Phonefast(serial=_SERIAL)
    found = pf._find_sockets()
    assert evil not in found, "uid 前缀碰撞的 socket 不得入选"
    assert foreign_serial_sock not in found, "其他 serial 的 socket 不得入选"


def test_find_sockets_prefers_serial_bound(monkeypatch):
    """serial 专属 socket 与 generic 并存时，serial 专属优先。"""
    monkeypatch.setattr(os.path, "exists", lambda p: p in (_sock(), _sock(_SERIAL)))
    pf = Phonefast(serial=_SERIAL)
    found = pf._find_sockets()
    assert found[0] == _sock(_SERIAL)


# ---- _ping：serial 校验（附加层）----

def test_ping_rejects_daemon_bound_to_other_device(monkeypatch, no_real_sockets):
    """daemon status 报告的设备与目标 serial 不符 → 拒绝复用（防静默打错手机）。"""
    pf = Phonefast(serial=_SERIAL)
    monkeypatch.setattr(pf, "_call_raw",
                        lambda path, method, params: {"devices": [_FOREIGN]})
    assert pf._ping(_sock()) is False


def test_ping_accepts_matching_device(monkeypatch, no_real_sockets):
    pf = Phonefast(serial=_SERIAL)
    monkeypatch.setattr(pf, "_call_raw",
                        lambda path, method, params: {"devices": [_SERIAL]})
    assert pf._ping(_sock()) is True


def test_ping_accepts_empty_devices(monkeypatch, no_real_sockets):
    """daemon 刚启动尚未连接设备（devices=[]）→ 接受，RPC 时按 device 参数路由。"""
    pf = Phonefast(serial=_SERIAL)
    monkeypatch.setattr(pf, "_call_raw", lambda path, method, params: {"devices": []})
    assert pf._ping(_sock()) is True


# ---- _ensure_daemon：L2 启动防线 ----

def test_ensure_daemon_starts_with_serial_flag(monkeypatch, no_real_sockets):
    """daemon 启动命令必须带 --serial <s>（不靠 daemon 默认选设备）。"""
    started: dict = {}
    serial_sock = _sock(_SERIAL)

    def fake_popen(cmd, **kwargs):
        started["cmd"] = cmd
        # daemon 启动后 socket 出现
        monkeypatch.setattr(os.path, "exists", lambda p: p == serial_sock)
        class _Proc:
            pass
        return _Proc()

    monkeypatch.setattr(pf_mod.subprocess, "Popen", fake_popen)
    pf = Phonefast(serial=_SERIAL)
    monkeypatch.setattr(pf, "_call_raw",
                        lambda path, method, params: {"devices": [_SERIAL]})

    path = pf._ensure_daemon()
    assert path == serial_sock
    assert started["cmd"][:2] == [os.environ.get("PHONEFAST_BINARY", "phonefast"), "daemon"]
    assert "--serial" in started["cmd"]
    assert _SERIAL in started["cmd"]


def test_ensure_daemon_reuses_matching_socket(monkeypatch):
    """已有匹配 daemon 时不重启——直接复用 serial 专属 socket。"""
    monkeypatch.setattr(os.path, "exists", lambda p: p == _sock(_SERIAL))
    pf = Phonefast(serial=_SERIAL)
    monkeypatch.setattr(pf, "_call_raw",
                        lambda path, method, params: {"devices": [_SERIAL]})

    def boom_popen(cmd, **kwargs):
        raise AssertionError("不应重启 daemon")

    monkeypatch.setattr(pf_mod.subprocess, "Popen", boom_popen)
    assert pf._ensure_daemon() == _sock(_SERIAL)


def test_ensure_daemon_foreign_daemon_raises_actionable_error(monkeypatch):
    """外来 daemon（绑定真机）占坑且拒绝退出 → 报错信息必须指出 serial 冲突。"""
    monkeypatch.setattr(os.path, "exists", lambda p: p == _sock())
    monkeypatch.setattr(Phonefast, "_DAEMON_START_TIMEOUT", 0.4)
    monkeypatch.setattr(Phonefast, "_DAEMON_POLL_INTERVAL", 0.1)

    pf = Phonefast(serial=_SERIAL)
    monkeypatch.setattr(pf, "_call_raw",
                        lambda path, method, params: {"devices": [_FOREIGN]})
    monkeypatch.setattr(pf_mod.subprocess, "Popen",
                        lambda cmd, **kw: type("_P", (), {})())

    with pytest.raises(PhonefastError, match="serial|绑定|不匹配"):
        pf._ensure_daemon()


# ---- serial 公共访问口（脚本层复用解析结果，不重复 adb 探测逻辑）----

def test_serial_property_returns_explicit():
    """显式传入的 serial 直接返回，不触发 adb 探测。"""
    assert Phonefast(serial=_SERIAL).serial == _SERIAL


def test_serial_property_resolves_single_device(monkeypatch):
    """未传 serial 时按 L1 规则解析（单设备自动选用）。"""
    class _Proc:
        stdout = "List of devices attached\nemulator-5554\tdevice\n"

    monkeypatch.setattr(pf_mod.subprocess, "run", lambda *a, **k: _Proc())
    assert Phonefast().serial == "emulator-5554"


def test_serial_property_refuses_multi_real_devices(monkeypatch):
    """多真机在线 → 拒绝猜测（L1）。"""
    class _Proc:
        stdout = ("List of devices attached\n"
                  "RF8R123\tdevice\n13709314CF044927\tdevice\n")

    monkeypatch.setattr(pf_mod.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(PhonefastError, match="--serial"):
        _ = Phonefast().serial
