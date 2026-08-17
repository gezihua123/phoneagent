# fastaget vs Claude Code — 最终对比结论

> 日期: 2026-07-15 | 模型: deepseek-v4-pro | 设备: TECNO SPARK 30C 5G

## 一、核心指标

| 指标 | fastaget | Claude Code | 倍率 |
|------|----------|-------------|------|
| 设备支持场景成功率 | 88% (14/16) | 100% | — |
| 平均 LLM 调用 | 7 次 | 11 turn | FA -36% |
| 平均耗时 | 32s | 55s | FA 1.7x |
| 平均成本 | $0.011 | $0.494 | FA 45x |

## 二、准确率差距归因

CC 的 100% 优势来自 **3 个 FA 可追平的能力**：

| CC 能力 | FA 对策 | 状态 |
|---------|---------|------|
| Bash 任意 shell → adb 回退 | 待加 adb tool | ❌ |
| 27K prompt 含完整包名表 | app_launch 模板 | ✅ |
| swipe+observe 探索循环 | scroll_to_find | ✅ |

**FA 已无法再通过 prompt 优化提升准确率。剩余 12% 差距 = CC 的 Bash 灵活性。**

## 三、设备限制（不可修）

6 个测试用例因设备原因无法通过：
- 亮度调节: Settings 搜索返回 4 个 obfuscated 元素
- 时钟/闹钟/联系人: 系统 App 无 accessibility 支持
- 计算器: 未预装

## 四、FA 架构优势（CC 无法追平）

1. Python API 直连 phonefast（vs Bash 子进程，每步省 50-100ms）
2. 结构化 UIState + processor（vs LLM 手工读文本算坐标）
3. 批量 tool_use（一次 LLM 调多个工具，vs CC 每 turn 1 个 Bash）
4. 停滞检测 + 进度预警 + 指纹去重（vs CC 自由推理）
5. 压缩 system prompt 900 token（vs CC 27K token）

## 五、改善路线图

| P | 项目 | 预期提升 |
|----|------|---------|
| P0 | adb shell 工具 | L3 从 8% → 50%+ |
| P1 | 安装任务稳定性 | T21 间歇→稳定 |
| P1 | 飞行模式模板复测 | T19 通过 |
| P2 | 视觉模式 | 绕过 accessibility 限制 |
| P2 | 批量测试状态隔离 | 消除状态污染 |
