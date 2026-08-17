"""ActionContext：每步刷新的执行上下文，是抽取链路与操作链路的枢纽。

ctx.observe() 是统一的屏幕观察原语——agent 和 tools 都通过它获取屏幕，
无需各自内联 observe→process→refresh 代码。

内存隔离与持久化：
  _memory_store = {serial: {key: value}, ...}
  memory property 按 phonefast serial 自动取当前设备命名空间。
  多机场景：每台设备独立命名空间，互不污染。
  设置 memory_dir 后自动持久化到 <dir>/<namespace>.json（原子写入）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from fastaget.device.phonefast import Phonefast, PhonefastError
from fastaget.device.uiprocessor import UIProcessor
from fastaget.device.uistate import UIState
from fastaget.tools.credential import CredentialManager

# observe 失败时的屏幕文本标记（英文铁律：发给 LLM 的文本必须英文）
_OBSERVE_FAILED_TEXT = (
    "OBSERVE FAILED: device UI service unreachable (phonefast UI socket down). "
    "This is a device-side error, NOT an empty screen. Retry observe; "
    "the framework restarts the UI service automatically."
)
# observe 尝试次数（首次失败触发 daemon 重启）
_OBSERVE_MAX_ATTEMPTS = 2


@dataclass
class ActionContext:
    """工具执行依赖包——只持有设备侧依赖，零 agent 反向引用。

    工具通过 ctx 访问设备/屏幕/记忆；工具的一切"效果"（终结声明、屏幕观察）
    通过 ActionResult.data 声明，由 agent 主循环统一解释——ctx 不再是
    agent 与工具之间的状态通道。

    memory 属性：_agent_memory 可用时委托给 AgentMemory（PI/mobilerun 模式），
    否则回退到旧 _memory_store dict。工具层无需感知差异。
    """

    phonefast: Phonefast
    ui: UIState | None = None  # 当前屏幕状态
    _processor: UIProcessor = field(default_factory=UIProcessor)
    # 凭证管理器（None=不使用凭证功能）
    credential_manager: CredentialManager | None = None

    # ── memory：AgentMemory 引用（PI/mobilerun 模式）或旧 _memory_store 回退 ──
    _agent_memory: Any | None = None  # AgentMemory 实例（避免硬依赖 import）
    _memory_store: dict[str, dict[str, str]] = field(default_factory=dict)
    _memory_dir: Path | None = None
    _memory_loaded: set[str] = field(default_factory=set)

    # ── AgentMemory 集成（PI/mobilerun 模式）──

    def set_agent_memory(self, mem: Any, namespace: str) -> None:
        """绑定 AgentMemory 实例。之后所有 memory 操作委托给 AgentMemory。"""
        self._agent_memory = mem
        mem._namespace = namespace
        # 如果已有 _memory_dir 但 AgentMemory 未配置，桥接
        if self._memory_dir and not mem._dir:
            mem.set_dir(str(self._memory_dir), namespace)

    # ── 旧持久化配置（_agent_memory 不存在时的回退）──

    def set_memory_dir(self, path: str | Path) -> None:
        """设置记忆持久化目录。_agent_memory 可用时委托，否则旧路径。"""
        self._memory_dir = Path(path)
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        if self._agent_memory is not None:
            ns = self._memory_namespace()
            self._agent_memory.set_dir(str(self._memory_dir), ns)
        else:
            ns = self._memory_namespace()
            self._load_from_disk(ns)

    def save_memory(self, namespace: str | None = None) -> bool:
        """持久化记忆。_agent_memory 可用时委托。"""
        if self._agent_memory is not None:
            return self._agent_memory.save()
        ns = namespace or self._memory_namespace()
        return self._save_to_disk(ns)

    def save_all_memory(self) -> int:
        """持久化全部记忆。_agent_memory 可用时委托。"""
        if self._agent_memory is not None:
            return 1 if self._agent_memory.save() else 0
        if not self._memory_dir:
            return 0
        count = 0
        for ns in self._memory_store:
            if self._save_to_disk(ns):
                count += 1
        return count

    def load_memory(self, namespace: str | None = None) -> int:
        """从磁盘加载记忆。_agent_memory 可用时无操作（已在 set_dir 时加载）。"""
        if self._agent_memory is not None:
            return len(self._agent_memory.facts)
        ns = namespace or self._memory_namespace()
        return self._load_from_disk(ns)

    # ── 内部持久化 ──

    def _file_path(self, namespace: str) -> Path | None:
        if not self._memory_dir:
            return None
        return self._memory_dir / f"{namespace}.json"

    def _load_from_disk(self, namespace: str) -> int:
        """从磁盘加载一个命名空间到内存（不覆盖已有的 key）。返回加载条目数。"""
        fpath = self._file_path(namespace)
        if fpath is None or not fpath.is_file():
            self._memory_loaded.add(namespace)
            return 0
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            self._memory_loaded.add(namespace)
            return 0
        if not isinstance(data, dict):
            self._memory_loaded.add(namespace)
            return 0
        if namespace not in self._memory_store:
            self._memory_store[namespace] = {}
        count = 0
        for k, v in data.items():
            if k not in self._memory_store[namespace]:
                self._memory_store[namespace][k] = str(v)
                count += 1
        self._memory_loaded.add(namespace)
        return count

    def _save_to_disk(self, namespace: str) -> bool:
        """原子写入：先写 .tmp 再 rename，进程安全。"""
        fpath = self._file_path(namespace)
        if fpath is None:
            return False
        data = self._memory_store.get(namespace)
        if data is None:
            return False
        tmp = Path(str(fpath) + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.rename(fpath)
            return True
        except Exception:
            return False

    # ── 记忆访问 ──

    @property
    def memory(self) -> Any:
        """当前设备的跨步记忆。_agent_memory 可用时委托给 AgentMemory（支持
        dict 风格读写 `ctx.memory[key] = value`），否则回退 _memory_store dict。

        AgentMemory 已按 device serial 命名空间隔离，无需额外处理。
        """
        if self._agent_memory is not None:
            return self._agent_memory
        ns = self._memory_namespace()
        if ns not in self._memory_store:
            self._memory_store[ns] = {}
        if ns not in self._memory_loaded:
            self._load_from_disk(ns)
        return self._memory_store[ns]

    @property
    def memory_namespace(self) -> str:
        """当前记忆命名空间（通常是设备 serial）。调试/报告用。"""
        return self._memory_namespace()

    @property
    def all_memory_namespaces(self) -> frozenset[str]:
        """所有已知的命名空间（只读，含从磁盘加载的）。"""
        return frozenset(self._memory_store.keys())

    def _memory_namespace(self) -> str:
        """解析当前设备的记忆命名空间。serial 未知时回退 _default。"""
        try:
            serial = getattr(self.phonefast, "_serial", None)
            if serial:
                return serial
        except Exception:
            pass
        return "_default"

    def observe(self) -> UIState:
        """统一的屏幕观察原语：observe → process → refresh → 返回 UIState。

        agent 和所有 tools 通过此方法获取屏幕，保证一致性。
        格式化文本通过 observe_text() 获取（需先调用 observe）。

        UI 服务失联自愈：失败 → 重启 daemon → 重试一次 → 仍失败则返回
        带错误标记的空状态。LLM 看到明确错误文本而非"空屏幕"，
        避免误判为 app a11y 缺失而进入 OCR 盲点螺旋。
        """
        state = UIState(elements=[])
        screen_text = _OBSERVE_FAILED_TEXT
        for attempt in range(_OBSERVE_MAX_ATTEMPTS):
            try:
                raw = self.phonefast.observe()
                state, screen_text = self._processor.process(raw.elements_text)
                break
            except PhonefastError:
                if attempt < _OBSERVE_MAX_ATTEMPTS - 1:
                    # 首败：重启 daemon 自愈（UI socket 失联，主进程存活）
                    try:
                        self.phonefast.restart_daemon()
                    except PhonefastError:
                        pass  # 重启失败不阻塞，进入最后一次重试
        self.ui = state
        self._last_screen_text = screen_text
        return state

    def observe_text(self) -> str:
        """返回上次 observe 的格式化屏幕文本。"""
        return getattr(self, "_last_screen_text", "") or ""

    def refresh(self, state: UIState) -> None:
        self.ui = state

    def require_ui(self) -> UIState:
        if self.ui is None:
            raise RuntimeError("UIState not refreshed; call observe first")
        return self.ui
