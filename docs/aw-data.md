# AndroidWorld 数据准备流程

> 模拟器环境一次搭建 + 评测数据每条用例独立初始化，100% 对齐 AndroidWorld。

## 整体架构

```
scripts/aw/
├── data.py       # 固定测试数据常量（89 个字段）
├── init.py       # initialize 命令生成器（112 个函数）
├── verify.py     # is_successful 命令生成器（80 个函数）
└── __init__.py   # 模块说明

meta/
├── eval_cases_aw_filled.yml    # 原始 116 条用例（goal 已填充）
└── eval_cases_aw_aligned.yml   # 对齐后 116 条用例（init + verify 完整）
                                  ↑
                    python3 scripts/align_aw_cases.py
```

## 两层准备模型

### 第一层：环境准备（一次性）

运行 `python3 fastaget/emulator_setup.py`：

| 步骤 | 内容 | 关键点 |
|------|------|--------|
| 系统设置 | 时区 UTC、日期冻结 2023-10-15、24 小时制、动画关闭 | 对齐 `Dockerfile` + `start_emu.sh` |
| APK 安装 | 16 个第三方 APK + VLC | 从 GCS 下载 + curl 直连 |
| 应用设置 | pm clear + grant + monkey 启动 + 引导页点击 | 对齐 `setup_device/apps.py` |
| 数据文件 | OsmAnd 地图 + VLC 目录 + chcon | 对齐 `OsmAndApp.setup()` |
| 特定配置 | SMS 默认应用、AWorld 悬浮窗权限 | 确保应用功能正常 |

### 第二层：评测数据初始化（每条用例独立）

评测脚本（`eval_aw.py`）在每条用例执行前，读取 YAML 中的 `initialize` 命令列表，逐条在设备上执行。

```
Case Flow:
  1. task.initialize(pf)     ← 执行 initialize 命令
  2. agent.run(task.goal)    ← Agent 执行任务
  3. task.is_successful(pf)  ← 执行 verify 命令
  4. task.tear_down(pf)      ← 清理（回桌面、重启 app 等）
```

## 数据定义：data.py

所有测试数据使用**固定值**（零随机，保证每次评测结果可重复）：

```
9 个 DB 路径    → DB_PATHS (broccoli/expense/calendar/tasks/...)
7 个食谱         → RECIPE_SPICY_TUNA / AVOCADO_TOAST / ...
10 个支出        → EXPENSE_LUNCH / COFFEE / TAXI / ...
6 个日历事件     → CAL_EVENT_TEAM_MEETING / LUNCH / ...
2 个联系人       → CONTACT_ALICE / BOB
1 条短信         → SMS_HELLO
5 个任务         → TASK_BUY_GROCERIES / CALL_DENTIST / ...
3 个运动记录     → OPENTRACKS_RUN_1 / RUN_2 / BIKE
4 条 Joplin 笔记 → JOPLIN_RECIPE_NOTE / MEETING_NOTE / ...
11 个 Markor 文件 → MARKOR_NOTE / HEADER / CHANGE / ...
6 个 Retro/VLC   → RETRO_PLAYLIST / VLC_PLAYLIST / ...
```

## 初始化命令层：init.py

112 个 `*_init()` 函数，每个返回 `list[str]`——shell 命令列表。

### SQLite 类（V1 验证）

```python
def recipe_delete_single_init() -> list[str]:
    return [
        f"sqlite3 {DB} \"DELETE FROM recipes;\"",        # 清空
        f"sqlite3 {DB} \"INSERT INTO recipes(...) ...\";", # 写目标行
        "am force-stop com.flauschcode.broccoli",          # 重启 app（Room 缓存）
    ]
```

**Room ORM 缓存处理**（Broccoli > Retro > VLC > Tasks > OpenTracks > Joplin > Calendar）：

`sqlite3` 直接写入的数据不被 Room 的内存缓存感知 → 必须 `am force-stop` + 重新启动 app。

### Content Provider 类（V2 验证）

```python
def contacts_add_init() -> list[str]:
    return ["pm clear com.android.providers.contacts 2>/dev/null || true"]
```

### 文件系统类（V3 验证）

```python
def markor_create_note_init() -> list[str]:
    return [
        "pm grant net.gsantner.markor android.permission.WRITE_EXTERNAL_STORAGE",
        "mkdir -p /sdcard/Documents/Markor",
    ]
```

### 系统设置类（V4 验证）

```python
def sys_wifi_off_init() -> list[str]:
    return ["svc wifi enable"]  # 初始状态与目标相反
```

## 验证命令层：verify.py

80 个 `*_verify()` 函数，每个返回 `list[dict]`——验证规格列表。

### 验证规格格式

```yaml
verify:
  - command: <shell 命令>
    expect: <精确匹配值>        # 三选一
    expect_re: <正则匹配模式>   # 三选一
    min_lines: <最小输出行数>   # 可选
    not_contain: <不应包含的文本> # 可选
```

