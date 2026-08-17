"""FillFieldsAction 单测——批量填表单工具。

Mock phonefast（observe 返回固定 flatref 串，真实 UIProcessor/FlatrefParser 解析），
断言：
  - 多字段全填：tap/type 次数 == 字段数
  - 标签大小写不敏感
  - 字段已有值 → 跳过（不重复 type）
  - 字段找不到 → 该字段 FAIL 但其他字段仍填
  - 空字段列表 → fail
  - 屏幕外字段 → 自动滚动后填充
  - 模式 2（独立 label TextView）→ 找其下方最近 Input

flatref 格式参考 uistate_phonefast.py：
  #N text="..." id="..." desc="..." (Class) | bounds=[x1,y1][x2,y2] | [flags] | depth=D parent=#M
"""
from unittest.mock import MagicMock

from fastaget.device.phonefast import ObserveResult
from fastaget.tools.actions import FillFieldsAction
from fastaget.tools.context import ActionContext

# Broccoli new-recipe form：空字段 text=hint 标签，class EditText，clickable
BROCCOLI_FORM = "\n".join([
    '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1',
    '#1 text="Add Recipe" (TextView) | bounds=[0,80][1080,200] | | depth=1 parent=#0',
    '#10 text="Title" id="new_title" (EditText) | bounds=[100,300][980,400] | [clickable] | depth=3 parent=#0',
    '#11 text="Description" id="new_description" (EditText) | bounds=[100,420][980,520] | [clickable] | depth=3 parent=#0',
    '#12 text="Source" id="new_source" (EditText) | bounds=[100,540][980,640] | [clickable] | depth=3 parent=#0',
    '#13 text="Servings" id="new_servings" (EditText) | bounds=[100,660][980,760] | [clickable] | depth=3 parent=#0',
    '#14 text="Time" id="new_time" (EditText) | bounds=[100,780][980,880] | [clickable] | depth=3 parent=#0',
    '#15 text="Ingredients" id="new_ingredients" (EditText) | bounds=[100,900][980,1100] | [clickable] | depth=3 parent=#0',
    '#16 text="Directions" id="new_directions" (EditText) | bounds=[100,1120][980,1320] | [clickable] | depth=3 parent=#0',
])


def _ctx(screen: str) -> ActionContext:
    """构造带固定屏幕的 ctx。screen 为 flatref 串。"""
    pf = MagicMock()
    pf.observe.return_value = ObserveResult(elements_text=screen)
    pf.status.return_value = {"device_width": 1080, "device_height": 2400}
    return ActionContext(phonefast=pf)


def _ctx_with_screens(*screens: str) -> ActionContext:
    """observe 依次返回不同屏幕（用于滚动场景）。"""
    pf = MagicMock()
    pf.observe.side_effect = [ObserveResult(elements_text=s) for s in screens]
    pf.status.return_value = {"device_width": 1080, "device_height": 2400}
    return ActionContext(phonefast=pf)


SIX_FIELDS = [
    {"label": "Title", "value": "Chocolate Cake"},
    {"label": "Description", "value": "A rich dessert"},
    {"label": "Source", "value": "Grandma"},
    {"label": "Servings", "value": "8"},
    {"label": "Time", "value": "45 mins"},
    {"label": "Ingredients", "value": "flour, sugar, cocoa"},
]


def test_fill_all_six_fields():
    """6 个空字段全部填充：tap/type 各 6 次，success，filled=6。"""
    ctx = _ctx(BROCCOLI_FORM)
    ar = FillFieldsAction()(ctx=ctx, fields=SIX_FIELDS)
    pf = ctx.phonefast
    assert ar.success, f"should succeed: {ar.summary}"
    assert ar.data["filled"] == 6
    assert ar.data["total"] == 6
    assert pf.tap.call_count == 6, f"expected 6 taps, got {pf.tap.call_count}"
    assert pf.type_text.call_count == 6
    typed = [c.args[0] for c in pf.type_text.call_args_list]
    assert typed == ["Chocolate Cake", "A rich dessert", "Grandma",
                     "8", "45 mins", "flour, sugar, cocoa"]


def test_label_case_insensitive():
    """传小写 label 'title' 仍能匹配 text='Title' 字段。"""
    ctx = _ctx(BROCCOLI_FORM)
    ar = FillFieldsAction()(ctx=ctx, fields=[{"label": "title", "value": "Cake"}])
    assert ar.success
    assert ar.data["filled"] == 1
    assert ctx.phonefast.type_text.call_args_list[0].args[0] == "Cake"


