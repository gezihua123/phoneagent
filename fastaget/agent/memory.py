"""AgentMemory：跨 run 持久化 agent 记忆（PI + mobilerun 架构对齐）。

三层 memory：
  1. facts（事实字典）        — mobilerun 的 agent_memory，跨 run 持久化
  2. actions（执行记录列表）    — mobilerun 的 action_history + action_outcomes
  3. visited（已访问追踪）      — mobilerun 的 visited_packages + visited_activities

注入模式（mobilerun 对齐）：
  _drain_pending 每轮调用 memory.inject_text() → 追加到最后一条 user message
  等价于 mobilerun fast_agent.py:317-318 的 TextBlock 追加。

持久化：
  memory.set_dir(path) → 自动 load 已有数据 → save() 原子写入 JSON
  命名空间按 device serial 隔离（多机场景互不污染）。

Usage::

    memory = AgentMemory()
    memory.set_dir("build/memory")
    memory.remember("pkg_google_play", "com.android.vending")  # 记事实
    memory.record(1, "tap_element", {"index": 69}, True, "tapped")  # 记执行

    # 每轮注入到 messages
    text = memory.inject_text()
    if text:
        _append_to_last_user(state.messages, text)

    # 跨 run 自动持久化
    memory.save()
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar


# ═══════════════════════════════════════════════════════════
# MemoryAction：单条执行记录
# ═══════════════════════════════════════════════════════════

@dataclass
class MemoryAction:
    """单次工具执行记录（mobilerun: action_history entry + action_outcome）."""

    step: int
    tool: str
    args: dict
    success: bool
    summary: str
    recorded_at: str = ""

    def __post_init__(self) -> None:
        if not self.recorded_at:
            self.recorded_at = datetime.now(timezone.utc).isoformat()

    @property
    def failed(self) -> bool:
        return not self.success


# ═══════════════════════════════════════════════════════════
# ErrorRecord：错误记忆条目（供 ErrorReflection 反省用）
# ═══════════════════════════════════════════════════════════

@dataclass
class ErrorRecord:
    """单次工具失败的错误记录——供反省机制归纳模式 + 查历史恢复方法。

    recovery / recovered 在后续成功步骤时自动回填（"失败后成功"= 恢复）。
    """

    step: int
    tool: str
    error_type: str        # "stale_index" / "element_not_found" / "device_error" / ...
    context: str           # "tap_element(index=5) on Settings screen, 42 elements"
    recovery: str = ""     # 恢复动作（"observe" / "scroll_to_find"），空=未恢复
    recovered: bool = False  # 恢复是否成功

    def failed(self) -> bool:
        return not self.recovered


# ═══════════════════════════════════════════════════════════
# AgentMemory
# ═══════════════════════════════════════════════════════════

@dataclass
class AgentMemory:
    """跨 run 持久化 agent 记忆。

    PI 对齐：AgentContext 级共享——同 FastAgent 实例多次 run() 共享同一份记忆。
    mobilerun 对齐：三层结构（facts + actions + visited）。
    """

    # 持久化/加载的行动记录上限（防止无界增长）
    _MAX_PERSIST_ACTIONS: ClassVar[int] = 50
    _MAX_LOAD_ACTIONS: ClassVar[int] = 20

    # ── 三层数据 ──
    facts: dict[str, str] = field(default_factory=dict)
    actions: list[MemoryAction] = field(default_factory=list)
    visited_packages: set[str] = field(default_factory=set)
    visited_activities: set[str] = field(default_factory=set)
    # ── 第四层：错误记忆（供 ErrorReflection 反省用）──
    errors: list[ErrorRecord] = field(default_factory=list)

    # ── 内部状态 ──
    _dir: Path | None = field(default=None, init=False, repr=False)
    _namespace: str = field(default="default", init=False, repr=False)
    _loaded: bool = field(default=False, init=False, repr=False)
    _dirty: bool = field(default=False, init=False, repr=False)

    # ═══════════════════════════════════════════════════════
    # 事实管理（mobilerun 的 agent_memory append-only 文本）
    # ═══════════════════════════════════════════════════════

    def remember(self, key: str, value: str) -> None:
        """记录一条事实。标记 dirty，由 _build_result 统一持久化。"""
        self.facts[key] = value
        self._dirty = True

    # ═══════════════════════════════════════════════════════
    # 执行追踪（mobilerun 的 action_history + action_outcomes）
    # ═══════════════════════════════════════════════════════

    def record(
        self, step: int, tool: str, args: dict, success: bool, summary: str,
    ) -> MemoryAction:
        """记录一次工具执行。标记 dirty，由 _build_result 统一持久化（避免每步同步磁盘写）。

        失败时自动追加 ErrorRecord；成功时检查是否恢复了上一条错误并回填。
        """
        ma = MemoryAction(step=step, tool=tool, args=args,
                          success=success, summary=summary)
        self.actions.append(ma)
        self._dirty = True

        # 错误记忆追踪：失败→记录；成功→回填上一条错误的 recovery
        if not success:
            self._record_error(step, tool, args, summary)
        elif self.errors and not self.errors[-1].recovered:
            # "失败后成功" = 这一步恢复了上一步的错误
            self.errors[-1].recovery = f"{tool}({_short_args(args)})"
            self.errors[-1].recovered = True
            self._dirty = True

        return ma

    def _record_error(self, step: int, tool: str, args: dict, summary: str) -> None:
        """从失败 summary 提取错误类型，追加 ErrorRecord。"""
        error_type = _classify_error(summary)
        ctx = f"{tool}({_short_args(args)}) → {summary[:80]}"
        self.errors.append(ErrorRecord(
            step=step, tool=tool, error_type=error_type, context=ctx))
        self._dirty = True

    def recent_actions(self, window: int = 5) -> list[MemoryAction]:
        """最近 N 条执行记录。"""
        return self.actions[-window:]

    def recent_errors(self, window: int = 3) -> list[ErrorRecord]:
        """最近 N 条错误记录（供 ErrorReflection 归纳模式）。"""
        return self.errors[-window:]

    def last_successful_recovery(self, error_type: str = "") -> ErrorRecord | None:
        """查找最近的同类型已恢复错误——供反省时引用"上次恢复方法"。"""
        for er in reversed(self.errors):
            if er.recovered and (not error_type or er.error_type == error_type):
                return er
        return None

    def recent_failures(self, window: int = 3) -> int:
        """最近 window 条记录中连续失败的次数（mobilerun: 连续失败检测）。

        Returns count of consecutive failures at the tail, bounded by window.
        """
        count = 0
        for ma in reversed(self.actions):
            if ma.failed:
                count += 1
                if count >= window:
                    break
            else:
                break
        return count

    # ═══════════════════════════════════════════════════════
    # 访问追踪（mobilerun 的 visited_packages + visited_activities）
    # ═══════════════════════════════════════════════════════

    def mark_visited(self, package: str, activity: str = "") -> None:
        """标记包名/Activity 已访问。"""
        if package:
            self.visited_packages.add(package)
        if activity:
            self.visited_activities.add(activity)


    # ═══════════════════════════════════════════════════════
    # 每轮注入（mobilerun: <memory> block → last_user_idx）
    # ═══════════════════════════════════════════════════════

    def inject_text(self) -> str:
        """构建注入 LLM 上下文的 memory 文本块。

        mobilerun 模式：每轮调用，追加到最后一条 user message。
        返回空串 = 无记忆，不需要注入。
        """
        parts: list[str] = []

        # Layer 1: 已知事实（最重要——LLM 不应重复探索）
        if self.facts:
            lines = ["## Known facts (no need to re-explore)"]
            for k, v in self.facts.items():
                lines.append(f"  {k} = {v}")
            parts.append("\n".join(lines))

        # Layer 2: 最近执行记录（LLM 能看到自己做过什么）
        recent = self.recent_actions(5)
        if recent:
            lines = ["## Recent actions"]
            for ma in recent:
                status = "✓" if ma.success else "✗"
                short_args = _short_args(ma.args)
                lines.append(f"  [{ma.step}] {status} {ma.tool}({short_args})")
            parts.append("\n".join(lines))

        # Layer 3: 已访问应用（LLM 知道哪些 app 已经打开过）
        if self.visited_packages:
            pkgs = sorted(self.visited_packages)[:10]
            parts.append(f"## Visited apps: {', '.join(pkgs)}")

        # Layer 4: 连续失败告警（PI mobilerun: consecutive_failure_detection）
        fails = self.recent_failures(2)
        if fails >= 2:
            parts.append(
                "⚠️ The last 2 tool executions failed consecutively. Check: is the index "
                "stale (run observe first)? Is the target element off-screen (use "
                "scroll_to_find)? Change strategy — do not repeat the failed action.")

        return "\n\n".join(parts) if parts else ""


    # ═══════════════════════════════════════════════════════
    # 持久化（JSON 文件，按 device serial 命名空间隔离）
    # ═══════════════════════════════════════════════════════

    def set_dir(self, path: str | Path, namespace: str = "default") -> None:
        """设置持久化目录 + 命名空间。自动 load 已有数据（不覆盖已有 key）。"""
        self._dir = Path(path)
        self._namespace = namespace
        self._dir.mkdir(parents=True, exist_ok=True)
        self._load()

    def save(self) -> bool:
        """持久化全量记忆到磁盘。返回是否成功。无 dirty 变更时跳过磁盘写。"""
        if not self._dir:
            return False
        if not self._dirty and self._loaded:
            return True  # 无变更，跳过
        fpath = self._file_path()
        data = {
            "facts": dict(self.facts),
            "actions": [_action_to_dict(ma) for ma in self.actions[-self._MAX_PERSIST_ACTIONS:]],
            "errors": [_error_to_dict(er) for er in self.errors[-self._MAX_PERSIST_ACTIONS:]],
            "visited_packages": sorted(self.visited_packages),
            "visited_activities": sorted(self.visited_activities),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = Path(str(fpath) + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.rename(fpath)
            self._dirty = False
            return True
        except Exception:
            return False

    def _load(self) -> None:
        """从磁盘加载已有数据（不覆盖内存中已有的数据）。"""
        if self._loaded:
            return
        self._loaded = True
        fpath = self._file_path()
        if not fpath.is_file():
            return
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        # facts: only load keys not already in memory
        disk_facts = data.get("facts", {})
        if isinstance(disk_facts, dict):
            for k, v in disk_facts.items():
                if k not in self.facts:
                    self.facts[k] = str(v)
        # actions: only load if we have none (disk actions are stale after continuation)
        disk_actions = data.get("actions", [])
        if isinstance(disk_actions, list) and not self.actions:
            for entry in disk_actions[-self._MAX_LOAD_ACTIONS:]:
                try:
                    self.actions.append(MemoryAction(
                        step=int(entry.get("step", 0)),
                        tool=str(entry.get("tool", "")),
                        args=entry.get("args", {}),
                        success=bool(entry.get("success", True)),
                        summary=str(entry.get("summary", "")),
                    ))
                except Exception:
                    pass
        # visited: merge sets
        if isinstance(data.get("visited_packages"), list):
            self.visited_packages.update(data["visited_packages"])
        if isinstance(data.get("visited_activities"), list):
            self.visited_activities.update(data["visited_activities"])

    def _file_path(self) -> Path:
        return self._dir / f"{self._namespace}.json" if self._dir else Path("/dev/null")

    def __getitem__(self, key: str) -> str:
        """dict 兼容：允许 `ctx.memory[key] = value` 语法。"""
        return self.facts[key]

    def __setitem__(self, key: str, value: str) -> None:
        """dict 兼容：允许 `ctx.memory[key] = value` 语法。"""
        self.remember(key, value)

    def __contains__(self, key: str) -> bool:
        return key in self.facts



# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════

def _action_to_dict(ma: MemoryAction) -> dict:
    return {
        "step": ma.step, "tool": ma.tool, "args": ma.args,
        "success": ma.success, "summary": ma.summary,
    }


def _error_to_dict(er: ErrorRecord) -> dict:
    return {
        "step": er.step, "tool": er.tool, "error_type": er.error_type,
        "context": er.context, "recovery": er.recovery, "recovered": er.recovered,
    }


# ── 错误类型分类（从 error_types.yml 加载，不硬编码）──

_ERROR_TYPES_CONFIG: list[dict] | None = None


def _load_error_types() -> list[dict]:
    """从 route_config.yml 加载错误类型配置。失败返回空。"""
    global _ERROR_TYPES_CONFIG
    if _ERROR_TYPES_CONFIG is not None:
        return _ERROR_TYPES_CONFIG
    try:
        import yaml
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "meta" / "prompts" / "route_config.yml"
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _ERROR_TYPES_CONFIG = data.get("error_types", [])
    except Exception:
        _ERROR_TYPES_CONFIG = []
    return _ERROR_TYPES_CONFIG


def _classify_error(summary: str) -> str:
    """从失败 summary 文本匹配错误类型（查 error_types.yml 关键词）。"""
    summary_lower = (summary or "").lower()
    for spec in _load_error_types():
        keywords = spec.get("match_keywords", [])
        if any(kw.lower() in summary_lower for kw in keywords):
            return spec.get("type", "unknown")
    return "unknown"


def _short_args(args: dict, max_len: int = 40) -> str:
    """参数截断展示。"""
    if not args:
        return "{}"
    items = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 20:
            s = s[:17] + "..."
        items.append(f"{k}={s}")
    full = ", ".join(items)
    return full[:max_len] + ("..." if len(full) > max_len else "")


# ═══════════════════════════════════════════════════════════
# 便捷函数（供 _drain_pending 使用）
# ═══════════════════════════════════════════════════════════

def append_to_last_user(messages: list[dict], text: str) -> list[dict]:
    """mobilerun 对齐：追加 text block 到最后一条 role=user 的消息。

    快路径：调用方保证最后一条就是 user（_drain_pending / compaction 恢复点）→ O(1)。
    回退：反向扫描 + 兜底新建（防御性，极少数路径触发）。
    兼容 string content（Anthropic 合法格式）——自动转 list。
    原地修改，返回 messages 引用。
    """
    if messages and messages[-1].get("role") == "user":
        _append_text_block(messages[-1], text)
        return messages
    for i in range(len(messages) - 2, -1, -1):
        if messages[i].get("role") == "user":
            _append_text_block(messages[i], text)
            return messages
    messages.append({"role": "user", "content": [{"type": "text", "text": text}]})
    return messages


def _append_text_block(msg: dict, text: str) -> None:
    """安全追加 text block——兼容 content 为 str 或 list。"""
    content = msg.get("content")
    if isinstance(content, str):
        msg["content"] = [{"type": "text", "text": content}, {"type": "text", "text": text}]
    else:
        content = msg.setdefault("content", [])
        content.append({"type": "text", "text": text})
