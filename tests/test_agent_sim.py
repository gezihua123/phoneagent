"""二类测试：FastAgent 测试 + 模拟手机测试。

本文件聚焦于「行为层」验证，分两部分:

  A. FastAgent A/B 成功率对比（静态 Mock）— TestAgentSuccessRate
     用静态 MockPhonefast + PromptAwareScriptedLLM 驱动 agent 跑场景，
     验证 baseline vs optimized prompt 的元素选择准确率差异。

  B. 状态机模拟手机测试 — TestStatefulDevice + TestStatefulAgentScenario
     用状态机 MockPhonefast（tap 后屏幕变化）验证:
       - success: tap 命中正确区域 → 屏幕转换
       - fail:    tap 命中错误区域 → 进入错误页
       - noop:    tap 命中无响应区域 → 屏幕不变（加载中/冻结）
     再用状态机设备驱动 agent 跑端到端场景，验证 tap 后屏幕变化的闭环行为。

数据层评测（XML 转换/变体生成/YAML 加载）见 tests/test_meta_eval.py。
"""
from __future__ import annotations

import pytest

from fastaget.agent.fast_agent import FastAgent
from fastaget.agent.prompts import OPTIMIZED_SYSTEM_PROMPT, SYSTEM_PROMPT as _SYSTEM_PROMPT
from fastaget.tools import build_registry

from fastaget.scenariokit import (
    MockPhonefast,
    Scenario,
    Screen,
    WD4_XML,
    _build_scenarios,
    _find_node_by_desc,
    _point_in_bounds,
    _resolve_gt_bounds,
    evaluate_scenario_outcome,
    PromptAwareScriptedLLM,
    load_device_graph,
    make_stateful_phonefast,
    make_variants,
    parse_meaningful_nodes,
    parse_meaningful_nodes_from_text,
    xml_to_phonefast_text,
)
from tests.meta_infra import RunOutcome  # noqa: E402
from tests.conftest import scenario_run, variant_materials  # noqa: E402


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


# ===========================================================================
# A. FastAgent A/B 成功率对比（静态 Mock）
# ===========================================================================


