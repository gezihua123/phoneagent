"""自愈层：四层分层防御的重试与升级原语。

借鉴 mobilerun 五层自愈，按测试场景重组为四层：
  L1 设备 I/O   — phonefast 调用失败：退避重试 + daemon 重启 + 重新 observe 校准
  L2 工具执行   — 工具异常已在 ToolRegistry.execute 转 ActionResult(success=False)
  L3 模型调用   — LLM 超时/空响应/异常：线性退避重试
  L4 测试编排   — 连续失败：升级到重新规划（在 agent 层处理 error_flag）

这里实现 L1/L3 的通用重试原语；L2 在 registry，L4 在 agent。
"""
from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    retries: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, Exception], None] | None = None,
    should_retry: Callable[[Exception], bool] | None = None,
) -> T:
    """线性退避重试。retries=总尝试次数（含首次）。

    delay = base_delay * attempt（attempt 从 1 起）。
    should_retry：可选，传入异常返回 False 则不重试直接抛（用于跳过确定性崩溃如 max_turns）。
    """
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — 通用重试原语
            last_exc = e
            # should_retry 判定：返回 False 则立即放弃重试（确定性崩溃）
            if should_retry is not None and not should_retry(e):
                break
            if attempt >= retries:
                break
            if on_retry:
                on_retry(attempt, e)
            sleep(base_delay * attempt)
    assert last_exc is not None
    raise last_exc


def is_max_turns_error(exc: Exception) -> bool:
    """判断是否为 claude_agent_sdk 的 max_turns 确定性崩溃。

    max_turns=1 模式下模型想多轮推理会被截断，抛 'Reached maximum number of turns'。
    这类崩溃对相同输入必复现，重试无意义，应跳过重试交由调用方降级。
    """
    msg = str(exc).lower()
    return "maximum number of turns" in msg or "max turns" in msg


def is_device_io_error(exc: Exception) -> bool:
    """判断是否为设备 I/O 类故障（L1 处理范围）。"""
    from fastaget.device.phonefast import PhonefastError

    if isinstance(exc, PhonefastError):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in ("device", "daemon", "scrcpy", "timeout", "connection"))


def is_llm_error(exc: Exception) -> bool:
    """判断是否为 LLM 调用类故障（L3 处理范围）。"""
    msg = str(exc).lower()
    return any(k in msg for k in ("timeout", "rate", "overloaded", "empty", "api", "connection"))
