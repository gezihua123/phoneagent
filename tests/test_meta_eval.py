"""一类测试：meta 文件夹信息评测与准确率评价。

本文件聚焦于「数据层」验证:
  1. XML → phonefast observe 文本转换器正确性（TestXmlConverter）
  2. wd4.xml 变体生成器合法性（TestVariantGenerator）
  3. 场景定义的 ground-truth bounds 正确性（TestScenarios）
  4. YAML 声明式定义加载正确性（TestYamlDeviceGraph）

这些测试不启动 FastAgent 循环，只验证输入数据的转换、派生、解析是否正确。
FastAgent + 模拟手机的端到端测试见 tests/test_agent_sim.py。
"""
from __future__ import annotations

import pytest

from fastaget.device.uiprocessor import processor
from fastaget.device.uistate_phonefast import phonefast_parser

from fastaget.scenariokit import (
    SCENARIOS_YML,
    WD4_XML,
    _build_scenarios,
    _find_node_by_desc,
    _find_node_by_text,
    load_device_graph,
    make_variants,
    parse_meaningful_nodes,
    xml_to_phonefast_text,
)


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def wd4_base_xml() -> str:
    """读取 tests/fixtures/wd4.xml 原始内容。"""
    return WD4_XML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wd4_nodes(wd4_base_xml: str) -> list[dict]:
    """解析 wd4.xml 的 meaningful 节点列表。"""
    return parse_meaningful_nodes(wd4_base_xml)


@pytest.fixture(scope="module")
def wd4_variants(wd4_base_xml: str) -> dict[str, str]:
    """生成 wd4.xml 的所有变体。"""
    return make_variants(wd4_base_xml)


@pytest.fixture(scope="module")
def wd4_scenarios(wd4_nodes: list[dict]) -> list:
    """构建场景列表。"""
    return _build_scenarios(wd4_nodes)


# ---------------------------------------------------------------------------
# 基础转换器测试
# ---------------------------------------------------------------------------


class TestXmlConverter:
    """验证 XML → phonefast 文本转换器正确性。"""

    def test_xml_to_phonefast_text_has_header(self, wd4_base_xml: str):
        text = xml_to_phonefast_text(wd4_base_xml)
        assert "Interactive elements on screen:" in text
        assert "tap_element with index=N" in text

    def test_xml_to_phonefast_text_parseable_by_uistate(self, wd4_base_xml: str):
        """转换后的文本必须能被 UIState.parse 正确解析。"""
        text = xml_to_phonefast_text(wd4_base_xml)
        state = phonefast_parser.parse(text)
        assert len(state.elements) > 0
        # 第一个元素的 index 应为 0
        assert state.elements[0].index == 0

    def test_xml_to_phonefast_text_contains_bluetooth_switch(self, wd4_base_xml: str):
        text = xml_to_phonefast_text(wd4_base_xml)
        state = phonefast_parser.parse(text)
        switch = next(
            (e for e in state.elements if e.desc and "蓝牙开关" in e.desc), None
        )
        assert switch is not None, "蓝牙开关元素必须存在于转换结果中"
        assert switch.clickable is True
        assert switch.cls == "Switch"

    def test_xml_to_phonefast_text_clickable_preserved(self, wd4_base_xml: str):
        """clickable 属性必须被正确保留。"""
        text = xml_to_phonefast_text(wd4_base_xml)
        state = phonefast_parser.parse(text)
        clickable_count = sum(1 for e in state.elements if e.clickable)
        # wd4 有 ~20 个 clickable 元素（设置项容器 + 开关 + 返回/搜索）
        assert clickable_count >= 15, f"clickable 元素过少: {clickable_count}"

    def test_processor_processes_converted_text(self, wd4_base_xml: str):
        """UIProcessor 能完整加工转换后的文本。"""
        text = xml_to_phonefast_text(wd4_base_xml)
        ui, formatted = processor.process(text)
        assert len(ui.elements) > 0
        assert "[index]" not in formatted or "top" in formatted or "middle" in formatted
        # formatted 应包含蓝牙相关文字
        bt_elements = [e for e in ui.elements if e.desc and "蓝牙" in e.desc]
        assert len(bt_elements) >= 1


# ---------------------------------------------------------------------------
# 变体生成器测试
# ---------------------------------------------------------------------------


class TestVariantGenerator:
    """验证变体生成器生成合法的 XML。"""

    def test_variants_all_parseable(self, wd4_variants: dict[str, str]):
        for name, xml in wd4_variants.items():
            text = xml_to_phonefast_text(xml)
            state = phonefast_parser.parse(text)
            assert len(state.elements) > 0, f"变体 {name} 解析后无元素"

    def test_bt_off_variant_changes_checked(self, wd4_variants: dict[str, str]):
        """bt_off 变体中蓝牙开关 checked=false。"""
        nodes = parse_meaningful_nodes(wd4_variants["bt_off"])
        bt_switch = _find_node_by_desc(nodes, "蓝牙开关")
        assert bt_switch is not None
        assert bt_switch["checked"] is False

    def test_baseline_bluetooth_checked_true(self, wd4_nodes: list[dict]):
        """baseline 中蓝牙开关 checked=true。"""
        bt_switch = _find_node_by_desc(wd4_nodes, "蓝牙开关")
        assert bt_switch is not None
        assert bt_switch["checked"] is True

    def test_scrolled_variant_shifts_y(self, wd4_variants: dict[str, str]):
        """scrolled 变体 y 坐标整体下移。"""
        base_nodes = parse_meaningful_nodes(wd4_variants["baseline"])
        shifted_nodes = parse_meaningful_nodes(wd4_variants["scrolled"])
        # 同一个 desc 的元素 y 应差 200
        base_bt = _find_node_by_desc(base_nodes, "蓝牙开关")
        shifted_bt = _find_node_by_desc(shifted_nodes, "蓝牙开关")
        assert shifted_bt["bounds"][1] == base_bt["bounds"][1] + 200

    def test_truncated_variant_removes_target(self, wd4_variants: dict[str, str]):
        """truncated 变体不含「存储」。"""
        nodes = parse_meaningful_nodes(wd4_variants["truncated"])
        assert _find_node_by_text(nodes, "存储") is None

    def test_noisy_variant_has_more_nodes(self, wd4_variants: dict[str, str]):
        """noisy 变体比 baseline 多出噪声节点。"""
        base_count = len(parse_meaningful_nodes(wd4_variants["baseline"]))
        noisy_count = len(parse_meaningful_nodes(wd4_variants["noisy"]))
        assert noisy_count > base_count