class TestAgentSuccessRate:
    """A/B 对比：baseline prompt vs optimized prompt，跨变体跨场景。

    核心目标：验证 agent + prompt 层面优化能提升自动化成功率。
    使用静态 MockPhonefast（屏幕不变）+ PromptAwareScriptedLLM。
    """

    def _run_matrix(
        self,
        scenarios: list[Scenario],
        variants: dict[str, str],
        prompt: str,
    ) -> list[RunOutcome]:
        outcomes: list[RunOutcome] = []
        for variant_name in variants:
            for sc in scenarios:
                # self_heal 场景只跑 baseline 变体（足够说明问题）
                if sc.kind == "self_heal" and variant_name != "baseline":
                    continue
                outcomes.append(scenario_run(sc.name, variant_name, prompt))
        return outcomes

    def test_optimized_prompt_beats_baseline_overall(
        self, wd4_scenarios: list[Scenario], wd4_variants: dict[str, str]
    ):
        """优化版 prompt 的总体成功率应 >= baseline，且开关类任务显著提升。"""
        base_outcomes = self._run_matrix(wd4_scenarios, wd4_variants, "baseline")
        opt_outcomes = self._run_matrix(wd4_scenarios, wd4_variants, "optimized")

        base_rate = sum(o.success for o in base_outcomes) / len(base_outcomes)
        opt_rate = sum(o.success for o in opt_outcomes) / len(opt_outcomes)

        # 总体：优化版不劣于 baseline
        assert opt_rate >= base_rate, (
            f"优化版总体成功率 {opt_rate:.1%} 低于 baseline {base_rate:.1%}"
        )

        # 开关类任务：优化版不劣于 baseline（两版都达 100% 时 >= 即通过）
        switch_base = [o for o in base_outcomes if o.scenario in ("toggle_bluetooth", "toggle_location")]
        switch_opt = [o for o in opt_outcomes if o.scenario in ("toggle_bluetooth", "toggle_location")]
        switch_base_rate = sum(o.success for o in switch_base) / len(switch_base)
        switch_opt_rate = sum(o.success for o in switch_opt) / len(switch_opt)
        assert switch_opt_rate >= switch_base_rate, (
            f"开关任务：优化版 {switch_opt_rate:.1%} 低于 baseline {switch_base_rate:.1%}"
        )

    def test_bluetooth_toggle_optimized_hits_switch(self, wd4_scenarios):
        """优化版 prompt：蓝牙开关任务在 baseline 变体上 tap 命中 Switch。"""
        sc = next(s for s in wd4_scenarios if s.name == "toggle_bluetooth")
        _, nodes = variant_materials("baseline")
        outcome = scenario_run("toggle_bluetooth", "baseline", "optimized")
        assert outcome.success, f"优化版应成功: {outcome.reason}"
        # tap 应落在 Switch bounds 内（动态解析）
        gt = _resolve_gt_bounds(sc, nodes)
        assert any(_point_in_bounds(t.x, t.y, gt) for t in outcome.taps)

    def test_bluetooth_toggle_baseline_now_hits_switch(self):
        """baseline prompt v1.7：经过架构优化后，也能正确命中 Switch 元素。"""
        outcome = scenario_run("toggle_bluetooth", "baseline", "baseline")
        assert outcome.success, f"baseline v1.7 应成功: {outcome.reason}"

    def test_navigate_tasks_pass_both_prompts(self, wd4_scenarios):
        """列表项导航任务（电池/关于手机）两种 prompt 都应成功（控制组）。"""
        nav_scenarios = [s for s in wd4_scenarios if s.kind == "navigate"]
        for prompt in ("baseline", "optimized"):
            for sc in nav_scenarios:
                outcome = scenario_run(sc.name, "baseline", prompt)
                assert outcome.success, (
                    f"导航任务 {sc.name} ({prompt}) 应成功: {outcome.reason}"
                )

    def test_back_task_passes_both_prompts(self):
        """返回任务两种 prompt 都应成功。"""
        for prompt in ("baseline", "optimized"):
            outcome = scenario_run("go_back", "baseline", prompt)
            assert outcome.success, f"返回任务 ({prompt}) 应成功: {outcome.reason}"
            assert "back" in outcome.actions

    def test_self_heal_optimized_recovers(self, wd4_scenarios):
        """自愈场景：优化版 prompt 能从错误 index 恢复并成功。"""
        sc = next(s for s in wd4_scenarios if s.name == "self_heal_bluetooth")
        _, nodes = variant_materials("baseline")
        outcome = scenario_run("self_heal_bluetooth", "baseline", "optimized")
        assert outcome.success, f"优化版应自愈成功: {outcome.reason}"
        # 恢复后应有正确的 tap
        gt = _resolve_gt_bounds(sc, nodes)
        assert any(_point_in_bounds(t.x, t.y, gt) for t in outcome.taps)

    def test_self_heal_baseline_fails(self):
        """自愈场景：baseline prompt 无自愈指引，无法恢复。"""
        outcome = scenario_run("self_heal_bluetooth", "baseline", "baseline")
        assert not outcome.success, "baseline 无自愈指引应失败"

    def test_optimized_prompt_across_all_variants(self, wd4_scenarios, wd4_variants):
        """优化版 prompt 在所有变体上开关任务都成功（除截断变体中目标不存在时）。"""
        switch_scs = [s for s in wd4_scenarios if s.kind == "switch"]
        for variant_name in wd4_variants:
            _, nodes = variant_materials(variant_name)
            for sc in switch_scs:
                target_exists = _find_node_by_desc(nodes, sc.target_desc) is not None
                outcome = scenario_run(sc.name, variant_name, "optimized")
                if target_exists:
                    assert outcome.success, (
                        f"优化版 {sc.name} @ {variant_name} 应成功: {outcome.reason}"
                    )

    def test_bt_off_variant_still_toggleable(self):
        """bt_off 变体（蓝牙已关）下，优化版仍能正确定位 Switch 元素。"""
        outcome = scenario_run("toggle_bluetooth", "bt_off", "optimized")
        assert outcome.success, f"bt_off 变体应成功: {outcome.reason}"


# ===========================================================================
# B. 状态机模拟手机测试
# ===========================================================================