def test_skip_field_with_existing_value():
    """字段已有值（text != label hint）→ 跳过不重复输入，其他字段仍填。"""
    # Title 字段已填 "Chocolate Cake"（!= "Title" hint）
    screen = BROCCOLI_FORM.replace(
        '#10 text="Title" id="new_title"',
        '#10 text="Chocolate Cake" id="new_title"')
    ctx = _ctx(screen)
    ar = FillFieldsAction()(ctx=ctx, fields=[
        {"label": "Title", "value": "New Title"},     # 已有值 → SKIP
        {"label": "Servings", "value": "8"},           # 空 → 填
    ])
    assert ar.success
    assert ar.data["filled"] == 1, f"only 1 should fill: {ar.summary}"
    assert "SKIP" in ar.summary and "Title" in ar.summary
    # 只 type 了 Servings 的值
    assert ctx.phonefast.type_text.call_count == 1
    assert ctx.phonefast.type_text.call_args_list[0].args[0] == "8"


def test_field_not_found_fails_that_field_but_fills_others():
    """找不到的字段 FAIL，其他字段仍填，summary 报告部分成功。"""
    # 屏幕只有 Title + Servings，没有 Source
    screen = "\n".join([
        '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1',
        '#10 text="Title" id="new_title" (EditText) | bounds=[100,300][980,400] | [clickable] | depth=3 parent=#0',
        '#13 text="Servings" id="new_servings" (EditText) | bounds=[100,660][980,760] | [clickable] | depth=3 parent=#0',
    ])
    ctx = _ctx(screen)
    ar = FillFieldsAction()(ctx=ctx, fields=[
        {"label": "Title", "value": "Cake"},
        {"label": "Source", "value": "Grandma"},   # 找不到 → FAIL（滚动后仍找不到 → 回滚视口）
        {"label": "Servings", "value": "8"},
    ])
    assert ar.success  # 工具本身成功（部分填充），FAIL 在 summary 里
    assert ar.data["filled"] == 2
    assert "FAIL" in ar.summary and "Source" in ar.summary
    # 3 次向下滚动寻找 + 3 次向上回滚视口（避免后续字段因视口偏移而漏判）
    assert ctx.phonefast.swipe.call_count == FillFieldsAction._MAX_FIELD_SCROLLS * 2


def test_empty_fields_list_fails():
    """空 fields 列表 → fail。"""
    ctx = _ctx(BROCCOLI_FORM)
    ar = FillFieldsAction()(ctx=ctx, fields=[])
    assert not ar.success
    assert "non-empty" in ar.summary
    assert ctx.phonefast.tap.call_count == 0


def test_missing_label_skipped():
    """字段缺 label → SKIP，不崩。"""
    ctx = _ctx(BROCCOLI_FORM)
    ar = FillFieldsAction()(ctx=ctx, fields=[
        {"value": "no label here"},                # 无 label → SKIP
        {"label": "Title", "value": "Cake"},
    ])
    assert ar.success
    assert ar.data["filled"] == 1
    assert "SKIP" in ar.summary


def test_scroll_finds_offscreen_field():
    """字段不在首屏 → 滚动后出现在第二屏 → 填充成功。"""
    screen_a = "\n".join([  # 首屏无 Directions
        '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1',
        '#10 text="Title" id="new_title" (EditText) | bounds=[100,300][980,400] | [clickable] | depth=3 parent=#0',
    ])
    screen_b = "\n".join([  # 滚动后 Directions 出现
        '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1',
        '#16 text="Directions" id="new_directions" (EditText) | bounds=[100,300][980,400] | [clickable] | depth=3 parent=#0',
    ])
    # observe 序列：找 Title(ok)→找 Directions 首屏 miss→滚动后命中→最终 observe
    ctx = _ctx_with_screens(screen_a, screen_a, screen_b, screen_b)
    ar = FillFieldsAction()(ctx=ctx, fields=[
        {"label": "Title", "value": "Cake"},
        {"label": "Directions", "value": "Mix and bake"},
    ])
    pf = ctx.phonefast
    assert ar.success, f"should succeed: {ar.summary}"
    assert ar.data["filled"] == 2
    assert pf.swipe.call_count == 1, "should scroll once for off-screen Directions"
    assert pf.type_text.call_count == 2
    assert pf.type_text.call_args_list[1].args[0] == "Mix and bake"


# ── 模式 2：独立 label TextView（Markor 风格）────────────────────────

MARKOR_FORM = "\n".join([
    '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1',
    '#5 text="Name" (TextView) | bounds=[100,300][980,380] | | depth=2 parent=#0',
    '#6 id="edit_text_1" (EditText) | bounds=[100,400][980,520] | [clickable] | depth=2 parent=#0',
])


