"""AndroidWorld 式评测验证任务——模拟器端终态判定。

参考 android_world/task_evals/ 设计：
  - TaskEval 基类：goal + initialize + is_successful + tear_down
  - 每任务用 shell / content provider 读设备真实状态
  - agent 不知道这些类的存在——纯评测层

模拟器要求：Android 33+，google_apis 镜像。
SQLite 深度验证见 tests/sqlite_verify.py（仅测试用，需 userdebug 镜像 + adb root）。
"""
from __future__ import annotations

import abc
import re
import time
from dataclasses import dataclass, field
from typing import Any

# ---- TaskEval 基类 ----

class TaskEval(abc.ABC):
    """AndroidWorld 式任务评测基类。

    Usage:
        task = WifiTurnOff()
        task.initialize(pf)           # 设置前提条件
        # ... agent runs ...
        score = task.is_successful(pf)  # 读设备状态，返回 0.0~1.0
        task.tear_down(pf)             # 恢复设备状态
    """

    complexity: float = 1.0   # 1=简单 2=中等 3=复杂，影响步数预算
    template: str = ""        # 目标模板（可用 {param} 占位）

    @property
    def goal(self) -> str:
        return self.template

    @abc.abstractmethod
    def is_successful(self, pf: Any) -> float:
        """读设备状态，返回 0.0 (失败) ~ 1.0 (成功)。"""
        ...

    def initialize(self, pf: Any) -> None:
        """设置任务前提条件（agent 开始前调用）。"""
        pass

    def tear_down(self, pf: Any) -> None:
        """恢复设备状态（agent 完成后调用）。"""
        pass


# ---- 通用 helper ----

def _shell(pf: Any, cmd: str) -> str:
    """执行 shell 命令，返回 strip 后的 stdout。"""
    try:
        return (pf.shell(cmd) or "").strip()
    except Exception:
        return ""

def _current_activity(pf: Any) -> str:
    """获取当前前台 Activity。"""
    out = _shell(pf, "dumpsys activity activities | grep topResumedActivity | head -1")
    if "topResumedActivity=" in out:
        return out.split("topResumedActivity=")[-1].strip()
    return ""

def _settings_get(pf: Any, namespace: str, key: str) -> str:
    """读 settings get <namespace> <key>。"""
    return _shell(pf, f"settings get {namespace} {key}")

def _package_exists(pf: Any, pkg: str) -> bool:
    """检查包是否已安装。"""
    out = _shell(pf, f"pm list packages 2>/dev/null | grep '^{pkg}$' || echo ''")
    return bool(out)


# ---- 系统设置类任务 ----

class SystemSettingToggle(TaskEval):
    """通用系统设置开关类验证——读 settings get 返回值比对。

    参数：namespace (system|global), key, on_val, off_val, target
    """

    def __init__(self, namespace: str, key: str, on_val: str, off_val: str,
                 target: str = "off", template: str = "") -> None:
        self.ns = namespace
        self.key = key
        self.on_val = on_val
        self.off_val = off_val
        self.target = target
        self._template = template

    @property
    def goal(self) -> str:
        return self._template

    def is_successful(self, pf: Any) -> float:
        actual = _settings_get(pf, self.ns, self.key)
        expected = self.off_val if self.target == "off" else self.on_val
        # 支持多值（如 wifi_on: 1 或 2 都算 on）
        expected_vals = expected.split("|")
        return 1.0 if actual in expected_vals else 0.0

    def initialize(self, pf: Any) -> None:
        # 设为目标相反的初始状态（如目标=off，先设为 on）
        init_val = self.on_val if self.target == "off" else self.off_val
        _shell(pf, f"settings put {self.ns} {self.key} {init_val}")

    def tear_down(self, pf: Any) -> None:
        # 恢复为默认值
        default = self.on_val.split("|")[0]  # 默认开
        _shell(pf, f"settings put {self.ns} {self.key} {default}")


def WifiTurnOff() -> SystemSettingToggle:
    return SystemSettingToggle(
        namespace="global", key="wifi_on",
        on_val="1|2", off_val="0", target="off",
        template="Turn Wi-Fi off.",
    )

def WifiTurnOn() -> SystemSettingToggle:
    return SystemSettingToggle(
        namespace="global", key="wifi_on",
        on_val="1|2", off_val="0", target="on",
        template="Turn Wi-Fi on.",
    )