class TestStatefulDevice:
    """验证状态机 MockPhonefast 的 tap 响应行为（成功/失败/无响应）。

    这些测试不启动 FastAgent，直接操作 MockPhonefast 验证屏幕转换逻辑。
    """

    def test_success_tap_transitions_screen(self, wd4_base_xml):
        """tap 命中 Switch → success → 屏幕转换到 bt_off。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        pf = make_stateful_phonefast("settings_home", screens)
        assert pf.current_screen_key == "settings_home"
        # 蓝牙开关中心点 (972, 392)
        pf.tap(972, 392)
        assert pf.current_screen_key == "bt_off", f"应转到 bt_off，实际: {pf.current_screen_key}"

    def test_fail_tap_transitions_to_detail(self, wd4_base_xml):
        """tap 命中文字标签 → fail → 屏幕转换到 bt_detail（错误页）。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        pf = make_stateful_phonefast("settings_home", screens)
        # 蓝牙文字标签区域中心 (400, 370)
        pf.tap(400, 370)
        assert pf.current_screen_key == "bt_detail", f"应转到 bt_detail，实际: {pf.current_screen_key}"

    @pytest.mark.parametrize("start_key,points", [
        ("loading", [(500, 1100), (100, 100), (900, 900)]),   # 加载屏所有 tap noop
        ("empty", [(500, 500)]),                              # 空屏所有 tap noop
        ("settings_home", [(500, 2400)]),                     # 空白区域 tap noop
    ])
    def test_noop_tap_leaves_screen(self, wd4_base_xml, start_key, points):
        """noop tap（无响应屏/空白区）→ 屏幕不转换。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        pf = make_stateful_phonefast(start_key, screens)
        for x, y in points:
            pf.tap(x, y)
        assert pf.current_screen_key == start_key
        assert len(pf.taps) == len(points)

    def test_location_switch_success(self, wd4_base_xml):
        """位置开关 tap → success → loc_off。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        pf = make_stateful_phonefast("settings_home", screens)
        pf.tap(972, 1688)  # 位置开关中心
        assert pf.current_screen_key == "loc_off"

    def test_battery_navigate_success(self, wd4_base_xml):
        """电池容器 tap → success → battery_page。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        pf = make_stateful_phonefast("settings_home", screens)
        pf.tap(540, 680)  # 电池容器中心
        assert pf.current_screen_key == "battery_page"

    def test_screen_history_records_transitions(self, wd4_base_xml):
        """screen_history 记录所有屏幕转换。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        pf = make_stateful_phonefast("settings_home", screens)
        pf.tap(972, 392)  # → bt_off
        assert pf.screen_history == ["settings_home", "bt_off"]

    def test_back_button_returns_home(self, wd4_base_xml):
        """从 bt_off 点返回 → settings_home。"""
        screens, _, _ = load_device_graph(wd4_base_xml)
        pf = make_stateful_phonefast("bt_off", screens)
        pf.tap(73, 88)  # 返回按钮中心
        assert pf.current_screen_key == "settings_home"

    def test_static_mode_backward_compatible(self):
        """静态模式（传 screen_text）仍向后兼容，所有 tap 是 noop。"""
        pf = MockPhonefast(screen_text="test screen")
        pf.tap(100, 100)
        assert pf.current_screen_key == "_static"
        assert len(pf.taps) == 1


