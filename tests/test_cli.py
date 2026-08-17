"""CLI 参数校验测试（不触发真实设备/LLM）。"""
import sys

from fastaget.cli import main


def test_run_without_goal_or_file_errors(capsys, monkeypatch):
    """既无 goal 也无 -f 应报错退出 2，不浪费 token。"""
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main(["run"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "测试目标" in err or "-f" in err or "凭证" in err


def test_run_help_exits_clean():
    try:
        main(["run", "--help"])
        assert False
    except SystemExit as e:
        assert e.code == 0


def test_default_model_is_deepseek_v4_pro(capsys):
    """默认模型 deepseek-v4-pro。"""
    try:
        main(["run", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "deepseek-v4-pro" in out