def BluetoothTurnOff() -> SystemSettingToggle:
    return SystemSettingToggle(
        namespace="global", key="bluetooth_on",
        on_val="1", off_val="0", target="off",
        template="Turn Bluetooth off.",
    )

def BluetoothTurnOn() -> SystemSettingToggle:
    return SystemSettingToggle(
        namespace="global", key="bluetooth_on",
        on_val="1", off_val="0", target="on",
        template="Turn Bluetooth on.",
    )

def AirplaneModeOn() -> SystemSettingToggle:
    return SystemSettingToggle(
        namespace="global", key="airplane_mode_on",
        on_val="1", off_val="0", target="on",
        template="Turn airplane mode on.",
    )

def AirplaneModeOff() -> SystemSettingToggle:
    return SystemSettingToggle(
        namespace="global", key="airplane_mode_on",
        on_val="1", off_val="0", target="off",
        template="Turn airplane mode off.",
    )


class BrightnessSet(TaskEval):
    """亮度设置验证——读 system screen_brightness 值。"""

    VAL_MAX = "255"
    VAL_MIN = "1"

    def __init__(self, target: str = "max") -> None:
        self._target = target
        self._expected = self.VAL_MAX if target == "max" else self.VAL_MIN

    @property
    def goal(self) -> str:
        return f"Set screen brightness to {self._target}."

    def is_successful(self, pf: Any) -> float:
        actual = _settings_get(pf, "system", "screen_brightness")
        return 1.0 if actual == self._expected else 0.0

    def initialize(self, pf: Any) -> None:
        # 反方向预设
        opp = self.VAL_MIN if self._target == "max" else self.VAL_MAX
        _shell(pf, f"settings put system screen_brightness {opp}")

    def tear_down(self, pf: Any) -> None:
        _shell(pf, "settings put system screen_brightness 102")  # 中等亮度


# ---- 应用导航类任务 ----

class AppLaunch(TaskEval):
    """验证应用是否成功启动到前台。"""

    def __init__(self, package: str, activity_pattern: str, app_name: str = "") -> None:
        self.package = package
        self.pattern = activity_pattern
        self._app_name = app_name or package
        self._template = f"Open the {self._app_name} app."

    @property
    def goal(self) -> str:
        return self._template

    def is_successful(self, pf: Any) -> float:
        activity = _current_activity(pf)
        return 1.0 if self.package in activity else 0.0

    def initialize(self, pf: Any) -> None:
        # 回到桌面
        pf.home()
        time.sleep(0.5)

    def tear_down(self, pf: Any) -> None:
        pf.home()


class NavigateToPage(TaskEval):
    """验证是否导航到了目标 Activity 页面。"""

    def __init__(self, activity_re: str, goal_template: str) -> None:
        self._re = re.compile(activity_re, re.IGNORECASE)
        self._template = goal_template

    @property
    def goal(self) -> str:
        return self._template

    def is_successful(self, pf: Any) -> float:
        activity = _current_activity(pf)
        return 1.0 if self._re.search(activity) else 0.0

    def initialize(self, pf: Any) -> None:
        pf.home()
        time.sleep(0.5)

    def tear_down(self, pf: Any) -> None:
        pf.home()


# ---- 包管理类任务 ----

class PackageInstalled(TaskEval):
    """验证包是否已安装。"""

    def __init__(self, package: str, app_name: str = "") -> None:
        self.package = package
        self._app_name = app_name or package
        self._template = f"Install {self._app_name} (package: {package})."

    @property
    def goal(self) -> str:
        return self._template

    def is_successful(self, pf: Any) -> float:
        return 1.0 if _package_exists(pf, self.package) else 0.0

    def initialize(self, pf: Any) -> None:
        # 先卸载（确保前置条件：未安装）
        _shell(pf, f"pm uninstall {self.package} 2>/dev/null || true")


class PackageUninstalled(TaskEval):
    """验证包是否已卸载。"""

    def __init__(self, package: str, app_name: str = "") -> None:
        self.package = package
        self._app_name = app_name or package
        self._template = f"Uninstall {self._app_name} (package: {package})."

    @property
    def goal(self) -> str:
        return self._template

    def is_successful(self, pf: Any) -> float:
        return 0.0 if _package_exists(pf, self.package) else 1.0

    def initialize(self, pf: Any) -> None:
        # 先安装（确保前置条件：已安装）
        # 注意：模拟器上需要 APK 文件才能 install，这里依赖已有的包
        pass


# ---- 复合任务 ----

