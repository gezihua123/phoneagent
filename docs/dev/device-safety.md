# 多设备安全规范与运行环境

> 目的：防连错手机。多设备在线时，任何一层都不得"猜"设备。

## 原则：serial 必选，禁止猜测

- **Phonefast 始终绑定明确 serial**——构造后首次 daemon/shell 调用时自动解析
- **单设备自动检测**：1 台设备在线 → 自动选用，无需传 `--serial`
- **多设备拒绝猜测**：>1 台真机在线 → `PhonefastError` 列出所有设备，要求显式指定 `--serial`
- **1 真机 + N 模拟器**：自动选唯一真机

## Phonefast 三层防线（`fastaget/device/phonefast.py`）

| 层 | 方法 | 防护 |
|----|------|------|
| L1   | `_resolve_serial()` | 查 `adb devices`，多真机 → 拒绝猜测报错 |
| L2   | `_ensure_daemon()` | 始终 `phonefast daemon --serial <s>`，不靠 daemon 默认选 |
| L3   | `shell()` | 始终 `adb -s <serial> shell`，不靠 `adb` 默认设备 |
| 附加 | `_ping()` | socket serial 不匹配 → 拒绝复用旧 daemon |

## CLI 入口必须支持 `--serial`

- `fastaget run --serial <s>` ✅
- `fastaget flow run --serial <s>` ✅
- 新增入口 → 必须加 `--serial` 参数

## 代码铁律：禁止绕过 Phonefast 直调 adb

- **禁止**：`subprocess.run(["adb", "shell", ...])` —— 没有 `-s`，多设备会打错
- **禁止**：`subprocess.run(["adb", "-s", hardcoded_serial, ...])` —— 硬编码 serial
- **只能**：`pf.shell(cmd)` —— Phonefast 实例已绑定正确 serial

## Phonefast 实例传递约定

- Phonefast 在 CLI 层创建（`Phonefast(serial=...)`），注入到 agent/flow/verify 各层
- 各层不自行创建 Phonefast——从上层接收已绑定 serial 的实例
- `eval_aw.py` 等库函数：接收 `phonefast` 参数，由调用方负责绑定 serial

## 评测环境约束

- **评测必须使用 AndroidWorld 标准模拟器**：`emulator-5554`（Pixel 6 API 33, google_apis, arm64-v8a）
- **严禁真机参与评测**：TECNO / RF8R 等真机缺少 AndroidWorld 预置应用和数据，不可用于评测
- **评测前准备**：
  ```bash
  pkill -9 -f "daemon_worker|scrcpy" 2>/dev/null
  adb disconnect 2>/dev/null  # 断开真机，仅保留 emulator-5554
  phonefast daemon --serial emulator-5554
  phonefast observe -s emulator-5554  # 验证: 分辨率应为 1080x2400（非 720x1600）
  ```
- **CLI 运行时指定**：`python3 -m fastaget.cli run --serial emulator-5554 -f ...`

## LLM 端点（硬性）

- **端点**：`https://api.deepseek.com/anthropic`（DeepSeek Anthropic 兼容 Messages API）
- **认证**：环境变量 `ANTHROPIC_AUTH_TOKEN` 或 `ANTHROPIC_API_KEY` = DeepSeek API Key
- **模型名**：仅 `deepseek-v4-pro`（准确率优先，thinking 已关闭——ReAct 只需动作输出）
- **禁止**：`deepseek-chat`（已停用）
- **设置方式**：
  ```bash
  export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
  export ANTHROPIC_AUTH_TOKEN="sk-xxx"
  unset ANTHROPIC_MODEL  # 用 fastaget CLI --model 指定，不靠 env
  ```
