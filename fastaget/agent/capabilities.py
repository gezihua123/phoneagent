"""Turn 级通用能力——独立"工具"，自持状态，统一接口，可插拔替换。

每个能力实现一个 Capability 协议（(RunState, TurnSnapshot) -> RunState），
在特定的生命周期阶段（post_llm / post_turn / finalize）被调用。

隔离原则：
  - 能力之间零交叉依赖——各自只读 TurnSnapshot 中的字段
  - 能力内部状态私有——不污染 RunState 字段
  - 独立可测——构造 RunState + TurnSnapshot 即可调用，不需要 FastAgent 实例
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from fastaget.agent.run_state import RunState


# ═══════════════════════════════════════════════════════════
# TurnSnapshot：能力读取的上下文快照
# ═══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TurnSnapshot:
    """一轮 turn 的快照——能力通过它读取所需上下文，零 FastAgent 依赖。

    各生命周期阶段填充不同字段：
      pre_run     — fingerprint / element_count（PreconditionGate 前置检查）
      pre_turn    — （无附加字段）每轮 LLM 调用前（PI prepareNextTurn）
      llm_failure — （无附加字段）LLM 调用重试耗尽后失败
      llm_success — （无附加字段）LLM 调用成功（供 llm_failure_caps 重置计数）
      post_llm    — llm_has_tool_calls
      after_tool  — tool_name / action_result / any_action_failed
      post_turn   — fingerprint / element_count / last_tool
      finalize    — assert_tools
    """

    phase: str = ""
    # post_llm
    llm_has_tool_calls: bool = False  # LLM 是否返回了 tool_use 块
    # after_tool
    tool_name: str = ""
    action_result: Any = None         # ActionResult（避免硬依赖 tools 层，鸭子类型）
    any_action_failed: bool = False   # 本批次此前是否有操作类工具失败
    # post_turn
    fingerprint: str = ""
    element_count: int = 0
    last_tool: str = ""
    # finalize
    assert_tools: frozenset[str] = frozenset()


class Capability(Protocol):
    """Turn 级通用能力接口。

    Optional: enrich(snap) → str — 工具执行后丰富 tool_result 内容
    （PI afterToolCall 对齐：cap 可修改工具结果，追加分析/建议文本）。
    """

    def __call__(self, state: "RunState", snap: TurnSnapshot) -> "RunState":
        """读取 state + snap，返回新 state（可修改 pending_feedback/terminal/success）。"""
        ...


# ═══════════════════════════════════════════════════════════
# 辅助：feedback 文件加载（单一来源 meta/feedback.py）
# ═══════════════════════════════════════════════════════════

def _load_feedback(name: str) -> str:
    from fastaget.meta.feedback import load_feedback
    return load_feedback(name)


# ═══════════════════════════════════════════════════════════
# 能力 1：CompletionNudge（纯文本催促）
# ═══════════════════════════════════════════════════════════

@dataclass
class CompletionNudge:
    """LLM 连续返回纯文本 → 催促调 complete / 超过上限 → 终止。

    post_llm 阶段生效。内部持 _nudges 计数，不写 RunState。
    """

    limit: int = 2
    _nudges: int = field(default=0, init=False)

    def reset(self) -> None:
        """外层续跑（_rearm）时清零——防止续跑首轮误触发终止。"""
        self._nudges = 0

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "post_llm":
            return state
        if snap.llm_has_tool_calls:
            self._nudges = 0  # LLM 正常调工具 → 重置
            return state
        self._nudges += 1
        if self._nudges > self.limit:
            # 不主动判失败——verify 层做最终仲裁
            return replace(state, terminal=True, success=False,
                          summary="LLM 多次只返回文本，自动终止")
        fb = _load_feedback("require_complete")
        if fb:
            state.pending_feedback.append(fb)
        return state


# ═══════════════════════════════════════════════════════════
# 能力 1b：CompletionSignal（连续纯操作信号）
# ═══════════════════════════════════════════════════════════

# 纯操作工具（改变设备状态，非查询/导航）——兜底默认值，被 registry 动态覆盖
_ACTION_TOOLS: frozenset[str] = frozenset({
    "tap", "tap_element", "tap_by_text", "long_press", "long_press_at",
    "swipe", "type", "type_secret", "key", "fill_fields",
})


@dataclass
class CompletionSignal:
    """连续 N 次纯操作工具（无 observe/complete）→ 提醒验证并完成。

    post_turn 阶段生效。内部持 _consecutive 计数 + _cooldown 去抖。
    查询类工具（observe/shell/assert）重置计数。
    action 工具集合从 registry 动态获取，fallback 到 _ACTION_TOOLS。

    冷却（v1.14）：触发后 N 轮内不再重复 nag。盲区里 agent 反复
    action→observe(无新信息)→action，旧逻辑每 3 步 nag 一次，占步数且无益。
    冷却按轮递减自然过期；observe 等非 action 工具仍正常重置 _consecutive。
    """

    limit: int = 3
    cooldown: int = 4  # 触发后冷却轮数——盲区里 action→observe→action 不反复 nag
    action_tools: frozenset[str] = _ACTION_TOOLS
    _consecutive: int = field(default=0, init=False)
    _cooldown: int = field(default=0, init=False)

    def reset(self) -> None:
        """外层续跑（_rearm）时清零。"""
        self._consecutive = 0
        self._cooldown = 0

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "post_turn":
            return state
        if snap.last_tool in self.action_tools:
            self._consecutive += 1
        else:
            self._consecutive = 0
        # 冷却期：触发后 N 轮内不重复 nag（盲区里 observe 不解决问题，反复 nag 只占步数）
        if self._cooldown > 0:
            self._cooldown -= 1
            return state
        if self._consecutive >= self.limit:
            self._consecutive = 0  # 触发后重置，避免重复提醒
            self._cooldown = self.cooldown
            fb = _load_feedback("completion_signal")
            if fb:
                state.pending_feedback.append(fb)
        return state


# ═══════════════════════════════════════════════════════════
# 能力 2：StagnationDetector（停滞/退化检测）
# ═══════════════════════════════════════════════════════════

# 停滞豁免工具（不改变屏幕的工具不计停滞）
# observe/ocr/current_app 是只读工具——a11y 树不稳定时 agent 反复 observe 确认屏幕
# 是正常行为（不是停滞），不应被停滞检测器杀死
_EXEMPT: frozenset[str] = frozenset({
    "back", "home", "launch", "wait", "shell", "assert",
    "current_state", "check_package", "device_status",
    "observe", "ocr", "current_app",
})

# 操作类工具——执行后期望屏幕变化（用于 stale tap 检测）
_ACTION_LIKE: frozenset[str] = frozenset({
    "tap", "tap_element", "tap_by_text", "long_press",
    "swipe", "type", "key", "fill_fields",
})

# 设备事实查询类工具——agent 用它们查证状态（shell/check_package/current_app 等）。
# 盲区检测：agent 已在用 fact 工具查证 → 不再 nag "用设备事实"（它正在做）
_FACT_TOOLS: frozenset[str] = frozenset({
    "shell", "check_package", "current_app", "current_state", "device_status",
    "ocr",
})


@dataclass
class StagnationDetector:
    """停滞/退化检测——屏幕指纹窗口比对。

    post_turn 阶段生效。内部持指纹窗口 + 计数，不写 RunState。

    优先级：停滞终止 > 停滞告警（短路退化/盲区） > 退化告警 / 盲区引导。
    告警两级升级：_count < force_limit 用软提示（stagnation_warn），
    达到后用强制命令（stagnation_force）——软提示的"请检查"会让 LLM
    继续 observe 确认，形成确认死循环；强制级明确禁止重复观察。

    低元素屏拆分（v1.14）：取景器/播放器等全屏 app 的 a11y 树天生只有 2-3 元素。
    旧逻辑一见骤降就报"wait for load recovery"→ observe→wait→observe 死循环。
    现拆分：el 持续 ≤阈值(连续 blind_persist 轮，即便指纹抖动)=盲区→注入 blind_zone
    (引导用设备事实查证)；骤降但未持续=flux→注入 degradation(建议 observe 确认，非 wait)。
    """

    window: int = 2
    limit: int = 6      # 容忍上限（shell 任务屏幕不变但状态在变，需足够容限）
    force_limit: int = 2
    exempt: frozenset[str] = _EXEMPT
    action_like: frozenset[str] = _ACTION_LIKE
    fact_tools: frozenset[str] = _FACT_TOOLS  # 设备事实查询工具——盲区里不 nag
    deg_abs_max: int = 5
    deg_ratio: float = 0.2
    blind_persist: int = 3  # 连续 N 轮低元素→判定盲区(取景器/播放器)，即便指纹抖动
    diversity_window: int = 3  # tool_diversity 检测窗口
    stale_tap_limit: int = 1   # 连续 stale tap 后注入反馈
    _fps: list[str] = field(default_factory=list)
    _count: int = 0
    _recent_tools: list[str] = field(default_factory=list)
    _stale_taps: int = 0  # 连续操作类工具后屏幕无变化的计数
    _blind_fired: bool = False  # 当前低元素盲区 episode 是否已注入 blind_zone（去抖）

    def feed_initial(self, fingerprint: str, el_count: int) -> None:
        """初始屏幕指纹喂入——建立检测基线。"""
        self._fps.append(f"{el_count}:{fingerprint}" if fingerprint else f"{el_count}:")

    def reset(self) -> None:
        """外层续跑（_rearm）时清空指纹窗口 + 计数。"""
        self._fps.clear()
        self._count = 0
        self._recent_tools.clear()
        self._stale_taps = 0
        self._blind_fired = False

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "post_turn":
            return state
        fp = snap.fingerprint or ""
        el = snap.element_count
        self._fps.append(f"{el}:{fp}" if fp else f"{el}:")
        # 防无界增长：只保留最近 window*2 条
        if len(self._fps) > self.window * 2:
            self._fps = self._fps[-self.window * 2:]

        # 追踪最近工具名（tool_diversity 检测用）
        self._recent_tools.append(snap.last_tool)
        if len(self._recent_tools) > self.diversity_window:
            self._recent_tools = self._recent_tools[-self.diversity_window:]

        # ── Stale tap 快速检测：操作类工具后屏幕未变 → 元素可能不可交互 ──
        if snap.last_tool in self.action_like and len(self._fps) >= 2:
            if self._fps[-1] == self._fps[-2]:
                self._stale_taps += 1
            else:
                self._stale_taps = 0
        else:
            self._stale_taps = 0  # 非操作类工具（observe/shell）或指纹变化 → 重置
        if self._stale_taps >= self.stale_tap_limit:
            self._stale_taps = 0  # 触发后重置，避免重复提醒
            fb = _load_feedback("stale_action")
            if fb:
                state.pending_feedback.append(fb)
            # 不 return——继续走停滞检测（stale tap != 停滞，可能只是点了同一个不响应元素）

        # ── 停滞：窗口内指纹全相同 + 非豁免工具 + 非策略切换 ──
        if len(self._fps) >= self.window and len(set(self._fps[-self.window:])) == 1:
            if snap.last_tool in self.exempt:
                pass  # 豁免工具不计停滞
            elif (len(self._recent_tools) >= self.diversity_window
                  and len(set(self._recent_tools)) > 1):
                pass  # agent 在换策略（不同工具）→ 不计停滞
            else:
                self._count += 1
        else:
            self._count = 0

        if self._count > self.limit:
            # 不主动判失败——verify 层做最终仲裁
            return replace(state, terminal=True, success=False,
                          summary="屏幕停滞过久，自动终止")

        if self._count > 0:
            # ← 改动点：两级升级——达到 force_limit 换强制命令式反馈
            fb = _load_feedback(
                "stagnation_force" if self._count >= self.force_limit else "stagnation_warn")
            if fb:
                state.pending_feedback.append(fb)
            return state  # 停滞告警短路退化检测

        # ── 低元素屏处理：盲区(持续低元素) vs 加载(骤降仍在 flux) ──
        # 取景器/播放器/全屏 app 的 a11y 树天生只有 2-3 元素——骤降≠加载。
        # 旧逻辑一见骤降就报"wait for load recovery"，致 observe→wait→observe 死循环。
        # 拆分：el 持续 ≤阈值(连续 blind_persist 轮)=盲区(引导用设备事实查证)；
        #       骤降但未持续到 blind_persist=flux(建议 observe 确认，非 wait)。
        # 持续低元素而非"指纹相同"：取景器 el 在 2-4 抖动(计时器/缩略图闪现)，指纹每轮变但 el 持续低。
        if len(self._fps) >= 2:
            try:
                recent_els = [int(f.split(":")[0]) for f in self._fps[-self.blind_persist:]]
            except (ValueError, IndexError):
                recent_els = []
            low_count = sum(1 for e in recent_els if e <= self.deg_abs_max)
            if low_count >= self.blind_persist:
                # 持续低元素=盲区——agent 已用 fact 工具查证则不 nag(它在做对的事)
                if snap.last_tool in self.fact_tools:
                    self._blind_fired = False  # agent 走对路，重置 episode
                elif not self._blind_fired:
                    self._blind_fired = True  # 每个持续低元素 episode 只注入一次
                    fb = _load_feedback("blind_zone")
                    if fb:
                        state.pending_feedback.append(fb.replace("{el}", str(el)))
            elif el <= self.deg_abs_max and self._fps[-1] != self._fps[-2]:
                # 骤降但未持续到 blind_persist + 指纹仍变=flux(加载/跳转)
                # 建议 observe 确认，而非 wait(wait 致 observe→wait→observe 死循环)
                try:
                    prev_el = int(self._fps[-2].split(":")[0])
                    if prev_el > 0 and el / prev_el < self.deg_ratio:
                        fb = _load_feedback("degradation")
                        if fb:
                            state.pending_feedback.append(fb)
                except (ValueError, IndexError):
                    pass
            # 元素数恢复正常→重置盲区 episode 标记
            if el > self.deg_abs_max:
                self._blind_fired = False

        return state


# ═══════════════════════════════════════════════════════════
# 能力 3：CompleteVerify（complete 覆盖判定）
# ═══════════════════════════════════════════════════════════

@dataclass
class CompleteVerify:
    """complete 声称成功但最近有操作类工具失败 → 覆盖为失败。

    after_tool 阶段生效。无状态——判定依赖：
    1. snap.any_action_failed（本批次内）
    2. 跨轮扫描：complete 前最近的 action 工具步骤是否失败
       （恢复 DefaultCompletePolicy 的跨轮防作弊守卫——tap 失败后未重新
       observe 验证就 complete(success=true) 应覆盖为 FAILED）
    action_tools 集合从 registry 注入。
    """

    action_tools: frozenset[str] = _ACTION_TOOLS

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "after_tool":
            return state
        ar = snap.action_result
        if ar is None or not ar.is_complete:
            return state
        declared = bool(ar.data.get("success", True))
        if not declared:
            return replace(state, terminal=True, success=False,
                          summary=str(ar.data.get("result", "")))
        # 本批次有操作失败 → 覆盖
        if snap.any_action_failed:
            return replace(state, terminal=True, success=False,
                          summary=str(ar.data.get("result", "")) + " | 覆盖:本批次操作失败")
        # 跨轮扫描：complete 前最近的 action 步骤（跳过 observe/assert 等非操作工具）
        # 若该 action 步骤失败且其后再无成功的 action → 覆盖为 FAILED
        for s in reversed(state.steps):
            if s.action in self.action_tools:
                if not s.success:
                    return replace(state, terminal=True, success=False,
                                  summary=str(ar.data.get("result", "")) + " | 覆盖:上步操作未验证")
                break  # 最近的 action 步骤成功 → 不覆盖
        return replace(state, terminal=True, success=True,
                      summary=str(ar.data.get("result", "")))

    def enrich(self, snap: TurnSnapshot) -> str:
        """PI afterToolCall 对齐：complete 判定后追加归因。"""
        ar = snap.action_result
        if ar is None or not ar.is_complete:
            return ""
        declared = bool(ar.data.get("success", True))
        if declared and snap.any_action_failed:
            return "[System] agent declared success but an action tool in this batch failed; overriding to FAILED"
        return ""


# ═══════════════════════════════════════════════════════════
# 能力 4：FaultTolerance（LLM 连续失败边界）
# ═══════════════════════════════════════════════════════════

@dataclass
class FaultTolerance:
    """LLM 连续调用失败 → 写反馈重试；超上限 → 终止。

    llm_failure 阶段计数+判定；post_llm 阶段（LLM 成功到达）重置。
    内部持 _fails 计数，不写 RunState。
    同一实例需同时注入 llm_failure_caps 与 post_llm_caps 两个列表。
    """

    limit: int = 3
    _fails: int = field(default=0, init=False)

    def reset(self) -> None:
        """外层续跑（_rearm）时清零。"""
        self._fails = 0

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase == "llm_failure":
            self._fails += 1
            if self._fails >= self.limit:
                return replace(state, terminal=True, success=False,
                              summary=f"LLM 连续 {self._fails} 次调用失败")
            fb = _load_feedback("llm_call_failed")
            if fb:
                state.pending_feedback.append(fb)
            return state
        if snap.phase == "llm_success":
            self._fails = 0
            return state
        return state


# ═══════════════════════════════════════════════════════════
# 能力 5：AssertFallback（assert 回退）
# ═══════════════════════════════════════════════════════════

@dataclass
class AssertFallback:
    """终局回退：未成功但已 assert(passed=true) → 视为通过。

    finalize 阶段生效。无状态——纯扫 steps 历史。
    """

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "finalize":
            return state
        if state.success or not snap.assert_tools:
            return state
        # last-assert-wins：最近一次 assert 的结果为准
        for s in reversed(state.steps):
            if s.action in snap.assert_tools:
                # 归一化 passed 为 bool：LLM 可能输出字符串 'true'/'false'
                passed = s.args.get("passed")
                if passed in (True, "true", "True", 1, "1"):
                    return replace(state, success=True,
                                  summary=f"【assert 回退】agent 因步数/停滞终止，但已 assert 成功: {state.summary}")
                return state  # 最近的 assert 是 false → 不回退
        return state


# ═══════════════════════════════════════════════════════════
# 能力 6：PlanFirst（首轮规划注入）
# ═══════════════════════════════════════════════════════════

@dataclass
class PlanFirst:
    """首轮注入规划指令——先分析目标再行动（PI before_task + plan-first 模式）。

    pre_turn 阶段生效，仅 turn 1 注入。无状态——条件完全从 state.turn_count 派生
    （第六条：能派生的就是缓存，不是状态机）。续跑时 turn_count 重置为 0，
    第二个 goal 的 turn 1 会再次注入 plan。
    """

    prompt_file: str = "plan_first"

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "pre_turn":
            return state
        if state.turn_count != 1:
            return state
        # 首轮注入来自 feedback 目录的规划提示
        fb = _load_feedback(self.prompt_file)
        if not fb:
            # fallback: 内联默认
            fb = (
                "Before acting, first output your execution plan in text: "
                "analyze the goal -> identify required tools and steps -> "
                "anticipate potential obstacles. Then begin execution."
            )
        state.pending_feedback.append(fb)
        return state


# ═══════════════════════════════════════════════════════════
# 能力 7：ErrorReflection（无状态反省注入器）
# ═══════════════════════════════════════════════════════════

@dataclass
class ErrorReflection:
    """连续工具失败 → 注入反省提示，基于错误记忆引导恢复。

    无状态——全部从 memory.errors 现算，不持计数器（不违第六条）。
    post_turn 阶段生效。
    错误类型→恢复建议映射从 error_types.yml 加载（不硬编码）。
    """

    reflect_threshold: int = 2  # 连续 2 次失败触发反省
    _error_types: list = field(default_factory=list, init=False)

    def _load_error_types(self) -> list[dict]:
        """懒加载 route_config.yml 的 error_types（首次调用时读，后续缓存）。"""
        if not self._error_types:
            try:
                import yaml
                from pathlib import Path
                p = Path(__file__).resolve().parent.parent / "meta" / "prompts" / "route_config.yml"
                with open(p, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self._error_types = data.get("error_types", [])
            except Exception:
                self._error_types = []
        return self._error_types

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "post_turn":
            return state
        # 从 state.steps 现算尾部连续失败数（无状态——不持计数器）
        fails = self._count_recent_failures(state)
        if fails < self.reflect_threshold:
            return state
        # 取最近错误记录，归纳模式
        errors = self._get_recent_errors(state)
        if not errors:
            return state
        fb = self._build_reflection(state, errors)
        if fb:
            state.pending_feedback.append(fb)
        return state

    @staticmethod
    def _count_recent_failures(state: RunState) -> int:
        """从 state.steps 现算尾部连续失败数（纯派生，不持状态）。"""
        count = 0
        for s in reversed(state.steps):
            if not s.success:
                count += 1
            else:
                break
        return count

    @staticmethod
    def _get_recent_errors(state: RunState) -> list:
        """从 state._memory_ref 取最近错误记录（若有）。"""
        mem = getattr(state, "_memory_ref", None)
        if mem is not None and hasattr(mem, "recent_errors"):
            return mem.recent_errors(3)
        return []

    def _build_reflection(self, state: RunState, errors: list) -> str:
        """归纳错误模式 + 查历史恢复 → 反省文本。"""
        if not errors:
            return ""
        last = errors[-1]
        error_type = getattr(last, "error_type", "unknown")

        # 从 error_types.yml 查恢复建议
        spec = None
        for s in self._load_error_types():
            if s.get("type") == error_type:
                spec = s
                break
        if spec is None:
            spec = {"type": "unknown", "pattern_label": "consecutive tool failures",
                    "recovery_hints": ["observe to re-check current state", "switch tool or approach"]}

        pattern_label = spec.get("pattern_label", "consecutive tool failures")
        hints = spec.get("recovery_hints", [])

        lines = [f"[REFLECTION] consecutive failures, error type: {error_type} ({pattern_label})"]
        for er in errors[-2:]:
            ctx = getattr(er, "context", str(er))[:80]
            lines.append(f"  - {ctx}")
        if hints:
            lines.append("Suggestions:")
            for h in hints[:3]:
                lines.append(f"  - {h}")

        # 查同类型历史成功恢复——"上次用 X 恢复了"
        mem = getattr(state, "_memory_ref", None)
        if mem is not None and hasattr(mem, "last_successful_recovery"):
            rec = mem.last_successful_recovery(error_type)
            if rec and rec.recovery:
                lines.append(f"Previous recovery: {rec.recovery} (successful)")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 能力 8：ToolLoopDetector（查询工具死循环检测——stateless，不违第六条）
# ═══════════════════════════════════════════════════════════

# 默认监控的查询类工具（只读、不改变屏幕，连续重复调用无意义）
_DEFAULT_QUERY_TOOLS: frozenset[str] = frozenset({"ocr", "observe", "run_script"})


@dataclass
class ToolLoopDetector:
    """连续调用同一查询类工具 → 注入停止指令，打断死循环。

    post_turn 阶段生效。无状态——连续调用次数从 state.steps 尾部现算
    （第六条：能派生的就是缓存不是状态机）。超过阈值时注入 tool_loop
    反馈，不强设 terminal——让 LLM 最后一次机会换方法。

    触发条件：steps 尾部连续 >= threshold 次调用同一 query_tool。
    中间插了其他工具立刻重置计数。

    query_tools 默认 {"ocr", "observe"}——observe 的死循环已有
    StagnationDetector 覆盖指纹相同场景，ToolLoopDetector 补指纹变化
    但 LLM 仍在反复 observe 的场景（如页面加载动画每帧不同但无新元素）。
    """

    threshold: int = 3
    query_tools: frozenset[str] = _DEFAULT_QUERY_TOOLS

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "post_turn":
            return state
        tool, consecutive = self._count_tail_loop(state)
        if consecutive < self.threshold:
            return state
        fb = _load_feedback("tool_loop")
        if fb:
            # 将 {tool} 占位符替换为实际工具名
            fb = fb.replace("{tool}", tool)
            state.pending_feedback.append(fb)
        return state

    def _count_tail_loop(self, state: RunState) -> tuple[str, int]:
        """从 state.steps 尾部现算：最后连续的同名 query_tool 及其次数。

        返回 (tool_name, count)。tool_name 为空串表示未检测到循环。
        """
        target: str = ""
        count = 0
        for s in reversed(state.steps):
            if s.action in self.query_tools:
                if target == "":
                    target = s.action
                if s.action == target:
                    count += 1
                else:
                    break  # 不同 query_tool → 不连续
            else:
                break  # 非 query_tool → 打断
        return (target, count)


# ═══════════════════════════════════════════════════════════
# 能力 9：ActionLoopDetector（动作循环检测——签名去重 vs 死循环）
# ═══════════════════════════════════════════════════════════

# 豁免工具：设计上就是重复调用的（滚动/输入/等待/截图）或只读查询（已有 ToolLoopDetector 覆盖）
_LOOP_EXEMPT: frozenset[str] = frozenset({
    "scroll", "scroll_to_find", "type", "type_secret", "wait",
    "wait_and_observe", "screenshot", "fill_fields", "observe", "ocr",
    "current_app", "device_status",
})


def _step_signature(step: "Step") -> str:
    """步骤签名 = tool + 第一个关键参数。同工具不同参数 = 不同签名。"""
    sig = step.action
    for key in ("index", "text", "x", "y", "package", "command", "direction",
                "app", "duration_ms", "seconds"):
        if key in step.args:
            sig += f":{key}={step.args[key]}"
            break
    return sig


@dataclass
class ActionLoopDetector:
    """动作签名重复检测——区分"正常重复"与"死循环"。

    post_turn 阶段生效。从 state.steps 现算签名序列（第六条：派生自 steps，不持状态）。
    豁免 scroll/type/wait 等天然重复的工具。不同参数 = 不同签名 = 不算循环。

    Advisory 提示，不强设 terminal——LLM 自己判断是正常进程还是死循环。
    防抖动：同一模式只注入一次（_last 去重）。
    """

    window: int = 6           # 检测窗口（最近 N 步）
    min_repeat: int = 3       # 同一签名至少出现 N 次才触发
    exempt: frozenset[str] = _LOOP_EXEMPT
    _last: str = ""           # 上次注入的模式标识（防抖动）

    def reset(self) -> None:
        self._last = ""

    def __call__(self, state: RunState, snap: TurnSnapshot) -> RunState:
        if snap.phase != "post_turn":
            return state
        if len(state.steps) < self.window:
            return state

        recent = state.steps[-self.window:]

        # ── 生成签名序列 ──
        sigs: list[str | None] = []
        for s in recent:
            if s.action in self.exempt:
                sigs.append(None)
            else:
                sigs.append(_step_signature(s))

        # ── 统计非豁免签名出现次数 ──
        from collections import Counter
        counts = Counter(s for s in sigs if s is not None)
        repeated = [sig for sig, cnt in counts.items() if cnt >= self.min_repeat]
        if not repeated:
            self._last = ""
            return state

        # ── 防抖动：同模式不重复注入 ──
        pattern_id = "|".join(sorted(repeated))
        if pattern_id == self._last:
            return state
        self._last = pattern_id

        # ── 收集重复签名的步骤详情 ──
        detail_lines: list[str] = []
        seen: set[str] = set()
        for i, sig in enumerate(sigs):
            if sig in repeated and sig not in seen:
                seen.add(sig)
                step = recent[i]
                cnt = counts[sig]
                arg_str = ", ".join(f"{k}={v}" for k, v in list(step.args.items())[:2])
                detail_lines.append(f"  - {step.action}({arg_str}) ×{cnt} (last: step {step.index})")

        lines = [
            "[System — MANDATORY] Your recent actions form a repeating pattern:",
            *detail_lines,
            "",
            "STOP immediately. You are trapped in a loop — continuing the same actions will waste all remaining steps.",
            "1. If this is intentional batch work (filling a form / repeated navigation) → verify one more step then switch tools.",
            "2. If you are stuck → back(), home(), or launch to escape; then observe and form a completely new plan.",
            "3. If all approaches exhausted → complete(success=false) with a clear failure reason.",
            "Do NOT repeat these same actions with different wrappers (run_script, wait_and_observe).",
        ]
        state.pending_feedback.append("\n".join(lines))
        return state