class CompositeTask(TaskEval):
    """组合多个子任务，返回平均分。

    仿 AndroidWorld composite/system.py 的 TurnOnWifiAndOpenApp 模式。
    """

    def __init__(self, sub_tasks: list[TaskEval], goal_template: str = "") -> None:
        self.sub_tasks = sub_tasks
        self._template = goal_template

    @property
    def goal(self) -> str:
        return self._template

    def initialize(self, pf: Any) -> None:
        for t in self.sub_tasks:
            t.initialize(pf)

    def is_successful(self, pf: Any) -> float:
        scores = [t.is_successful(pf) for t in self.sub_tasks]
        return sum(scores) / len(scores) if scores else 0.0

    def tear_down(self, pf: Any) -> None:
        for t in self.sub_tasks:
            t.tear_down(pf)


# ---- 信息和查看类任务 ----

class InformationDisplayed(TaskEval):
    """验证信息页面是否可访问——检查 Activity 在目标页 + 屏幕有内容。"""

    def __init__(self, activity_re: str, goal_template: str) -> None:
        self._re = re.compile(activity_re, re.IGNORECASE)
        self._template = goal_template

    @property
    def goal(self) -> str:
        return self._template

    def is_successful(self, pf: Any) -> float:
        activity = _current_activity(pf)
        if not self._re.search(activity):
            return 0.0
        # 额外检查：屏幕至少要有元素
        raw = pf.observe()
        has_content = "elements" in raw.elements_text.lower() and "no interactive" not in raw.elements_text.lower()
        return 1.0 if has_content else 0.5  # 页面正确但无内容给半分

    def initialize(self, pf: Any) -> None:
        pf.home()
        time.sleep(0.5)

    def tear_down(self, pf: Any) -> None:
        pf.home()


# ---- 异常恢复类任务 ----

class ErrorRecovery(TaskEval):
    """验证异常恢复——执行非法操作后是否回到安全状态。"""

    def __init__(self, trigger: str, safe_activity_re: str, goal_template: str) -> None:
        self.trigger = trigger     # 触发异常的 shell 命令
        self._re = re.compile(safe_activity_re, re.IGNORECASE)
        self._template = goal_template

    @property
    def goal(self) -> str:
        return self._template

    def is_successful(self, pf: Any) -> float:
        activity = _current_activity(pf)
        return 1.0 if self._re.search(activity) else 0.0

    def initialize(self, pf: Any) -> None:
        # 先执行触发操作
        _shell(pf, self.trigger)
        time.sleep(1)

    def tear_down(self, pf: Any) -> None:
        pf.home()


# ---- Content Provider 验证（短信、日历等）----

def _content_query(pf: Any, uri: str) -> str:
    """查询 Android Content Provider。"""
    return _shell(pf, f"content query --uri {uri}")


class SmsSent(TaskEval):
    """验证短信是否已发送——查 content://sms/sent。

    仿 AndroidWorld sms_validators.py:was_sent()。
    """

    def __init__(self, phone_number: str, body: str) -> None:
        self.number = phone_number
        self.body = body
        self._before: list[str] = []   # 前置快照

    @property
    def goal(self) -> str:
        return f"Send SMS to {self.number}: {self.body}"

    def initialize(self, pf: Any) -> None:
        _shell(pf, "content delete --uri content://sms 2>/dev/null || true")

    def is_successful(self, pf: Any) -> float:
        rows = _content_query(pf, "content://sms/sent")
        if not rows:
            return 0.0
        # 按号码 + 正文模糊匹配
        n = self.number.replace("-", "").replace(" ", "")
        for row in rows.split("\n"):
            if n in row.replace("-", "").replace(" ", "") and self.body[:10] in row:
                return 1.0
        return 0.0


class CalendarEventCreated(TaskEval):
    """验证日历事件是否已创建——查 content://com.android.calendar/events。"""

    def __init__(self, title: str) -> None:
        self.title = title

    @property
    def goal(self) -> str:
        return f"Create a calendar event: {self.title}"

    def initialize(self, pf: Any) -> None:
        _shell(pf, "content delete --uri content://com.android.calendar/events 2>/dev/null || true")

    def is_successful(self, pf: Any) -> float:
        rows = _content_query(pf, "content://com.android.calendar/events")
        return 1.0 if self.title in rows else 0.0


# ---- 文件系统验证（Markor、Draw、Audio Recorder）----

