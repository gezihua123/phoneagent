"""自愈层重试原语测试。"""
import pytest

from fastaget.heal.retry import is_device_io_error, is_llm_error, is_max_turns_error, with_retry
from fastaget.device.phonefast import PhonefastError


def test_with_retry_succeeds_first_try():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    assert with_retry(fn, retries=3, sleep=lambda _: None) == "ok"
    assert len(calls) == 1


def test_with_retry_retries_then_succeeds():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    sleeps = []
    assert with_retry(fn, retries=3, base_delay=0.5, sleep=sleeps.append) == "ok"
    assert len(calls) == 3
    # 线性退避：0.5*1, 0.5*2
    assert sleeps == [0.5, 1.0]


def test_with_retry_exhausts_and_raises():
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError("perm")

    try:
        with_retry(fn, retries=2, sleep=lambda _: None)
        assert False
    except RuntimeError as e:
        assert "perm" in str(e)
    assert len(calls) == 2


def test_is_device_io_error():
    assert is_device_io_error(PhonefastError("daemon died"))
    assert is_device_io_error(RuntimeError("connection reset"))
    assert not is_device_io_error(ValueError("bad index"))


def test_is_llm_error():
    assert is_llm_error(RuntimeError("request timeout"))
    assert is_llm_error(RuntimeError("rate limit exceeded"))
    assert not is_llm_error(RuntimeError("unknown tool"))


def test_is_max_turns_error():
    assert is_max_turns_error(RuntimeError("Reached maximum number of turns (1)"))
    assert is_max_turns_error(Exception("Claude Code returned an error result: Reached max turns (1)"))
    assert not is_max_turns_error(RuntimeError("request timeout"))
    assert not is_max_turns_error(ValueError("bad index"))


def test_with_retry_should_retry_false_skips_retry():
    """max_turns 等确定性崩溃：should_retry 返回 False 应立即抛出，不重试。"""
    calls = []

    def fn():
        calls.append(1)
        raise RuntimeError("Reached maximum number of turns (1)")

    with pytest.raises(RuntimeError, match="maximum number of turns"):
        with_retry(
            fn, retries=3, sleep=lambda _: None,
            should_retry=lambda e: not is_max_turns_error(e),
        )
    assert len(calls) == 1  # 不重试，只调一次


def test_with_retry_should_retry_true_still_retries():
    """可恢复异常：should_retry 返回 True 应正常重试。"""
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("timeout")
        return "ok"

    assert with_retry(
        fn, retries=3, sleep=lambda _: None,
        should_retry=lambda e: not is_max_turns_error(e),
    ) == "ok"
    assert len(calls) == 2
