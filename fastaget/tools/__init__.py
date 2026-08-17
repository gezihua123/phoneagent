"""工具注册——actions.py 是唯一定义源（描述/参数/标记全部在类上声明）。"""
from __future__ import annotations

from fastaget.tools import actions as A
from fastaget.tools.registry import ToolRegistry


def build_registry(
    capabilities: set[str] | None = None,
    credential_manager=None,
) -> ToolRegistry:
    """构建工具注册表。从 Action 类自动注册（无外部 YAML 依赖）。"""
    # 解析可用凭证 ID（供 type_secret 工具描述填充）
    available_secrets = ""
    if credential_manager is not None:
        try:
            ids = credential_manager.list_ids()
            available_secrets = ", ".join(ids) if ids else "(no available secrets)"
        except Exception:
            available_secrets = "(credential resolution failed)"

    reg = ToolRegistry()
    for action in A._all_actions():
        desc = action.description
        # 动态填充占位符
        if "{available_secrets}" in desc:
            desc = desc.replace("{available_secrets}", available_secrets)
        reg.register(action.name, action, desc, params=action.params)
        if action.is_action:
            reg.mark_action(action.name)
        if getattr(action, "is_observation", False):
            reg.mark_observation(action.name)
        if getattr(action, "is_assert", False):
            reg.mark_assert(action.name)
        if not getattr(action, "is_retryable", True):
            reg.mark_no_retry(action.name)
    if capabilities is not None:
        n = reg.disable_unsupported(capabilities)
        if n > 0:
            import logging
            logging.getLogger("fastaget").debug(
                f"禁用 {n} 个不满足能力 {capabilities} 的工具: {sorted(reg.disabled)}"
            )
    return reg
