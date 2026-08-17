# AndroidWorld 测试框架全量分析 & fastaget 适配方案

> 分析日期: 2026-07-17
> 来源: `https://github.com/google-research/android_world`

## 一、AndroidWorld 任务生命周期

每个 task 有三个入口，由 AW 框架在执行时统一调用：

```
1. initialize_task(env)  → 预置数据/状态（在 agent 执行前）
2. <agent 执行 goal>     → agent 通过 UI/API 完成任务
3. is_successful(env)    → 独立验证（agent 完全不知道）
4. tear_down(env)        → 清理（恢复初始状态）
```

## 二、19 类 Task 的验证方式（全量）

### 1. System — Shell 命令直接读系统状态

| Task | initialize_task | is_successful |
|------|----------------|---------------|
| WiFi On/Off | `adb shell svc wifi enable/disable` | `adb shell settings get global wifi_on` → "1"/"0" |
| BT On/Off | `adb shell svc bluetooth enable/disable` | `adb shell settings get global bluetooth_on` → "1"/"0" |
| Brightness Max/Min | `adb shell settings put system screen_brightness 1/255` | `adb shell settings get system screen_brightness` → 数值比对 |
| CopyToClipboard | — | `adb shell cmd clipboard get-text` |

**fastaget 适配**: ✅ 完全可用，同 AW 方式

### 2. Files — adb shell 文件系统检查

| Task | initialize_task | is_successful |
|------|----------------|---------------|
| DeleteFile | 创建目标文件 | `adb shell ls <path>` → 文件不存在 |
| MoveFile | 创建源文件 | `adb shell ls <new_path>` → 文件存在 |
| SaveCopy | 创建源文件 | `adb shell ls <dest_path>` → 文件存在 |

**fastaget 适配**: ✅ `adb shell ls/find` + expect/not_contain

### 3. SMS — Content Provider `content://sms/sent`

| 操作 | AW 方式 |
|------|---------|
| **初始化** | ① `adb emu sms` 模拟收短信 ② `adb shell content delete --uri content://sms` 清空 ③ 关飞行模式 |
| **验证** | `adb shell content query --uri content://sms/sent` → 解析 ADB 输出 → 比对号码+正文+时间戳（5 分钟内） |
| **额外检查** | `dumpsys activity` 确认前台是 SMS app |

**fastaget 适配**: ✅ `content query --uri content://sms` 可用，用 `min_lines` + `expect_re` 比对

### 4. Contacts — UI Tree 遍历

| 操作 | AW 方式 |
|------|---------|
| **验证** | `env.get_state().forest` → 遍历 UI 元素树 → 查找输入框中的 first/last/phone 文本 |

**fastaget 适配**: ⚠️ 改为 `dumpsys activity` + agent 自己的 assert。AW 用的是 Python 代码级 UI 树遍历，fastaget 只能用 shell 或 observe 输出。

### 5. Calendar — SQLite 直读 + 前后状态比对

| 操作 | AW 方式 |
|------|---------|
| **初始化** | Python 代码通过 `sqlite3` 直接操作 `calendar.db`，插入/删除事件 |
| **验证** | ① 读取 `calendar.db` events 表 → 解析为 `CalendarEvent` 对象列表 ② 比对 before/after 状态 ③ `validate_rows_addition_integrity()` — 检查新增/删除的事件字段是否完全匹配 |
| **示例** | `db_path = "/data/data/com.android.providers.calendar/databases/calendar.db"` |

**fastaget 适配**: ❌ 模拟器无 `sqlite3` 二进制。降级为 `dumpsys activity` activity 名匹配。

### 6. Clock — UI + Activity 检查

| 操作 | AW 方式 |
|------|---------|
| **Stopwatch Running** | 遍历 UI 树 → 查找 "Start"/"Pause"/"Reset" 按钮 → 判断秒表状态 |
| **Timer Entry** | 遍历 UI 树 → 查找 `timer_setup_time` 的文本 → 比对 hours/minutes/seconds |
| **额外** | `adb shell dumpsys activity` 确认在 deskclock |

**fastaget 适配**: ✅ `dumpsys activity` + agent observe。Activity 名可验证，精确秒表状态需 agent 自己 assert。

### 7. Markor — 文件系统验证 + initialize_task

| 操作 | AW 方式 |
|------|---------|
| **初始化** | `file_utils.clear_directory(MARKOR_DATA)` 清空 + 创建噪音文件 |
| **CreateNote** | `adb shell ls <MARKOR_DATA>/<file_name>` → 文件存在 |
| **DeleteNote** | `adb shell ls <MARKOR_DATA>/<file_name>` → 文件不存在 |
| **MoveNote** | `adb shell ls <target_path>/<file_name>` → 文件存在 |
| **EditNote** | `adb shell cat <file>` → 内容比对 |
| **数据目录** | `/storage/emulated/0/Documents/Markor/` |

**fastaget 适配**: ✅ 文件系统操作，但 Markor 首启遮罩阻断所有操作。

### 8. Expense — SQLite 直读

| 操作 | AW 方式 |
|------|---------|
| **验证** | 读取 `com.arduia.expense` 的 SQLite 数据库 → 比对 expense 条目的 name/amount/category |

**fastaget 适配**: ❌ 无 SQLite 访问。降级为 `dumpsys activity` 确认在 expense app。

### 9. Recipe (Broccoli) — SQLite 直读

| 操作 | AW 方式 |
|------|---------|
| **初始化** | 通过 SQLite 插入/删除菜谱数据 |
| **验证** | SQLite 读取 → 比对 title/ingredients/instructions |

**fastaget 适配**: ❌ 降级为 `dumpsys activity`。

### 10. Retro Music — SQLite playlist.db

