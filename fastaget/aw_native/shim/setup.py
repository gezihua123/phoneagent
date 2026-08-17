"""setup_device.setup 的 shim——fastaget 环境 app 已由 emulator_setup.py 预装。

AW 原版 install_app_if_not_installed 会从 GCS 下载 APK（网络 + 重依赖）。
fastaget 的模拟器环境由 fastaget/emulator_setup.py 一次性装齐 16 个 app，
此 shim 只做存在性检查：已安装 → no-op；未安装 → 明确报错提示先跑
emulator_setup.py。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def install_app_if_not_installed(app_name: str, env) -> None:
    """检查 app 是否已安装；未安装时报错（不自动下载）。"""
    del env  # 不在此 shim 使用
    from fastaget.aw_native.shim import interface

    # app_name 是 AppSetup 对象（有 app_name 属性）或字符串
    name = getattr(app_name, "app_name", None) or str(app_name)
    out = interface.shell(f"pm list packages 2>/dev/null | grep {name}", timeout=20.0)
    if name in out:
        logger.info("app 已安装: %s", name)
        return
    raise RuntimeError(
        f"app 未安装: {name}——请先运行 python3 fastaget/emulator_setup.py "
        f"完成模拟器环境准备（fastaget 不走 AW 的 GCS 下载流程）"
    )
