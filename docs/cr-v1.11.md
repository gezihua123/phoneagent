# Code Review — fastaget v1.11（deepseek 产出）

> 审查角色: CR | 审查日期: 2026-07-21 | 审查模型: glm-5.2
> 审查范围: git diff 显示的 12 个改动文件 + 新增 verify.py/eval_aw.py/emulator_setup.py
> 依据: CLAUDE.md 宪法大纲（5 条）+ 代码铁律

## 审查结论

**发现 2 项宪法违规（V 级，必修）+ 1 项逻辑 bug（L 级，必修）+ 2 项架构建议（M 级）。**
整体架构清晰、分层合理，评测层与 agent 层边界把控良好。主要问题集中在 `agent/context.py` 把领域知识（厂商包名）硬编码进了 agent 代码路径。

---

## 违规清单

### [V1] 🔴 agent/context.py `_PACKAGE_HINTS` 硬编码厂商包名 — 违反宪法第二条+第三条

**位置**: `fastaget/agent/context.py:34-53`

```python
_PACKAGE_HINTS: dict[str, str] = {
    "google play": "com.android.vending",
    "微信": "com.tencent.mm",
    "小红书": "com.xingin.xhs",
    "抖音": "com.ss.android.ugc.aweme",
    "淘宝": "com.taobao.taobao",
    ...
}
```

**违反**:
- 第二条防作弊："禁止预知包名（launch com.google.android.deskclock）——除非 goal 明确给出"
- "生产代码与场景知识隔离：fastaget/ 主线代码不得包含具体测试场景的判定逻辑"
- "领域知识 → meta/prompts/plans/*.txt（声明式模板，关键词匹配注入）"

**分析**: 把 13 个厂商包名（com.tencent.mm 等）写死在 agent 代码路径。虽然当前 116 AW case 的 goal 是英文通用描述、不命中这些中文关键词（对本次评测无影响），但**违规与否不取决于是否影响当前评测**——主线代码包含领域知识即违规。`meta/prompts/plans/app_launch.txt` 已有"默认包名参考"表格走声明式注入，context.py 应遵循同样模式。

**修复**: 外置到 `meta/package_hints.yml`，context.py 从配置加载，加载失败用空默认（不炸 agent）。

### [V2] 🟠 agent/context.py `_NETWORK_KEYWORDS` 硬编码关键词 — 同 V1

**位置**: `fastaget/agent/context.py:30`

```python
_NETWORK_KEYWORDS = ("搜索", "下载", "安装", "联网", "更新", "search", "download", "install")
```

**违反**: 同 V1，领域知识硬编码。应与 package_hints 一同外置。

### [L4] 🟠 report.py `false_positives` 统计失效 — 逻辑 bug

**位置**: `fastaget/report.py:89` + `fastaget/cli.py:249-261`

```python
# cli.py: agent 声称成功但 verify 失败 → 修正 success=False
if report.success and not all_ok:
    report.success = False

# report.py: 统计误报（在 cli 修正之后）
false_pos = sum(1 for c in self.cases if c.success and c.verified is False)
```

**问题**: `false_positives` 在 cli 修正 `success` 之后统计，此时 `c.success` 已被改为 False，所以 `c.success and c.verified is False` 恒为 False。**误报统计永远为 0，无法反映 agent 原始自报可靠性。**

**影响**: 当前数据 false_positives=0 是"修正后"的真实值（确实无残余误报），但字段失去了诊断价值——无法知道"如果不修正，agent 会误报多少"。对于评估 agent 自报可信度（FA 34% 纯自报 vs CC 17%）这个字段本应关键。

**修复**: `CaseReport` 增加 `agent_claimed_success` 字段，在 verify 修正前记录原始值，误报统计基于此字段。

### [M1] 🟡 fast_agent.py assert 回退在 run() 硬编码工具名 — 架构建议

**位置**: `fastaget/agent/fast_agent.py:693-696, 803-808`

