"""Phonefast.observe 自愈测试——UI 服务失联（socket 死亡）时的 daemon 重启重试。

背景：长评测中 daemon UI 子进程/视频流会失联（observe 报 connection refused /
no device connected / EOF），主进程却仍存活。observe() 需按 _HEAL_MIN_INTERVAL
限频重启 daemon 并重试一次——否则 ScreenObserver/ctx.observe 拿到的全是空屏，
agent 盲跑，UI 类 case 集体失败（SimpleCalendar 8/8、full_0814 两连败均此根因）。
"""
from __future__ import annotations

import pytest

from fastaget.device import phonefast as pf_mod
from fastaget.device.phonefast import Phonefast, PhonefastError, ObserveResult


@pytest.fixture
def pf() -> Phonefast:
    return Phonefast(serial="emulator-5554")


def _fake_observe(failures: list[Exception]):
    """构造 _observe_once 假实现：前 len(failures) 次抛对应异常，之后成功。"""
    def fake(self, *args, **kwargs):
        if failures:
            raise failures.pop(0)
        return ObserveResult(elements_text="ok-elements", image_b64=None)
    return fake


def test_observe_heals_on_first_failure(monkeypatch, pf):
    """首败 → 重启 daemon → 重试成功。"""
    monkeypatch.setattr(pf, "_observe_once", _fake_observe([PhonefastError("ui socket refused")]))
    restarts: list[int] = []
    monkeypatch.setattr(pf, "restart_daemon", lambda: restarts.append(1))

    result = pf.observe()

    assert result.elements_text == "ok-elements"
    assert len(restarts) == 1  # 恰好重启一次


def test_observe_second_failure_in_window_raises_without_restart(monkeypatch, pf):
    """窗口内二次失败：直接抛错，不重复重启（rate-limit）。"""
    # 两个异常：首次调用 + 重启后的重试都失败 → observe 抛错
    monkeypatch.setattr(pf, "_observe_once",
                        _fake_observe([PhonefastError("dead"), PhonefastError("dead")]))
    restarts: list[int] = []
    monkeypatch.setattr(pf, "restart_daemon", lambda: restarts.append(1))

    # 第一次：触发重启，重试仍失败 → 抛错，时间戳已更新
    with pytest.raises(PhonefastError):
        pf.observe()
    assert len(restarts) == 1

    # 第二次（窗口内）：直接抛错，不再重启
    monkeypatch.setattr(pf, "_observe_once", _fake_observe([PhonefastError("dead")]))
    with pytest.raises(PhonefastError):
        pf.observe()
    assert len(restarts) == 1


def test_observe_heals_again_after_window(monkeypatch, pf):
    """间隔超过 _HEAL_MIN_INTERVAL 后，失败可再次触发重启。"""
    fake_clock = {"now": 1000.0}
    monkeypatch.setattr(pf_mod.time, "monotonic", lambda: fake_clock["now"])
    monkeypatch.setattr(pf, "_observe_once",
                        _fake_observe([PhonefastError("dead"), PhonefastError("dead")]))
    restarts: list[int] = []
    monkeypatch.setattr(pf, "restart_daemon", lambda: restarts.append(1))

    with pytest.raises(PhonefastError):
        pf.observe()  # t=1000：重启一次
    assert len(restarts) == 1

    fake_clock["now"] += pf._HEAL_MIN_INTERVAL + 1.0
    monkeypatch.setattr(pf, "_observe_once",
                        _fake_observe([PhonefastError("dead"), PhonefastError("dead")]))
    with pytest.raises(PhonefastError):
        pf.observe()  # 窗口外：再次重启
    assert len(restarts) == 2


def test_observe_retries_even_when_restart_fails(monkeypatch, pf):
    """restart_daemon 抛错不阻塞——仍执行最后一次 observe 重试。"""
    monkeypatch.setattr(pf, "_observe_once", _fake_observe([PhonefastError("dead")]))
    monkeypatch.setattr(pf, "restart_daemon", lambda: (_ for _ in ()).throw(
        PhonefastError("daemon restart failed")))

    result = pf.observe()  # 重试成功

    assert result.elements_text == "ok-elements"


def test_observe_success_never_restarts(monkeypatch, pf):
    """成功路径零开销：不调用 restart_daemon。"""
    monkeypatch.setattr(pf, "_observe_once", _fake_observe([]))
    restarts: list[int] = []
    monkeypatch.setattr(pf, "restart_daemon", lambda: restarts.append(1))

    result = pf.observe()

    assert result.elements_text == "ok-elements"
    assert restarts == []


def test_restart_daemon_resets_cached_socket(monkeypatch, pf):
    """重启必须清 _socket_path/_warmed——否则重试连到已失效的旧 socket，自愈白做。"""
    pf._socket_path = "/tmp/stale.sock"
    pf._warmed = True
    monkeypatch.setattr(pf_mod.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(pf, "_find_sockets", lambda: [])
    ensured: list[str] = []
    monkeypatch.setattr(pf, "_ensure_daemon", lambda: ensured.append("fresh") or "/tmp/fresh.sock")

    path = pf.restart_daemon()

    assert path == "/tmp/fresh.sock"
    assert pf._socket_path is None, "旧 socket 缓存必须清除"
    assert pf._warmed is False, "warm 标记必须重置，触发下次 _call 重新发现 daemon"
    assert ensured == ["fresh"]
