# fastaget v1.9 vs Claude Code — AndroidWorld 24 Fast Combo 对比

> 日期: 2026-07-17
> 环境: Pixel 6 API 33 Emulator (Tiramisu, google_apis_playstore, arm64-v8a)
> 模型: deepseek-v4-pro（双方同级）
> 验证: AndroidWorld 式 shell 命令后验

## 总体对比

| 指标 | fastaget v1.9 | Claude Code |
|------|---------------|-------------|
| 成功率（agent 声称） | 25.0% (6/24) | 57.1% (4/7 T1 实测) |
| 成功率（设备验证） | **87.5% (14/16)** | 57.1% (4/7) |
| 误报（声称成功但验证失败） | 1 (AW-MarkorCreateNote) | 0 |
| **漏报（声称失败但验证通过）** | **8** | 0 |
| 平均步数 | 7.5 | 1.4 |
| 平均耗时 | 25.8s/case | 1.3s/case |
| 总成本 | $0.266 (24 cases) | ~$0 (7 T1 cases 均为 shell) |

## 核心发现：fastaget 的最大问题是停滞检测误杀

**8 个漏报** — agent 声称失败但设备验证实际通过：

| Case | Agent 说 | 设备实际 | 根因 |
|------|---------|---------|------|
| AW-CameraTakePhoto | ✗ 步数上限 | ✓ | 步数不够 + 停滞检测 |
| AW-ClockStopWatchRunning | ✗ 步数上限 | ✓ | 同上 |
| AW-ClockTimerEntry | ✗ 停滞 | ✓ | assert 已通过但被停滞检测终止 |
| AW-ContactsAddContact | ✗ 停滞 | ✓ | 同上 |
| AW-ContactsNewContactDraft | ✗ 停滞 | ✓ | 同上 |
| AW-ExpenseAddSingle | ✗ 步数上限 | ✓ | 步数不够 |
| AW-FilesDeleteFile | ✗ 步数上限 | ✓ | 步数不够 |
| AW-SimpleCalendarAddOneEvent | ✗ 停滞 | ✓ | 已找到"New Event"但被终止 |
| AW-SimpleSmsSend | ✗ 步数上限 | ✓ | 步数不够 |

**停滞检测 + 步数上限 = 双重过早终止**。Agent 在探索过程中被 kill，但实际已经完成了目标。

## 分层详细对比（T1-T3 可验证 case）

### T1 — Shell 验证案例

| Case | FA 声称 | FA 验证 | CC | 备注 |
|------|---------|---------|----|------|
| AW-SystemWifiTurnOff | ✓ 3步 | ✓ | ✓ | CC 1步 shell |
| AW-SystemBrightnessMax | ✓ 3步 | ✓ | ✓ | CC 1步 shell |
| AW-SystemBluetoothTurnOn | ✓ 2步 | ✓ | ✓ | CC 1步 shell |
| AW-CameraTakePhoto | ✗ 6步 | ✓ | ✗ | 模拟器相机限制 |
| AW-MarkorCreateNote | ✗ 10步 | ✗ | ✗ | 存储权限弹窗 |
| AW-FilesDeleteFile | ✗ 9步 | ✓ | — | agent 步数不够 |
| AW-SystemCopyToClipboard | ✗ 6步 | ✗ | ✗ | emulator clipboard 不可用 |
| AW-OpenAppTaskEval | ✓ 5步 | ✓ | — | |
| AW-TurnOffWifiAndTurnOnBluetooth | ✓ 2步 | ✓ | ✓ | CC 1步 shell |

**T1 验证通过率**: FA 7/9, CC 4/6

### T2 — Activity/UI 验证案例

| Case | FA 声称 | FA 验证 | CC | 备注 |
|------|---------|---------|----|------|
| AW-ClockStopWatchRunning | ✗ 9步 | ✓ | — | 停滞检测误杀 |
| AW-ClockTimerEntry | ✗ 9步 | ✓ | — | assert 通过但仍被终止 |
| AW-ContactsNewContactDraft | ✗ 9步 | ✓ | — | 同上 |
| AW-ExpenseAddSingle | ✗ 15步 | ✓ | — | 步数不够 |

**T2 验证通过率**: FA 4/4（全部漏报！）

### T3 — Content Provider 案例

| Case | FA 声称 | FA 验证 | CC | 备注 |
|------|---------|---------|----|------|
| AW-ContactsAddContact | ✗ 9步 | ✓ | — | 停滞检测误杀 |
| AW-SimpleSmsSend | ✗ 12步 | ✓ | — | 步数不够 |
| AW-SimpleCalendarAddOneEvent | ✗ 15步 | ✓ | — | 已找到 UI 但停滞检测终止 |

**T3 验证通过率**: FA 3/3（全部漏报！）

### T4-T5 — 无验证/复杂案例

| Case | FA 声称 | 备注 |
|------|---------|------|
| AW-AudioRecorderRecordAudio | ✗ 10步 | 停滞 |
| AW-BrowserDraw | ✗ 14步 | task.html 文件不存在 |
| AW-MarkorCreateNoteAndSms | ✓ 0步 | 正确拒绝（参数占位符未填充） |
| AW-OsmAndFavorite | ✗ 14步 | 步数不够 |
| AW-RetroCreatePlaylist | ✗ 10步 | 停滞 |
| AW-SimpleCalendarEventsOnDate | ✗ 8步 | 步数不够 |
| AW-SimpleDrawProCreateDrawing | ✗ 10步 | 停滞 |
| AW-TasksDueOnDate | ✗ 6步 | 步数不够 |

## 问题归因矩阵

| 根因 | 影响 case 数 | 严重度 |
|------|------------|--------|
| **停滞检测误杀** | 10 | 🔴 P0 |
| **步数上限太低** | 6 | 🟡 P1 |
| **环境缺失（无 task.html 等）** | 2 | 🟡 P1 |
| **参数占位符未填充** | 大多数 T4+ | 🟡 P1 |
| **模拟器限制（clipboard/相机）** | 2 | 🟢 已知 |

## 结论

1. **fastaget 的真实能力被严重低估**：声称 25% 但设备验证 87.5%。停滞检测和步数上限造成了 8 个漏报（false negative）。

2. **Claude Code 在简单 shell case 上效率碾压**（1步 vs 2-3步），但在交互 App case 上没有本质优势——两者面临的权限弹窗、首次运行引导等问题相同。

3. **最 urgent 的修复不是 agent 推理能力，而是评测框架本身**：
   - 停滞检测：assert 通过后不应终止；back/navigation 不计数
   - 步数上限：T2-T3 app 操作需要更多步数（目前 10-15 不够）
   - 参数填充：AW case 中的 `{name}` `{number}` 等占位符需要替换为具体值

4. **如果只看设备验证结果**，fastaget 在可验证 case 上的真实通过率是 **14/16 = 87.5%**，远超 agent 自报的 25%。

---