class FileCreated(TaskEval):
    """验证文件是否创建——ls + 模糊匹配文件名。"""

    def __init__(self, directory: str, name_pattern: str, goal_template: str) -> None:
        self.dir = directory
        self.pattern = name_pattern
        self._template = goal_template

    @property
    def goal(self) -> str:
        return self._template

    def initialize(self, pf: Any) -> None:
        _shell(pf, f"rm -rf {self.dir}/* 2>/dev/null || true")
        _shell(pf, f"mkdir -p {self.dir}")

    def is_successful(self, pf: Any) -> float:
        out = _shell(pf, f"ls {self.dir} 2>/dev/null || echo ''")
        if not out or "No such file" in out:
            return 0.0
        return 1.0 if self.pattern.lower() in out.lower() else 0.0


class FileDeleted(TaskEval):
    """验证文件是否已删除。"""

    def __init__(self, directory: str, name_pattern: str, goal_template: str) -> None:
        self.dir = directory
        self.pattern = name_pattern
        self._template = goal_template

    @property
    def goal(self) -> str:
        return self._template

    def initialize(self, pf: Any) -> None:
        _shell(pf, f"mkdir -p {self.dir}")
        _shell(pf, f"touch {self.dir}/{self.pattern}")

    def is_successful(self, pf: Any) -> float:
        out = _shell(pf, f"ls {self.dir} 2>/dev/null || echo ''")
        return 0.0 if self.pattern.lower() in out.lower() else 1.0


class FileMoved(TaskEval):
    """验证文件是否已移动——源不存在 + 目标存在。"""

    def __init__(self, src_dir: str, dst_dir: str, name: str, goal_template: str) -> None:
        self.src_dir = src_dir
        self.dst_dir = dst_dir
        self.name = name
        self._template = goal_template

    @property
    def goal(self) -> str:
        return self._template

    def initialize(self, pf: Any) -> None:
        _shell(pf, f"mkdir -p {self.src_dir} {self.dst_dir}")
        _shell(pf, f"rm -f {self.dst_dir}/{self.name}")
        _shell(pf, f"touch {self.src_dir}/{self.name}")

    def is_successful(self, pf: Any) -> float:
        src = _shell(pf, f"ls {self.src_dir}/{self.name} 2>/dev/null || echo 'NOT_FOUND'")
        dst = _shell(pf, f"ls {self.dst_dir}/{self.name} 2>/dev/null || echo 'NOT_FOUND'")
        return 1.0 if ("NOT_FOUND" in src and "NOT_FOUND" not in dst) else 0.0


# ---- Media / App 特定任务 ----

class AudioRecorded(TaskEval):
    """验证录音文件是否已创建。"""

    def __init__(self) -> None:
        pass

    @property
    def goal(self) -> str:
        return "Record an audio clip using Audio Recorder."

    def initialize(self, pf: Any) -> None:
        _shell(pf, "rm -rf /sdcard/Music/Recordings/* /sdcard/Android/data/com.dimowner.audiorecorder/* 2>/dev/null || true")

    def is_successful(self, pf: Any) -> float:
        out = _shell(pf, "find /sdcard -name '*.mp3' -o -name '*.m4a' -o -name '*.wav' 2>/dev/null | head -5 || echo ''")
        return 1.0 if out and "No such file" not in out else 0.0


class CameraPhotoTaken(TaskEval):
    """验证照片是否已拍摄。"""

    @property
    def goal(self) -> str:
        return "Take a photo using Camera."

    def initialize(self, pf: Any) -> None:
        _shell(pf, "rm -rf /sdcard/DCIM/Camera/* 2>/dev/null || true")

    def is_successful(self, pf: Any) -> float:
        out = _shell(pf, "ls /sdcard/DCIM/Camera/*.jpg /sdcard/Pictures/*.jpg 2>/dev/null | head -3 || echo ''")
        return 1.0 if out and ".jpg" in out else 0.0


class BrowserSearch(TaskEval):
    """验证浏览器搜索——检查 Chrome history content provider。"""

    def __init__(self, query: str) -> None:
        self.query = query

    @property
    def goal(self) -> str:
        return f"Search for '{self.query}' in Chrome."

    def is_successful(self, pf: Any) -> float:
        # 检查 Chrome 是否在前台
        activity = _current_activity(pf)
        if "chrome" not in activity.lower():
            return 0.0
        # 屏幕应有搜索相关内容
        raw = pf.observe()
        return 0.5 if self.query.lower() in raw.elements_text.lower() else 0.0


# ---- Suite 运行器 ----

