"""Prompt 加载——从 meta/prompts/ 外置文件加载系统提示词/反馈模板/领域模板。

PI 式 pull 模型 + task-type 路由：
  - load_startup_knowledge(goal)      → 启动注入：apps.txt #k 块（~3-6 行）
  - load_steering_knowledge(goal,ctx)  → 转向注入：_universal.txt + task-type 路由文件 #pull-on 块

路由规则：
  goal 关键词 → task type → 决定加载 kb/ 目录下哪些文件
  _universal.txt（§1）始终注入；其余按 task type 按需加载
  路由配置外置到 meta/prompts/route_config.yml（不硬编码场景知识）
"""
from __future__ import annotations

import re
from pathlib import Path


def _prompts_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / "meta" / "prompts"
    return d if d.is_dir() else d


def _kb_dir() -> Path:
    return _prompts_dir()  # flat structure — kb files are directly in prompts/


# ── 解析工具 ──

_SECTION_RE = re.compile(r"^##\s+§(\d+)\s+(.+)$")
_BLOCK_HEADER_RE = re.compile(r"^###\s+(.+?)\s*\|\s*#(k|pull-on):\s*(.+)$")


def _parse_kb_blocks(filepath: Path) -> list[dict]:
    """解析单个 KB 文件为结构化块列表。

    返回 [{section, title, type: 'k'|'pull-on', trigger, lines}, ...]
    section header（## §N）只记录 section 编号，不产生 block——避免空 block。
    子节头（### title | #k:xxx / #pull-on:xxx）才产生 block。
    """
    blocks: list[dict] = []
    current: dict | None = None
    section: str = ""

    for line in filepath.read_text(encoding="utf-8").splitlines():
        # 节头：只记录 section 编号，不创建 block
        sm = _SECTION_RE.match(line)
        if sm:
            if current and current.get("lines"):
                blocks.append(current)
            section = sm.group(1)
            current = None
            continue

        # 子节头：创建 block
        sm = _BLOCK_HEADER_RE.match(line)
        if sm:
            if current and current.get("lines"):
                blocks.append(current)
            current = {
                "section": section,
                "title": sm.group(1).strip(),
                "type": sm.group(2),
                "trigger": sm.group(3).strip(),
                "lines": [line],
            }
            continue

        # 内容行：追加到当前 block（无 block 时丢弃——section header 后的游离行）
        if current:
            current["lines"].append(line)

    if current and current.get("lines"):
        blocks.append(current)
    return blocks


# ── 路由配置（从 route_config.yml 加载，不硬编码）──

_ROUTE_CONFIG_PATH = _prompts_dir() / "route_config.yml"
_ROUTE_CONFIG: dict | None = None


def _load_route_config() -> dict:
    """加载路由配置 yml，失败时用空默认（不炸 agent）。"""
    global _ROUTE_CONFIG
    if _ROUTE_CONFIG is not None:
        return _ROUTE_CONFIG
    try:
        import yaml
        with open(_ROUTE_CONFIG_PATH, encoding="utf-8") as f:
            _ROUTE_CONFIG = yaml.safe_load(f) or {}
    except Exception:
        _ROUTE_CONFIG = {}
    return _ROUTE_CONFIG


def _get_task_types() -> dict[str, dict]:
    """返回 task_type → {keywords, steering_files, wanted_triggers} 的有序字典。

    顺序保持 yml 声明顺序（具体词先于通用词）。
    """
    return _load_route_config().get("task_types", {})


def _classify_goal(goal: str) -> str:
    """从 goal 文本判定 task type（查 yml 关键词，首次匹配即返回）。

    Returns one of: yml 中声明的 task type | "default"
    """
    goal_lower = goal.lower()
    for task_type, spec in _get_task_types().items():
        keywords = spec.get("keywords", [])
        if any(kw.lower() in goal_lower for kw in keywords):
            return task_type
    return "default"


def _resolve_routes(task_type: str) -> list[str]:
    """转向注入加载的 kb 文件列表——所有 task type 共用 ui.txt。"""
    return _load_route_config().get("steering_files", ["ui"])


def _get_universal_triggers() -> set[str]:
    return set(_load_route_config().get("universal_triggers", []))