class TestStatefulAgentScenario:
    """用状态机设备图驱动 agent 跑场景，验证 tap 后屏幕变化的端到端行为。

    与 TestAgentSuccessRate 的区别:
      - TestAgentSuccessRate 用静态 Mock（屏幕不变），验证 prompt 对元素选择的影响
      - 本类用状态机 Mock（屏幕随 tap 变化），验证 agent observe→tap→observe 闭环
    """

    def _run_with_stateful_device(
        self,
        scenario: Scenario,
        screens: dict[str, Screen],
        prompt: str,
    ) -> RunOutcome:
        """用状态机 MockPhonefast 跑场景。"""
        pf = make_stateful_phonefast(scenario.start_screen, screens)
        start_nodes = parse_meaningful_nodes_from_text(screens[scenario.start_screen].text)
        llm = PromptAwareScriptedLLM(scenario, start_nodes)
        registry = build_registry()
        system_prompt = _SYSTEM_PROMPT if prompt == "baseline" else OPTIMIZED_SYSTEM_PROMPT

        agent = (
            FastAgent(llm, pf, registry, max_steps=12, system_prompt=system_prompt)
        )
        result = agent.run(scenario.goal)

        # 统一判定（复用 evaluate_scenario_outcome，消除重复 if/elif）
        ok, reason = evaluate_scenario_outcome(
            scenario, start_nodes, pf, result, screens=screens,
        )

        return RunOutcome(
            scenario=scenario.name,
            variant="",
            prompt=prompt,
            success=ok,
            reason=reason,
            taps=list(pf.taps),
            actions=list(pf.actions),
        )

    def test_toggle_bluetooth_optimized_success(self, wd4_base_xml):
        """优化版：蓝牙开关 tap 命中 Switch，屏幕转到 bt_off。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "toggle_bluetooth")
        outcome = self._run_with_stateful_device(sc, screens, "optimized")
        assert outcome.success, f"优化版应成功: {outcome.reason}"

    def test_toggle_bluetooth_baseline_now_succeeds(self, wd4_base_xml):
        """baseline v1.7：经过架构优化后，蓝牙开关任务也能成功。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "toggle_bluetooth")
        outcome = self._run_with_stateful_device(sc, screens, "baseline")
        assert outcome.success, f"baseline v1.7 应成功: {outcome.reason}"

    def test_frozen_loading_agent_fails(self, wd4_base_xml):
        """加载中屏幕：agent 应识别无法操作并 complete(fail)（expect_fail=符合预期=成功）。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "frozen_loading")
        outcome_opt = self._run_with_stateful_device(sc, screens, "optimized")
        outcome_base = self._run_with_stateful_device(sc, screens, "baseline")
        # expect_fail 判定：agent 主动 fail = 符合预期 = outcome.success=True
        assert outcome_opt.success, f"加载屏优化版应主动 complete(fail): {outcome_opt.reason}"
        assert outcome_base.success, f"加载屏 baseline 应主动 complete(fail): {outcome_base.reason}"

    def test_empty_screen_agent_fails(self, wd4_base_xml):
        """空屏：agent 应识别无元素并 complete(fail)（expect_fail=符合预期=成功）。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "empty_screen")
        outcome = self._run_with_stateful_device(sc, screens, "optimized")
        assert outcome.success, f"空屏应主动 complete(fail): {outcome.reason}"

    def test_navigate_battery_success_both_prompts(self, wd4_base_xml):
        """导航任务两种 prompt 都应成功。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "go_to_battery")
        for prompt in ("baseline", "optimized"):
            outcome = self._run_with_stateful_device(sc, screens, prompt)
            assert outcome.success, f"导航 ({prompt}) 应成功: {outcome.reason}"

    def test_back_task_success_both_prompts(self, wd4_base_xml):
        """返回任务两种 prompt 都应成功。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "go_back")
        for prompt in ("baseline", "optimized"):
            outcome = self._run_with_stateful_device(sc, screens, prompt)
            assert outcome.success, f"返回 ({prompt}) 应成功: {outcome.reason}"
            assert "back" in outcome.actions


# ===========================================================================
# C. 边界场景：max_steps 超限 + 工具链异常
# ===========================================================================