@dataclass
class AWCase:
    """AndroidWorld 式评测用例。"""
    name: str
    task: TaskEval
    max_steps: int = 10
    tags: list[str] = field(default_factory=list)


@dataclass
class AWResult:
    """单 case 评测结果。"""
    case: AWCase
    agent_success: bool         # agent 自评
    verify_score: float         # is_successful 返回值
    agent_summary: str = ""
    agent_steps: int = 0
    agent_cost: float = 0.0

    @property
    def verified(self) -> bool:
        return self.verify_score >= 1.0

    @property
    def false_positive(self) -> bool:
        """agent 声称成功但设备验证失败。"""
        return self.agent_success and not self.verified

    @property
    def false_negative(self) -> bool:
        """agent 声称失败但设备验证成功。"""
        return not self.agent_success and self.verified


# ---- AW case 注册表（模拟器版）----

def build_aw_cases() -> list[AWCase]:
    """返回与 eval_cases.yml 对应的 19 个 AndroidWorld 式验证用例。"""
    return [
        # L1 简单
        AWCase("T01-返回桌面", NavigateToPage(r"QuickstepLauncher|NexusLauncher", "go back to home screen"), 6, ["L1"]),
        AWCase("T02-打开设置", AppLaunch("com.android.settings", "settings", "Settings"), 8, ["L1"]),
        AWCase("T03-查看蓝牙", NavigateToPage(r"[Bb]luetooth", "open Bluetooth settings page"), 10, ["L1"]),
        AWCase("T04-关闭WiFi", WifiTurnOff(), 12, ["L1"]),
        AWCase("T05-开启WiFi", WifiTurnOn(), 12, ["L1"]),
        AWCase("T06-亮度最大", BrightnessSet("max"), 10, ["L1"]),
        AWCase("T07-亮度最小", BrightnessSet("min"), 10, ["L1"]),
        # L2 中等
        AWCase("T08-查看存储", InformationDisplayed(r"[Ss]torage", "view device storage usage"), 12, ["L2"]),
        AWCase("T09-打开时钟", AppLaunch("com.google.android.deskclock", "deskclock", "Clock"), 10, ["L2"]),
        AWCase("T10-打开计算器", AppLaunch("com.google.android.calculator2", "calculator", "Calculator"), 10, ["L2"]),
        AWCase("T11-截屏", NavigateToPage(r".*", "take a screenshot"), 8, ["L2"]),  # 弱验证
        AWCase("T12-系统信息", InformationDisplayed(r"device|[Aa]bout", "view About Phone page"), 15, ["L2"]),
        AWCase("T13-搜索设置", NavigateToPage(r"[Ss]earch|[Ss]ettings", "search for 'battery' in Settings"), 15, ["L2"]),
        AWCase("T14-开启飞行模式", AirplaneModeOn(), 12, ["L2"]),
        AWCase("T15-关闭飞行模式", AirplaneModeOff(), 12, ["L2"]),
        # L3 复杂
        AWCase("T16-安装应用", PackageInstalled("com.xingin.xhs", "Xiaohongshu"), 30, ["L3"]),
        AWCase("T17-卸载应用", PackageUninstalled("com.xingin.xhs", "Xiaohongshu"), 25, ["L3"]),
        AWCase("T18-多页面导航", CompositeTask([
            AppLaunch("com.android.settings", "settings", "Settings"),
            NavigateToPage(r"[Bb]luetooth", "Bluetooth"),
            NavigateToPage(r"[Ss]ettings", "back to Settings"),
            NavigateToPage(r"[Ww]ifi", "Wi-Fi"),
            NavigateToPage(r"[Ss]ettings", "back to Settings"),
            NavigateToPage(r"[Ss]torage", "Storage"),
            NavigateToPage(r"QuickstepLauncher|NexusLauncher", "back to home"),
        ], "navigate: Settings→Bluetooth→back→WiFi→back→Storage→back→Home"), 25, ["L3"]),
        AWCase("T19-异常恢复", ErrorRecovery(
            "monkey -p com.fake.nonexistent 1 2>/dev/null; sleep 1",
            r"QuickstepLauncher|NexusLauncher",
            "launch non-existent app and recover to home screen",
        ), 12, ["L3"]),
        # ---- 新增：SMS / Calendar / Markor / Media ----
        AWCase("T20-发送短信", SmsSent("+1234567890", "Hello from fastaget"), 15, ["L2", "sms"]),
        AWCase("T21-创建日历事件", CalendarEventCreated("Team meeting"), 15, ["L2", "calendar"]),
        AWCase("T22-创建笔记", FileCreated(
            "/sdcard/Documents/Markor", ".md",
            "Create a new note in Markor."), 12, ["L2", "markor"]),
        AWCase("T23-删除笔记", FileDeleted(
            "/sdcard/Documents/Markor", "test_note.md",
            "Delete 'test_note.md' in Markor."), 10, ["L2", "markor"]),
        AWCase("T24-移动文件", FileMoved(
            "/sdcard/Download", "/sdcard/Documents", "test_file.txt",
            "Move 'test_file.txt' from Downloads to Documents."), 12, ["L2", "files"]),
        AWCase("T25-录音", AudioRecorded(), 10, ["L2", "audio"]),
        AWCase("T26-拍照", CameraPhotoTaken(), 8, ["L2", "camera"]),
        AWCase("T27-浏览器搜索", BrowserSearch("fastaget"), 12, ["L2", "browser"]),
        # ---- 复合任务 ----
        AWCase("T28-笔记+短信", CompositeTask([
            FileCreated("/sdcard/Documents/Markor", "meeting_notes.md",
                        "Create 'meeting_notes.md' in Markor."),
            SmsSent("+1234567890", "Notes created"),
        ], "Create a note then send confirmation SMS."), 25, ["L3", "composite"]),
    ]


