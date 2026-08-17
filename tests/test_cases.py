"""用例 DSL 加载器测试。"""
from pathlib import Path

from fastaget.cases import Case, load_cases


def write(tmp: Path, content: str) -> Path:
    p = tmp / "case.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_single_case_dict(tmp_path: Path):
    p = write(tmp_path, """
name: 打开设置
goal: 启动设置应用并确认进入设置页
max_steps: 8
asserts:
  - description: 设置标题可见
    expected: true
""")
    cases = load_cases(p)
    assert len(cases) == 1
    c = cases[0]
    assert c.name == "打开设置"
    assert c.goal.startswith("启动设置")
    assert c.max_steps == 8
    assert len(c.asserts) == 1
    assert c.asserts[0].description == "设置标题可见"
    assert c.asserts[0].expected is True


def test_load_cases_list(tmp_path: Path):
    p = write(tmp_path, """
- name: 用例1
  goal: 做A
- name: 用例2
  goal: 做B
  model: deepseek-v4-pro
""")
    cases = load_cases(p)
    assert len(cases) == 2
    assert cases[0].name == "用例1"
    assert cases[1].model == "deepseek-v4-pro"


def test_load_cases_key(tmp_path: Path):
    p = write(tmp_path, """
cases:
  - name: x
    goal: y
""")
    cases = load_cases(p)
    assert len(cases) == 1
    assert cases[0].name == "x"


def test_empty_file(tmp_path: Path):
    p = write(tmp_path, "")
    assert load_cases(p) == []


def test_assert_default_expected_true(tmp_path: Path):
    p = write(tmp_path, """
name: a
goal: b
asserts:
  - description: 某断言
""")
    cases = load_cases(p)
    assert cases[0].asserts[0].expected is True


def test_reset_default_true(tmp_path: Path):
    p = write(tmp_path, "name: a\ngoal: b\n")
    assert load_cases(p)[0].reset is True


def test_reset_can_be_disabled(tmp_path: Path):
    p = write(tmp_path, "name: a\ngoal: b\nreset: false\n")
    assert load_cases(p)[0].reset is False
