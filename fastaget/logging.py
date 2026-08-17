"""logging 配置——Filter 注入 session_id，模块级 logger 直接用。

用法:
    # Session 初始化时调一次
    from fastaget.logging import setup_logging
    setup_logging(session_id="xxx", log_dir="logs")

    # 任何地方直接用（不用传 logger、不用 if 判空）
    import logging
    logger = logging.getLogger("fastaget.agent")
    logger.info("run_start | goal=%s", goal)
    logger.debug("llm_call | turn=%d cost=%.6f", turn, cost)

产物:
    logs/<session_id>.log       — INFO+（关键事件）
    logs/<session_id>.debug.log — DEBUG+（完整诊断）

格式:
    2026-08-05 14:30:01 | s_001 | fastaget.agent | INFO | run_start | goal=关闭wifi
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path


class _SessionFilter(logging.Filter):
    """Handler 级 Filter——给每条 record 补 session_id。

    比 LoggerAdapter 更可靠：不管 logger 怎么来的（直接 getLogger 或 adapter），
    只要有 handler 挂了此 Filter，record.session_id 都会被填充。
    """

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "session_id"):
            record.session_id = self.session_id
        return True


def setup_logging(
    session_id: str,
    *,
    log_dir: str = "logs",
    console: bool = True,
) -> None:
    """为 session 配置日志——在 fastaget logger 上挂 handler + Filter。

    配置后，任何模块用 `logging.getLogger("fastaget.xxx").info(...)` 都会自动带上 session_id。
    不动 root logger，不破坏其他库。
    """
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(session_id)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sf = _SessionFilter(session_id)

    # info 日志文件
    info_fh = logging.FileHandler(str(Path(log_dir) / f"{session_id}.log"), encoding="utf-8")
    info_fh.setLevel(logging.INFO)
    info_fh.setFormatter(fmt)
    info_fh.addFilter(sf)

    # debug 日志文件
    debug_fh = logging.FileHandler(str(Path(log_dir) / f"{session_id}.debug.log"), encoding="utf-8")
    debug_fh.setLevel(logging.DEBUG)
    debug_fh.setFormatter(fmt)
    debug_fh.addFilter(sf)

    # 配置 fastaget logger（不动 root）
    fastaget_logger = logging.getLogger("fastaget")
    fastaget_logger.setLevel(logging.DEBUG)
    # 清除 fastaget 自身的旧 handler（不动 root handler）
    for h in list(fastaget_logger.handlers):
        fastaget_logger.removeHandler(h)
    fastaget_logger.addHandler(info_fh)
    fastaget_logger.addHandler(debug_fh)

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.WARNING)
        ch.setFormatter(fmt)
        ch.addFilter(sf)
        fastaget_logger.addHandler(ch)
