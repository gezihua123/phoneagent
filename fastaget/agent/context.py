"""DeviceContext：任务相关的设备级上下文，注入 agent 首条消息。

设计原则（agents.md 原则 4）：
  - 只注入「能改变 agent 决策 + 无法通过 observe 发现 + prompt 没说」的信息
  - 按 goal 关键词过滤，任务相关才注入（不全量堆砌）
  - 注入失败不炸 agent（设备上下文是增强，不是必需）

为何精简：
  - screen_size / android_version：index 枢纽架构下 agent 不点裸坐标，observe 已含 bounds，
    设备规格不改变决策 → 不注入
  - current_package：首步 auto-observe 即见 → 不注入
  - keyboard：prompt 已规定用拼音 → 不注入
  - serial：LLM 永远不需要 → 不注入
  - installed_packages：不跳转就能判断应用是否已装，规避广告"打开"按钮幻觉 → 关键，注入
  - network=none：搜索/下载类任务无网会失败，提前告知避免空转重试 → 条件关键，仅相关任务注入

Usage::

    ctx = DeviceContext.from_phonefast(pf, goal="搜索小红书并下载",
                                       watch_packages=["com.xingin.xiaohongshu"])
    agent = FastAgent.builder(llm, pf, registry).with_device_context(ctx).build()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# 领域知识（包名映射、网络关键词）外置于 meta/package_hints.yml，不硬编码进 agent 代码。
# 宪法第三条：领域知识放 meta/，主线代码零场景知识。
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "meta" / "package_hints.yml"

# 加载失败时的空默认——不炸 agent（设备上下文是增强，不是必需）
# 条目结构 (label, package, keywords)：keywords 仅用于匹配 goal，
# 注入 prompt 的是英文 label（Prompt 英文铁律），中文关键词不达 LLM。
_PACKAGE_HINTS: list[tuple[str, str, tuple[str, ...]]] = []
_NETWORK_KEYWORDS: tuple[str, ...] = ()


def _load_hints_config() -> tuple[list[tuple[str, str, tuple[str, ...]]], tuple[str, ...]]:
    """从 meta/package_hints.yml 加载包名映射和网络关键词。失败返回空。"""
    try:
        import yaml
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        hints: list[tuple[str, str, tuple[str, ...]]] = []
        for entry in data.get("package_hints") or []:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label", "")).strip()
            package = str(entry.get("package", "")).strip()
            keywords = tuple(str(k) for k in (entry.get("keywords") or []))
            if label and package and keywords:
                hints.append((label, package, keywords))
        kws = tuple(str(k) for k in (data.get("network_keywords") or []))
        return hints, kws
    except Exception:
        return [], ()


_PACKAGE_HINTS, _NETWORK_KEYWORDS = _load_hints_config()


@dataclass
class DeviceContext:
    """任务相关的设备级上下文（注入 LLM 首条消息）。"""

    installed_packages: list[str] = field(default_factory=list)
    network: str = ""  # "wifi"/"mobile"/"none"，空=不注入
    package_hints: dict[str, str] = field(default_factory=dict)  # 包名映射 hint

    @classmethod
    def from_phonefast(
        cls,
        pf: Any,
        *,
        goal: str = "",
        watch_packages: list[str] | None = None,
    ) -> "DeviceContext":
        """从 phonefast 采集任务相关的设备上下文。

        goal: 当前任务目标，用于决定是否采集 network（搜索/下载类才采）
        watch_packages: 关注的包名列表，逐一查是否已装
        采集失败返回空上下文（不抛异常）。
        """
        ctx = cls()

        # 包名映射：根据 goal 关键词匹配常用包名
        # 关键词仅用于匹配 goal（可为中文）；注入 LLM 的是英文 label（Prompt 英文铁律）
        # 去空格归一化匹配——"googleplay" 也能命中 "google play" 的 hint
        if goal:
            goal_normalized = goal.lower().replace(" ", "")
            for label, pkg, keywords in _PACKAGE_HINTS:
                if any(kw.lower().replace(" ", "") in goal_normalized for kw in keywords):
                    ctx.package_hints[label] = pkg

        # 关注的已装应用（设备事实，规避屏幕幻觉）
        if watch_packages:
            for pkg in watch_packages:
                try:
                    if pf.is_package_installed(pkg):
                        ctx.installed_packages.append(pkg)
                except Exception:
                    pass

        # network：仅当 goal 涉及搜索/下载/安装时才采集
        if goal and any(kw in goal for kw in _NETWORK_KEYWORDS):
            try:
                status = pf.status()
                if isinstance(status, dict):
                    net = status.get("network")
                    if net:
                        ctx.network = str(net)
            except Exception:
                pass

        return ctx

    def is_empty(self) -> bool:
        return not (self.installed_packages or self.network or self.package_hints)

    def to_prompt_text(self) -> str:
        if self.is_empty():
            return ""
        lines = ["## Device Info"]
        if self.package_hints:
            hints = ", ".join(f"{k}→{v}" for k, v in self.package_hints.items())
            lines.append(f"- Common package names: {hints} (use launch(package=<package>) to start an app)")
        if self.installed_packages:
            lines.append(f"- Installed watched apps: {', '.join(self.installed_packages)}"
                         " (treat as ground truth for whether an app is installed; do not rely solely on on-screen buttons)")
        if self.network:
            if self.network == "none":
                lines.append("- Network: offline (search/download tasks will fail; call complete(fail) directly, do not retry)")
            else:
                lines.append(f"- Network: {self.network} (online)")
        return "\n".join(lines)
