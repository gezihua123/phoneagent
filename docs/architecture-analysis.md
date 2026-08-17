# AndroidWorld 架构分析：验证 + 对比 + 复杂链路设计

> 基于 google-research/android_world 源码分析，对比 fastaget 现状，给出实施路径

## 1. AndroidWorld 的核心设计

### 1.1 验证模型——确定性程序验证，非 agent 自评

```
fastaget 现状:  agent 执行 → agent 调 complete(success=True) → eval 通过
                 ↑ 问题：agent 声称"WiFi 已关闭"，但你不知道是不是真的关了

AndroidWorld:   agent 执行 → TaskEval.is_successful(env) → 设备 shell 命令独立验证
                ↑ 命令如：settings get global wifi_on → 读返回值 → 0=关 1/2=开
```

每个 Task 的 `is_successful()` 是一个**纯函数**：读设备状态 → 返回 0.0~1.0。agent 的 `complete` 声明不影响分数。

```python
# AndroidWorld: brightness 验证（system.py:41-52）
def is_successful(self, env):
    res = adb_utils.issue_generic_request(
        ['shell', 'settings', 'get', 'system', 'screen_brightness'],
        env.controller,
    )
    brightness = int(res.generic.output.decode().strip())
    return 1.0 if brightness == 255 else 0.0  # max → 255, min → 1
```

### 1.2 任务变体设计——4 类变体覆盖能力维度

每个操作类任务拆成 4 个变体，分离"改变状态"和"验证状态"：

```
SystemWifiTurnOn          → 前提：WiFi 关 → agent 需主动开
SystemWifiTurnOff         → 前提：WiFi 开 → agent 需主动关
SystemWifiTurnOnVerify    → 前提：WiFi 已开 → agent 只需确认（不要操作！）
SystemWifiTurnOffVerify   → 前提：WiFi 已关 → agent 只需确认
```

**这有什么用？**
- TurnOn/TurnOff 测"是否能改变状态"
- Verify 测"是否能正确判断当前状态"（不会过度操作）
- 对比这两种 case 的成功率可以发现 agent 是"操作"还是"判断"出了问题

```python
# verify 类：只是确认，不需要操作
class SystemWifiTurnOffVerify(_SystemWifiToggle):
    def initialize_task(self, env):
        super().initialize_task(env)
        adb_utils.toggle_wifi(env.controller, 'off')  # 预设 WiFi 已关

    @classmethod
    def generate_random_params(cls):
        return {'on_or_off': 'off'}  # 固定参数，不随机
```

### 1.3 复合任务——子任务组合 + 平均分

```
TurnOnWifiAndOpenApp:
  sub_tasks = [SystemWifiTurnOn, OpenAppTaskEval]
  score = (wifi_score + open_app_score) / 2.0
```

实现非常简洁（composite/system.py 完整代码）：

```python
class TurnOnWifiAndOpenApp(task_eval.TaskEval):
    complexity = 2  # 比单个任务高一档
    template = "Turn on Wifi, then open the {app_name} app"

    def initialize_task(self, env):
        super().initialize_task(env)
        self.turn_on_wifi_task = system.SystemWifiTurnOn(params={"on_or_off": "on"})
        self.turn_on_wifi_task.initialize_task(env)
        self.open_app_task = system.OpenAppTaskEval(params={"app_name": self.params["app_name"]})
        self.open_app_task.initialize_task(env)

    def is_successful(self, env) -> float:
        wifi_score = self.turn_on_wifi_task.is_successful(env)
        open_app_score = self.open_app_task.is_successful(env)
        return (wifi_score + open_app_score) / 2.0

    def tear_down(self, env):
        self.open_app_task.tear_down(env)
        self.turn_on_wifi_task.tear_down(env)
        super().tear_down(env)
```

关键设计点：
- 子任务重用已有的 single task，不是重新实现
- `complexity = 2` → 自动获得更多步数预算
- 分数是子任务平均分——agent 必须两道都做对
- `initialize_task` 里设好前提条件（WiFi 关 → 再开）

### 1.4 通用验证器——按 domain 分组复用

```
common_validators/
├── file_validators.py    → MoveFile, DeleteFile, CreateFile
├── contacts_validators.py → Add/Edit/Delete contact
├── sms_validators.py     → Send/Read SMS
├── sqlite_validators.py  → DB-level verification
└── phone_validators.py   → Call verification
```

每个 validator 都是独立可测的 `TaskEval` 子类，可以：
- 单独跑（单元测试有 `*_test.py`）
- 被 composite 任务组合使用
- 被其他任务引用验证其中间状态

### 1.5 前提管理——initialize + tear_down 保证可重复

```python
# 每个 task 都有三个生命周期方法
initialize_task(env)  → 设置设备到初始状态（关 WiFi、清除文件、设时间）
                       → 用 random seed 保证可重复
agent.run()           → 执行
is_successful(env)    → 读设备状态 → 返回分数
tear_down(env)        → 清理（关闭 app、恢复快照、清除数据）
```

## 2. fastaget vs AndroidWorld — gap 分析

| 维度 | fastaget v1.8 | AndroidWorld | gap |
|------|--------------|-------------|-----|
| 验证来源 | agent 自评 `complete(success=True)` | 独立 shell 命令验证 | **核心 gap** |
| 分数粒度 | 二元 (pass/fail) | 0.0–1.0 浮点 | 中 |
| 任务变体 | 无 | 4类（change/verify × on/off） | 中 |
| 复合任务 | 无 | 子任务组合 + 平均分 | 中 |
| 前提管理 | CLI `--reset` flag | `initialize_task` + `tear_down` | 中 |
| 通用验证器 | 无 | domain 分组复用 | 低（先修核心 gap） |
| 随机参数 | 无 | `generate_random_params` | 低 |
| 复杂度预算 | 手动 `max_steps` | `complexity` → 自动分配 | 低 |