### 五级验证体系

| 级别 | 方式 | 适用场景 | 精确度 |
|------|------|---------|--------|
| V1 | `sqlite3 <db> "SELECT COUNT(*)"` | Expense, Recipe, Calendar, Retro, VLC, Tasks, OpenTracks | ★★★★★ |
| V2 | `content query --uri content://` | Contacts, SMS | ★★★★ |
| V3 | `ls / cat / find` | Markor, Files, Camera, Audio, SimpleDraw | ★★★★ |
| V4 | `settings get <ns> <key>` | WiFi, Bluetooth, Brightness | ★★★★★ |
| V5 | `dumpsys activity` + observe | Info Retrieval（查询类） | ★★ |

### 示例

```python
# V1: recipe 删除验证
def recipe_delete_single_verify() -> list[dict]:
    return [_verify_spec(
        f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title='Spicy Tuna Wraps';\"",
        expect="0",
    )]

# V2: SMS 发送验证
def sms_send_verify() -> list[dict]:
    return [_verify_spec(
        "content query --uri content://sms/sent 2>/dev/null | grep body",
        expect_re=r"Hello from automated test",
    )]

# V3: Markor 笔记创建验证
def markor_create_note_verify() -> list[dict]:
    return [_verify_spec(
        "cat /sdcard/Documents/Markor/test_note_hsxn.md 2>/dev/null",
        expect_re=r".+",
    )]
```

## 对齐脚本：align_aw_cases.py

`ALIGN_MAP` 字典将每条用例名映射到三个入口：

```python
(name) → (init_fn, verify_fn, goal_text)
```

生成流程：

```bash
$ python3 scripts/align_aw_cases.py
# 读取 meta/eval_cases_aw_filled.yml
# 用 ALIGN_MAP 补全 init / verify / goal
# 写入 meta/eval_cases_aw_aligned.yml
# 输出: Aligned 116/116 cases
```

## 特殊应用初始化说明

### Broccoli (Recipe)

- **问题**：Room ORM，sqlite3 直写后端不显示
- **解决**：init 末尾追加 `am force-stop`，Agent 启动时重新 launch

### SimpleCalendar

- **问题**：content provider 无 Google 账号，`content insert` 无法写入
- **解决**：改用 `sqlite3 events.db` 直接操作，时间戳单位换算（毫秒 → 秒）

### Pro Expense

- **问题**：`accounting.db` 需要应用首次启动后才创建
- **解决**：`emulator_setup.py` 已完成 app setup（pm clear + launch + onboarding）

### Retro Music / VLC

- **问题**：需要真实 MP3/MP4 文件 + 媒体扫描
- **解决**：`dd if=/dev/urandom` 创建 dummy 文件，V5 验证

### Info Retrieval 类（Tasks/Joplin/OpenTracks 查询）

- **问题**：Agent 的文字回答无法用 shell 验证
- **解决**：V5 级验证（activity 检查 + 屏幕内容存在性），预置数据确保可查询

## 验证清单

检查数据准备是否完备：

```bash
# 1. 模块导入检查
python3 -c "from scripts.aw import data, init, verify; print('OK')"

# 2. 对齐覆盖率
python3 -c "
import yaml
with open('meta/eval_cases_aw_aligned.yml') as f:
    data = yaml.safe_load(f)
cases = data['cases']
print(f'Total: {len(cases)}')
print(f'With init: {sum(1 for c in cases if c.get(\"initialize\"))}')
print(f'With verify: {sum(1 for c in cases if c.get(\"verify\"))}')
"

# 3. 设备连接检查
adb devices | grep emulator-5554

# 4. SQLite 二进制检查
adb -s emulator-5554 shell which sqlite3

# 5. 关键 DB 存在性检查
adb -s emulator-5554 shell "
for db in \
  /data/data/com.flauschcode.broccoli/databases/broccoli \
  /data/data/com.arduia.expense/databases/accounting.db \
  /data/data/com.simplemobiletools.calendar.pro/databases/events.db
do
  if [ -f \$db ]; then echo \"  ✓ \$db\"; else echo \"  ✗ \$db MISSING\"; fi
done
"
```

## 常见问题

| 症状 | 根因 | 解决 |
|------|------|------|
| `INSERT OK` 但 app 不显示数据 | Room ORM 缓存 | `am force-stop` 后重新启动 |
| `content insert` 报错 "For input string" | int 溢出（timestamp > 32bit） | 用 `l` 类型替代 `i` |
| `SELECT COUNT()` 返回 0 | DB 路径错误或表不存在 | 检查 `emulator_setup.py` 是否运行过 |
| Calendar 查询无结果 | 无 Google 账号，无日历 | 改用 SimpleCalendar 的 `events.db` |