def _get_late_triggers() -> set[str]:
    return set(_load_route_config().get("late_triggers", []))


def _get_task_wanted(task_type: str) -> set[str]:
    types = _get_task_types()
    spec = types.get(task_type) or types.get("default", {})
    return set(spec.get("wanted_triggers", []))


def _get_startup_blocks() -> list[str]:
    return _load_route_config().get("startup_blocks", ["apps", "tasks"])


# ── 公开接口 ──

def load_prompt(name: str) -> str:
    """从 meta/prompts/<name>.txt 加载，文件不存在返回空。"""
    fpath = _prompts_dir() / f"{name}.txt"
    return fpath.read_text(encoding="utf-8").strip() if fpath.is_file() else ""


def load_feedback(name: str) -> str:
    """加载反馈模板（从 feedback.txt 按 section 名查）。"""
    from fastaget.meta.feedback import load_feedback as _lf
    return _lf(name)


def load_startup_knowledge(goal: str) -> str:
    """启动注入——KB #k 块匹配 goal 关键词（apps + tasks）。

    加载 route_config.yml 的 startup_blocks（apps.txt / categories_rag.txt / recovery_knowledge.txt），
    回退：均无匹配 → plans/*.txt（兼容旧模板）。
    """
    kb = _kb_dir()
    goal_lower = goal.lower()
    picked: list[list[str]] = []

    for fname in _get_startup_blocks():
        fpath = kb / f"{fname}.txt"
        if not fpath.is_file():
            continue
        for b in _parse_kb_blocks(fpath):
            if b["type"] == "k" and b["trigger"]:
                keywords = [kw.strip().lower() for kw in b["trigger"].split(",")]
                if any(kw in goal_lower for kw in keywords):
                    picked.append(b["lines"])

    if not picked:
        return ""

    # 去重（手维护 apps.txt 与 tasks.txt 可能有重复行）
    seen: set[str] = set()
    deduped: list[str] = []
    for line in sum(picked, []):
        s = line.strip()
        if s and s not in seen:
            seen.add(s)
            deduped.append(line)

    return "\n".join(deduped).strip()


def load_steering_knowledge(goal: str, context: dict) -> str:
    """转向注入——按 goal task type 路由加载 kb 文件 + 按轮次匹配 #pull-on 块。

    wanted = universal_triggers（始终） + task-specific wanted_triggers（按需）
    两阶段轮次：≤6 轮用全量，>6 轮追加 late_triggers。
    路由配置从 route_config.yml 加载。
    """
    kb = _kb_dir()
    if not kb.is_dir():
        return ""

    turn = context.get("turn", 0)

    # 1. 确定 task type
    task_type = _classify_goal(goal)

    # 2. 构建 wanted 集合：universal + task-specific
    wanted = _get_universal_triggers()
    wanted.update(_get_task_wanted(task_type))

    # 3. 后期轮次追加恢复触发词
    if turn > 6:
        wanted.update(_get_late_triggers())

    # 4. 加载转向注入文件（所有 task type 共用 ui.txt）
    all_blocks: list[dict] = []
    for fname in _resolve_routes(task_type):
        fpath = kb / f"{fname}.txt"
        if fpath.is_file():
            all_blocks.extend(_parse_kb_blocks(fpath))

    # 5. 匹配 #pull-on 块
    picked: list[list[str]] = []
    for b in all_blocks:
        if not b["trigger"] or b["type"] != "pull-on":
            continue
        triggers = set(t.strip() for t in b["trigger"].split(","))
        if wanted.intersection(triggers):
            picked.append(b["lines"])

    # 6. 去重
    seen: set[str] = set()
    deduped: list[str] = []
    for line in sum(picked, []):
        s = line.strip()
        if s and s not in seen:
            seen.add(s)
            deduped.append(line)

    return "\n".join(deduped).strip() if deduped else ""


# ── 兼容旧接口 ──

def load_domain_template(goal: str) -> str:
    """按 goal 关键词匹配领域模板（兼容旧调用，内部走 pull 模型启动注入）。"""
    return load_startup_knowledge(goal)


# 模块级常量
SYSTEM_PROMPT = load_prompt("baseline")
OPTIMIZED_SYSTEM_PROMPT = load_prompt("optimized")
