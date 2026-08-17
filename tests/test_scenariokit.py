"""scenariokit 独立单测：验证各模块纯域逻辑，不依赖 fastaget agent。

覆盖：
  - xmltext: XML↔phonefast 文本转换 + 节点解析
  - variants: 变体生成
  - device: MockPhonefast 状态机 + 故障注入 + key_transitions
  - scenarios: YAML 加载 + 字段推导 + GT 解析
  - outcomes: 判定器注册表 + 各 checker
"""
from __future__ import annotations

import pytest

from fastaget.scenariokit import (
    MockPhonefast,
    Screen,
    Scenario,
    TapZone,
    WD4_XML,
    evaluate_scenario_outcome,
    load_device_graph,
    make_variants,
    parse_meaningful_nodes,
    parse_meaningful_nodes_from_text,
    xml_to_phonefast_text,
)


# ===========================================================================
# xmltext
# ===========================================================================


class TestXmlText:
    def test_xml_to_phonefast_text_has_header(self):
        xml = '''<?xml version="1.0"?>
        <node bounds="[0,0][1080,2400]">
          <node text="蓝牙" content-desc="蓝牙开关" clickable="true"
                class="android.widget.Switch" bounds="[900,368][1044,416]"/>
        </node>'''
        text = xml_to_phonefast_text(xml)
        assert "Interactive elements on screen:" in text
        assert "蓝牙" in text

    def test_parse_meaningful_nodes_index_alignment(self):
        """xml_to_phonefast_text 与 parse_meaningful_nodes 的 index 必须对齐。"""
        xml = WD4_XML.read_text(encoding="utf-8")
        nodes = parse_meaningful_nodes(xml)
        text = xml_to_phonefast_text(xml)
        # 节点数与文本中 [N] 数量一致
        import re
        idxs_in_text = re.findall(r"\[(\d+)\]", text.split("=" * 50)[1])
        assert len(nodes) == len(idxs_in_text)

    def test_parse_from_text_roundtrip(self):
        """phonefast 文本反向解析出 nodes。"""
        text = '[0] text="蓝牙" desc="蓝牙开关" (Switch) [clickable] bounds=[900,368][1044,416]'
        nodes = parse_meaningful_nodes_from_text(text)
        assert len(nodes) == 1
        assert nodes[0]["text"] == "蓝牙"
        assert nodes[0]["desc"] == "蓝牙开关"
        assert nodes[0]["clickable"] is True


# ===========================================================================
# variants
# ===========================================================================


class TestVariants:
    def test_make_variants_all_present(self):
        xml = WD4_XML.read_text(encoding="utf-8")
        v = make_variants(xml)
        for name in ("baseline", "bt_off", "loc_off", "scrolled", "truncated", "noisy"):
            assert name in v

    def test_bt_off_changes_checked(self):
        xml = WD4_XML.read_text(encoding="utf-8")
        v = make_variants(xml)
        assert 'checked="false"' in v["bt_off"]


# ===========================================================================
# device (MockPhonefast 状态机)
# ===========================================================================


