"""phonefast daemon Unix Socket 客户端。

直连 phonefast daemon 的 Unix Socket（换行分隔 JSON-RPC），消除每次 subprocess.run
的 fork+exec 开销。单步设备交互从 ~80ms（subprocess）降到 ~10ms（socket）。

socket 路径约定（新旧二进制兼容，_find_sockets 精确构造两候选）：
  /tmp/phonefast-<uid>-<serial>.sock   旧版 per-serial daemon
  /tmp/phonefast-<uid>.sock            新版统一 daemon
daemon 为一请求一连接模式（每次响应后关闭连接），故每次调用新建 socket——
Unix socket connect() 仅 ~0.1ms，远低于 subprocess 启动开销。

若 daemon 未运行，先尝试 `phonefast daemon` 后台启动一次，再连。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass


class PhonefastError(RuntimeError):
    """phonefast 调用失败（执行器层异常，交由自愈层捕获）。"""


def _pid_alive(pid: int) -> bool:
    """PID 是否存在（macOS/Linux 通用：signal 0 探测，不发实际信号）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 进程在，只是无权限发信号
    return True


@dataclass
class ObserveResult:
    """一次 observe 的结果：UI 元素文本 + 截图 base64（可选）。"""

    elements_text: str
    image_b64: str | None = None  # base64 编码的 PNG，视觉模式用