# ---- Suite Runner ----

def run_aw_suite(
    cases: list[AWCase],
    phonefast: Any,
    agent_factory,
    verbose: bool = True,
) -> dict[str, Any]:
    """批量执行 AndroidWorld 式评测并输出汇总报告。

    Usage:
        pf = Phonefast(serial='emulator-5554')
        llm = AnthropicHTTPDelegate(model='deepseek-v4-pro')
        registry = build_registry(capabilities=pf.FULL_CAPABILITIES)

        def make_agent(max_steps):
                return FastAgent(llm, pf, registry, max_steps=max_steps)

        report = run_aw_suite(build_aw_cases(), pf, make_agent)
    """
    results: list[AWResult] = []
    total_cost = 0.0

    for i, case in enumerate(cases, 1):
        task = case.task
        if verbose:
            print(f"\n[{i}/{len(cases)}] {case.name} ({'/'.join(case.tags)})")
            print(f"  Goal: {task.goal}")

        # Phase 1: setup
        task.initialize(phonefast)

        # Phase 2: agent execute
        agent = agent_factory(max_steps=case.max_steps)
        result = agent.run(task.goal)
        total_cost += result.total_cost_usd

        # Phase 3: verify
        score = task.is_successful(phonefast)
        r = AWResult(
            case=case, agent_success=result.success, verify_score=score,
            agent_summary=result.summary, agent_steps=result.steps,
            agent_cost=result.total_cost_usd,
        )
        results.append(r)

        # Phase 4: cleanup
        task.tear_down(phonefast)

        if verbose:
            agent_tag = "PASS" if r.agent_success else "FAIL"
            verify_tag = "✓" if r.verified else "✗"
            fp = " FALSE+" if r.false_positive else ""
            fn = " FALSE-" if r.false_negative else ""
            print(f"  Agent: {agent_tag} {r.agent_steps}步 ${r.agent_cost:.4f} | Verify: {verify_tag} ({r.verify_score:.0f}){fp}{fn}")
            if r.agent_summary:
                print(f"  Summary: {r.agent_summary[:120]}")

    # Summary
    agent_pass = sum(1 for r in results if r.agent_success)
    verify_pass = sum(1 for r in results if r.verified)
    fp_count = sum(1 for r in results if r.false_positive)
    fn_count = sum(1 for r in results if r.false_negative)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Summary: {agent_pass}/{len(results)} agent声称 | "
              f"{verify_pass}/{len(results)} 设备验证 | "
              f"{fp_count}误报 {fn_count}漏报 | ${total_cost:.4f}")

    return {
        "total": len(results),
        "agent_pass": agent_pass,
        "verify_pass": verify_pass,
        "false_positives": fp_count,
        "false_negatives": fn_count,
        "total_cost": round(total_cost, 4),
        "results": [
            {
                "name": r.case.name,
                "goal": r.case.task.goal,
                "agent_success": r.agent_success,
                "verify_score": r.verify_score,
                "false_positive": r.false_positive,
                "false_negative": r.false_negative,
                "steps": r.agent_steps,
                "cost": round(r.agent_cost, 4),
                "summary": r.agent_summary,
            }
            for r in results
        ],
    }
