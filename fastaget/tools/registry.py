"""工具层：ToolRegistry + ActionResult + ActionContext。

借鉴 mobilerun：工具统一签名，异常转结构化 ActionResult(success=False)，
不让异常炸断 agent 循环。支持 deps 能力声明——工具标注依赖的设备能力，
registry 根据实际 capabilities 自动 disable 不满足依赖的工具。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from fastaget.device.phonefast import PhonefastError

if TYPE_CHECKING:
    from fastaget.tools.context import ActionContext


@dataclass
class ActionResult:
    """工具执行的结构化结果——工具与系统之间的唯一契约。

    效果即数据（Effect-as-Data）：工具通过 data 声明"发生了什么"，
    由 agent 主循环统一解释，工具自身不接触 agent/observer/hooks。
    两条显式约定：
      - is_complete:     工具声明任务终结（complete 工具）
      - observation_data: 工具声明观察了屏幕（返回 elements+count），
                          任意工具可返回（observe/scroll_to_find/key(enter)…），
                          executor 据此同步屏幕指纹做停滞检测。
    """

    success: bool
    summary: str  # 给 LLM 看的一句话摘要
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, summary: str, **data: Any) -> "ActionResult":
        return cls(success=True, summary=summary, data=data)

    @classmethod
    def fail(cls, summary: str, **data: Any) -> "ActionResult":
        return cls(success=False, summary=summary, data=data)

    @classmethod
    def complete(cls, result: str, success: bool) -> "ActionResult":
        """构造终结声明。executor 读到后终止本轮 run。"""
        return cls(success=success, summary=f"complete: {result}",
                   data={"complete": True, "result": result, "success": success})

    @property
    def is_complete(self) -> bool:
        """工具是否声明了任务终结。"""
        return bool(self.data.get("complete"))

    @property
    def observation_data(self) -> tuple[str, int] | None:
        """工具是否带回了屏幕观察（elements+count）。有则返回 (文本, 元素数)。"""
        elements = self.data.get("elements")
        count = self.data.get("count")
        if elements is not None and count is not None:
            return (str(elements), int(count))
        return None

    def to_llm_text(self) -> str:
        tag = "OK" if self.success else "FAILED"
        return f"[{tag}] {self.summary}"


class ToolRegistry:
    """工具注册表。register 存工具，execute 统一注入 ctx 并捕获异常。

    工具元数据（如 is_action 操作类标记）通过 mark_action() 独立声明，
    不侵入 register 接口，保持注册主链路稳定。

    能力声明（deps）：工具声明依赖的设备能力（如 a11y/coordinate/shell），
    disable_unsupported(capabilities) 自动移除不满足的工具。
    """

    # 已知的设备能力定义（文档用途）
    KNOWN_CAPABILITIES = {"a11y", "coordinate", "shell", "input", "app_mgmt"}

    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}
        # 操作类工具名集合（tap/swipe/type 等改变设备状态的工具）
        # agent 据此判断"最后操作是否失败"，不在 agent 代码硬编码工具名
        self._action_tools: set[str] = set()
        # 感知类工具名集合（observe 等刷新屏幕状态的工具）
        # agent 据此判断"本轮是否已刷新过屏幕"，决定要不要 auto-observe
        self._observation_tools: set[str] = set()
        # 断言类工具名集合（assert 等）
        # agent 据此追踪断言结果、判断是否需要提示 complete 收尾
        self._assert_tools: set[str] = set()
        # 不可重试工具名集合（wait 等——网络自愈重试会导致重复等待，语义上不安全）
        # agent 的 L1 自愈层据此跳过重试，不在 agent 代码硬编码工具名
        self._no_retry_tools: set[str] = set()
        # 已禁用的工具名记录（供调试/报告）
        self._disabled: set[str] = set()

    def register(
        self,
        name: str,
        fn: Callable[..., ActionResult],
        description: str,
        params: dict[str, Any] | None = None,
        deps: set[str] | None = None,
    ) -> None:
        """注册工具（接口稳定，不含元数据参数）。

        deps: 设备能力依赖集合（如 {"a11y", "coordinate"}），None = 通用工具。
        """
        self._tools[name] = ToolEntry(name=name, fn=fn, description=description,
                                      params=params or {}, deps=deps)
        # 预计算签名信息——execute 时直接用，避免每调 inspect.signature
        sig = inspect.signature(fn)
        self._tools[name]._valid_param_names = frozenset(
            p for p in sig.parameters if p != "ctx")
        self._tools[name]._has_ctx_param = "ctx" in sig.parameters

    def disable_unsupported(self, capabilities: set[str]) -> int:
        """移除所有 deps 不被 capabilities 满足的工具。

        Tools with deps=None（通用工具，如 observe/wait/complete）始终保留。
        返回移除的工具数。
        """
        to_remove: list[str] = []
        for name, entry in self._tools.items():
            if entry.deps is None:
                continue  # 通用工具，无需任何特定能力
            if not entry.deps <= capabilities:
                to_remove.append(name)

        for name in to_remove:
            self._disable_one(name)
        return len(to_remove)

    def _disable_one(self, name: str) -> None:
        """移除单个工具及其元数据。"""
        self._tools.pop(name, None)
        self._action_tools.discard(name)
        self._observation_tools.discard(name)
        self._assert_tools.discard(name)
        self._no_retry_tools.discard(name)
        self._disabled.add(name)

    @property
    def disabled(self) -> frozenset[str]:
        """只读：已禁用的工具名集合。"""
        return frozenset(self._disabled)

    def mark_action(self, name: str) -> None:
        """标记工具为操作类（改变设备状态：tap/swipe/type/key/launch/back/home）。

        与 register 解耦：感知/验证类工具（observe/wait/assert/check_package）不标记。
        agent 通过 action_tool_names() 查询，不在代码里硬编码工具名集合。
        """
        if name in self._tools:
            self._action_tools.add(name)

    def mark_observation(self, name: str) -> None:
        """标记工具为感知类（刷新屏幕状态：observe）。

        agent 通过 observation_tool_names() 判断"本轮是否已刷新过屏幕"，
        据此决定是否需要 auto-observe，不在代码里硬编码工具名字符串。
        """
        if name in self._tools:
            self._observation_tools.add(name)

    def mark_assert(self, name: str) -> None:
        """标记工具为断言类（验证预期：assert）。

        agent 通过 expect_tool_names() 判断本轮是否做了断言，据此追踪断言
        结果/提示收尾，不在代码里硬编码工具名字符串。
        """
        if name in self._tools:
            self._assert_tools.add(name)

    def mark_no_retry(self, name: str) -> None:
        """标记工具为不可重试（如 wait——网络自愈重试会导致重复等待）。

        agent 的 L1 设备 I/O 自愈层通过 no_retry_tool_names() 判断是否要
        跳过重试直接单次执行，不在代码里硬编码工具名字符串。
        """
        if name in self._tools:
            self._no_retry_tools.add(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get(self, name: str) -> "ToolEntry | None":
        return self._tools.get(name)

    def action_tool_names(self) -> set[str]:
        """返回所有操作类工具名。agent 据此判断操作失败，不硬编码。"""
        return set(self._action_tools)

    def observation_tool_names(self) -> set[str]:
        """返回所有感知类工具名（如 observe）。agent 据此判断屏幕是否已刷新，不硬编码。"""
        return set(self._observation_tools)

    def expect_tool_names(self) -> set[str]:
        """返回所有断言类工具名（如 assert）。agent 据此追踪断言结果，不硬编码。"""
        return set(self._assert_tools)

    def no_retry_tool_names(self) -> set[str]:
        """返回所有不可重试工具名（如 wait）。agent 自愈层据此跳过重试，不硬编码。"""
        return set(self._no_retry_tools)

    def definitions(self) -> list[dict[str, Any]]:
        """产出 Anthropic Messages API 的 tool definitions（input_schema 格式）。"""
        return [
            {
                "name": e.name,
                "description": e.description,
                "input_schema": _to_json_schema(e.params) or {"type": "object", "properties": {}},
            }
            for e in self._tools.values()
        ]

    def execute(self, name: str, args: dict[str, Any], ctx: "ActionContext") -> ActionResult:
        """执行工具，一切异常转 ActionResult(success=False)。"""
        entry = self._tools.get(name)
        if entry is None:
            return ActionResult.fail(f"Unknown tool: {name}")
        try:
            # schema 校验：必填参数 + 类型检查（对照 entry.params 声明）
            missing = [k for k, v in entry.params.items() if v.get("required") and k not in args]
            if missing:
                return ActionResult.fail(f"{name} missing required params: {', '.join(missing)}")
            # 类型强转：声明 int/number 的参数尝试转 int/float
            coerced = dict(args)
            for pname, pinfo in entry.params.items():
                if pname in coerced and pinfo.get("type") in ("int", "integer", "number"):
                    try:
                        if pinfo["type"] in ("int", "integer"):
                            coerced[pname] = int(coerced[pname])
                        else:
                            coerced[pname] = float(coerced[pname])
                    except (ValueError, TypeError):
                        pass  # 转不了就保持原值，工具自己处理
                # boolean 强转：LLM 可能输出 passed="false" 作为字符串 → 转 bool
                if pname in coerced and pinfo.get("type") == "boolean":
                    v = coerced[pname]
                    if isinstance(v, str):
                        coerced[pname] = v.lower() not in ("false", "0", "", "no")
                    elif not isinstance(v, bool):
                        coerced[pname] = bool(v)
            # 过滤多余参数：只保留函数签名里声明的形参（预计算，免 inspect.signature）
            filtered = {k: v for k, v in coerced.items() if k in entry._valid_param_names}
            if entry._has_ctx_param:
                return entry.fn(ctx=ctx, **filtered)
            return entry.fn(**filtered)
        except TypeError as e:
            return ActionResult.fail(f"Invalid arguments for {name}: {e}")
        except PhonefastError:
            raise  # 设备级错误穿透到 _execute_one 的 L1 自愈层
        except Exception as e:  # noqa: BLE001 — 工具层兜底，转结构化结果
            return ActionResult.fail(f"{name} failed: {e}")


@dataclass
class ToolEntry:
    name: str
    fn: Callable[..., ActionResult]
    description: str
    params: dict[str, Any]
    deps: set[str] | None = None  # None = 通用工具（无需特定设备能力）
    # 预计算字段（register 时填入，execute 时直接读，免去每调 inspect.signature）
    _valid_param_names: frozenset[str] = frozenset()
    _has_ctx_param: bool = False


def _to_json_schema(params: dict[str, Any]) -> dict[str, Any]:
    """把简写的参数描述转 JSON Schema。空则返回空 dict。

    简写约定：{name: {"type": "int", "desc": "...", "required": True}, ...}
    """
    if not params:
        return {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, pinfo in params.items():
        properties[pname] = {"type": pinfo.get("type", "string"), "description": pinfo.get("desc", "")}
        if pinfo.get("required"):
            required.append(pname)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema
