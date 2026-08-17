"""UIState 解析器测试，用真实 phonefast observe 输出样本。"""
from fastaget.device.uiprocessor import processor
from fastaget.device.uistate import UIState
from fastaget.device.uistate_phonefast import phonefast_parser

# 真实 observe 样本（截取自设备设置页）
SAMPLE = """Interactive elements on screen:
==================================================
[0] id="action_bar_root" (LinearLayout) bounds=[0,80][1080,2274]
[4] desc="转到上一层级" (ImageButton) [clickable] bounds=[0,90][147,237]
[5] text="设置" (TextView) bounds=[157,117][279,211]
[9] text="聊天时停止下载任务" id="tvLabel" (TextView) bounds=[84,443][870,502]
[10] id="switchControl" (Switch) bounds=[891,409][996,535]
[12] text="选择下载提供商" id="tv_label_sampler_type" (TextView) bounds=[84,592][356,651]
[15] text="语音模型管理" id="btn_voice_model_management" (TextView) [clickable] bounds=[42,685][1038,811]
==================================================
Use tap_element with index=N or text='...' to interact.
"""


def test_parse_extracts_index_text_id_class_bounds():
    state = phonefast_parser.parse(SAMPLE)
    el9 = state.get_coords(9) and next(e for e in state.elements if e.index == 9)
    assert el9.text == "聊天时停止下载任务"
    assert el9.id == "tvLabel"
    assert el9.cls == "TextView"
    assert el9.clickable is False
    assert el9.bounds == (84, 443, 870, 502)
    assert el9.center() == (477, 472)


def test_parse_desc_and_clickable():
    state = phonefast_parser.parse(SAMPLE)
    el4 = next(e for e in state.elements if e.index == 4)
    assert el4.desc == "转到上一层级"
    assert el4.clickable is True
    assert el4.cls == "ImageButton"


def test_get_coords_returns_center():
    state = phonefast_parser.parse(SAMPLE)
    # [5] bounds=[157,117][279,211] -> center (218, 164)
    assert state.get_coords(5) == (218, 164)


def test_get_coords_missing_raises():
    state = phonefast_parser.parse(SAMPLE)
    try:
        state.get_coords(999)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "999" in str(e)


def test_filter_drops_pure_containers():
    state = phonefast_parser.parse(SAMPLE)
    # filter/format 已移至 UIProcessor，通过 processor 调用
    filtered = processor.filter(state)
    indices = {e.index for e in filtered.elements}
    # [0] id-only 非点击容器 -> 丢弃
    assert 0 not in indices
    # [10] id-only 非点击 (Switch) -> 丢弃（其状态由同行 text 元素表达）
    assert 10 not in indices
    # clickable 或有 text/desc 的保留
    assert 4 in indices  # clickable + desc
    assert 5 in indices  # text
    assert 9 in indices  # text
    assert 12 in indices  # text
    assert 15 in indices  # text + clickable


def test_find_by_text():
    state = phonefast_parser.parse(SAMPLE)
    el = state.find_by_text("设置")
    assert el is not None
    assert el.index == 5
    assert state.find_by_text("不存在") is None


def test_format_is_nonempty():
    state = phonefast_parser.parse(SAMPLE)
    filtered = processor.filter(state)
    text = processor.format(filtered)
    assert "[5]" in text
    assert "设置" in text


def test_parse_empty():
    state = phonefast_parser.parse("")
    assert state.elements == []
