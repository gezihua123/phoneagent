"""模拟器环境设置——对齐 AndroidWorld。

三步：
  1. 系统设置（时区/日期/动画）
  2. 安装 APK
  3. 清除数据 + 授权 + 点引导页

Usage:
    python3 fastaget/emulator_setup.py --serial emulator-5554
"""
import argparse
import os
import re
import subprocess
import sys
import time


def _parse_serial() -> str:
    parser = argparse.ArgumentParser(description="配置模拟器为 AndroidWorld 环境")
    parser.add_argument("--serial", default="emulator-5554",
                        help="设备 serial（默认 emulator-5554）")
    args, _ = parser.parse_known_args()
    return args.serial

GCS = "https://storage.googleapis.com/gresearch/android_world"
CACHE = "/tmp/android_world_apks"
# AW 官方 VLC 版本（org.videolan.vlc_13050407.apk）——task_evals 的 vlc.py
# 依赖旧版 DB 结构（app_db/vlc_media.db: Media/Playlist 表）；3.7.0 的 Room 新
# 结构与 AW 评测代码不兼容（collation FILENAME / 表名不同）
VLC_URL = "https://storage.googleapis.com/gresearch/android_world/org.videolan.vlc_13050407.apk"


def adb(serial, *args, timeout=60):
    r = subprocess.run(["adb", "-s", serial] + list(args),
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def download(name):
    dest = os.path.join(CACHE, name)
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.isfile(dest):
        print(f"  download {name}")
        subprocess.run(["curl", "-fL", "-o", dest, f"{GCS}/{name}"],
                       check=True, capture_output=True)
    return dest


def install(serial, apk_name):
    dest = download(apk_name)
    out = adb(serial, "install", "-r", dest)
    ok = "Success" in out
    print(f"  {'✓' if ok else '✗'} install {apk_name}")
    return ok


def install_vlc(serial):
    dest = os.path.join(CACHE, "VLC-Android-3.7.0-arm64-v8a.apk")
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.isfile(dest):
        print(f"  download VLC from videolan.org")
        subprocess.run(["curl", "-fL", "-o", dest, VLC_URL],
                       check=True, capture_output=True)
    out = adb(serial, "install", "-r", dest)
    ok = "Success" in out
    print(f"  {'✓' if ok else '✗'} install VLC")
    return ok


def tap(serial, text):
    """通过 phonefast 找文本并点击。"""
    try:
        from fastaget.device.phonefast import Phonefast
        pf = Phonefast(serial=serial)
        r = pf.observe(format="flatref", max_elements=200)
        for line in r.elements_text.split("\n"):
            if text.lower() in line.lower() and "clickable" in line:
                m = re.search(r"bounds=\[(\d+),(\d+)\]\[(\d+),(\d+)\]", line)
                if m:
                    cx, cy = (int(m.group(1))+int(m.group(3)))//2, (int(m.group(2))+int(m.group(4)))//2
                    pf.tap(x=cx, y=cy)
                    return True
    except Exception:
        pass
    return False


def setup(serial, pkg, perms=None, clicks=None, wait=2):
    """清除数据 + 授权 + 启动 + 点引导。"""
    adb(serial, "shell", "pm", "clear", pkg)
    if perms:
        for p in perms:
            adb(serial, "shell", "pm", "grant", pkg, p)
    adb(serial, "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(wait)
    if clicks:
        for text in clicks:
            tap(serial, text)
            time.sleep(1.5)
    adb(serial, "shell", "am", "force-stop", pkg)


def system_settings(serial):
    """系统设置——对齐 AndroidWorld。"""
    print("=== 系统设置 ===")
    adb(serial, "shell", "settings", "put", "global", "auto_time", "0")
    adb(serial, "shell", "settings", "put", "global", "auto_time_zone", "0")
    adb(serial, "shell", "settings", "put", "system", "time_12_24", "24")
    adb(serial, "shell", "service", "call", "alarm", "3", "s16", "UTC")
    adb(serial, "shell", "settings", "put", "system", "pointer_location", "0")
    adb(serial, "shell", "settings", "put", "global", "heads_up_notifications_enabled", "0")
    # 关闭动画（AndroidWorld docker_setup/start_emu.sh）
    adb(serial, "shell", "settings", "put", "global", "window_animation_scale", "0.0")
    adb(serial, "shell", "settings", "put", "global", "transition_animation_scale", "0.0")
    adb(serial, "shell", "settings", "put", "global", "animator_duration_scale", "0.0")
    print("  done")


def freeze_date(serial):
    """冻结日期到 2023-10-15 15:34:00 UTC（需要 root）。"""
    print("=== 冻结日期 ===")
    adb(serial, "root")
    time.sleep(1)
    adb(serial, "shell", "date", "1015153423.00")
    print(f"  {adb(serial, 'shell', 'date')}")


def install_apks(serial):
    """安装全部 APK。"""
    print("=== 安装 APK ===")
    apks = [
        "androidworld.apk",
        "com.dimowner.audiorecorder_926.apk",
        "com.arduia.expense_11.apk",
        "com.flauschcode.broccoli_1020600.apk",
        "com.simplemobiletools.calendar.pro_238.apk",
        "com.simplemobiletools.draw.pro_79.apk",
        "com.simplemobiletools.gallery.pro_396.apk",
        "com.simplemobiletools.smsmessenger_85.apk",
        "clipper.apk",
        "miniwobapp.apk",
        "net.cozic.joplin_2097740.apk",
        "net.gsantner.markor_146.apk",
        "net.osmand-4.6.13.apk",
        "code.name.monkey.retromusic_10603.apk",
        "de.dennisguse.opentracks_5705.apk",
        "org.tasks_130605.apk",
    ]
    for apk in apks:
        install(serial, apk)
    install_vlc(serial)


def setup_apps(serial):
    """全部应用设置。"""
    print("=== 设置应用 ===")

    # 预装应用
    setup(serial, "com.android.camera2",
          perms=["android.permission.ACCESS_COARSE_LOCATION"],
          clicks=["NEXT"])

    setup(serial, "com.android.chrome",
          clicks=["Accept & continue", "No thanks", "No thanks"])

    setup(serial, "com.google.android.deskclock")

    setup(serial, "com.google.android.contacts",
          clicks=["Skip", "Don't allow"])

    # Markor — 5次NEXT + DONE + OK + Allow
    setup(serial, "net.gsantner.markor",
          clicks=["NEXT", "NEXT", "NEXT", "NEXT", "NEXT",
                   "DONE", "OK", "Allow access to manage all files"],
          wait=3)

    # Simple SMS — 设为默认 + 引导
    adb(serial, "shell", "settings", "put", "secure",
        "sms_default_application", "com.simplemobiletools.smsmessenger")
    setup(serial, "com.simplemobiletools.smsmessenger",
          clicks=["SMS Messenger", "Set as default"])

    # Simple Calendar
    setup(serial, "com.simplemobiletools.calendar.pro",
          perms=["android.permission.READ_CALENDAR",
                 "android.permission.WRITE_CALENDAR",
                 "android.permission.POST_NOTIFICATIONS"])

    # Simple Gallery
    setup(serial, "com.simplemobiletools.gallery.pro",
          perms=["android.permission.WRITE_EXTERNAL_STORAGE",
                 "android.permission.ACCESS_MEDIA_LOCATION",
                 "android.permission.READ_MEDIA_IMAGES",
                 "android.permission.READ_MEDIA_VIDEO",
                 "android.permission.POST_NOTIFICATIONS"],
          clicks=["All files", "Allow access to manage all files"])

    # Expense
    setup(serial, "com.arduia.expense",
          clicks=["NEXT", "CONTINUE"])

    # OsmAnd — SKIP DOWNLOAD + 地图
    setup(serial, "net.osmand",
          perms=["android.permission.POST_NOTIFICATIONS"],
          clicks=["SKIP DOWNLOAD"])
    map_dest = "/storage/emulated/0/Android/data/net.osmand/files/"
    adb(serial, "shell", "mkdir", "-p", map_dest)
    adb(serial, "push", download("Liechtenstein_europe.obf"), map_dest)
    adb(serial, "shell", "chcon",
        "u:object_r:media_rw_data_file:s0",
        os.path.join(map_dest, "Liechtenstein_europe.obf"))

    # VLC
    adb(serial, "shell", "mkdir", "-p", "/storage/emulated/0/VLCVideos")
    setup(serial, "org.videolan.vlc",
          perms=["android.permission.POST_NOTIFICATIONS"],
          clicks=["Skip", "GRANT PERMISSION", "OK",
                   "Allow access to manage all files"],
          wait=3)

    # Joplin
    setup(serial, "net.cozic.joplin",
          perms=["android.permission.ACCESS_COARSE_LOCATION",
                 "android.permission.ACCESS_FINE_LOCATION"],
          wait=10)

    # Retro Music
    setup(serial, "code.name.monkey.retromusic",
          perms=["android.permission.READ_MEDIA_AUDIO",
                 "android.permission.POST_NOTIFICATIONS"])

    # OpenTracks
    setup(serial, "de.dennisguse.opentracks",
          perms=["android.permission.ACCESS_COARSE_LOCATION",
                 "android.permission.ACCESS_FINE_LOCATION",
                 "android.permission.POST_NOTIFICATIONS"],
          clicks=["Allow"])

    # Audio Recorder
    setup(serial, "com.dimowner.audiorecorder",
          perms=["android.permission.RECORD_AUDIO",
                 "android.permission.POST_NOTIFICATIONS"])

    # Tasks
    setup(serial, "org.tasks")

    # Recipe
    setup(serial, "com.flauschcode.broccoli")

    # Clipper
    setup(serial, "ca.zgrs.clipper",
          clicks=["Continue", "OK"])

    # AndroidWorld — 悬浮窗权限
    adb(serial, "shell", "appops", "set", "com.example.androidworld",
        "android:system_alert_window", "allow")
    setup(serial, "com.example.androidworld")


def main():
    serial = _parse_serial()
    print(f"Configuring {serial} for AndroidWorld alignment...\n")

    system_settings(serial)
    freeze_date(serial)
    install_apks(serial)
    setup_apps(serial)

    print("\n=== 完成 ===")
    print(f"  日期: {adb(serial, 'shell', 'date')}")
    print(f"  时区: {adb(serial, 'shell', 'getprop', 'persist.sys.timezone')}")
    print(f"  SMS:  {adb(serial, 'shell', 'settings', 'get', 'secure', 'sms_default_application')}")


if __name__ == "__main__":
    main()
