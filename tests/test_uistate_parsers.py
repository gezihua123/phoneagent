"""FlatrefParser 解析测试——生产唯一格式。"""
from fastaget.device.uistate_phonefast import FlatrefParser


# ── Mock 数据 ──────────────────────────────────────────────────────

FLATREF_SAMPLE = """#0 (FrameLayout) | bounds=[0,80][720,1600] | | depth=0 parent=#-1
#1 text="Settings" (Text) | bounds=[48,200][672,320] | [clickable] | depth=3 parent=#0
#2 desc="WiFi switch" (Switch) | bounds=[600,400][680,500] | [clickable] [checked] | depth=5 parent=#1
#3 text="Bluetooth" desc="Bluetooth settings" id="bluetooth_btn" (Button) | bounds=[100,600][620,720] | [clickable] | depth=7 parent=#2"""

LEGACY_SAMPLE = """Interactive elements on screen:
==================================================
[1] text="Settings" (Text) [clickable] bounds=[48,200][672,320]
[2] desc="WiFi switch" (Switch) [clickable] bounds=[600,400][680,500]
==================================================
Use tap_element with index=N or text='...' to interact."""


# ── FlatrefParser Tests ───────────────────────────────────────────

class TestFlatrefParser:
    def test_basic(self):
        state = FlatrefParser().parse(FLATREF_SAMPLE)
        assert len(state.elements) == 4
        assert state.elements[0].cls == "FrameLayout"
        assert state.elements[1].text == "Settings"
        assert state.elements[1].clickable is True
        assert state.elements[2].desc == "WiFi switch"
        assert "checked" in state.elements[2].flags
        assert state.elements[3].text == "Bluetooth"
        assert state.elements[3].id == "bluetooth_btn"

    def test_element_centers(self):
        state = FlatrefParser().parse(FLATREF_SAMPLE)
        cx, cy = state.elements[1].center()
        assert cx == (48 + 672) // 2
        assert cy == (200 + 320) // 2

    def test_legacy_format(self):
        state = FlatrefParser().parse(LEGACY_SAMPLE)
        assert len(state.elements) == 2
        assert state.elements[0].text == "Settings"
        assert state.elements[0].clickable is True
        assert state.elements[1].desc == "WiFi switch"

    def test_bounds_normalization(self):
        state = FlatrefParser().parse(
            '#1 text="X" (View) | bounds=[100,50][50,30] | | depth=0 parent=#-1')
        assert len(state.elements) == 1
        x1, y1, x2, y2 = state.elements[0].bounds
        assert x1 < x2
        assert y1 < y2

    def test_flags_group_parsing(self):
        state = FlatrefParser().parse(
            '#5 text="Item" (View) | bounds=[10,10][100,100] | '
            '[clickable] [scrollable] [focused] | depth=1 parent=#0')
        assert len(state.elements) == 1
        assert "clickable" in state.elements[0].flags
        assert "scrollable" in state.elements[0].flags
        assert "focused" in state.elements[0].flags

    def test_empty_flags_group(self):
        state = FlatrefParser().parse(
            '#5 text="Item" (View) | bounds=[10,10][100,100] | | depth=1 parent=#0')
        assert len(state.elements) == 1
        assert state.elements[0].clickable is False

    def test_desc_with_special_chars(self):
        state = FlatrefParser().parse(
            '#10 desc="Open (main) menu" (Button) | bounds=[100,200][300,400] | '
            '[clickable] | depth=3 parent=#5')
        assert len(state.elements) == 1
        assert state.elements[0].desc == "Open (main) menu"
        assert state.elements[0].cls == "Button"

    def test_contiguous_all_group3_empty(self):
        sample = (
            '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1\n'
            '#1 (Button) | bounds=[100,200][300,400] | | depth=2 parent=#0')
        state = FlatrefParser().parse(sample)
        assert len(state.elements) == 2
        assert state.elements[0].cls == "FrameLayout"
        assert state.elements[0].clickable is False
        assert state.elements[1].cls == "Button"


def test_parse_empty_string_yields_no_elements():
    assert len(FlatrefParser().parse("").elements) == 0