class Phonefast:
    """phonefast daemon 的 Unix Socket 客户端。

    所有方法经 daemon 通道（<10ms 触控）。失败抛 PhonefastError。
    """

    # Phonefast 通过 daemon + adb 支持全部设备能力
    FULL_CAPABILITIES: set[str] = {"a11y", "coordinate", "shell", "input", "app_mgmt"}

    # daemon 启动等待参数（测试可调小）
    _DAEMON_START_TIMEOUT: float = 8.0
    _DAEMON_POLL_INTERVAL: float = 0.3

    # daemon stop 超时（秒）——restart_daemon 用
    _DAEMON_STOP_TIMEOUT: float = 30.0

    # shell 失败时 stderr 截断上限（错误上下文长度，控制送达调用方/日志的信息量）
    _SHELL_ERR_TRUNCATE: int = 200

    # adb devices 探测超时（秒）
    _ADB_DEVICES_TIMEOUT: float = 5.0

    # socket 单次读取分块大小（字节）
    _RECV_CHUNK_SIZE: int = 65536

    # observe 自愈最小间隔（秒）——UI 子进程/视频流失联时重启 daemon 的 rate-limit。
    # 重启耗时数秒，若每步都失败每次都重启，会比直接抛错更慢；
    # 30s 窗口内只允许一次重启（后续失败直接抛，交上层处理）。
    _HEAL_MIN_INTERVAL: float = 30.0

    def __init__(self, serial: str | None = None, timeout: float = 15.0) -> None:
        self._serial = serial
        self._timeout = timeout
        self._socket_path: str | None = None
        self._warmed = False
        # 自愈时间戳：-inf 保证首次失败立即允许重启（monotonic 时钟）
        self._last_heal_ts: float = -float("inf")

    @property
    def serial(self) -> str:
        """目标设备 serial——未显式指定时按 L1 规则解析（多真机拒绝猜测）。

        公共访问口：脚本层（batch_eval 等）复用同一解析逻辑，
        不重复实现 adb devices 探测。
        """
        return self._resolve_serial()

    # ---- 设备检测 ----

    def _resolve_serial(self) -> str:
        """解析目标设备 serial。

        若已指定 serial 则直接返回；未指定时自动从 adb devices 检测。
        多台真机同时在线时拒绝猜测，要求显式传 --serial 指定目标设备。
        """
        if self._serial:
            return self._serial

        # 查询 adb 已连接设备
        try:
            result = subprocess.run(
                ["adb", "devices"], capture_output=True, text=True,
                timeout=self._ADB_DEVICES_TIMEOUT,
            )
        except FileNotFoundError:
            raise PhonefastError("adb is not installed or not in PATH")

        lines = result.stdout.strip().split("\n")[1:]  # 跳过 "List of devices attached"
        devices = [l.split()[0] for l in lines if l.strip() and "\tdevice" in l]

        if not devices:
            raise PhonefastError("no connected devices; connect a phone or start an emulator")

        if len(devices) == 1:
            # 唯一设备，自动选用
            self._serial = devices[0]
            return self._serial

        # 多设备：优先选唯一真机，否则拒绝猜测
        real = [d for d in devices if not d.startswith("emulator-")]
        if len(real) == 1:
            self._serial = real[0]
            return self._serial

        device_list = "\n".join(f"  - {d}" for d in devices)
        raise PhonefastError(
            f"Detected {len(devices)} devices online; specify the target with --serial:\n{device_list}"
        )

    # ---- socket 发现与连接 ----

    def _find_sockets(self) -> list[str]:
        """候选 socket 路径——精确构造，不用 glob。

        `/tmp/phonefast-{uid}*.sock` 的 glob 会前缀碰撞其他 uid 的 socket
        （501 匹配 5012-xxx.sock）。候选仅两个：serial 专属优先，generic 兜底。
        """
        uid = os.getuid()
        candidates: list[str] = []
        if self._serial:
            candidates.append(f"/tmp/phonefast-{uid}-{self._serial}.sock")
        candidates.append(f"/tmp/phonefast-{uid}.sock")
        return [p for p in candidates if os.path.exists(p)]

    def _ensure_daemon(self) -> str:
        """确保 daemon 运行并返回 socket 路径。首次调用时懒启动 daemon。

        多设备防线（CLAUDE.md 硬性规范）：
          L2   启动始终 `phonefast daemon --serial <s>`，不靠 daemon 默认选
          附加 _ping 校验 serial——绑定其他设备的旧 daemon 拒绝复用
        """
        serial = self._resolve_serial()  # L1：多设备时拒绝猜测

        for path in self._find_sockets():
            if self._ping(path):
                return path

        # L2：启动 daemon（后台模式）——始终绑定明确 serial
        binary = os.environ.get("PHONEFAST_BINARY", "phonefast")
        cmd = [binary, "daemon", "--serial", serial]
        # launcher 输出落临时文件：起不来时（如 "daemon already running"）把真实
        # 原因带回错误信息——DEVNULL 吞掉后只剩误导性的 "failed to start in time"
        start_err_f = tempfile.TemporaryFile()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=start_err_f,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as e:
            start_err_f.close()
            raise PhonefastError(f"phonefast binary not found: {binary}") from e

        # 等待匹配 socket 出现（单调时钟，防 NTP 跳变误判）。
        # launcher 可能因 "already running" 立刻非零退出——但仍等满超时：
        # 并发启动竞态下 socket 可能稍后才由胜出的那个进程绑上（此时退出是假阴性）。
        deadline = time.monotonic() + self._DAEMON_START_TIMEOUT
        mismatch = ""
        while time.monotonic() < deadline:
            for path in self._find_sockets():
                if self._ping(path):
                    start_err_f.close()
                    return path
                mismatch = (
                    f"Existing daemon is bound to a device that does not match target serial={serial}; "
                    f"refusing to reuse. Run 'phonefast daemon --stop' and retry "
                    f"(will restart with --serial {serial})"
                )
            time.sleep(self._DAEMON_POLL_INTERVAL)
        start_err_f.seek(0)
        start_err = start_err_f.read(self._SHELL_ERR_TRUNCATE).decode(errors="replace").strip()
        start_err_f.close()
        if mismatch:
            raise PhonefastError(mismatch)
        if start_err:
            raise PhonefastError(f"phonefast daemon failed to start: {start_err}")
        raise PhonefastError("phonefast daemon failed to start in time; check the device connection")

    def restart_daemon(self) -> str:
        """强制重启 daemon 并返回 socket 路径——UI 服务失联时的自愈入口。

        背景：daemon 长跑（数小时持续 observe）后其 UI 子进程可能失联
        （observe 报 "connect ui socket: connection refused"），主进程却仍存活，
        无自愈。此时 stop 旧 daemon → 清掉 socket 残留 → 按 serial 重启。
        调用方（ctx.observe / Phonefast.observe）在 observe 失败时调用；
        eval 启动时也调一次防长跑退化。

        死锁防线（2026-08 事故复盘）：① stop 必须带 --serial——旧版 per-serial
        daemon 的 --stop 不带 serial 读通用 pidfile，永远 no-op；② **确认进程
        已死才 unlink socket**——活 daemon 的 socket 被删后，新 daemon 被
        "already running" 拒绝：进程活着、socket 没了，谁也连不上。
        stop 没杀死时宁可抛错（socket 原样保留，旧 daemon 仍可连），也不制造幽灵态。

        必须重置 _socket_path/_warmed：_call 缓存旧 socket，重启后旧连接
        已失效（或新 daemon 尚未绑定），不重置会让重试连到死 socket——
        自愈永远失败。重置后下次 _call 走 _ensure_daemon 重新发现+等待就绪。
        """
        binary = os.environ.get("PHONEFAST_BINARY", "phonefast")
        serial = self._resolve_serial()
        stop_err = ""
        try:
            r = subprocess.run(
                [binary, "daemon", "--stop", "--serial", serial],
                capture_output=True, text=True, timeout=self._DAEMON_STOP_TIMEOUT,
            )
            if r.returncode != 0:
                stop_err = (r.stderr or r.stdout or "").strip()
        except Exception as e:
            stop_err = str(e)
        if self._daemon_alive():
            detail = f": {stop_err}" if stop_err else ""
            raise PhonefastError(
                f"daemon --stop did not kill the daemon{detail}; socket left untouched. "
                f"Kill it manually (pkill -f daemon_worker) and retry"
            )
        for path in self._find_sockets():
            try:
                os.unlink(path)
            except OSError:
                pass  # socket 已消失/无权限，继续
        self._socket_path = None
        self._warmed = False
        return self._ensure_daemon()

    def _daemon_alive(self) -> bool:
        """daemon 进程是否仍存活——stop 后校验（活进程持有的 socket 不能 unlink）。

        新旧 pidfile 都要查：新版统一 daemon 写 /tmp/phonefast-<uid>.pid，
        旧版 per-serial daemon 写 /tmp/phonefast-<uid>-<serial>.pid。
        pidfile 缺失/损坏时兜底：socket 还能 ping 通说明仍有进程持有。
        """
        uid = os.getuid()
        pidfiles = [f"/tmp/phonefast-{uid}.pid"]
        if self._serial:
            pidfiles.append(f"/tmp/phonefast-{uid}-{self._serial}.pid")
        for path in pidfiles:
            try:
                with open(path) as f:
                    pid = int(f.read().strip() or "0")
            except (OSError, ValueError):
                continue
            if pid > 0 and _pid_alive(pid):
                return True
        for path in self._find_sockets():
            if self._ping(path):
                return True
        return False

    def _ping(self, path: str) -> bool:
        """探测 socket 可连且 daemon 绑定的设备与目标 serial 不冲突。

        附加防线：daemon 报告的设备列表非空且不含目标 serial → 拒绝复用
        （旧 daemon 可能绑定真机，复用会静默操作错设备）。
        devices 为空（刚启动未连接）→ 接受，RPC 按 params["device"] 路由。
        """
        try:
            result = self._call_raw(path, "status", {})
        except Exception:
            return False
        devices = result.get("devices") or []
        if devices and self._serial and self._serial not in devices:
            return False
        return True

    def _call_raw(self, socket_path: str, method: str, params: dict) -> dict:
        """发送一次 JSON-RPC 请求，返回 result 或抛 PhonefastError。"""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._timeout)
        try:
            sock.connect(socket_path)
            req = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
            sock.sendall((json.dumps(req) + "\n").encode())
            data = b""
            while True:
                chunk = sock.recv(self._RECV_CHUNK_SIZE)
                if not chunk:
                    break
                data += chunk
                if b"\n" in chunk:
                    break
        except (socket.timeout, ConnectionRefusedError, FileNotFoundError) as e:
            raise PhonefastError(f"socket {method} failed: {e}")
        finally:
            sock.close()

        if not data:
            raise PhonefastError(f"phonefast {method}: empty response")
        try:
            obj = json.loads(data.decode(errors="replace").split("\n", 1)[0])
        except json.JSONDecodeError as e:
            raise PhonefastError(f"phonefast {method}: bad json: {e}")

        if "error" in obj:
            err = obj["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise PhonefastError(f"phonefast {method}: {msg}")
        return obj.get("result", {})

    def _call(self, method: str, params: dict | None = None) -> dict:
        """公共调用入口：确保 daemon → 调用。

        daemon 通过 RPC params 中的 "device" 字段路由到对应设备 Actor
        （daemon.go handleConn → parseStringParam(req.Params, "device")）。
        "device" 为空时 daemon 走 auto-detect（首台 ADB 设备）。
        """
        if self._socket_path is None or not self._warmed:
            self._socket_path = self._ensure_daemon()
            self._warmed = True
        params = dict(params or {})
        if self._serial:
            params.setdefault("device", self._serial)
        return self._call_raw(self._socket_path, method, params)

    # ---- 公共 API ----

    def warmup(self) -> None:
        """显式预热 daemon。"""
        if self._warmed:
            return
        self._socket_path = self._ensure_daemon()
        self._warmed = True

    def status(self) -> dict:
        """返回 daemon 状态。"""
        return self._call("status")

    # 默认元素上限：密集屏幕（长列表/多卡片表单）80 会截掉视口尾部的关键行
    # （Expense Logs 7 行列表实测需 125 元素；截断导致列表尾部目标行对 LLM 不可见，
    #  违反宪法第七条"屏幕必须完整送达"）。类属性配置化，可被调用方覆盖。
    _DEFAULT_MAX_ELEMENTS: int = 200

    def observe(
        self,
        concise: bool = True,
        max_elements: int = _DEFAULT_MAX_ELEMENTS,
        *,
        format: str = "flatref",
    ) -> ObserveResult:
        """观察屏幕，返回 UI 元素文本 + 截图 base64。

        concise=True 让 phonefast 在 legacy 模式下过滤布局容器。
        format: 输出格式，支持 flatref/jsonl/simplexml/yml，默认 flatref。

        自愈：daemon 长跑后 UI 子进程/视频流可能失联（observe 报
        "connect ui socket: connection refused" / "no device connected" / EOF），
        主进程却仍存活。此时按 _HEAL_MIN_INTERVAL 限频重启 daemon 并重试一次；
        窗口内二次失败直接抛 PhonefastError（上层 ScreenObserver/ctx 已各自兜底，
        避免每步都重启比直接失败更慢）。
        """
        try:
            return self._observe_once(concise, max_elements, format)
        except PhonefastError:
            now = time.monotonic()
            if now - self._last_heal_ts < self._HEAL_MIN_INTERVAL:
                raise
            self._last_heal_ts = now
            try:
                self.restart_daemon()
            except PhonefastError:
                pass  # 重启失败不阻塞——直接进入最后一次重试
            return self._observe_once(concise, max_elements, format)

    def _observe_once(
        self,
        concise: bool,
        max_elements: int,
        format: str,
    ) -> ObserveResult:
        r = self._call("observe", {
            "concise": concise,
            "max_elements": max_elements,
            "format": format,
        })
        text = r.get("text", "")
        image = r.get("image_data")
        return ObserveResult(elements_text=text, image_b64=image)

    def tap(self, x: int, y: int) -> str:
        r = self._call("tap", {"x": int(x), "y": int(y)})
        return r.get("message", "")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
        r = self._call("swipe", {
            "start_x": int(x1), "start_y": int(y1),
            "end_x": int(x2), "end_y": int(y2),
            "duration_ms": int(duration_ms),
        })
        return r.get("message", "")

    def type_text(self, text: str) -> str:
        r = self._call("type_text", {"text": text})
        return r.get("message", "")

    def back(self) -> str:
        r = self._call("back", {})
        return r.get("message", "")

    def home(self) -> str:
        r = self._call("home", {})
        return r.get("message", "")

    def key(self, name_or_keycode: str) -> str:
        """按下硬件/系统键。name 小写（enter/back/home/search/space/power）或 keycode 数字字符串。"""
        r = self._call("press_key", {"key": str(name_or_keycode).lower()})
        return r.get("message", "")

    def launch(self, package: str) -> str:
        r = self._call("launch_app", {"package": package})
        return r.get("message", "")

    def screenshot(self) -> str:
        """截图，返回 base64 编码的 PNG。"""
        r = self._call("screenshot", {})
        return r.get("image_data", "")

    def ocr(self) -> dict:
        """OCR: read text from the current screen via image recognition.

        Returns {count, image_height, image_width, items: [{text, box, center, confidence}]}.
        Use as fallback when observe returns too few elements (broken accessibility tree
        on real devices / custom ROMs).
        """
        return self._call("ocr", {})

    # ---- 设备级事实查询（ground truth，不依赖屏幕文本）----
    # 从原理上规避 LLM 幻觉：agent 的感知不只看屏幕，还能直接查设备事实

    def shell(self, command: str, timeout: float = 10.0) -> str:
        """执行 adb shell 命令，返回 stdout。

        这是设备级事实通道的底层入口。直接调 adb shell（不经过 daemon），
        始终指定 -s <serial>，杜绝多设备时连错。
        """
        try:
            # 确保 serial 已解析（多设备时拒绝猜测，防止 adb 连错设备）
            if not self._serial:
                self._resolve_serial()
            serial = self._serial
            cmd = ["adb", "-s", serial, "shell", command]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            # 合并 stderr → stdout
            output = (proc.stdout + "\n" + proc.stderr).strip()
            # rc=1 是 find/grep 等命令的正常语义（无匹配结果），不报错
            # rc>1 且无任何输出 → 命令执行失败
            if proc.returncode > 1 and not output:
                raise PhonefastError(
                    f"adb shell failed (rc={proc.returncode}): "
                    f"{proc.stderr.strip()[:self._SHELL_ERR_TRUNCATE]}"
                )
            return output
        except subprocess.TimeoutExpired:
            raise PhonefastError(f"adb shell timeout: {command}")
        except FileNotFoundError:
            raise PhonefastError("adb not found in PATH")

    def is_package_installed(self, package: str) -> bool:
        """查包管理器：指定包是否已安装（ground truth，非屏幕文本）。

        用 `pm list packages` 查询，彻底规避 LLM 把广告"打开"按钮
        误判为"已安装"的幻觉。
        """
        try:
            out = self.shell(f"pm list packages {package}")
            return f"package:{package}" in out
        except PhonefastError:
            return False

    def current_activity(self) -> str:
        """查前台 Activity（ground truth）。

        返回格式如 com.android.vending/.xxx.DetailActivity。
        用于验证当前确实在目标应用页面，而非广告页面。
        """
        try:
            out = self.shell("dumpsys activity activities | grep -E 'topResumedActivity|ResumedActivity'")
            for line in out.splitlines():
                if "ActivityRecord" in line:
                    # 从 ActivityRecord{xxx u0 pkg/.cls tNN} 提取 pkg/.cls
                    # 匹配 u0 后面的 component
                    import re
                    m = re.search(r"u0\s+(\S+/\S+?)[\s}]", line)
                    if m:
                        return m.group(1).rstrip("}")
                    # fallback: 找任意 pkg/.cls 模式
                    m = re.search(r"(\w+\.\w+[\w.]*/\.\S+?)[\s}]", line)
                    if m:
                        return m.group(1).rstrip("}")
            return ""
        except PhonefastError:
            return ""

    def current_package(self) -> str:
        """查前台包名（ground truth）。"""
        activity = self.current_activity()
        if "/" in activity:
            return activity.split("/")[0]
        return activity
