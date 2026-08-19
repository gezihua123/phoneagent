# AndroidWorld 环境对齐指南

> 目标：让 fastaget 模拟器环境与 AndroidWorld 100% 一致，确保评测结果可比。
>
> 本文档三部分：**配置要求（硬性）→ 配置脚本（一键）→ 手动步骤参考（排查用）**。

---

## 1. 配置要求（硬性，逐项不可变）

| 项目 | 要求 | 为什么（违反的后果） |
|------|------|---------------------|
| 设备型号 | Pixel 6 | AW 的 UI 布局/元素位置在 Pixel 6 上验证；其他机型 UI 结构不同，observe 结果偏差 |
| API Level | 33（Android 13, Tiramisu） | AW task_evals、adb 命令、全部 APK 版本均在 API 33 上开发验证（如 Clipper 剪贴板限制需要 API 33 专属 shim 补丁）；其他版本行为差异引入未知变量 |
| 镜像类型 | `google_apis`（**非 playstore**） | AW 假设设备**无 Google 账号**（Calendar 无账号 → 改用 events.db 直写）；playstore 镜像引入 Play 服务状态污染 |
| ABI | arm64-v8a | 宿主机 Apple Silicon |
| Build 类型 | **userdebug（有 root）** | 三处硬依赖 root：① 冻结日期（`adb root` + `date`）② V1 级验证 sqlite3 读应用私有 DB ③ OsmAnd 地图 `chcon` 安全上下文 |
| 分辨率 | 1080×2400（2400×1080 横） | observe/verify 坐标正确性的前提；评测前必须验证（**非 720×1600**） |
| 密度 | 420dpi | 与 Pixel 6 设备规格一致 |
| 启动参数 | `-no-snapshot -grpc 8554` | `-no-snapshot` 干净启动保证每条 case 状态可控；`-grpc 8554` AW 官方 accessibility 转发端口 |
| 日期 | 冻结 2023-10-15 15:34:00 UTC | 日历/任务/运动记录验证断言依赖固定时钟；**每个 task 前重设**，不是设一次就不动 |
| 时区 | UTC + 24 小时制 + 自动时间关闭 | AW Dockerfile/start_emu.sh 对齐 |
| 动画 | window/transition/animator 全 0 | 评测稳定性，对齐 start_emu.sh |
| APK 版本 | **精确锁定** GCS 官方版本 | task_evals 依赖特定版本 DB 结构（例：VLC 必须 3.7.0 旧版，新版 Room 结构与评测代码不兼容） |

## 2. 配置脚本（一键完成）

### 2.1 从零到可评测（完整流程）

```bash
# 前置：sdkmanager/avdmanager 需 JDK 8（JDK 17 缺 JAXB 报 ClassNotFoundException）
export JAVA_HOME=/Library/Java/JavaVirtualMachines/zulu-8.jdk/Contents/Home

# ① 下载系统镜像（约 1.7GB，仅首次）
sdkmanager "system-images;android-33;google_apis;arm64-v8a"

# ② 创建 AVD（仅首次）
#    旧版 avdmanager 设备库无 pixel_6 profile，直接创建后手动写 config.ini
echo no | avdmanager create avd \
  -n Pixel_6_API_33 \
  -k "system-images;android-33;google_apis;arm64-v8a" \
  --force
# 手动补 Pixel 6 硬件参数到 ~/.android/avd/Pixel_6_API_33.avd/config.ini：
#   hw.lcd.width=1080  hw.lcd.height=2400  hw.lcd.density=420
#   hw.ramSize=4096    hw.gpu.mode=auto
# （参考本机现成 config.ini）

# ③ 启动模拟器（AndroidWorld 方式）
#    必须用 emulator 包的完整路径——PATH 里的 emulator 是 legacy tools 包装器，会报
#    "Qt library not found" / qemu 找不到。且不要加 | head 之类的管道（SIGPIPE 会杀掉它）
~/Library/Android/sdk/emulator/emulator \
  -avd Pixel_6_API_33 \
  -no-snapshot \
  -grpc 8554 \
  -no-window \
  -no-audio \
  -no-boot-anim > /tmp/emulator_pixel6.log 2>&1 &

# ④ 等待启动完成（出现 emulator-5554 且 boot_completed=1）
adb wait-for-device
adb shell 'while [ "$(getprop sys.boot_completed)" != "1" ]; do sleep 2; done'

# ⑤ 一键对齐 AW 环境（系统设置 + 冻结日期 + 17 APK + 引导 + 数据文件）
python3 fastaget/emulator_setup.py --serial emulator-5554
# 输出重定向到文件时 Python 缓冲不会实时刷新，期间可看 /tmp/android_world_apks 增长判断进度
```