## 3. fastaget 终态验证方案（已落地）

### 3.1 架构总览

```
┌──────────────┐        ┌─────────────────┐        ┌──────────────────┐
│ eval_cases   │───────▶│ Agent 执行（真机） │───────▶│ 市后验证（模拟器）  │
│ .yml          │        │ phonefast        │        │ verify.py        │
│               │        │ 22 tools         │        │ phonefast.shell()│
│ goal + verify │        │ ReAct loop       │        │ 4 种比对规则      │
└──────────────┘        └─────────────────┘        └──────────────────┘
                                  │                          │
                                  │ AgentResult              │ VerificationResult
                                  │ (success, steps, $)      │ (passed, actual)
                                  ▼                          ▼
                         ┌────────────────────────────────────┐
                         │         CaseReport                  │
                         │  success = agent声称 AND 设备验证   │
                         │  verified: ✓ / ✗ / ·              │
                         └────────────────────────────────────┘
```

### 3.2 模拟器环境要求

| 项目 | 规格 |
|------|------|
| 系统镜像 | `system-images;android-35;google_apis;arm64-v8a` |
| 原因 | API 35 非 PS16K，uiautomator/a11y 正常工作 |
| AVD | Pixel 8, 1080×2400, 2GB RAM |
| phonefast | daemon 模式的 a11y 服务自动抢占 UI 树 |
| 禁止 | PS16K 镜像（16K 页大小，a11y 和 uiautomator 冲突） |

> phonefast daemon 的 a11y 服务会抢占 UiAutomation 连接，导致系统 `uiautomator dump` 被 kill。
> console 元素检测完全依赖 phonefast observe 输出（daemon 内置的 a11y 服务），不依赖系统 uiautomator。

### 3.3 YAML 验证语法：4 种比对规则

```yaml
# meta/eval_cases.yml — 每条 case 的 verify: 字段
verify:
  - command: "settings get global wifi_on"        # shell 命令
    expect: "0"                                    # 精确匹配
    # expect_re: "^[12]$"                          # 正则匹配
    # not_contain: "NOT_FOUND"                     # 不应包含
    # min_lines: 1                                 # 最少行数
```

### 3.4 验证执行流程

```python
# cli.py — agent.run() 之后自动执行，agent 全程不知道
if case.verifications:
    specs = [VerificationSpec.from_dict(v) for v in case.verifications]
    results = run_verification(specs, pf)  # phonefast.shell() 直发
    # 覆盖：agent 声称 success=True 但设备验证不通过 → 修正为成功
    if report.success and not all(r.passed for r in results):
        report.success = False
```

### 3.5 19 case 验证覆盖

| 验证强度 | case | 命令 | 规则 |
|---------|------|------|------|
| 硬—系统数值 | T04-T07, T14-T15 | `settings get global/system xxx` | expect / expect_re |
| 硬—包管理 | T16-T17 | `pm list packages \| grep xingin.xhs` | not_contain / expect |
| 中—Activity | T01-T03, T08-T10, T12-T13, T18-T19 | `dumpsys activity \| grep topResumedActivity` | expect_re |
| 无 | T11 | — | 截图路径无通用验证 |
  goal: 确认 WiFi 开关处于关闭状态
  max_steps: 5
  tags: [L1, verify]
  verify:
    command: "settings get global wifi_on"
    expect: "0"
```

### 3.3 第三优先级：复合任务

```yaml
- name: C01-WiFi关+蓝牙开
  goal: 关闭 WiFi 并开启蓝牙
  max_steps: 20
  tags: [composite]
  sub_tasks:                  # NEW
    - T04-关闭WiFi
    - T03-查看蓝牙
  scoring: average            # average / all_or_nothing
  verify:
    - command: "settings get global wifi_on"
      expect: "0"
    - command: "settings get global bluetooth_on"
      expect: "1"
```

### 3.4 前提管理

```yaml
- name: T04-关闭WiFi
  setup:                       # NEW: case 执行前的准备
    - command: "svc wifi enable"
      verify: "settings get global wifi_on | grep 1"
  teardown:                    # NEW: case 执行后的清理
    - command: "svc wifi enable"
```

## 4. 对比分析框架

有了独立验证后，对比就是四维表格：

| 维度 | fastaget | Claude Code | 差异来源 |
|------|----------|-------------|---------|
| **agent 声称成功** | N% | N% | 自我评估倾向 |
| **设备验证成功** | N% | N% | **真实成功率** |
| **过度操作率** | N% | N% | Verify 类 case 中操作了不该操作的比例 |
| **操作效率** | N 步 | N 步 | 步数 |

关键是第 2 行与第 1 行的差值——agent 声称成功但设备验证失败的比例，就是"agent 的不可信度"。

## 5. 实施建议

**本周**（~2h）：
1. `fastaget/verify.py` — 后置验证模块（40 行）
2. `eval_cases.yml` 加 `verify:` 字段（19 条 × 1 行）
3. `cli.py` 加验证调用（10 行）
4. 重跑评测 → 拿到真实成功率

**下周**（~2h）：
5. 新增 Verify 类变体（~10 条）
6. 对比 Change vs Verify 的行为差异

**后续**（~3h）：
7. 复合任务 YAML 定义 + runner
8. 前提管理 setup/teardown
