#!/usr/bin/env python3
"""批量评测脚本：非破坏性任务在前，破坏性任务在后，每个破坏性任务前重置设备状态。

用法:
    ANTHROPIC_BASE_URL=... ANTHROPIC_AUTH_TOKEN=... \
    python3 scripts/batch_eval.py --model deepseek-v4-pro --serial emulator-5554

设备选择遵守多设备安全规范：不硬编码 serial——单设备自动检测，多设备必须
显式 --serial（评测只用 emulator-5554，严禁真机）。adb 操作一律走 Phonefast。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import time

from fastaget.device.phonefast import Phonefast

# ── 设备状态重置基线（每个破坏性任务前执行）──────────────────
# 轻量重置：只关飞行模式（避免触发锁屏），其余靠用例自身的"先检查再操作"
DEVICE_RESET_COMMANDS = [
    "settings put global airplane_mode_on 0",  # 飞行模式会影响 WiFi/蓝牙可用性
]


def reset_device(pf: Phonefast) -> None:
    """轻量重置设备：回桌面 + 关飞行模式。不切换 WiFi/蓝牙（交给用例先检查）。

    一律经 Phonefast（已绑定 serial）——禁止直调 adb（多设备安全铁律）。
    """
    pf.key("home")
    for cmd in DEVICE_RESET_COMMANDS:
        pf.shell(cmd)
    time.sleep(1.0)


# ── 测试用例 ──────────────────────────────────────────────────
# 非破坏性：只读/导航，不改系统状态
TESTS_SAFE = [
    ("T01-返回桌面", "返回桌面"),
    ("T02-打开设置", "打开设置"),
    ("T03-查看蓝牙", "打开设置，查看蓝牙选项"),
    ("T08-查看存储", "打开设置，查看存储空间"),
    ("T13-查看电池", "打开设置，查看电池用量"),
    ("T18-查看应用", "打开设置，查看所有应用"),
    ("T20-截屏", "截取当前屏幕"),
]

# 破坏性：改变 WiFi/蓝牙/亮度/飞行模式，放最后 + 每个前重置
TESTS_STATEFUL = [
    ("T09-关闭蓝牙", "打开设置，关闭蓝牙"),
    ("T10-开启蓝牙", "打开设置，开启蓝牙"),
    ("T04-开启WiFi", "打开设置，开启WiFi"),
    ("T05-关闭WiFi", "打开设置，关闭WiFi"),
    ("T06-亮度最大", "打开设置，亮度调到最大"),
    ("T07-亮度最小", "打开设置，亮度调到最小"),
    ("T19-飞行模式", "开启飞行模式"),
]

# L3 复杂任务：多步操作，放最后
TESTS_COMPLEX = [
    ("T21-安装小红书", "打开 Google Play，安装小红书"),
    ("T30-开发者选项", "打开设置，开启开发者选项"),
    ("T23-切换语言", "打开设置，切换系统语言为English"),
    ("T22-查看应用详情", "打开设置，查看相机应用详情"),
]


def run_one(goal: str, model: str, max_steps: int, env: dict, serial: str = "") -> dict:
    t0 = time.monotonic()
    cmd = ["python3", "-m", "fastaget", "run", goal, "--model", model, "--max-steps", str(max_steps), "--trace"]
    if serial:
        cmd += ["--serial", serial]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
    wall = time.monotonic() - t0
    out = p.stdout + p.stderr
    ok = "[PASS]" in out
    llm = out.count("── LLM #")
    cost = 0.0
    for line in out.split("\n"):
        if "花费 $" in line:
            try:
                cost = float(line.split("$")[1].split()[0])
            except ValueError:
                pass
    return {"ok": ok, "llm": llm, "wall": wall, "cost": cost}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek-v4-pro")
    ap.add_argument("--max-steps", type=int, default=15)
    ap.add_argument("--serial", default=None,
                    help="设备 serial（多设备时必须指定；评测用 emulator-5554）")
    args = ap.parse_args()

    env = {
        **os.environ,
        "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic"),
        "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN", ""),
        "PATH": os.environ["HOME"] + "/.local/bin:" + os.environ.get("PATH", ""),
    }
    if not env["ANTHROPIC_AUTH_TOKEN"]:
        raise SystemExit("ANTHROPIC_AUTH_TOKEN 未设置")

    # serial 解析委托 Phonefast（L1：单设备自动检测，多真机拒绝猜测）
    pf = Phonefast(serial=args.serial)
    serial = pf.serial

    # 首次重置
    reset_device(pf)

    results = []
    print(f"{'用例':<18} {'结果':<4} {'LLM':>4} {'耗时':>7} {'成本':>8}")
    print("-" * 48)

    print("── 非破坏性任务 ──")
    for label, goal in TESTS_SAFE:
        r = run_one(goal, args.model, args.max_steps, env, serial)
        results.append((label, r))
        print(f"{label:<18} {'✅' if r['ok'] else '❌':<4} {r['llm']:>4} {r['wall']:>6.1f}s ${r['cost']:>7.4f}")

    print("── 破坏性任务（每个前重置设备）──")
    for label, goal in TESTS_STATEFUL:
        reset_device(pf)
        r = run_one(goal, args.model, args.max_steps, env, serial)
        results.append((label, r))
        print(f"{label:<18} {'✅' if r['ok'] else '❌':<4} {r['llm']:>4} {r['wall']:>6.1f}s ${r['cost']:>7.4f}")

    print("── L3 复杂任务 ──")
    for label, goal in TESTS_COMPLEX:
        reset_device(pf)
        r = run_one(goal, args.model, args.max_steps, env, serial)
        results.append((label, r))
        print(f"{label:<18} {'✅' if r['ok'] else '❌':<4} {r['llm']:>4} {r['wall']:>6.1f}s ${r['cost']:>7.4f}")

    # 收尾重置
    reset_device(pf)

    passed = sum(1 for _, r in results if r["ok"])
    total_llm = sum(r["llm"] for _, r in results)
    total_wall = sum(r["wall"] for _, r in results)
    total_cost = sum(r["cost"] for _, r in results)
    n = len(results)
    print("-" * 48)
    print(f"总计: {passed}/{n} ({passed/n*100:.0f}%) | {total_llm}LLM | {total_wall:.0f}s | ${total_cost:.4f}")
    print(f"平均: {total_llm/n:.1f}LLM | {total_wall/n:.1f}s | ${total_cost/n:.4f}")


if __name__ == "__main__":
    main()
