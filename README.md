# fastaget — 准确的 Android 自动化测试 AI Agent

> 构建**准确**的自动化测试 AI Agent。
>
> **准确** = 操作准确（LLM 选的元素与设备一致）＋ 判定准确（基于设备事实）＋ 稳定可重复。

Agent 只接收自然语言 goal，自主决策：观察屏幕 → 调用工具 → 循环，直至完成任务或触顶步数。设备交互走 [phonefast](https://github.com/gezihua123/phonefast) 执行器，评测判定与 Agent 执行**硬隔离**——成功率永远以设备端独立验证为准，而非 Agent 自报。

## 演示

![fastagent 演示](docs/fastagent.gif)

## 特性

- **纯 goal 驱动** — 入参只有自然语言，无步骤/坐标/包名注入，Agent 自主规划
- **防作弊设计** — 坐标从 observe 动态计算、包名靠搜索发现，禁止 shell 冒充 app 操作
- **执行与判定分离** — 评测层（`verify.py` / `eval_aw.py`）独立验证设备状态，与 Agent 代码零 import
- **四层自愈** — L1 设备 I/O → L2 工具执行 → L3 模型调用 → L4 编排注入
- **多设备安全** — adb 只走 `pf.shell()`，CLI 层创建注入 Phonefast，多设备必须 `--serial`
- **声明式 flow 测试** — YAML 驱动的流程图用例（`fastaget flow run`），带独立判定模型
- **原生 tool-calling** — 走 Anthropic Messages API 协议，无正则解析

## 快速开始

```bash
# 1. 安装
pip install -e .            # 依赖：httpx / pyyaml / rich（Python >= 3.10）

# 2. 配置 LLM 端点（key 走环境变量，不进代码）
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_AUTH_TOKEN="sk-xxx"
unset ANTHROPIC_MODEL       # 让 --model 参数生效

# 3. 确保 phonefast daemon 已连接目标设备（emulator-5554 或真机）

# 4. 跑一个任务
python -m fastaget.cli run \
  --serial emulator-5554 \
  --model deepseek-v4-pro \
  --max-steps 15 \
  --trace \
  "打开camera 拍照,并且分享到小红书"
```

首次使用建议先跑 `python -m fastaget.cli doctor --model deepseek-v4-pro` 诊断执行器与模型配置。

## CLI

```bash
fastaget devices                 # 列出已连接设备
fastaget observe                 # observe 一次并打印 UI 元素
fastaget doctor [--model M]      # 诊断执行器与模型配置
fastaget run [GOAL] [选项]       # LLM agent 执行测试目标（或 -f 用例 YAML 批量）
fastaget flow run -f file.yaml   # 声明式流程图测试（可配独立 --judge-model）
```

`run` 常用选项：

| 选项 | 说明 |
|------|------|
| `goal` / `-f FILE` | 自然语言目标 / 用例 YAML（可批量） |
| `--serial` | 目标设备 serial（多设备必须指定，防连错；单设备自动检测） |
| `--model` | 模型名（默认 `deepseek-v4-pro`） |
| `--max-steps` | 最大步数（默认 15） |
| `--error-thresh` | 连续失败阈值（默认 3） |
| `--vision` | 视觉模式：截图喂多模态模型 |
| `--trace` | 记录 trace（默认 `build/traces`，可重放） |
| `--verbose-timing` | 打印每步耗时、LLM 决策、工具执行详情 |

## 架构

```
fastaget/
├── agent/        # Agent 主循环（3 阶段状态管道）、LLM delegate、护栏、上下文
├── device/       # ScreenObserver（observe+去重+压缩）、Phonefast 设备执行
├── tools/        # ToolRegistry、动作工具、sandbox、credential
├── llm/          # HTTP 直连 Anthropic Messages API 委托
├── flow/         # 声明式流程图测试（case/condition/expectation/judge/runner）
├── heal/         # 四层自愈策略
├── meta/         # prompts（baseline/kb/feedback）、场景与用例 YAML、凭证定义
├── aw_native/    # AndroidWorld 评测（shim + vendor task_evals）
├── verify.py     # AndroidWorld 式独立验证（评测层，Agent 不可 import）
└── eval_aw.py    # AW 式评测编排（评测层）
```

核心决策（详见 [docs/dev/architecture.md](docs/dev/architecture.md)）：

- **Plan 融入首轮** — 无独立 plan call；domain 模板匹配时加 plan 指令
- **auto-observe** — ScreenObserver 内建指纹去重 + 文本压缩
- **一切异常转结构化结果** — 工具异常 → `ActionResult(success=False)`；LLM 失败 → 注入错误提示，不丢消息历史
- **成功率铁律** — 成功率 = 设备验证通过率（`TaskEval.is_successful(pf)`），与 Agent 自报率严格区分展示

## 设计宪法（七条）

1. Agent 只收 goal，自主决策
2. 防作弊（无硬编码坐标/包名/UI 假设，shell 仅查询不冒充 app 操作）
3. 评测层与 Agent 代码硬隔离
4. CC Agent 执行定义（CC 交互模式 + phonefast 工具 + 动态坐标）
5. 通用优化优先于 case 特判
6. 状态机纪律（上限 5，见 [docs/dev/constitution.md](docs/dev/constitution.md)）
7. 框架无能区 — 信息归 LLM、事实归设备、裁决归评测层

完整版见 [docs/dev/constitution.md](docs/dev/constitution.md) 与项目根 [CLAUDE.md](CLAUDE.md)。

## 测试

```bash
pip install -e ".[dev]"
pytest                        # 单测（Mock 驱动，无需真机/模拟器）
```

## 文档索引

| 文档 | 内容 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | 项目宪法（精简版）：红线、开发流程、CR 检查清单 |
| [docs/dev/constitution.md](docs/dev/constitution.md) | 宪法七条完整版：边界判定、状态机四条件与 5 个 sanctioned 实例 |
| [docs/dev/architecture.md](docs/dev/architecture.md) | 架构分层、硬边界、关键模块表、核心架构决策 |
| [docs/dev/device-safety.md](docs/dev/device-safety.md) | 多设备三层防线、评测环境准备、LLM 端点配置 |
| [docs/dev/eval-rules.md](docs/dev/eval-rules.md) | 评测铁律、验证覆盖、对比规则 |
| [docs/dev/prompts.md](docs/dev/prompts.md) | 提示词原则、prompts 目录结构与注入时机 |
| [docs/](docs/) | 各轮评测分析、架构演进与对比报告 |

## 开发流程

四人角色协作：**TL**（架构决策）→ **RD**（实现）→ **CR**（逐行审查）→ **QA**（评测归因）→ 回到 TL。详见 [CLAUDE.md](CLAUDE.md) 的「团队角色与开发流程」。
