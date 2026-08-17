"""scenarios: Scenario 数据结构 + YAML 加载 + 字段推导 + GT 解析。

职责：声明式场景定义加载（scenarios.yml）、场景名→行为字段推导、GT bounds 解析。
不含判定逻辑（那是 outcomes 的职责），不含 MockPhonefast（那是 device 的职责）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from fastaget.scenariokit.device import Screen, TapZone, _auto_derive_zones
from fastaget.scenariokit.variants import make_variants
from fastaget.scenariokit.xmltext import xml_to_phonefast_text

_FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"
WD4_XML = _FIXTURES_DIR / "wd4.xml"
SCENARIOS_YML = Path(__file__).resolve().parent.parent / "meta" / "scenarios.yml"


@dataclass
class Scenario:
    """一个测试场景：目标 + 目标元素 + 成功判定。"""
    name: str
    goal: str
    kind: str  # "switch" | "navigate" | "back" | "self_heal" | ...
    target_desc: str = ""
    label_text: str = ""
    target_text: str = ""
    gt_bounds: tuple[int, int, int, int] = (0, 0, 0, 0)
    check: str = "tap_in_gt"
    expected_action: str = ""
    expected_actions: list[str] = field(default_factory=list)
    forbidden_screens: list[str] = field(default_factory=list)
    target_screen: str = ""
    gt_screen: str = ""
    start_screen: str = "settings_home"
    expect: dict[str, dict[str, Any]] = field(default_factory=dict)


def _find_node_by_desc(nodes: list[dict], desc_contains: str) -> dict | None:
    for n in nodes:
        if desc_contains in n["desc"]:
            return n
    return None


def _find_node_by_text(nodes: list[dict], text: str) -> dict | None:
    for n in nodes:
        if n["text"] == text:
            return n
    return None


def _find_clickable_ancestor(nodes: list[dict], target: dict) -> dict | None:
    """找 target 的最近 clickable 祖先（bounds 包含 target 且 clickable）。"""
    tx1, ty1, tx2, ty2 = target["bounds"]
    for n in nodes:
        if n is target or not n["clickable"]:
            continue
        nx1, ny1, nx2, ny2 = n["bounds"]
        if nx1 <= tx1 and ny1 <= ty1 and nx2 >= tx2 and ny2 >= ty2:
            if n["bounds"] != target["bounds"]:
                return n
    return None


def _point_in_bounds(x: int, y: int, bounds: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = bounds
    return x1 <= x <= x2 and y1 <= y <= y2


def _build_scenarios(nodes: list[dict]) -> list[Scenario]:
    """基于 wd4.xml 的 meaningful 节点构建场景。"""
    scenarios: list[Scenario] = []
    bt_switch = _find_node_by_desc(nodes, "蓝牙开关")
    if bt_switch:
        scenarios.append(Scenario(
            name="toggle_bluetooth", goal="关闭蓝牙开关", kind="switch",
            target_desc="蓝牙开关", label_text="蓝牙",
            gt_bounds=bt_switch["bounds"], check="tap_in_gt",
        ))
    loc_switch = _find_node_by_desc(nodes, "位置信息开关")
    if loc_switch:
        scenarios.append(Scenario(
            name="toggle_location", goal="关闭位置信息开关", kind="switch",
            target_desc="位置信息开关", label_text="位置信息",
            gt_bounds=loc_switch["bounds"], check="tap_in_gt",
        ))
    bt_label = _find_node_by_text(nodes, "电池")
    if bt_label:
        ancestor = _find_clickable_ancestor(nodes, bt_label) or bt_label
        scenarios.append(Scenario(
            name="go_to_battery", goal="进入电池设置页面", kind="navigate",
            target_text="电池", gt_bounds=ancestor["bounds"], check="tap_in_gt",
        ))
    about_label = _find_node_by_text(nodes, "关于手机")
    if about_label:
        ancestor = _find_clickable_ancestor(nodes, about_label) or about_label
        scenarios.append(Scenario(
            name="go_to_about", goal="查看关于手机信息", kind="navigate",
            target_text="关于手机", gt_bounds=ancestor["bounds"], check="tap_in_gt",
        ))
    scenarios.append(Scenario(
        name="go_back", goal="返回上一页", kind="back",
        gt_bounds=(0, 0, 0, 0), check="action_match", expected_action="back",
    ))
    if bt_switch:
        scenarios.append(Scenario(
            name="self_heal_bluetooth", goal="关闭蓝牙开关", kind="self_heal",
            target_desc="蓝牙开关", gt_bounds=bt_switch["bounds"], check="tap_in_gt",
        ))
    return scenarios


def _resolve_gt_bounds(scenario: Scenario, nodes: list[dict]) -> tuple[int, int, int, int] | None:
    """从变体的 nodes 动态解析 GT bounds（适配 scrolled 等变体坐标偏移）。

    返回 None 表示目标元素在该变体中不存在。
    """
    if scenario.kind in ("switch", "self_heal", "recover", "verify_state"):
        n = _find_node_by_desc(nodes, scenario.target_desc)
        return n["bounds"] if n else None
    if scenario.kind == "navigate":
        n = _find_node_by_text(nodes, scenario.target_text)
        if n is None:
            return None
        ancestor = _find_clickable_ancestor(nodes, n) or n
        return ancestor["bounds"]
    return scenario.gt_bounds  # back 等无 GT 需求


# 场景名 → 行为字段映射（兼容 PromptAwareScriptedLLM）
_DERIVE_MAP: dict[str, dict] = {
    "toggle_bluetooth": {"kind": "switch", "target_desc": "蓝牙开关",
                         "label_text": "蓝牙", "check": "tap_in_gt"},
    "toggle_location": {"kind": "switch", "target_desc": "位置信息开关",
                        "label_text": "位置信息", "check": "tap_in_gt"},
    "go_to_battery": {"kind": "navigate", "target_text": "电池", "check": "tap_in_gt"},
    "go_back": {"kind": "back", "check": "action_match", "expected_action": "back"},
    "self_heal_bluetooth": {"kind": "self_heal", "target_desc": "蓝牙开关", "check": "tap_in_gt"},
    "frozen_loading": {"kind": "unresponsive", "check": "expect_fail"},
    "empty_screen": {"kind": "unresponsive", "check": "expect_fail"},
    "verify_bluetooth_off": {"kind": "verify_state", "target_desc": "蓝牙开关",
                             "check": "no_change_success", "forbidden_screens": ["bt_on"]},
    "search_setting": {"kind": "input_flow", "target_text": "搜索设置",
                       "check": "action_all", "expected_actions": ["type", "key(enter)"],
                       "target_screen": "search_results"},
    "recover_from_detail": {"kind": "recover", "target_desc": "蓝牙开关",
                            "check": "tap_in_gt", "gt_screen": "settings_home"},
    "scroll_to_find": {"kind": "navigate", "target_text": "关于手机", "check": "tap_in_gt"},
    "max_steps_exhaustion": {"kind": "exhaustion", "check": "expect_fail"},
    "tool_chain_failure": {"kind": "tool_failure", "target_desc": "蓝牙开关", "check": "expect_fail"},
}


def _derive_scenario_fields(s: Scenario) -> Scenario:
    """从 YAML 场景名自动推导行为字段。已显式声明 kind 的不推导。"""
    if s.kind:
        return s
    fields = _DERIVE_MAP.get(s.name, {})
    if not fields:
        return s
    s.kind = fields.get("kind", s.kind)
    s.target_desc = fields.get("target_desc", s.target_desc)
    s.label_text = fields.get("label_text", s.label_text)
    s.target_text = fields.get("target_text", s.target_text)
    s.check = fields.get("check", s.check)
    s.expected_action = fields.get("expected_action", s.expected_action)
    s.expected_actions = fields.get("expected_actions", s.expected_actions)
    s.forbidden_screens = fields.get("forbidden_screens", s.forbidden_screens)
    if "target_screen" in fields:
        s.target_screen = fields["target_screen"]
    if "gt_screen" in fields:
        s.gt_screen = fields["gt_screen"]
    return s


def _build_screen_from_def(
    sdef: dict[str, Any],
    base_xml: str,
    variants_xml: dict[str, str],
) -> Screen:
    """从 YAML 屏幕定义构建 Screen 对象。"""
    if "source" in sdef:
        variant = sdef.get("variant", "baseline")
        xml_str = variants_xml.get(variant, base_xml)
        text = xml_to_phonefast_text(xml_str)
    else:
        text = sdef["text"]

    zones: list[TapZone] = []
    for zdef in sdef.get("zones", []):
        zones.append(TapZone(
            bounds=tuple(zdef["bounds"]),
            response=zdef["response"],
            next_screen=zdef.get("next"),
            label=zdef.get("label", ""),
        ))
    back_to = sdef.get("back_to") or sdef.get("back_screen")
    transitions = sdef.get("transitions", {})
    key_transitions = sdef.get("key_transitions", {})
    return Screen(key="", text=text, zones=zones, back_to=back_to,
                  transitions=transitions, key_transitions=key_transitions)


def load_device_graph(
    base_xml: str | None = None,
    variants_xml: dict[str, str] | None = None,
) -> tuple[dict[str, Screen], list[Scenario], dict[str, Any]]:
    """从 meta/scenarios.yml 加载设备屏幕图 + 场景定义。

    返回 (screens, scenarios, raw_yaml)。
    """
    if base_xml is None:
        base_xml = WD4_XML.read_text(encoding="utf-8")
    if variants_xml is None:
        variants_xml = make_variants(base_xml)

    raw = yaml.safe_load(SCENARIOS_YML.read_text(encoding="utf-8"))

    screens: dict[str, Screen] = {}
    for key, sdef in raw.get("screens", {}).items():
        screen = _build_screen_from_def(sdef, base_xml, variants_xml)
        screen.key = key
        screens[key] = screen

    scenarios: list[Scenario] = []
    for sdef in raw.get("scenarios", []):
        start_key = sdef.get("start") or sdef.get("start_screen", "settings_home")
        raw_expect = sdef.get("expect", {})
        if isinstance(raw_expect, str):
            expect_dict = {"_": {"success": True, "reason": raw_expect}}
        else:
            expect_dict = raw_expect

        sc = Scenario(
            name=sdef["name"], goal=sdef["goal"],
            kind=sdef.get("kind", ""),
            target_desc=sdef.get("target_desc", ""),
            label_text=sdef.get("label_text", ""),
            target_text=sdef.get("target_text", ""),
            gt_bounds=(0, 0, 0, 0),
            check=sdef.get("check", ""),
            expected_action=sdef.get("expected_action", ""),
        )
        sc.start_screen = start_key
        sc.expect = expect_dict
        sc = _derive_scenario_fields(sc)
        scenarios.append(sc)

    # 后处理：为无显式 transitions 的屏幕自动推导 transitions
    for key, screen in screens.items():
        if screen.transitions:
            continue
        _back_dest = screen.back_to or ""
        if screen.back_to:
            screen.transitions["返回"] = screen.back_to
        _SKIP_SUFFIXES = ("_on", "_already_off", "_focus", "_results", "_scrolled")
        child_items = [
            (ck, cs) for ck, cs in screens.items()
            if cs.back_to == key and ck != key
            and not any(ck.endswith(suf) for suf in _SKIP_SUFFIXES)
        ]
        child_items.sort(key=lambda x: (x[0].endswith("_off"), x[0]))
        derived: dict[str, str] = {}
        for child_key, child_screen in child_items:
            child_text = child_screen.text
            for line in child_text.splitlines():
                m_desc = re.search(r'desc="([^"]+)"', line)
                m_text = re.search(r'text="([^"]+)"', line)
                if m_desc and m_desc.group(1) not in derived:
                    derived[m_desc.group(1)] = child_key
                if m_text and m_text.group(1) not in derived and m_text.group(1) != "返回":
                    derived[m_text.group(1)] = child_key
        screen.transitions.update(derived)
        if _back_dest:
            screen.transitions["返回"] = _back_dest

    # 文字标签重分配：_detail/_off 配对时，文本标签映射到 _detail（fail）
    for key, screen in screens.items():
        off_children = {ck for ck in screens if screens[ck].back_to == key and ck.endswith("_off") and ck != key}
        for off_key in off_children:
            prefix = off_key[:-4]
            detail_key = f"{prefix}_detail"
            if detail_key not in screens or screens[detail_key].back_to != key:
                continue
            off_text = screens[off_key].text
            for line in off_text.splitlines():
                m_text = re.search(r'text="([^"]+)"', line)
                if not m_text:
                    continue
                t = m_text.group(1)
                if screen.transitions.get(t) == off_key:
                    screen.transitions[t] = detail_key

    # 触发 zone 推导
    for screen in screens.values():
        if not screen.zones and screen.transitions:
            screen.zones = _auto_derive_zones(screen.text, screen.transitions)

    return screens, scenarios, raw