### 2.2 配置脚本做什么（执行顺序）

| 步骤 | 内容 | 对齐源 |
|------|------|--------|
| 1. 系统设置 | 时区 UTC、日期冻结、24 小时制、动画关闭、pointer/heads-up 关闭 | AW Dockerfile + start_emu.sh |
| 2. 冻结日期 | `adb root` + `date 1015153423.00` | AW datetime_utils（每 task 前重设） |
| 3. 安装 APK | 16 个 GCS APK + VLC 官方 3.7.0 arm64 | setup_device/apps.py |
| 4. 应用设置 | pm clear + grant 权限 + monkey 启动 + 引导页点击 | setup_device/apps.py |
| 5. 数据文件 | OsmAnd 地图推送 + chcon、VLCVideos 目录 | OsmAndApp.setup() |
| 6. 特定配置 | SMS 默认应用、AndroidWorld 悬浮窗 appops | device_constants.py |
| 7. 验证输出 | 打印日期/时区/SMS 默认应用供确认 | — |

脚本已实现：`fastaget/emulator_setup.py`（277 行），带 `--serial` 参数（默认 emulator-5554）。

### 2.3 脚本完成后的验证清单

```bash
# 分辨率必须是 1080x2400（非 720x1600）
phonefast observe -s emulator-5554

# sqlite3 二进制（V1 验证依赖）
adb -s emulator-5554 shell which sqlite3

# 关键 DB 存在性（app setup 完成标志）
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

---

## 3. 手动步骤参考（脚本内部逻辑，排查故障时对照）

### 3.1 系统设置细节

```bash
# 关闭自动时间
adb shell settings put global auto_time 0
adb shell settings put global auto_time_zone 0

# 24 小时制
adb shell settings put system time_12_24 24

# 时区 UTC
adb shell service call alarm 3 s16 UTC

# Root（设置日期需要）
adb root

# 冻结日期：2023-10-15 15:34:00 UTC
# 注意：AndroidWorld 在每个 task 前重新设置，不是设一次就不动
adb shell date 1015153423.00
```

**日期格式**：`MMDDHHMMYY.SS`
- MM=10, DD=15, HH=15, MM=34, YY=23, .SS=00
- 即 `1015153423.00`

**关于 root**：
- `adb root` 是宿主机命令，重启 adbd 为 root
- 不能在设备 shell 里执行 `root`（shell 里没有这个命令）
- 执行 `adb root` 后，后续所有 `adb shell <cmd>` 都以 root 身份运行

```bash
# 关闭指针位置显示
adb shell settings put system pointer_location 0

# 关闭 heads-up 通知
adb shell settings put global heads_up_notifications_enabled 0

# 关闭动画（start_emu.sh 对齐）
adb shell settings put global window_animation_scale 0.0
adb shell settings put global transition_animation_scale 0.0
adb shell settings put global animator_duration_scale 0.0
```

### 3.2 应用清单与设置

**预装应用（无需安装 APK）**

| 应用 | 包名 | 权限 | 首次启动操作 |
|------|------|------|-------------|
| Camera | `com.android.camera2` | `ACCESS_COARSE_LOCATION` | 点 "NEXT" |
| Chrome | `com.android.chrome` | — | 点 "Accept & continue" → "No thanks" ×2 |
| Clock | `com.google.android.deskclock` | — | 启动一次即可 |
| Contacts | `com.google.android.contacts` | — | 点 "Skip" → "Don't allow" |
| Dialer | `com.google.android.dialer` | — | 清除数据即可 |
| Files | `com.google.android.documentsui` | — | 清除数据即可 |
| Settings | `com.android.settings` | — | 清除数据即可 |

**第三方应用（需安装 APK，版本精确锁定）**

APK 统一下载源：`https://storage.googleapis.com/gresearch/android_world/{apk_name}`