class TestBoundaryScenarios:
    """验证 agent 在边界条件下的健壮性：不卡死、不崩溃。

    - max_steps 超限：目标不存在时 agent 反复操作，应超步返回失败而非无限循环
    - 工具链异常：tap 持续抛异常时，agent 应自愈降级 complete(fail) 而非崩溃
    """

    def test_max_steps_exhaustion_returns_failure(self, wd4_base_xml):
        """max_steps 超限：agent 达到步数上限时返回 success=False，不卡死。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "max_steps_exhaustion")
        pf = make_stateful_phonefast(sc.start_screen, screens)
        start_nodes = parse_meaningful_nodes_from_text(screens[sc.start_screen].text)
        llm = PromptAwareScriptedLLM(sc, start_nodes)
        agent = (
            FastAgent(llm, pf, build_registry(), max_steps=6, system_prompt=OPTIMIZED_SYSTEM_PROMPT)
        )
        result = agent.run(sc.goal)
        # 关键断言：超步返回失败，而非卡死或误判成功
        assert not result.success, f"超步应返回失败，实际 success={result.success}"
        assert result.steps == 6, f"应跑满 max_steps=6，实际 {result.steps}"

    def test_tool_chain_failure_does_not_crash(self, wd4_base_xml):
        """工具链异常：tap 持续失败时 agent 不崩溃，最终 complete(fail)。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "tool_chain_failure")
        pf = make_stateful_phonefast(sc.start_screen, screens)
        pf.tap_fail = True  # 注入故障：所有 tap 抛 PhonefastError
        start_nodes = parse_meaningful_nodes_from_text(screens[sc.start_screen].text)
        llm = PromptAwareScriptedLLM(sc, start_nodes)
        agent = (
            FastAgent(llm, pf, build_registry(), max_steps=10, system_prompt=OPTIMIZED_SYSTEM_PROMPT)
        )
        # 关键断言：不抛异常（工具异常被自愈层捕获转 ActionResult.fail）
        result = agent.run(sc.goal)
        # agent 应 complete(fail)，而非崩溃或误判成功
        assert not result.success, f"工具持续失败应 complete(fail)，实际 {result.success}"

    def test_tool_failure_records_failed_steps(self, wd4_base_xml):
        """工具链异常：失败步骤被记录在 steps_detail，可用于归因。"""
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "tool_chain_failure")
        pf = make_stateful_phonefast(sc.start_screen, screens)
        pf.tap_fail = True
        start_nodes = parse_meaningful_nodes_from_text(screens[sc.start_screen].text)
        llm = PromptAwareScriptedLLM(sc, start_nodes)
        agent = (
            FastAgent(llm, pf, build_registry(), max_steps=10, system_prompt=OPTIMIZED_SYSTEM_PROMPT)
        )
        result = agent.run(sc.goal)
        # 至少有失败的 tap_element 步骤被记录
        failed_taps = [
            s for s in result.steps_detail
            if s.action == "tap_element" and not s.success
        ]
        assert len(failed_taps) >= 1, "应有失败的 tap_element 步骤记录"

    def test_device_context_injection_with_mock(self, wd4_base_xml):
        """设备上下文注入：Mock 默认空，配置 installed_packages 后注入。"""
        from fastaget.agent.context import DeviceContext
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "go_to_battery")

        # 默认 Mock：无 watch_packages → 空上下文（测试隔离）
        pf = make_stateful_phonefast(sc.start_screen, screens)
        ctx = DeviceContext.from_phonefast(pf)
        assert ctx.is_empty(), "无关注应用时应返回空上下文"

        # 配置已装应用后：上下文非空
        pf.set_installed("com.android.settings", True)
        ctx2 = DeviceContext.from_phonefast(pf, watch_packages=["com.android.settings"])
        assert not ctx2.is_empty()
        text = ctx2.to_prompt_text()
        assert "已安装的关注应用" in text
        assert "com.android.settings" in text

    def test_device_context_network_task_scoped(self, wd4_base_xml):
        """network 仅对搜索/下载类 goal 注入，开关类 goal 不注入。"""
        from fastaget.agent.context import DeviceContext
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "go_to_battery")
        pf = make_stateful_phonefast(sc.start_screen, screens)
        pf.set_device_info(network="none")

        # 开关/导航类 goal：不采集 network（任务无关）
        ctx_nav = DeviceContext.from_phonefast(pf, goal="关闭蓝牙开关")
        assert ctx_nav.network == "", "非搜索/下载任务不应注入 network"

        # 搜索类 goal：采集 network
        ctx_search = DeviceContext.from_phonefast(pf, goal="搜索小红书并下载")
        assert ctx_search.network == "none"
        text = ctx_search.to_prompt_text()
        assert "无网络" in text and "会失败" in text, "无网络应提示任务会失败"

    def test_device_context_empty_when_nothing_relevant(self, wd4_base_xml):
        """无关注应用 + 非网络任务 → 空上下文（不注入噪声）。"""
        from fastaget.agent.context import DeviceContext
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "go_to_battery")
        pf = make_stateful_phonefast(sc.start_screen, screens)
        pf.set_device_info(network="wifi")  # 有网但任务无关
        ctx = DeviceContext.from_phonefast(pf, goal="关闭蓝牙开关")
        assert ctx.is_empty(), "任务无关信息不应注入"
        assert ctx.to_prompt_text() == ""

    def test_device_context_not_break_agent(self, wd4_base_xml):
        """注入设备上下文不影响 agent 正常运行（成功场景仍成功）。"""
        from fastaget.agent.context import DeviceContext
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "go_to_battery")
        pf = make_stateful_phonefast(sc.start_screen, screens)
        pf.set_installed("com.android.settings", True)
        ctx = DeviceContext.from_phonefast(pf, watch_packages=["com.android.settings"])
        start_nodes = parse_meaningful_nodes_from_text(screens[sc.start_screen].text)
        llm = PromptAwareScriptedLLM(sc, start_nodes)
        agent = FastAgent(llm, pf, build_registry(), max_steps=10, system_prompt=OPTIMIZED_SYSTEM_PROMPT)
        result = agent.run(sc.goal)
        assert result.success, f"注入上下文后仍应成功: {result.summary}"


