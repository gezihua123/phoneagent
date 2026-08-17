"""ScreenObserver 单元测试 — 验证指纹去重和文本压缩。"""
from unittest.mock import MagicMock, patch, PropertyMock

from fastaget.device.screen_observer import ScreenObserver
from fastaget.device.uistate import UIState


def _ui_with(elements: int) -> UIState:
    """构造有 N 个空元素的 UIState。"""
    from fastaget.device.uistate import Element
    els = [
        Element(index=i, text="", id="", desc="", cls="View",
                bounds=(0, 0, 100, 100), clickable=True)
        for i in range(elements)
    ]
    return UIState(elements=els)


def _make_obs(raw_texts: list[str], ui_states: list[UIState] = None):
    """构造 ScreenObserver，mock 掉 phonefast 和 processor。"""
    if ui_states is None:
        ui_states = [_ui_with(1)] * len(raw_texts)

    pf = MagicMock()
    pf.observe.side_effect = [
        MagicMock(elements_text=t, image_b64=None) for t in raw_texts
    ]

    obs = ScreenObserver(pf)
    # 绕过 processor，直接用 mock 结果
    orig_process = obs._processor.process

    calls = iter(ui_states)

    def mock_process(raw_text):
        ui = next(calls)
        screen_text = f"[index] label | class | flags | bounds\n{chr(10).join(f'[{i}]' for i in range(len(ui.elements)))}"
        return ui, screen_text

    obs._processor.process = mock_process
    return obs


def test_initial_returns_screen():
    obs = _make_obs(["raw text"], [_ui_with(5)])
    text, count = obs.initial()
    assert count == 5
    assert "label" in text
    assert obs.last_ui is not None


def test_same_screen_skipped():
    obs = _make_obs(["raw A", "raw A"], [_ui_with(3), _ui_with(3)])
    obs.initial()
    result = obs.after_action()
    assert result is None, "unchanged screen should return None"


def test_different_screen_returned():
    # raw text 需要有 >3 行才能让 header-skip 后的内容不同
    header = "line1\nline2\nline3\n"
    obs = _make_obs([header + "AAAA", header + "BBBB"],
                    [_ui_with(3), _ui_with(7)])
    obs.initial()
    result = obs.after_action()
    assert result is not None, "changed screen should return text"


def test_screen_never_compressed():
    """宪法第七条：屏幕文本必须完整送达，无论 observe 多少次都不压缩/截断。"""
    obs = ScreenObserver(MagicMock())
    texts = ["L1\nL2\nL3\nA"] + [f"L1\nL2\nL3\nB{i}" for i in range(8)]
    pf = MagicMock()
    pf.observe.side_effect = [MagicMock(elements_text=t, image_b64=None) for t in texts]
    obs._phonefast = pf

    def _make_long(k):
        return "[index] label\n" + "\n".join(f"  [{j}] element-{j}" for j in range(k)) + "\n" + "x" * 500

    obs._processor.process = lambda raw: (_ui_with(5), _make_long(5))
    obs.initial()
    for i in range(7):  # 远超旧 compress_after=5 阈值
        result = obs.after_action()
        assert result is not None, f"iter {i}: should return text"
        assert "x" * 500 in result, f"iter {i}: 屏幕文本被截留（宪法第七条）"


def test_delay_on_action_hit():
    obs = _make_obs(["raw A", "raw A"], [_ui_with(3), _ui_with(3)])
    obs._observe_delay = 0.1
    obs.initial()
    import time
    t0 = time.monotonic()
    obs.after_action(action_hit=True)
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.09, f"should delay ~0.1s, got {elapsed:.3f}s"


def test_note_observed_syncs_fingerprint():
    obs = _make_obs(["raw"], [_ui_with(3)])
    obs.initial()
    fp_before = obs.fingerprint
    obs.note_observed("different text", 10)
    assert obs.fingerprint != fp_before
    assert obs.element_count == 10


def test_initial_empty_raw():
    obs = _make_obs([""], [_ui_with(0)])
    text, count = obs.initial()
    assert text == ""
    assert count == 0


def test_after_action_empty_raw():
    obs = _make_obs(["raw A", ""], [_ui_with(3), _ui_with(0)])
    obs.initial()
    result = obs.after_action()
    assert result is None


def _processed_text(n: int) -> str:
    """与 _make_obs 中 mock_process 生成的 processed 文本保持一致。"""
    return "[index] label | class | flags | bounds\n" + "\n".join(f"[{i}]" for i in range(n))


def test_fingerprint_consistent_across_paths():
    """混合路径指纹一致性：after_action 必须与 note_observed/initial 同格式（processed 文本）。

    回归：after_action 曾用 raw 文本算 _prev_fp → 与 note_observed 的 processed
    指纹永不匹配，observe→tap→observe 循环中指纹交替，StagnationDetector 失效。
    """
    header = "line1\nline2\nline3\n"
    obs = _make_obs([header + "AAAA", header + "BBBB"], [_ui_with(3), _ui_with(5)])
    obs.initial()
    result = obs.after_action()  # 屏幕变化：raw 不同 → processed(5 元素)
    assert result is not None
    fp_after_action = obs.fingerprint
    # 同一屏幕经显式 observe 工具路径（note_observed）——processed 文本+元素数相同
    changed = obs.note_observed(_processed_text(5), 5)
    assert not changed, "same screen via different paths must yield identical fingerprint"
    assert obs.fingerprint == fp_after_action