| 应用 | APK 文件 | 包名 | 权限 | 首次启动操作 |
|------|---------|------|------|-------------|
| AndroidWorld | `androidworld.apk` | `com.example.androidworld` | `system_alert_window` (appops) | 启动→关闭 |
| Audio Recorder | `com.dimowner.audiorecorder_926.apk` | `com.dimowner.audiorecorder` | `RECORD_AUDIO`, `POST_NOTIFICATIONS` | monkey 启动→等 2s→关闭 |
| Markor | `net.gsantner.markor_146.apk` | `net.gsantner.markor` | — | 点 "NEXT"×5 → "DONE" → "OK" → "Allow access to manage all files" |
| Clipper | `clipper.apk` | `ca.zgrs.clipper` | — | 点 "Continue" → "OK" |
| Simple Calendar Pro | `com.simplemobiletools.calendar.pro_238.apk` | `com.simplemobiletools.calendar.pro` | `READ_CALENDAR`, `WRITE_CALENDAR`, `POST_NOTIFICATIONS` | 启动→关闭 |
| Tasks | `org.tasks_130605.apk` | `org.tasks` | — | 启动→关闭 |
| Simple Draw Pro | `com.simplemobiletools.draw.pro_79.apk` | `com.simplemobiletools.draw.pro` | — | 清除数据即可 |
| Simple Gallery Pro | `com.simplemobiletools.gallery.pro_396.apk` | `com.simplemobiletools.gallery.pro` | `WRITE_EXTERNAL_STORAGE`, `ACCESS_MEDIA_LOCATION`, `READ_MEDIA_IMAGES`, `READ_MEDIA_VIDEO`, `POST_NOTIFICATIONS` | 点 "All files" → "Allow access to manage all files" |
| Simple SMS Messenger | `com.simplemobiletools.smsmessenger_85.apk` | `com.simplemobiletools.smsmessenger` | — | 设为默认 SMS → 点 "SMS Messenger" → "Set as default" |
| MiniWob | `miniwobapp.apk` | `com.google.androidenv.miniwob` | — | 清除数据即可 |
| Pro Expense | `com.arduia.expense_11.apk` | `com.arduia.expense` | — | 点 "NEXT" → "CONTINUE" |
| Broccoli Recipe | `com.flauschcode.broccoli_1020600.apk` | `com.flauschcode.broccoli` | — | 启动→等 2s→关闭 |
| OsmAnd | `net.osmand-4.6.13.apk` | `net.osmand` | `POST_NOTIFICATIONS` | 点 "SKIP DOWNLOAD" → 复制地图（见 4.1） |
| OpenTracks | `de.dennisguse.opentracks_5705.apk` | `de.dennisguse.opentracks` | `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION`, `POST_NOTIFICATIONS` | 点 "Allow"（蓝牙权限） |
| VLC | `org.videolan.vlc_13050407.apk`（ARM 官方 3.7.0） | `org.videolan.vlc` | `POST_NOTIFICATIONS` | 点 "Skip" → "GRANT PERMISSION" → "OK" → "Allow access to manage all files" |
| Joplin | `net.cozic.joplin_2097740.apk` | `net.cozic.joplin` | `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION` | monkey 启动→等 10s→关闭→等 10s→创建 note→清 DB |
| Retro Music | `code.name.monkey.retromusic_10603.apk` | `code.name.monkey.retromusic` | `READ_MEDIA_AUDIO`, `POST_NOTIFICATIONS` | 启动→等 2s→关闭 |

**VLC 版本锁定说明**：必须用 `org.videolan.vlc_13050407.apk`（3.7.0）。task_evals 的 vlc.py 依赖旧版 DB 结构（app_db/vlc_media.db: Media/Playlist 表）；3.7.0 之后的 Room 新结构与 AW 评测代码不兼容（collation FILENAME / 表名不同）。

**特殊设置**：

```bash
# 默认 SMS 应用
adb shell settings put secure sms_default_application com.simplemobiletools.smsmessenger

# AndroidWorld 悬浮窗权限
adb shell appops set com.example.androidworld android:system_alert_window allow
```

### 3.3 数据文件

**OsmAnd 地图**：

