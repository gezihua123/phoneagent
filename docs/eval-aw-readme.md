# fastaget — AndroidWorld 116 Task 导入 & 快速验证组合

> 生成日期: 2026-07-17
> 来源: `https://github.com/google-research/android_world/blob/main/android_world/task_metadata.json`

## 总览

| 维度 | 数量 |
|------|------|
| 总 case | **116** |
| shell 直接验证 (T1) | 26 |
| Activity/UI 验证 (T2) | 8 |
| Content Provider (T3) | 17 |
| 复杂 App 状态 (T4) | 60 |
| 媒体文件 (T5) | 5 |
| 有验证规则 | **37 (32%)** |
| 无验证规则（需深度 setup） | 79 (68%) |

## 按难度

| 难度 | 数量 | 分布 |
|------|------|------|
| Easy | 61 | 52.6% |
| Medium | 36 | 31.0% |
| Hard | 19 | 16.4% |

## 按应用

| 应用 | Case 数 | 验证覆盖 |
|------|---------|---------|
| System (WiFi/BT/Brightness/Clipboard) | 15 | 15/15 T1 |
| Simple Calendar Pro | 17 | 1/17 T3 |
| Markor | 14 | 7/14 T1 |
| Recipe (Broccoli) | 13 | 0/13 T4 |
| Expense | 9 | 1/9 T2 |
| Simple SMS | 6 | 1/6 T3 |
| OpenTracks | 6 | 0/6 T4 |
| Tasks.org | 6 | 0/6 T4 |
| Joplin | 4 | 0/4 T4 |
| Retro Music | 4 | 0/4 T4 |
| Browser | 3 | 0/3 T5 |
| Clock | 3 | 3/3 T2 |
| OsmAnd | 3 | 0/3 T4 |
| Audio Recorder | 2 | 0/2 T4 |
| Camera | 2 | 2/2 T1 |
| Contacts | 2 | 2/2 T2+T3 |
| Files | 2 | 2/2 T1 |
| VLC | 2 | 0/2 T4 |
| Simple Draw | 1 | 0/1 T5 |

## 快速验证组合（Fast Verification Combo）

**24 case，覆盖所有 5 个 tier + 所有难度 + 15 个应用，预计总耗时 ~15 分钟**

### T1 — Shell 直接验证 (8 cases)

| Case | Difficulty | App | 验证方式 |
|------|-----------|-----|---------|
| AW-SystemWifiTurnOff | E | system | `settings get global wifi_on` → 0 |
| AW-SystemBrightnessMax | E | system | `settings get system screen_brightness` → 255 |
| AW-SystemBluetoothTurnOn | E | system | `settings get global bluetooth_on` → 1 |
| AW-SystemCopyToClipboard | E | system | `cmd clipboard get-text` |
| AW-CameraTakePhoto | E | camera | `ls /sdcard/DCIM/Camera/ \| wc -l` ≥ 1 |
| AW-MarkorCreateNote | M | markor | `ls /sdcard/Documents/Markor/` has file |
| AW-FilesDeleteFile | M | files | `ls /sdcard/<path>/` no file |
| AW-OpenAppTaskEval | E | generic | dumpsys activity 匹配 |

### T2 — Activity/UI 验证 (4 cases)

| Case | Difficulty | App | 验证方式 |
|------|-----------|-----|---------|
| AW-ClockStopWatchRunning | E | clock | dumpsys → deskclock activity |
| AW-ClockTimerEntry | E | clock | dumpsys → deskclock activity |
| AW-ContactsNewContactDraft | E | contacts | dumpsys → contact activity |
| AW-ExpenseAddSingle | E | expense | dumpsys → expense activity |

### T3 — Content Provider (4 cases)

| Case | Difficulty | App | 验证方式 |
|------|-----------|-----|---------|
| AW-ContactsAddContact | E | contacts | `content query contacts` |
| AW-SimpleSmsSend | M | sms | `content query --uri content://sms` |
| AW-SimpleCalendarAddOneEvent | H | calendar | `content query calendar/events` |
| AW-TurnOffWifiAndTurnOnBluetooth | M | system | composite: wifi_on=0 + bluetooth_on=1 |

### T4 — 复杂 App 状态 (6 cases)

| Case | Difficulty | App | 说明 |
|------|-----------|-----|------|
| AW-MarkorCreateNoteAndSms | H | markor+sms | 跨应用复合操作 |
| AW-SimpleCalendarEventsOnDate | M | calendar | 信息检索（回答而非操作） |
| AW-TasksDueOnDate | E | tasks | 信息检索 |
| AW-RetroCreatePlaylist | M | retro_music | 媒体播放列表 |
| AW-OsmAndFavorite | M | osmand | 地图收藏 |
| AW-AudioRecorderRecordAudio | E | audio_recorder | 录音验证（文件名检查） |

### T5 — 媒体 (2 cases)

| Case | Difficulty | App | 说明 |
|------|-----------|-----|------|
| AW-BrowserDraw | E | browser | 浏览器内交互绘图 |
| AW-SimpleDrawProCreateDrawing | E | draw | 绘图文件验证 |

## 使用方式

```bash
# 跑全部 116 case（需要预先 setup 各应用数据）
python3 -m fastaget run --file meta/eval_cases_aw.yml --serial emulator-5554

# 只跑快速验证组合 24 case
python3 -c "
import yaml
with open('meta/eval_cases_aw.yml') as f:
    data = yaml.safe_load(f)
fast = data['meta']['fast_combo']
cases = [c for c in data['cases'] if c['name'] in fast]
with open('/tmp/fast_combo.yml', 'w') as f:
    yaml.dump({'cases': cases}, f, allow_unicode=True)
"
python3 -m fastaget run --file /tmp/fast_combo.yml --serial emulator-5554
```

## 与原 19 case 的关系

`meta/eval_cases.yml` (19 case) 保留为手工设计的快速回归套件。
`meta/eval_cases_aw.yml` (116 case) 是 AndroidWorld 全量导入。

两者独立维护，可分别运行或合并评测。