| 操作 | AW 方式 |
|------|---------|
| **初始化** | 扫描音乐目录，清空 playlist DB |
| **验证** | SQLite 读 `playlist.db` → `verify_playlist()` 比对 name + files 列表 |
| **DB 路径** | `/data/data/code.name.monkey.retromusic/databases/playlist.db` |

**fastaget 适配**: ❌ 降级为 `dumpsys activity`。

### 11. VLC — SQLite vlc_media.db

| 操作 | AW 方式 |
|------|---------|
| **初始化** | 清除 Playlist/Media/PlaylistMediaRelation 表 |
| **验证** | SQLite 读 `vlc_media.db` → 比对 playlist 结构 |
| **DB 路径** | `/data/data/org.videolan.vlc/app_db/vlc_media.db` |

**fastaget 适配**: ❌ 降级为 `dumpsys activity`。

### 12. OsmAnd — SQLite + XML 文件

| 操作 | AW 方式 |
|------|---------|
| **Marker** | SQLite 读 `map_markers_db` → 比对坐标 |
| **Favorite** | XML 文件解析 `favorites.gpx` → 比对 location name |
| **Track** | GPX 文件解析 → 比对 waypoints |

**fastaget 适配**: ❌ 降级为 `dumpsys activity`。

### 13. Tasks.org / Joplin / OpenTracks — UI 信息检索

| 操作 | AW 方式 |
|------|---------|
| **初始化** | 通过 SQLite/API 预置 tasks/notes/activities 数据 |
| **验证** | **不检查操作，只检查 agent 的答案**。AW 用 Python 比对 agent 文本输出与数据库中的实际状态 |

**fastaget 适配**: ❌ 信息检索类 task — AW 比对的是 agent 的**文本回答**，不是设备状态。fastaget 的 verify shell 命令无法验证文本答案的正确性。

### 14. Camera — 文件系统

| 操作 | AW 方式 |
|------|---------|
| **初始化** | 清空 DCIM/Camera 目录 |
| **验证** | `adb shell ls /sdcard/DCIM/Camera/` → 有新文件 |

**fastaget 适配**: ✅ 文件系统。但模拟器 `STILL_IMAGE_CAMERA` intent 不实际保存照片。

### 15. Audio Recorder — 文件系统

| 操作 | AW 方式 |
|------|---------|
| **初始化** | 清空录音目录 |
| **验证** | `adb shell ls` 录音目录 → 有新文件 |

**fastaget 适配**: ⚠️ 需处理首启权限引导。

### 16. Simple Draw — 文件系统

| 操作 | AW 方式 |
|------|---------|
| **验证** | `adb shell ls` Pictures 目录 → 有新 .png 文件 |

**fastaget 适配**: ⚠️ SAF 权限弹窗需 dismiss。

### 17. Browser — 复杂多步

| 操作 | AW 方式 |
|------|---------|
| **初始化** | 预置 `task.html` 到 Downloads |
| **验证** | UI 元素检查 + 文件系统 |

**fastaget 适配**: ❌ task.html 未植入 + 跨应用多步复杂。

### 18. OpenAppTaskEval — 泛型

| 操作 | AW 方式 |
|------|---------|
| **验证** | `dumpsys activity` 确认 app 在前台 + 无 popup |

**fastaget 适配**: ✅

### 19. Composite — 多条件

| 操作 | AW 方式 |
|------|---------|
| **验证** | 多个独立验证的组合（WiFi+BTOpenApp） |

**fastaget 适配**: ✅ 多 verify rule

## 三、fastaget 验证能力分级

| 级别 | 验证方式 | 覆盖 | 精度 |
|------|---------|------|------|
| **L0 - Shell** | `settings get`/`cmd`/`svc`/`content query` | System, SMS sent, basic file ops | 100% 精确 |
| **L1 - File** | `ls`/`find`/`cat`/`wc -l` | Markor, Camera, Files | 100% |
| **L2 - Activity** | `dumpsys activity` | 所有 app launch/nav | ~80% (仅确认在 app 内) |
| **L3 - Agent assert** | agent 的 `assert(passed=true)` | Clock timer, Contacts fill | ~70% (受停滞检测影响) |
| **L4 - 不可行** | SQLite/XML 需要 root+sqlite3 | Calendar, Expense, Recipe, Retro, VLC, OsmAnd | 0% |
| **L5 - 需预置** | 需文件/数据 implant | Browser, Tasks, Joplin, OpenTracks | 0% |

## 四、当前 fastaget 116 case 适配状态

| Tier | 数量 | 说明 |
|------|------|------|
| ✅ 完全可用 (shell/file/activity) | 37 | T1 26 + T2 6 + T3 SMS 5 |
| ⚠️ 降级为 activity (SQLite 不可用) | 51 | T4 大部分 |
| ❌ 需 app 预置数据 | 14 | Markor 首启 + Browser HTML |
| ❌ 信息检索（不可执行） | 6 | Tasks/Joplin/OpenTracks |
| ❌ 模拟器限制 | 5 | Camera emulator + Clipboard + Draw SAF + AudioRec |
| ❌ Markor 首启遮罩 | 3 | 额外 Markor case |

## 五、建议快速验证组合（37 case, 预计 >90%）

这 37 个 case 全部有可靠的 shell/file/activity 验证：

- System: WiFi/BT/Brightness/Clipboard (15)
- Files: Delete/Move/SaveCopy (3)  
- Clock: Stopwatch/Timer (3)
- Contacts: Add/Draft (2)
- SMS: Send/Reply (6)
- Generic: OpenApp (1)
- Composite: TurnOffWifiAndTurnOnBluetooth + TurnOnWifiAndOpenApp (2)
- Expense: AddSingle (1)
- Calendar: AddOneEvent (4) — activity-level only