```bash
# 下载
curl -fL -o /tmp/android_world_apks/Liechtenstein_europe.obf \
  https://storage.googleapis.com/gresearch/android_world/Liechtenstein_europe.obf

# 推送
adb push /tmp/android_world_apks/Liechtenstein_europe.obf \
  /storage/emulated/0/Android/data/net.osmand/files/

# 设置安全上下文（需要 root）
adb shell chcon u:object_r:media_rw_data_file:s0 \
  /storage/emulated/0/Android/data/net.osmand/files/Liechtenstein_europe.obf
```

**VLC 视频目录**：

```bash
adb shell mkdir -p /storage/emulated/0/VLCVideos
```

**数据路径常量**：

| 常量 | 路径 | 用途 |
|------|------|------|
| `EMULATOR_DATA` | `/storage/emulated/0/` | 根数据目录 |
| `AUDIORECORDER_DATA` | `/storage/emulated/0/Android/data/com.dimowner.audiorecorder/files/Music/records` | 录音文件 |
| `DOWNLOAD_DATA` | `/storage/emulated/0/Download` | 下载目录 |
| `GALLERY_DATA` | `/sdcard/DCIM` | 相册/照片 |
| `MARKOR_DATA` | `/storage/emulated/0/Documents/Markor` | Markor 笔记 |
| `MUSIC_DATA` | `/sdcard/Music` | 音乐文件 |
| `OSMAND_DATA` | `/storage/emulated/0/Android/data/net.osmand/files` | OsmAnd 地图 |
| `PHOTOS_DATA` | `/sdcard/Pictures` | 图片 |
| `VIDEOS_DATA` | `/sdcard/Movies` | 视频文件 |

## 4. 当前环境状态（2026-08-18 本机配置完成）

| 项目 | 状态 | 验证 |
|------|------|------|
| 镜像 android-33 google_apis arm64 (r17) | ✅ | `ls ~/Library/Android/sdk/system-images/android-33/google_apis/arm64-v8a/` |
| AVD Pixel_6_API_33 | ✅ | `~/Library/Android/sdk/emulator/emulator -list-avds` |
| emulator-5554 在线 | ✅ | `adb devices \| grep emulator-5554`，boot_completed=1 |
| 分辨率 1080x2400 @ 420 | ✅ | `wm size` = 1080x2400 |
| userdebug（root） | ✅ | `ro.build.type` = userdebug |
| 时区 UTC | ✅ | `getprop persist.sys.timezone` = UTC |
| 日期冻结 | ✅ | `date` = Oct 15 2023（每个 task 前重设） |
| 24 小时制 | ✅ | `time_12_24` = 24 |
| 自动时间关闭 | ✅ | `auto_time` = 0, `auto_time_zone` = 0 |
| 默认 SMS | ✅ | `sms_default_application` = Simple SMS |
| OsmAnd 地图 | ✅ | `Liechtenstein_europe.obf` 已推送 |
| VLC 目录 | ✅ | `/storage/emulated/0/VLCVideos` 已创建 |
| AndroidWorld 悬浮窗 | ✅ | `system_alert_window` = allow |
| sqlite3 二进制 | ✅ | `/system/bin/sqlite3` |
| 17 个 APK 安装 | ✅ | 16 GCS + VLC 3.7.0 |
| 应用 DB 就绪 | ✅ | broccoli / accounting.db / events.db 均存在 |
| 应用设置（引导+权限） | ✅ | emulator_setup.py 完成（exit 0） |

**本机注意**：
- 启动模拟器必须用完整路径 `~/Library/Android/sdk/emulator/emulator`——PATH 里的 `emulator` 是 legacy tools 包装器（x86_64 时代），会导致 Qt/qemu 找不到
- sdkmanager/avdmanager 需 `JAVA_HOME=/Library/Java/JavaVirtualMachines/zulu-8.jdk/Contents/Home`（JDK 17 缺 JAXB 会崩）
- AVD config.ini 的 Pixel 6 硬件参数为手动写入（旧版 avdmanager 设备库无 pixel_6 profile）
- 评测前若真机在线，按 device-safety.md 先 `adb disconnect` 断开

## 5. 参考

- AndroidWorld 源码：`~/Downloads/android_world/`（如已 clone）
- 应用设置：`android_world/env/setup_device/apps.py`
- 设备常量：`android_world/env/device_constants.py`
- 设置编排：`android_world/env/setup_device/setup.py`
- ADB 工具：`android_world/env/adb_utils.py`
- 日期工具：`android_world/utils/datetime_utils.py`
