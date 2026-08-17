"""adb_pb2 最小等价物——AW adb_utils/file_utils 用到的消息类型与枚举。

fastaget 评测层不用 android_env 的 GRPC 通道，AdbRequest 由
shim 的 AsyncEnv.execute_adb_call 直接翻译为 phonefast 调用。
此模块只提供 AW 代码构造/读取所需的结构与类路径
（如 AdbRequest.SettingsRequest.Namespace.GLOBAL）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Status 枚举 ──
class Status:
    # OK 必须为真值——AW 代码用 `if not res.status` 判定失败
    OK = 1
    ERROR = 0


# ── 子消息 ──
@dataclass
class GenericRequest:
    args: list = field(default_factory=list)


@dataclass
class GetCurrentActivity:
    pass


@dataclass
class InputText:
    text: str = ""


class PressButton:
    # AW 的 Button 枚举（HOME/BACK/ENTER）
    HOME = "HOME"
    BACK = "BACK"
    ENTER = "ENTER"
    MENU = "MENU"

    def __init__(self, button: str = ""):
        self.button = button


@dataclass
class Tap:
    x: int = 0
    y: int = 0


@dataclass
class StartActivity:
    full_activity: str = ""
    extra_args: list = field(default_factory=list)


@dataclass
class SendBroadcast:
    action: str = ""
    extras: dict = field(default_factory=dict)


class PackageManagerRequest:
    class List:
        class Packages:
            pass

        packages: Optional["PackageManagerRequest.List.Packages"] = None
        name: str = ""

    def __init__(self, command: str = "", package_name: str = "", **kw):
        self.command = command
        self.package_name = package_name
        for k, v in kw.items():
            setattr(self, k, v)


class SettingsRequest:
    class Namespace:
        GLOBAL = "global"
        SECURE = "secure"
        SYSTEM = "system"

    class Put:
        def __init__(self, key: str = "", value: str = ""):
            self.key = key
            self.value = value

    class Get:
        def __init__(self, key: str = ""):
            self.key = key

    def __init__(self, name_space: str = "", namespace: str = "", put: Optional["SettingsRequest.Put"] = None,
                 get: Optional["SettingsRequest.Get"] = None):
        self.name_space = name_space or namespace
        self.put = put
        self.get = get

    @property
    def namespace(self) -> str:
        return self.name_space


@dataclass
class Pull:
    path: str = ""


@dataclass
class Push:
    path: str = ""
    content: bytes = b""


# ── 顶层请求/响应 ──
class AdbRequest:
    GenericRequest = GenericRequest
    GetCurrentActivity = GetCurrentActivity
    InputText = InputText
    PressButton = PressButton
    Tap = Tap
    StartActivity = StartActivity
    SendBroadcast = SendBroadcast
    PackageManagerRequest = PackageManagerRequest
    SettingsRequest = SettingsRequest
    Pull = Pull
    Push = Push

    def __init__(self, generic: Optional[GenericRequest] = None,
                 get_current_activity: Optional[GetCurrentActivity] = None,
                 input_text: Optional[InputText] = None,
                 press_button: Optional[PressButton] = None,
                 tap: Optional[Tap] = None,
                 start_activity: Optional[StartActivity] = None,
                 send_broadcast: Optional[SendBroadcast] = None,
                 package_manager_request: Optional[PackageManagerRequest] = None,
                 settings: Optional[SettingsRequest] = None,
                 pull: Optional[Pull] = None,
                 push: Optional[Push] = None,
                 timeout_sec: Optional[float] = None):
        self.generic = generic
        self.get_current_activity = get_current_activity
        self.input_text = input_text
        self.press_button = press_button
        self.tap = tap
        self.start_activity = start_activity
        self.send_broadcast = send_broadcast
        self.package_manager_request = package_manager_request
        self.settings = settings
        self.pull = pull
        self.push = push
        self.timeout_sec = timeout_sec


@dataclass
class GenericResponse:
    output: bytes = b""


@dataclass
class PullResponse:
    content: bytes = b""


@dataclass
class SettingsGetResponse:
    value: str = ""


@dataclass
class GetCurrentActivityResponse:
    full_activity: str = ""


class AdbResponse:
    Status = Status
    OK = Status.OK  # 部分 AW 代码用 AdbResponse.OK

    def __init__(self, status: int = Status.OK, generic: Optional[GenericResponse] = None,
                 pull: Optional[PullResponse] = None,
                 settings_get: Optional[SettingsGetResponse] = None,
                 get_current_activity: Optional[GetCurrentActivityResponse] = None,
                 error_message: str = ""):
        self.status = status
        self.generic = generic or GenericResponse()
        self.pull = pull or PullResponse()
        self.settings_get = settings_get or SettingsGetResponse()
        self.get_current_activity = get_current_activity or GetCurrentActivityResponse()
        self.error_message = error_message

    def ok(self) -> bool:
        return self.status == self.Status.OK
