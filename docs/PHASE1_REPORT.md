# FastAgent 第一期完成报告

> 日期：2026-07-13
> 状态：第一期完成，进入第二期

## 一、目标与达成

### 第一期定义目标（agents.md）

| 目标 | 达成 |
|------|------|
| 模拟环境（MockPhonefast + 脚本化 LLM） | ✅ 状态机 Mock + 8 种 kind 脚本化 |
| 打磨 agent 循环稳定性 | ✅ 原生 tool-calling，零解析失败 |
| 工具链正确性 | ✅ 异常转 ActionResult，四层自愈 |

**三项核心目标全部达成。**

## 二、测试覆盖

| 测试层 | 数量 | 状态 |
|--------|------|------|
| fastaget 单元测试（flow/registry/heal/...） | 42 | ✅ |
| agent 模拟测试（A/B + 状态机 + 扩展性） | 30 | ✅ |
| scenariokit 独立单测（纯域） | 19 | ✅ |
| **合计** | **152** | **全部通过** |

### 13 个场景覆盖 8 种执行能力

| 能力 | 场景 | 判定模式 |
|------|------|---------|
| 开关选择 | toggle_bluetooth, toggle_location | tap_in_gt |
| 容器导航 | go_to_battery, scroll_to_find | tap_in_gt |
| 返回工具 | go_back | action_match |
| index 错误恢复 | self_heal_bluetooth | tap_in_gt |
| 无响应识别 | frozen_loading, empty_screen | expect_fail |
| 状态感知 | verify_bluetooth_off | no_change_success |
| 输入流程 | search_setting | action_all |
| 错误恢复 | recover_from_detail | tap_in_gt |
| 边界健壮性 | max_steps_exhaustion, tool_chain_failure | expect_fail |

## 三、真实 LLM 评测（第二期前置）

| 指标 | 结果 |
|------|------|
| 成功率 | 13/13 = 100%（deepseek-v4-flash + optimized + region） |
| 平均步数 | 5.5 步/场景 |
| 平均耗时 | 6.4s/场景 |
| 平均成本 | $0.0034/场景 |

## 四、架构原则（8 条，写入 agents.md）

1. 生产代码与场景判定隔离
2. 原生 tool-calling，不引入文本解析框架
3. 一切异常转结构化结果，不炸断循环
4. 上下文通过参数注入，不在循环里加分支
5. 声明式测试定义，数据与逻辑分离
6. 模拟优先，真机在后
7. 少一层抽象，少一层 bug
8. 判定逻辑分散，不集中在一处

## 五、代码结构

```
fastaget/              生产代码（agent 引擎，通用，无场景知识）
├── agent/             FastAgent + hooks + history + context + policy
├── tools/             ToolRegistry + actions（is_action 元数据）
├── device/            phonefast + uistate + uiprocessor
├── heal/              四层自愈重试
├── llm/               LLMDelegate + AnthropicHTTPDelegate
└── flow/              flow 引擎 + SemanticJudge（tool-calling）

scenariokit/           场景工具包（独立成包，可被外部调用）
├── xmltext/           XML↔phonefast 文本
├── variants/          变体生成
├── device/            MockPhonefast 状态机
├── scenarios/         Scenario + YAML 加载
├── outcomes/          判定器注册表
└── scripted/          PromptAwareScriptedLLM

meta/                  声明式数据（非开发人员可编辑）
├── prompts/           baseline/optimized/judge + feedback/
├── tools.yml          14 工具定义
├── scenarios.yml      13 场景 + 16 屏幕
└── wd4.xml            测试数据
```

## 六、关键技术决策

| 决策 | 理由 |
|------|------|
| 原生 tool-calling 而非 LangChain | 2026 年原生 tool_use 已成熟，框架层成累赘 |
| scenariokit 独立成包 | 1488 行单文件拆为 6 模块，纯域可独立测 |
| 判定注册表 + 策略注入 | 新增判定=写函数+装饰器，主逻辑零改动 |
| judge 改 tool-calling | 输入输出协议级结构化，零文本解析 |
| 设备上下文任务相关注入 | 只注入改变决策的字段，不全量堆砌 |
| is_action 工具元数据 | mark_action 独立标记，不侵入 register 接口 |

## 七、剩余风险（第二期/第三期关注）

| 风险 | 影响 | 缓解 |
|------|------|------|
| tool_chain_failure 偶发误判 | LLM 凭空 complete(success) | CompletePolicy 覆盖最后操作失败；prompt 强化 |
| 真机 I/O 未验证 | 第三期风险 | phonefast daemon 路径已就绪，待真机测试 |
| 视觉模式（vision）未测 | 多模态场景缺口 | 第三期补 vision=True 测试 |
| 多 model 矩阵未跑 | glm-5.2 未验证 | 第二期 B 阶段跑 |

## 八、结论

第一期目标全部达成，且超额完成第二期前置能力（真实 LLM 评测、判定分散、结构化 IO、scenariokit 独立包）。模拟基础设施稳定，152/152 测试通过，可正式进入第二期。
