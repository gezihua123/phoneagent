"""ScreenObserver: 封装 phonefast observe，内建指纹去重。

FastAgent 通过 self.observer.after_action() 获取自动观察文本，
无需在 agent 代码中硬编码去重逻辑。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from fastaget.device.phonefast import Phonefast, PhonefastError
from fastaget.device.uiprocessor import UIProcessor


def _hash_b64(b64: str) -> str:
    """对 base64 截图做 md5——只存 8 字节指纹，不存全量（100KB+）。"""
    return hashlib.md5(b64.encode("utf-8")).hexdigest()[:16] if b64 else ""


class ScreenObserver:
    """屏幕观察器：observe + 指纹去重。

    屏幕文本必须完整送达（宪法第七条）——不做任何压缩/截断。

    用法:
        obs = ScreenObserver(phonefast)
        screen_text, el_count = obs.initial()
        ctx.refresh(obs.last_ui)

        text = obs.after_action(action_hit=True)
        if text:
            messages.append({"role": "user", "content": [{"type": "text", "text": text}]})
            ctx.refresh(obs.last_ui)
    """

    # 指纹算法参数（raw text 前 200 chars 为固定 header，跳过）
    _FP_SKIP_LINES: int = 3
    _FP_HASH_BYTES: int = 8

    def __init__(
        self,
        phonefast: Any,  # Phonefast
        processor: UIProcessor | None = None,
        *,
        observe_delay: float = 0.5,
        observe_prefix: str = "[auto-refresh] ",
        observe_empty: str = "(empty)",
        format_mode: str = "detailed",  # "detailed" | "concise" | "auto"
    ) -> None:
        self._phonefast = phonefast
        self._processor = processor or UIProcessor(format_mode=format_mode)
        self._observe_delay = observe_delay
        self._observe_prefix = observe_prefix
        self._observe_empty = observe_empty
        self._prev_fp: str = ""
        self._raw_prev_fp: str = ""
        self._last_el_count: int = 0
        self.last_ui: Any = None   # 最近一次 observe 的 UIState
        self.last_image_hash: str = ""  # 最近一次截图的 md5（vision 模式用，存 hash 不存全量）

    @property
    def phonefast(self) -> Any:
        """只读访问底层 Phonefast 客户端。"""
        return self._phonefast

    @property
    def element_count(self) -> int:
        return self._last_el_count

    @property
    def fingerprint(self) -> str:
        return self._prev_fp

    def _make_fingerprint(self, screen_text: str, element_count: int) -> str:
        # 跳过固定 header 行（"Interactive elements on screen:\n=====...\n"）
        lines = (screen_text or "").split("\n")
        core = "\n".join(lines[self._FP_SKIP_LINES:])
        h = hashlib.md5(core.encode("utf-8")).hexdigest()[:self._FP_HASH_BYTES]
        return f"{element_count}:{h}"

    def note_observed(self, screen_text: str, element_count: int) -> bool:
        """外部 observe（如 observe 工具调用）后同步指纹，供进度检测使用。

        返回指纹是否变化——False 表示屏幕与上次完全相同，
        调用方可据此跳过重复的全量文本注入。
        """
        self._last_el_count = element_count
        fp = self._make_fingerprint(screen_text or "", element_count)
        changed = fp != self._prev_fp
        self._prev_fp = fp
        # 同步重置 raw 指纹——防止 after_action 用旧的 raw_fp 做 early-return
        # 跳过 processor.process() 导致 screen_text 不更新（双指纹 desync）
        self._raw_prev_fp = ""
        return changed

    def format_observation(self, text: str) -> str:
        """工具带回的观察文本 → 注入 messages 的统一格式（与轮末 auto-observe 前缀一致）。"""
        return f"{self._observe_prefix}{text}"

    def observe_raw(self) -> tuple[str, str | None]:
        """原始 observe：返回 (元素文本, 截图 base64)。"""
        try:
            raw = self._phonefast.observe()
            return raw.elements_text, raw.image_b64
        except PhonefastError as e:
            # 不静默吞——记录错误，让上层（after_action / 显式 observe 工具）能感知
            import logging
            _log = logging.getLogger(__name__)
            _log.warning("observe_raw failed: %s", e)
            return "", None

    def after_action(self, *, action_hit: bool = False) -> str | None:
        """操作后调用：等待屏幕稳定 → observe → 去重 → 返回文本。

        action_hit=True 时先等待 observe_delay 秒再采样（屏幕动画期间元素可能不准）。
        返回 None 表示屏幕未变化，无需注入 messages。
        """
        if action_hit and self._observe_delay > 0:
            time.sleep(self._observe_delay)

        raw_text, image_b64 = self.observe_raw()
        if not raw_text:
            return None
        self.last_image_hash = _hash_b64(image_b64) if image_b64 else ""

        # 指纹前置：比对原始文本指纹，未变化跳过 processor.process()
        raw_fp = self._make_fingerprint(raw_text, 0)
        if raw_fp == self._raw_prev_fp:
            return None
        self._raw_prev_fp = raw_fp

        ui, screen_text = self._processor.process(raw_text)
        self.last_ui = ui
        el_cnt = len(ui.elements) if ui else 0
        self._last_el_count = el_cnt
        # 同步 _prev_fp——必须用 processed 文本（与 initial/note_observed 同格式）。
        # 用 raw 文本会产生双格式指纹，混合路径下永不匹配，停滞检测失效
        self._prev_fp = self._make_fingerprint(screen_text or "", el_cnt)

        body = screen_text or self._observe_empty
        return f"{self._observe_prefix}{body}"

    def initial(self) -> tuple[str, int]:
        """首步 observe（无去重，无压缩）。返回 (屏幕文本, 元素数)。"""
        raw_text, image_b64 = self.observe_raw()
        self.last_image_hash = _hash_b64(image_b64) if image_b64 else ""
        if not raw_text:
            return "", 0
        ui, screen_text = self._processor.process(raw_text)
        self.last_ui = ui
        el_cnt = len(ui.elements) if ui else 0
        self._last_el_count = el_cnt
        self._prev_fp = self._make_fingerprint(screen_text or "", el_cnt)
        self._raw_prev_fp = self._make_fingerprint(raw_text, 0)
        return screen_text or "", el_cnt