def test_mode2_separate_label_textview():
    """label 是独立 Text 元素，Input 在其下方且自身不含 label 文本 → 模式 2 命中。"""
    ctx = _ctx(MARKOR_FORM)
    ar = FillFieldsAction()(ctx=ctx, fields=[{"label": "Name", "value": "my_note"}])
    assert ar.success, f"should succeed: {ar.summary}"
    assert ar.data["filled"] == 1
    assert ctx.phonefast.tap.call_count == 1
    assert ctx.phonefast.type_text.call_args_list[0].args[0] == "my_note"


# ── 通用性扩展：水平布局 / 多次滚动 / AutoComplete ──────────────────

def test_mode2_horizontal_label_left_input_right():
    """label 在左、input 在右（同行 y 重叠）→ 模式 2 同行命中，非下方布局也支持。"""
    # label "Port" 在左半屏 y=300-380，input 在右半屏 y 同行 y=300-400
    screen = "\n".join([
        '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1',
        '#5 text="Port" (TextView) | bounds=[40,300][300,380] | | depth=2 parent=#0',
        '#6 id="port_input" (EditText) | bounds=[340,300][980,400] | [clickable] | depth=2 parent=#0',
    ])
    ctx = _ctx(screen)
    ar = FillFieldsAction()(ctx=ctx, fields=[{"label": "Port", "value": "8080"}])
    assert ar.success, f"horizontal layout should match: {ar.summary}"
    assert ar.data["filled"] == 1
    assert ctx.phonefast.tap.call_count == 1
    assert ctx.phonefast.type_text.call_args_list[0].args[0] == "8080"


def test_multiscroll_finds_field_after_two_scrolls():
    """字段需滚动 2 次才出现 → _MAX_FIELD_SCROLLS(=3) 足够覆盖，填充成功。"""
    a = '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1'
    b = a  # 滚动 1 次后仍无目标
    c = "\n".join([  # 滚动 2 次后目标出现
        '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1',
        '#10 text="Notes" id="notes" (EditText) | bounds=[100,300][980,400] | [clickable] | depth=3 parent=#0',
    ])
    # observe 序列：_find_field(a,无)→滚→_find_field(b,无)→滚→_find_field(c,命中)→最终 observe(c)
    ctx = _ctx_with_screens(a, b, c, c)
    ar = FillFieldsAction()(ctx=ctx, fields=[{"label": "Notes", "value": "N"}])
    assert ar.success, f"2-scroll field should be found: {ar.summary}"
    assert ar.data["filled"] == 1
    assert ctx.phonefast.swipe.call_count == 2, "should scroll twice"
    assert ctx.phonefast.type_text.call_args_list[0].args[0] == "N"


def test_multiscroll_gives_up_after_max():
    """字段滚动 _MAX_FIELD_SCROLLS 次仍不出现 → FAIL，不无限滚动。"""
    a = '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1'
    # 每次滚动后都返回空屏 a → 永远找不到（5 次 observe：初始+3次滚动查找+最终observe）
    ctx = _ctx_with_screens(a, a, a, a, a)
    ar = FillFieldsAction()(ctx=ctx, fields=[{"label": "Ghost", "value": "x"}])
    assert ar.success  # 工具成功，字段 FAIL 在 summary
    assert ar.data["filled"] == 0
    assert "FAIL" in ar.summary and "Ghost" in ar.summary
    # _MAX_FIELD_SCROLLS 次向下滚动 + 同数次向上回滚视口
    assert ctx.phonefast.swipe.call_count == FillFieldsAction._MAX_FIELD_SCROLLS * 2


def test_autocomplete_textview_recognized_as_input():
    """AutoCompleteTextView 是可输入控件 → _is_input 识别，能填充。"""
    screen = "\n".join([
        '#0 (FrameLayout) | bounds=[0,0][1080,2400] | | depth=0 parent=#-1',
        '#10 text="Category" id="cat" (AutoCompleteTextView) | bounds=[100,300][980,400] | [clickable] | depth=3 parent=#0',
    ])
    ctx = _ctx(screen)
    ar = FillFieldsAction()(ctx=ctx, fields=[{"label": "Category", "value": "Food"}])
    assert ar.success, f"AutoCompleteTextView should be fillable: {ar.summary}"
    assert ar.data["filled"] == 1
    assert ctx.phonefast.type_text.call_args_list[0].args[0] == "Food"


def test_returns_observation_data_for_fingerprint_sync():
    """返回 elements+count → executor 可同步屏幕指纹（observation_data 属性）。"""
    ctx = _ctx(BROCCOLI_FORM)
    ar = FillFieldsAction()(ctx=ctx, fields=[{"label": "Title", "value": "Cake"}])
    assert ar.observation_data is not None
    text, count = ar.observation_data
    assert isinstance(count, int) and count > 0
    assert "Title" in text or "Cake" in text
