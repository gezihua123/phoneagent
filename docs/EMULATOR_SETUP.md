# AndroidWorld 环境对齐指南

> 目标：让 fastaget 模拟器环境与 AndroidWorld 100% 一致，确保评测结果可比。

## 1. 镜像要求

| 项目 | AndroidWorld | 验证状态 |
|------|-------------|---------|
| 设备型号 | Pixel 6 | ✅ |
| API Level | 33 (Android 13, Tiramisu) | ✅ |
| 镜像类型 | google_apis（非 playstore） | ✅ |
| ABI | arm64-v8a | ✅ |
| Build 类型 | userdebug（有 root） | ✅ |
| 分辨率 | 2400×1080 | ✅ |
| 密度 | 420dpi | ✅ |
| 启动参数 | `-no-snapshot -grpc 8554` | ✅ |

### 创建 AVD

```bash
# 下载镜像（如未下载）
sdkmanager "system-images;android-33;google_apis;arm64-v8a"

# 创建 AVD
avdmanager create avd \
  -n Pixel_6_API_33 \
  -d "pixel_6" \
  -k "system-images;android-33;google_apis;arm64-v8a" \
  --force
```

### 启动模拟器（AndroidWorld 方式）

```bash
~/Library/Android/sdk/emulator/emulator \
  -avd Pixel_6_API_33 \
  -no-snapshot \
  -grpc 8554 \
  -no-window \
  -no-audio \
  -no-boot-anim
```

**关键参数说明**：
- `-no-snapshot`：不加载保存的状态，确保干净启动
- `-grpc 8554`：gRPC 端口，AndroidWorld 用于 accessibility 转发

## 2. 系统设置

### 2.1 时区与时间

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

### 2.2 其他系统设置

```bash
# 关闭指针位置显示
adb shell settings put system pointer_location 0

# 关闭 heads-up 通知
adb shell settings put global heads_up_notifications_enabled 0
```

## 3. 应用清单与设置

### 3.1 预装应用（无需安装 APK）

| 应用 | 包名 | 权限 | 首次启动操作 |
|------|------|------|-------------|
| Camera | `com.android.camera2` | `ACCESS_COARSE_LOCATION` | 点 "NEXT" |
| Chrome | `com.android.chrome` | — | 点 "Accept & continue" → "No thanks" ×2 |
| Clock | `com.google.android.deskclock` | — | 启动一次即可 |
| Contacts | `com.google.android.contacts` | — | 点 "Skip" → "Don't allow" |
| Dialer | `com.google.android.dialer` | — | 清除数据即可 |
| Files | `com.google.android.documentsui` | — | 清除数据即可 |
| Settings | `com.android.settings` | — | 清除数据即可 |

### 3.2 第三方应用（需安装 APK）

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
| VLC | `org.videolan.vlc_13050408.apk` (x86) / `org.videolan.vlc_13050407.apk` (ARM) | `org.videolan.vlc` | `POST_NOTIFICATIONS` | 点 "Skip" → "GRANT PERMISSION" → "OK" → "Allow access to manage all files" |
| Joplin | `net.cozic.joplin_2097740.apk` | `net.cozic.joplin` | `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION` | monkey 启动→等 10s→关闭→等 10s→创建 note→清 DB |
| Retro Music | `code.name.monkey.retromusic_10603.apk` | `code.name.monkey.retromusic` | `READ_MEDIA_AUDIO`, `POST_NOTIFICATIONS` | 启动→等 2s→关闭 |

### 3.3 特殊设置

**默认 SMS 应用**：
```bash
adb shell settings put secure sms_default_application com.simplemobiletools.smsmessenger
```

**AndroidWorld 悬浮窗权限**：
```bash
adb shell appops set com.example.androidworld android:system_alert_window allow
```

## 4. 数据文件

### 4.1 OsmAnd 地图

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

### 4.2 VLC 视频目录

```bash
adb shell mkdir -p /storage/emulated/0/VLCVideos
```

### 4.3 数据路径常量

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

## 5. 当前环境状态（2026-07-29 已配置完成）

| 项目 | 状态 | 验证 |
|------|------|------|
| 镜像 Pixel_6_API_33 | ✅ | userdebug + google_apis + arm64 |
| 时区 UTC | ✅ | `getprop persist.sys.timezone` = UTC |
| 日期冻结 | ✅ | `date` = Oct 15 2023（时钟自然走秒，每个 task 前重设） |
| 24 小时制 | ✅ | `time_12_24` = 24 |
| 自动时间关闭 | ✅ | `auto_time` = 0, `auto_time_zone` = 0 |
| 默认 SMS | ✅ | `sms_default_application` = Simple SMS |
| OsmAnd 地图 | ✅ | `Liechtenstein_europe.obf` 已推送 |
| VLC 目录 | ✅ | `/storage/emulated/0/VLCVideos` 已创建 |
| AndroidWorld 悬浮窗 | ✅ | `system_alert_window` = allow |
| 全部 18 个应用设置 | ✅ | 清除数据 + 权限 + 首次启动引导 完成 |

## 6. 参考

- AndroidWorld 源码：`/Users/mulei/Downloads/android_world/`
- 应用设置：`android_world/env/setup_device/apps.py`
- 设备常量：`android_world/env/device_constants.py`
- 设置编排：`android_world/env/setup_device/setup.py`
- ADB 工具：`android_world/env/adb_utils.py`
- 日期工具：`android_world/utils/datetime_utils.py`