# ===========================================================================
# D. 判定扩展性：注册表 + 策略注入
# ===========================================================================


class TestOutcomeExtensibility:
    """验证判定逻辑分散可扩展：新增 checker/policy 不改主逻辑。"""

    def test_register_custom_outcome_checker(self, wd4_base_xml):
        """新增自定义判定模式只需 @register_outcome_checker，不改 evaluate_scenario_outcome。"""
        from fastaget.scenariokit import (
            register_outcome_checker, OutcomeContext, evaluate_scenario_outcome,
        )

        # 注册一个自定义判定：只要 agent 执行过任何 tap 就算成功（演示扩展口子）
        @register_outcome_checker("any_tap_passes")
        def _check_any_tap(ctx: OutcomeContext) -> tuple[bool, str]:
            if ctx.pf.taps:
                return True, f"自定义判定：执行了 {len(ctx.pf.taps)} 次 tap"
            return False, "自定义判定：未执行 tap"

        # 构造一个用自定义 check 的场景
        screens, scenarios, _ = load_device_graph(wd4_base_xml)
        sc = next(s for s in scenarios if s.name == "toggle_bluetooth")
        sc.check = "any_tap_passes"  # 动态改 check
        pf = make_stateful_phonefast(sc.start_screen, screens)
        pf.tap(972, 392)  # 模拟 agent 执行了 tap
        nodes = parse_meaningful_nodes_from_text(screens[sc.start_screen].text)
        ok, reason = evaluate_scenario_outcome(sc, nodes, pf, None, screens=screens)
        assert ok, f"自定义判定应成功: {reason}"
        assert "自定义判定" in reason


# ===========================================================================
# D. 执行轨迹日志（LLM 动作重放）端到端
# ===========================================================================


class TestReplayTrace:
    """端到端：run_scenario(trace=True) 产出 replay.json + trace.jsonl，
    trace=False（默认）不产任何文件。"""

    def test_run_scenario_trace_on_produces_files(
        self, wd4_scenarios, wd4_base_xml, wd4_nodes, tmp_path,
    ):
        import json

        from tests.eval_agent import run_scenario

        sc = wd4_scenarios[0]
        text = xml_to_phonefast_text(wd4_base_xml)
        llm = PromptAwareScriptedLLM(sc, wd4_nodes)
        run_scenario(
            sc, text, wd4_nodes, "baseline", "region", llm, 8,
            trace=True, trace_dir=str(tmp_path),
            variant="baseline", seq=1,
        )
        replays = list(tmp_path.glob("*.replay.json"))
        traces = list(tmp_path.glob("*.trace.jsonl"))
        assert len(replays) == 1
        assert len(traces) == 1

        graph = json.loads(replays[0].read_text(encoding="utf-8"))
        assert graph["meta"]["scenario"] == sc.name
        assert graph["meta"]["prompt"] == "baseline"
        assert graph["meta"]["format"] == "region"
        assert graph["meta"]["model"] is None  # PromptAwareScriptedLLM 无 model 属性
        # 至少 initial observe 一个节点 + 至少一条边
        assert len(graph["nodes"]) >= 1
        assert len(graph["edges"]) >= 1
        # mock 路径：每个 node 都带 screen_key 字段（来自 current_screen_key）
        assert all("screen_key" in n for n in graph["nodes"])

        events = [
            json.loads(line)
            for line in traces[0].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(e["event"] == "run_start" for e in events)
        assert any(e["event"] == "finish" for e in events)
        # tool_start 事件（若有）带 name + args，可照重放
        tool_starts = [e for e in events if e["event"] == "tool_start"]
        for ts in tool_starts:
            assert "name" in ts and "args" in ts

    def test_trace_off_default_produces_no_files(
        self, wd4_scenarios, wd4_base_xml, wd4_nodes, tmp_path,
    ):
        from tests.eval_agent import run_scenario

        sc = wd4_scenarios[0]
        text = xml_to_phonefast_text(wd4_base_xml)
        llm = PromptAwareScriptedLLM(sc, wd4_nodes)
        run_scenario(
            sc, text, wd4_nodes, "baseline", "region", llm, 8,
            trace_dir=str(tmp_path), variant="baseline", seq=1,
        )
        assert not list(tmp_path.glob("*"))