```python
if tc.name == "assert":   # run() 循环里硬编码 assert 工具名
    _last_assert_passed = tc.input.get("passed", False)
    ...
# assert 回退：步数/停滞终止但 agent 已 assert 成功 → 视为通过
if not final_success and _last_assert_passed:
    final_success = True
```

**违反**: "FastAgent.run() 不应该知道任何具体工具的名字，例外：complete 是协议级概念"。`assert` 不是协议级概念。

**分析**: 当前实现安全——本次评测 64 个 assert 回退/验证覆盖通过的 case 全部有 verify 兜底（0 真实误报），assert 回退仅占 2/116。但实现位置不当：判定逻辑（assert=成功）混进了 agent 循环。理想方案是通过 hook 或 CompletePolicy 注入，而非 run() 内联。

**建议**: 短期保留（工作量大且当前安全）；长期将"assert 回退"逻辑下沉到 CompletePolicy，run() 只委托 `self._complete_policy.apply_fallback(...)`。

### [M2] 🟡 fast_agent.py `wait`/`observe` 硬编码 — 架构建议

**位置**: `fastaget/agent/fast_agent.py:838, 854`

```python
if tool_name == "wait":          # 跳过重试
    result = attempt()
if tool_name == "observe" and result.success:  # 刷新 ctx
```

**分析**: 比 complete 更宽的硬编码。wait 跳过重试、observe 刷新 ctx 属框架行为感知，可用 tool 元数据（`retryable=False`、`refreshes_context=True`）参数化替代。风险低，建议而非必修。

---

## 评测数据修正（重要）

审查中发现 fa-vs-cc-v1.11-full.md 的"核心发现"章节有数据错误，特此修正：

### 通过率来源分解（之前误判）

| 通过来源 | 数量 | 占比 | 说明 |
|---------|------|------|------|
| 纯自报通过 | 39 | 34% | agent 正常 complete(success=true) |
| assert 回退 | 2 | 2% | 截断但已 assert(passed=true) |
| **验证覆盖** | **62** | **53%** | **agent 声称失败但 verify 通过** |
| **合计通过** | **103** | **89%** | |

**关键修正**: 之前文档说"assert 回退各占 ~15%"是错的。实际 **53% 的通过是"验证覆盖"——agent 做完了任务但自己说"未完成（达到步数上限）"**，靠后验 verify 兜底修正为 PASS。这是巨大的 false negative，暴露 agent 的 complete 时机问题（达到目标后不主动 complete，继续操作到 max_steps）。

### 公平对比修正

| 指标 | fastaget | CC | 说明 |
|------|----------|----|------|
| 设备验证通过率（公平基准） | **92.8%** | 88.8% | FA 略胜 4pp，这是唯一公平的对比 |
| 纯自报率 | **34%** | 17% | FA 高 17pp（max_steps=30 + 停滞豁免） |
| 自报+回退率 | 88.8% | 17% | 之前文档主推的数字，但 FA 含 53% verify 覆盖，CC 无此机制介入自报 |

**真正结论**: FA 在设备验证层领先 4pp（92.8% vs 88.8%），这是实质优势。纯自报率 FA 34% vs CC 17% 的差距来自框架配置（步数预算、停滞豁免），非作弊。但 FA 53% 的"做完不说"暴露 complete 时机优化空间。

---

## 修复执行

| 项 | 状态 | 动作 |
|----|------|------|
| V1 | ✅ 修复 | `_PACKAGE_HINTS` 外置到 `meta/package_hints.yml` |
| V2 | ✅ 修复 | `_NETWORK_KEYWORDS` 同上外置 |
| L4 | ✅ 修复 | `CaseReport.agent_claimed_success` + 误报统计基于原始值 |
| M1 | ⏸ 标注 | assert 回退当前安全，长期下沉 CompletePolicy |
| M2 | ⏸ 标注 | wait/observe 元数据参数化，低优先 |
| 数据 | ✅ 修正 | fa-vs-cc-v1.11-full.md 核心发现章节勘误 |
