"""UIProcessor：独立的 UI 加工层。

职责分离（关注点解耦）：
  - FlatrefParser（uistate_phonefast.py）：flatref 格式 → UIState
  - UIProcessor（本模块）：加工层，负责清洗（filter）+ 结构化格式化（format）。

加工流水线：
  raw_text → FlatrefParser.parse → filter（几何+屏幕内+语义三层清洗）→ format

数据源可注入：
  process(raw_text)           → 默认使用 FlatrefParser
  process(raw_text, parser=x) → 自定义 UIParser（测试用 mock 解析器）
"""
from __future__ import annotations

from fastaget.device.uistate import Element, UIState, UIParser
from fastaget.device.uistate_phonefast import phonefast_parser

# 默认屏幕尺寸回退值（多数 Android 手机 1080x2400）
_DEFAULT_SCREEN = (1080, 2400)


class UIProcessor:
    """UI 加工层：phonefast 原始输出 → 清洗 + 结构化格式化。

    无状态，可全局复用单例（见模块级 `processor`）。
    支持 format_mode 控制输出粒度：
      - "detailed": 含 bounds（当前，适合小屏/<30元素）
      - "concise": 无 bounds（省 token，适合大屏/>30元素）
      - "auto": ≤30元素用 detailed，>30用 concise
    """

    def __init__(self, format_mode: str = "detailed") -> None:
        self.format_mode = format_mode

    def process(
        self,
        raw_text: str,
        *,
        parser: UIParser | None = None,
        max_elements: int = 80,
    ) -> tuple[UIState, str]:
        """一步加工：原始文本 → (清洗后 UIState, 结构化格式文本)。

        parser: 数据源解析器，默认使用 FlatrefParser（生产唯一格式）。
        max_elements: 格式化输出的最大元素数。
        """
        if parser is None:
            parser = phonefast_parser
        ui = parser.parse(raw_text)
        clean = self.filter(ui)
        text = self.format(clean, max_elements=max_elements)
        return clean, text

    # ---- 清洗 ----

    def filter(self, ui: UIState) -> UIState:
        """三层清洗，剔除对 LLM 有害的噪声元素。

          1. 几何合法性：丢弃零/负面积（x1>=x2 或 y1>=y2）的非法元素
             —— phonefast 偶发解析出负宽度 bounds，会误导坐标选择
          2. 屏幕内可见：丢弃完全在屏幕外的元素
             —— 多页桌面/ViewPager 的其他页，物理上点不到
          3. 语义有效性：仅保留可交互（clickable）或有语义内容（text/desc）的元素
             —— id-only 且不可点击的纯容器（content/toolbar 等）对 LLM 是噪声

        保留编号不变（仍用 phonefast 原始 index），LLM 报的 index 可直接查坐标。
        """
        sw, sh = self._infer_screen(ui)
        kept: list[Element] = []
        for e in ui.elements:
            x1, y1, x2, y2 = e.bounds
            if x2 - x1 <= 0 or y2 - y1 <= 0:  # 几何合法性
                continue
            if x2 <= 0 or y2 <= 0 or x1 >= sw or y1 >= sh:  # 屏幕内可见
                continue
            if not (e.clickable or e.text or e.desc or e.flags):  # 语义有效性
                continue
            kept.append(e)
        return UIState(kept)

    # ---- 格式化 ----

    # 要在格式化输出中展示的标记（对 LLM 决策有用）
    _VISIBLE_FLAGS = ("checked", "scrollable", "focused", "selected")

    def format(self, ui: UIState, max_elements: int = 80) -> str:
        """格式化为 LLM 友好的结构化文本。

        按空间分区组织元素，避免一维平铺串行导致 LLM 误关联。
        format_mode 控制输出粒度：
          - "detailed": index | label | class | flags | bounds
          - "concise":  index | label | class | flags （无 bounds，省 ~30% token）
          - "auto":     ≤30 元素用 detailed，>30 用 concise
        """
        if not ui.elements:
            # 空屏幕：用 actual mode 决定 header
            m = self.format_mode
            if m == "auto":
                m = "detailed"  # 空屏回退 detailed
            header = self._fmt_header(m)
            return f"{header}\n(no elements)"

        # 自动切换
        mode = self.format_mode
        if mode == "auto":
            mode = "detailed" if len(ui.elements) <= 30 else "concise"

        els = ui.elements[:max_elements]
        truncated = len(ui.elements) - max_elements if len(ui.elements) > max_elements else 0

        regions = self._partition_regions(els, ui)

        header = self._fmt_header(mode)
        lines = [header]
        for region_name in ("top", "middle", "bottom"):
            region_els = regions[region_name]
            if not region_els:
                continue
            lines.append(f"--- {region_name} ---")
            region_els.sort(key=lambda e: (e.bounds[1], e.bounds[0]))
            used: set[int] = set()
            for e in region_els:
                if e.index in used:
                    continue
                lines.append(self._fmt_element(e, mode=mode))
                children = [
                    c for c in region_els
                    if c.index != e.index and c.index not in used and e.contains(c)
                ]
                children.sort(key=lambda c: (c.bounds[1], c.bounds[0]))
                for c in children:
                    lines.append("  " + self._fmt_element(c, mode=mode))
                    used.add(c.index)

        if truncated:
            lines.append(f"... ({truncated} more)")
        return "\n".join(lines)

    def _fmt_header(self, mode: str = "detailed") -> str:
        """根据实际使用的 mode 返回匹配的表头。"""
        if mode == "concise":
            return "[index] label | class | flags"
        return "[index] label | class | flags | bounds"

    def _partition_regions(self, els: list[Element], ui: UIState) -> dict[str, list[Element]]:
        """按 y 坐标分顶部/中部/底部三区。"""
        _, screen_h = self._infer_screen(ui)
        y1_3 = screen_h / 3
        y2_3 = screen_h * 2 / 3
        regions: dict[str, list[Element]] = {"top": [], "middle": [], "bottom": []}
        for e in els:
            cy = (e.bounds[1] + e.bounds[3]) / 2
            if cy < y1_3:
                regions["top"].append(e)
            elif cy < y2_3:
                regions["middle"].append(e)
            else:
                regions["bottom"].append(e)
        return regions

    # ---- 内部 ----

    @staticmethod
    def _infer_screen(ui: UIState) -> tuple[int, int]:
        """推断屏幕尺寸。取 [0,0][W,H] 形全屏元素的最大 W/H，回退默认值。"""
        sw, sh = _DEFAULT_SCREEN
        for e in ui.elements:
            x1, y1, x2, y2 = e.bounds
            if x1 == 0 and y1 == 0:
                sw = max(sw, x2)
                sh = max(sh, y2)
        return sw, sh

    def _fmt_element(self, e: Element, mode: str = "detailed") -> str:
        """格式化单个元素为一行。标记列优先展示对 LLM 决策有用的 flags。

        detailed: [index] label | class | flags | bounds
        concise:  [index] label | class | flags （省 token）
        """
        parts = []
        if e.clickable:
            parts.append("clickable")
        for flag in self._VISIBLE_FLAGS:
            if flag in e.flags:
                parts.append(flag)
        flags_str = " ".join(parts) if parts else "-"
        base = f"[{e.index}] {e.label()} | {e.cls} | {flags_str}"
        if mode == "concise":
            return base
        return f"{base} | {e.bounds}"


# 模块级单例：无状态，所有调用方共享
processor = UIProcessor()
