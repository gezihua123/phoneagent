"""device: MockPhonefast 状态机模拟器 + Screen + TapZone。

职责：模拟 phonefast 设备，服务屏幕文本，记录操作，tap/key 命中 zone 时转换屏幕。
不含 YAML 加载（那是 scenarios 的职责）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastaget.device.phonefast import ObserveResult

from fastaget.scenariokit.xmltext import parse_meaningful_nodes_from_text


@dataclass
class TapRecord:
    """一次 tap 的记录，用于成功率判定。"""
    x: int
    y: int
    source: str  # "tap" | "tap_element"


@dataclass
class TapZone:
    """屏幕上的一个可交互区域，定义 tap 后的设备响应。

    response 类型:
      - "success": tap 命中正确交互区域，屏幕转换到 next_screen
      - "fail":    tap 命中错误区域，屏幕转换到 next_screen（错误页）
      - "noop":    tap 命中无响应区域，屏幕不变
    """
    bounds: tuple[int, int, int, int]
    response: str  # "success" | "fail" | "noop"
    next_screen: str | None = None
    label: str = ""


@dataclass
class Screen:
    """一个屏幕状态：phonefast observe 文本 + tap zones。

    zones 可手写，也可从 text + transitions 自动推导（_auto_derive_zones）。
    back_to: 调 back 工具后屏幕转换到的目标。
    transitions: 元素→目标屏幕映射，用于自动推导 zone。
    key_transitions: 按键→目标屏幕映射（输入流程：type 后按 enter → 结果页）。
    """
    key: str
    text: str
    zones: list[TapZone] = field(default_factory=list)
    back_to: str | None = None
    transitions: dict[str, str] = field(default_factory=dict)
    key_transitions: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """若未手写 zones，从 text 自动推导。"""
        if not self.zones and self.transitions:
            self.zones = _auto_derive_zones(self.text, self.transitions)

    @property
    def back_screen(self):
        """向后兼容：back_to 的别名。"""
        return self.back_to


def _auto_derive_zones(
    screen_text: str,
    transitions: dict[str, str],
) -> list[TapZone]:
    """从屏幕文本自动推导 tap zone，无需手写 bounds。

    - transitions 的 key 匹配元素的 text 或 desc（部分匹配，长 key 优先）
    - 目标屏幕名含 "_off" → success（开关翻转）
    - 目标屏幕名含 "detail" → fail（点文字标签进详情页）
    - 其他 → success（正常导航）
    - 按 bounds 面积从小到大排序（子元素优先匹配）
    """
    nodes = parse_meaningful_nodes_from_text(screen_text)
    sorted_transitions = sorted(transitions.items(), key=lambda x: len(x[0]), reverse=True)
    zones: list[TapZone] = []
    for node in nodes:
        text = node.get("text", "")
        desc = node.get("desc", "")
        bounds = node.get("bounds")
        if not bounds:
            continue
        matched_target = None
        matched_key = None
        for tkey, ttarget in sorted_transitions:
            if tkey in text or tkey in desc:
                matched_target = ttarget
                matched_key = tkey
                break
        if matched_target is None:
            continue
        if "detail" in matched_target:
            response = "fail"
        else:
            response = "success"
        zones.append(TapZone(
            bounds=tuple(bounds),
            response=response,
            next_screen=matched_target,
            label=matched_key,
        ))
    zones.sort(key=lambda z: (z.bounds[2] - z.bounds[0]) * (z.bounds[3] - z.bounds[1]))
    return zones


class MockPhonefast:
    """模拟 phonefast 设备：服务屏幕文本，记录所有操作。

    两种模式:
      1. 静态模式: MockPhonefast(screen_text) — 单一固定屏幕，所有 tap 是 noop。
      2. 状态机模式: MockPhonefast(screen=Screen(...), screens={...}) —
         tap 命中 zone 时按 response 转换屏幕。

    故障注入：tap_fail=True 时 tap 抛 PhonefastError，测工具链自愈。
    """

    def __init__(
        self,
        screen_text: str | None = None,
        *,
        screen: Screen | None = None,
        screens: dict[str, Screen] | None = None,
    ) -> None:
        if screen is not None:
            self._screen: Screen = screen
            self._screens: dict[str, Screen] = screens or {screen.key: screen}
        elif screen_text is not None:
            self._screen = Screen(key="_static", text=screen_text)
            self._screens = {"_static": self._screen}
        else:
            raise ValueError("必须提供 screen_text 或 screen")

        self.taps: list[TapRecord] = []
        self.actions: list[str] = []
        self._installed: set[str] = set()
        self._current_pkg = ""
        self._current_activity = ""
        self._device_info: dict = {}
        self.tap_fail: bool = False
        self._screen_history: list[str] = [self._screen.key]

    @property
    def current_screen_key(self) -> str:
        return self._screen.key

    @property
    def screen_history(self) -> list[str]:
        return list(self._screen_history)

    def warmup(self) -> None:
        pass

    def status(self) -> dict:
        """返回 daemon 状态。默认空 dict（模拟模式无真实设备上下文）。"""
        return dict(self._device_info) if self._device_info else {}

    def set_device_info(self, network: str = "") -> None:
        """配置模拟设备信息（供 DeviceContext 采集测试用）。"""
        self._device_info = {}
        if network:
            self._device_info["network"] = network

    def observe(self, concise: bool = True, max_elements: int = 80) -> ObserveResult:
        return ObserveResult(elements_text=self._screen.text, image_b64=None)

    def _find_zone(self, x: int, y: int) -> TapZone | None:
        for zone in self._screen.zones:
            zx1, zy1, zx2, zy2 = zone.bounds
            if zx1 <= x <= zx2 and zy1 <= y <= zy2:
                return zone
        return None

    def tap(self, x: int, y: int) -> str:
        if self.tap_fail:
            from fastaget.device.phonefast import PhonefastError
            raise PhonefastError(f"tap({x},{y}) failed: device I/O error (注入故障)")
        self.taps.append(TapRecord(x=int(x), y=int(y), source="tap"))
        self.actions.append(f"tap({x},{y})")
        zone = self._find_zone(x, y)
        if zone is not None:
            if zone.response in ("success", "fail") and zone.next_screen:
                target = self._screens.get(zone.next_screen)
                if target is not None:
                    self._screen = target
                    self._screen_history.append(self._screen.key)
        return "ok"

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        self.actions.append(f"swipe({x1},{y1}->{x2},{y2})")
        return "ok"

    def type_text(self, text: str) -> str:
        self.actions.append(f"type({text})")
        return "ok"

    def back(self) -> str:
        self.actions.append("back")
        back_target = self._screen.back_to or self._screen.back_screen
        if back_target:
            target = self._screens.get(back_target)
            if target is not None:
                self._screen = target
                self._screen_history.append(self._screen.key)
        return "ok"

    def home(self) -> str:
        self.actions.append("home")
        return "ok"

    def key(self, name_or_keycode: str) -> str:
        self.actions.append(f"key({name_or_keycode})")
        target = self._screen.key_transitions.get(str(name_or_keycode).lower())
        if target:
            t = self._screens.get(target)
            if t is not None:
                self._screen = t
                self._screen_history.append(self._screen.key)
        return "ok"

    def launch(self, package: str) -> str:
        self.actions.append(f"launch({package})")
        self._current_pkg = package
        return "ok"

    def screenshot(self) -> str:
        return ""

    def is_package_installed(self, package: str) -> bool:
        return package in self._installed

    def current_activity(self) -> str:
        return self._current_activity

    def current_package(self) -> str:
        return self._current_pkg

    def set_installed(self, package: str, installed: bool = True) -> None:
        if installed:
            self._installed.add(package)
        else:
            self._installed.discard(package)


def make_stateful_phonefast(
    start_screen_key: str,
    screens: dict[str, Screen] | None = None,
    base_xml: str | None = None,
) -> MockPhonefast:
    """构建一个状态机模式的 MockPhonefast，从指定屏幕开始。

    若 screens 未提供，自动从 YAML 加载完整设备图。
    """
    if screens is None:
        from fastaget.scenariokit.scenarios import load_device_graph
        screens, _, _ = load_device_graph(base_xml)
    start = screens[start_screen_key]
    return MockPhonefast(screen=start, screens=screens)