# ---------------------------------------------------------------------------
# 场景定义测试
# ---------------------------------------------------------------------------


class TestScenarios:
    """验证场景的 ground-truth bounds 正确。"""

    def test_scenarios_built(self, wd4_scenarios: list):
        assert len(wd4_scenarios) >= 5

    def test_bluetooth_switch_gt_is_switch_element(self, wd4_scenarios: list):
        s = next(s for s in wd4_scenarios if s.name == "toggle_bluetooth")
        # GT bounds 应是 Switch 区域，不是文字标签区域
        assert s.gt_bounds == (900, 368, 1044, 416)

    def test_battery_gt_is_clickable_container(self, wd4_scenarios: list, wd4_nodes: list[dict]):
        s = next(s for s in wd4_scenarios if s.name == "go_to_battery")
        # GT 应是 clickable 容器，bounds 覆盖整个电池行
        x1, y1, x2, y2 = s.gt_bounds
        assert x1 == 0  # 容器从屏幕左边缘开始
        assert x2 == 1080
        assert y2 - y1 == 144  # 标准设置项高度

    def test_self_heal_scenario_exists(self, wd4_scenarios: list):
        s = next((s for s in wd4_scenarios if s.name == "self_heal_bluetooth"), None)
        assert s is not None
        assert s.kind == "self_heal"


# ---------------------------------------------------------------------------
# YAML 声明式定义加载测试
# ---------------------------------------------------------------------------


class TestYamlDeviceGraph:
    """验证 YAML 声明式定义能正确加载为设备屏幕图 + 场景。"""

    def test_yaml_file_exists(self):
        assert SCENARIOS_YML.exists(), f"YAML 定义文件不存在: {SCENARIOS_YML}"

    def test_load_device_graph_returns_screens(self, wd4_base_xml: str):
        screens, scenarios, raw = load_device_graph(wd4_base_xml)
        # 应有主设置页 + 详情页 + 结果页 + 加载页
        assert "settings_home" in screens
        assert "bt_off" in screens
        assert "bt_detail" in screens
        assert "loading" in screens
        assert "empty" in screens

    def test_settings_home_text_generated_from_xml(self, wd4_base_xml: str):
        """settings_home 的 text 应从 wd4.xml baseline 变体生成。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        home = screens["settings_home"]
        state = phonefast_parser.parse(home.text)
        # 应包含蓝牙开关元素
        bt = next((e for e in state.elements if e.desc and "蓝牙开关" in e.desc), None)
        assert bt is not None, "settings_home 应含蓝牙开关"

    def test_synthetic_screen_text_parseable(self, wd4_base_xml: str):
        """内联合成的屏幕文本（bt_off, loading 等）必须可被 UIState.parse 解析。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        for key in ("bt_off", "bt_detail", "loc_off", "loc_detail", "battery_page", "loading", "empty"):
            state = phonefast_parser.parse(screens[key].text)
            assert isinstance(state.elements, list), f"{key} 屏幕文本无法解析"

    def test_scenarios_loaded_with_fields(self, wd4_base_xml: str):
        """YAML 场景应加载成功，且行为字段由 _derive_scenario_fields 填充。"""
        _, scenarios, _ = load_device_graph(wd4_base_xml)
        assert len(scenarios) >= 6
        # 验证关键场景的字段推导
        bt = next(s for s in scenarios if s.name == "toggle_bluetooth")
        assert bt.kind == "switch"
        assert bt.target_desc == "蓝牙开关"
        assert bt.label_text == "蓝牙"
        assert bt.check == "tap_in_gt"
        assert bt.start_screen == "settings_home"
        # expect 字段为自然语言字符串（新 YAML 格式）
        assert bt.expect, f"{bt.name} 缺 expect 字段"
        assert "_" in bt.expect or "success" in str(bt.expect), f"{bt.name} expect 格式异常"

    def test_frozen_loading_scenario_exists(self, wd4_base_xml: str):
        _, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next((s for s in scenarios if s.name == "frozen_loading"), None)
        assert sc is not None
        assert sc.start_screen == "loading"
        assert sc.kind == "unresponsive"
        assert sc.check == "expect_fail"

    def test_empty_screen_scenario_exists(self, wd4_base_xml: str):
        _, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next((s for s in scenarios if s.name == "empty_screen"), None)
        assert sc is not None
        assert sc.start_screen == "empty"
        assert sc.kind == "unresponsive"
        assert sc.check == "expect_fail"
