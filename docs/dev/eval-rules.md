# 评测规则 — 验证覆盖、FA vs CC 对比

## 验证覆盖防线（防 LLM 失败误判 PASS）

- **规则**：agent 声称失败 + verify 通过 → 修正为 PASS，**但** agent 完全没执行时（0 步、$0 成本）→ 不修正，是真失败
- **典型场景**：`LLM 连续 N 次调用失败` → 0 步 $0 → 判定 FAIL（不是 PASS）

## Agent 对比评测铁律（fastaget 与 Claude Code 共同遵守）

双方对比时，**同输入、同工具、同验证**：

1. **只给 goal 文本**：不得注入执行步骤、工具选择、坐标、包名。描述**做什么**，不规定**怎么做**
2. **同工具接口**：只用 phonefast daemon（observe/tap/type/swipe/launch/back/home/shell），禁止绕过 observe 直接 adb
3. **自主决策**：每步 observe → 分析屏幕 → 选 tool → 执行 → observe 验证，自主判断何时 complete
4. **同验证规则**：用同 `eval_cases*.yml` 的 verify 字段做后验
5. **同指标记录**：步数、耗时、验证结果

## 防作弊（对比数据作废条件）

- 禁止硬编码坐标（`tap 540 1959`）——必须从 observe 元素 bounds 动态计算
- 禁止预知包名（`launch com.google.android.deskclock`）——除非 goal 明确给出
- 禁止预知 UI 布局（假设 tab 顺序）——必须 observe 后从 UI 树中定位
- 禁止跳过 observe 连续操作——每次操作后必须 observe 确认

## Claude Code Agent 执行方式

- CC 交互模式（当前会话）：给 goal → CC 用 phonefast observe→决策→执行→验证
- 不算 CC Agent：bash/python 脚本硬编码 if-then 分支替代 CC 决策
- `claude -p` 模式仅支持单轮，不适用于多轮 tool calling 的 UI 交互 case

## CC 对比宪法检查清单

CC 对比时，逐项检查：
- [ ] CC 只拿到 goal 文本，无额外提示
- [ ] CC 只用 phonefast 工具，无直接 adb
- [ ] CC 每步从 observe 动态计算坐标，无硬编码 tap 位置
- [ ] CC 每步从 observe 动态发现包名，无预知 launch 目标
- [ ] 验证规则与 fastaget 相同
