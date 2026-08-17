# 架构分层与核心决策

## 逻辑下沉，不要堆在 Agent 里

- 设备层 → `device/`（ScreenObserver、UIProcessor）
- 工具层 → `tools/`（Action 类、ToolRegistry）
- 提示词 → `meta/prompts/`（baseline.txt、kb/*.txt、feedback/*.txt）
- 判定层 → 能力管道（`agent/capabilities.py`）/ checker 装饰器注册
- 评测层 → `verify.py`（shell 验证）+ `eval_aw.py`（AW 式编排）
- FastAgent.run() 只做编排：observe→LLM→tool→loop

## 评测层与 Agent 代码的硬边界

评测层模块（`verify.py`、`sqlite_verify.py`、`eval_aw.py`）**不得被 agent 代码路径 import**：
- `fastaget/agent/` — 零依赖评测层
- `fastaget/tools/` — 零依赖评测层
- `fastaget/device/` — 零依赖评测层
- `fastaget/cli.py` — 零 SQLite/root 代码
- `fastaget/cases/` — Case 数据不含 SQLite 验证字段

验证入口仅在 `eval_aw.py` 层调用，agent 完全不知晓。

## Agent 与验证的运行环境分离

- **Agent 执行层**：真机上跑，通过 phonefast daemon 交互。工具链、prompt、自愈策略均基于真机环境设计
- **评测判定层**：模拟器（Android Emulator）上做独立验证（AndroidWorld 式 `is_successful(env)`）。
  验证逻辑不与 agent 共享任何代码路径——agent 不知道、不调用、不受影响
- **禁止**：用模拟器环境优化 agent 执行策略（如"模拟器 UI 树完整所以优先读 UI 元素"）。
  真机环境的残缺性（国产 ROM accessibility 缺失）是 agent 必须面对的客观约束
- **允许**：评测时用模拟器的 root 权限做深层验证（SQLite 直读、content provider、文件系统），
  这些验证能力不暴露给 agent
- Shell 验证优先（`settings get`、`pm list`、`dumpsys activity`）— 真机/模拟器通用
- SQLite 验证仅在模拟器 userdebug 镜像上做（`adb root` + `/system/bin/sqlite3`）— 不暴露给 agent
- Content provider 验证（`content query --uri content://sms`）— 真机/模拟器通用

## 核心架构决策

- **模型**: deepseek-v4-pro（thinking 已通过 ModelCapabilities 关闭——ReAct 循环只需动作输出，不必推理）
- **Plan**: 融入首轮（无独立 plan call）；domain 模板匹配时加 plan 指令
- **auto-observe**: ScreenObserver 封装，内建指纹去重 + 文本压缩
- **tool-calling**: 原生 Anthropic Messages API，砍掉正则解析
- **四层自愈**: L1 设备 I/O → L2 工具执行 → L3 模型调用 → L4 编排注入

## 参数化优于内联

- ClassVar 类常量 > 构造函数参数 > 方法默认值 > 内联字面量
- 不要让调用方 hack 私有属性（如 `self.observer._prev_fp`）
- 测试问题在测试代码中修，不为了通过测试改 agent 代码

## 关键模块

| 模块 | 文件 | 职责 |
|------|------|------|
| Agent 主循环 | fast_agent.py | 3 阶段状态管道（_init→_llm_turn→executor.turn） |
| LLM 委托 | anthropic_http_delegate.py | HTTP 直连 API + tool_choice 结构化输出 |
| 工具执行引擎 | tools/tool_executor.py | 解析+执行+效果解释+轮末观察，委托护栏 |
| 状态机护栏 | tools/progress.py, tools/guards.py, agent/guards.py | ProgressGuard/CompleteGuard/ProtocolGuard（5 上限，宪法第六条） |
| 工具注册+执行 | tools/registry.py, actions.py | 工具定义+兜底异常+元数据分类 |
| 屏幕观察 | device/screen_observer.py | observe+去重+压缩 |
| 设备执行 | device/phonefast.py | Unix Socket 直连 daemon |
| 声明式配置 | meta/tools.yml, scenarios.yml | 工具定义+场景+GT |
| 提示词 | meta/prompts/ | baseline/kb/feedback（见 prompts.md） |
| 评测验证 | verify.py | AndroidWorld 式独立验证（真机 shell） |