class TestMockPhonefast:
    def test_static_mode_all_taps_noop(self):
        pf = MockPhonefast("test screen")
        pf.tap(100, 100)
        assert pf.current_screen_key == "_static"
        assert len(pf.taps) == 1

    def test_stateful_tap_transitions_screen(self):
        """状态机模式：tap 命中 zone → 屏幕转换。"""
        home = Screen(key="home", text="home screen",
                       zones=[TapZone(bounds=(0, 0, 100, 100), response="success", next_screen="next")])
        nxt = Screen(key="next", text="next screen")
        pf = MockPhonefast(screen=home, screens={"home": home, "next": nxt})
        pf.tap(50, 50)
        assert pf.current_screen_key == "next"

    def test_noop_zone_keeps_screen(self):
        home = Screen(key="home", text="home",
                       zones=[TapZone(bounds=(0, 0, 100, 100), response="noop")])
        pf = MockPhonefast(screen=home, screens={"home": home})
        pf.tap(50, 50)
        assert pf.current_screen_key == "home"

    def test_tap_fail_raises_phonefast_error(self):
        """故障注入：tap_fail=True 时 tap 抛异常（测工具链自愈）。"""
        from fastaget.device.phonefast import PhonefastError
        pf = MockPhonefast("test")
        pf.tap_fail = True
        with pytest.raises(PhonefastError):
            pf.tap(50, 50)

    def test_key_transitions_screen(self):
        """key_transitions：按 enter 转屏（输入流程）。"""
        focus = Screen(key="focus", text="input focused",
                       key_transitions={"enter": "results"})
        results = Screen(key="results", text="results")
        pf = MockPhonefast(screen=focus, screens={"focus": focus, "results": results})
        pf.key("enter")
        assert pf.current_screen_key == "results"

    def test_back_transitions_via_back_to(self):
        child = Screen(key="child", text="child", back_to="parent")
        parent = Screen(key="parent", text="parent")
        pf = MockPhonefast(screen=child, screens={"child": child, "parent": parent})
        pf.back()
        assert pf.current_screen_key == "parent"

    def test_screen_history_records_transitions(self):
        home = Screen(key="home", text="home",
                       zones=[TapZone(bounds=(0, 0, 100, 100), response="success", next_screen="nxt")])
        nxt = Screen(key="nxt", text="nxt")
        pf = MockPhonefast(screen=home, screens={"home": home, "nxt": nxt})
        pf.tap(50, 50)
        assert pf.screen_history == ["home", "nxt"]


# ===========================================================================
# scenarios (YAML 加载 + 字段推导)
# ===========================================================================


class TestScenarios:
    def test_load_device_graph_returns_all(self):
        xml = WD4_XML.read_text(encoding="utf-8")
        screens, scenarios, raw = load_device_graph(xml)
        assert len(screens) >= 10
        assert len(scenarios) >= 7
        assert "screens" in raw and "scenarios" in raw

    def test_derive_fields_for_known_scenarios(self):
        xml = WD4_XML.read_text(encoding="utf-8")
        _, scenarios, _ = load_device_graph(xml)
        by_name = {s.name: s for s in scenarios}
        assert by_name["toggle_bluetooth"].kind == "switch"
        assert by_name["toggle_bluetooth"].target_desc == "蓝牙开关"
        assert by_name["go_back"].check == "action_match"
        assert by_name["frozen_loading"].check == "expect_fail"
        assert by_name["search_setting"].check == "action_all"
        assert by_name["verify_bluetooth_off"].check == "no_change_success"

    def test_resolve_gt_bounds_switch(self):
        """GT bounds 从 nodes 动态解析。"""
        xml = WD4_XML.read_text(encoding="utf-8")
        _, scenarios, _ = load_device_graph(xml)
        sc = next(s for s in scenarios if s.name == "toggle_bluetooth")
        nodes = parse_meaningful_nodes(xml)
        from fastaget.scenariokit import _resolve_gt_bounds
        gt = _resolve_gt_bounds(sc, nodes)
        assert gt is not None
        assert gt[2] > gt[0]  # 非零面积


# ===========================================================================
# outcomes (判定器注册表)
# ===========================================================================


class TestOutcomes:
    def test_evaluate_tap_in_gt_hit(self):
        """tap 命中 GT = 成功（状态机模式）。"""
        from fastaget.scenariokit import TapRecord
        sc = Scenario(name="t", goal="g", kind="switch",
                      target_desc="蓝牙开关", check="tap_in_gt")
        nodes = [{"idx": 0, "text": "", "desc": "蓝牙开关",
                  "clickable": True, "bounds": (900, 368, 1044, 416)}]
        pf = MockPhonefast("test")
        pf.taps = [TapRecord(x=972, y=392, source="tap")]
        ok, reason = evaluate_scenario_outcome(sc, nodes, pf, None, screens={})
        assert ok
        assert "命中 GT" in reason

    def test_evaluate_expect_fail(self):
        """expect_fail：agent 主动 fail = 成功。"""
        from fastaget.agent.fast_agent import AgentResult
        sc = Scenario(name="t", goal="g", kind="unresponsive", check="expect_fail")
        pf = MockPhonefast("test")
        # agent fail
        result = AgentResult(session_id="test", success=False, summary="无法操作", steps=2,
                             total_cost_usd=0, steps_detail=[])
        ok, _ = evaluate_scenario_outcome(sc, [], pf, result)
        assert ok  # agent fail = 符合预期 = 成功
