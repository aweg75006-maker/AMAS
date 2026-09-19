"""工具注册中心（Tool Registry）。

职责：
- 以"注册表"模式统一管理 Agent 可调用的工具：工具先登记（名称 + 处理器 + 元数据），
  运行时按名称查找并执行；
- 把"工具清单"与"工具执行"解耦：图节点只声明自己需要哪些工具名，
  真正的实现由注册中心按名分发，新增/替换工具无需改动节点代码。

典型用法：
    registry = get_tool_registry()      # 拿到全局注册表（已内置 RAG / 搜索工具）
    spec = registry.get("rag.retrieve") # 按名取工具定义
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.core.exceptions import ConfigurationError


# 工具处理器签名：接收调用参数 dict + 运行时上下文，返回任意结果
ToolHandler = Callable[[dict[str, Any], "ToolContext"], Any]


@dataclass(frozen=True)
class ToolContext:
    """工具执行时的运行时上下文。

    node_name: 当前调用该工具的图节点名（用于定位/日志）；
    state:     图节点当前的完整状态快照（只读），工具可据此做决策
               （例如证据评估工具需要看预算状态）。
    """

    node_name: str
    state: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    """已注册工具的定义（元数据 + 可执行处理器）。

    name:          工具唯一名称（形如 "rag.retrieve"），注册后按此查找；
    handler:       实际执行函数；
    description:   人类可读描述（可注入提示词，让模型知道何时调用）；
    input_schema:  入参说明（形如 "query:string, knowledge_base_id:string"）。
                   注意：这是**给人看 / 给 Harness manifest 对照用的说明字符串**，
                   不是机器校验依据（机器校验请用下面的 params），两者不要混淆；
    output_schema: 出参说明；
    version:       工具版本（写入运行追踪元数据）；
    tags:          标签集合，用于按类别检索/过滤工具；
    params:        ★ S1 新增。参数模型（Pydantic BaseModel 子类）。
                   一份模型同时驱动两件事：
                     ① 服务端校验：app/tools/validation.py 的 validate_params()
                     ② LLM function schema：convert_to_openai_function() 生成工具签名
                   两者同源，所以永远不会漂移。
                   为 None 表示"这个工具还没迁移到模型校验"，此时校验环节原样放行
                   （保证新老工具可以共存，不必一次性改完所有工具才能启动）；
    server_filled: ★ S1 新增（S2 生效）。服务端注入的参数名列表，例如
                   ("knowledge_base_id",)。这些参数**不能写进 params 模型**，
                   否则会出现在模型可见的 function schema 里 ——
                   模型就有机会编造一个不属于本次会话的知识库 id。
                   运行时由 app/tools/runtime.py 从图状态注入。

    关于 frozen=True：本类要求可哈希（会被放进集合/字典），
    所以新增字段的类型也必须是可哈希的 —— type[BaseModel] 是类对象、tuple[str, ...] 是元组，
    两者都可哈希，不会破坏 dataclass 自动生成的 __hash__。
    """

    name: str
    handler: ToolHandler
    description: str = ""
    input_schema: str = ""
    output_schema: str = ""
    version: str = "v1"
    tags: tuple[str, ...] = ()
    # ↓ 以下两个字段必须带默认值、且排在末尾 ——
    #   现有构造点（tests/test_tool_registry.py、tests/test_researcher_tool_registry.py）
    #   只传 name/handler，中间插字段会让它们全部报 "unexpected keyword"/"missing positional"。
    params: type[BaseModel] | None = None
    server_filled: tuple[str, ...] = ()


class ToolRegistry:
    """进程内工具目录：负责工具的注册、按名查找与清单导出。"""

    def __init__(self) -> None:
        # 内部存储：工具名 → ToolSpec 的映射（注册表核心数据结构）
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """注册一个工具；重名或空名会直接报配置错误（宁可启动失败，不默默覆盖）。"""
        if not spec.name:
            raise ConfigurationError("工具注册失败：name 不能为空。")
        if spec.name in self._tools:
            raise ConfigurationError(f"工具重复注册：{spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        """按名称取工具；未注册时抛出配置错误（把运行时问题提前暴露）。"""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ConfigurationError(f"工具未注册：{name}") from exc

    def has(self, name: str) -> bool:
        """判断某工具是否已注册。"""
        return name in self._tools

    def list_specs(self) -> list[ToolSpec]:
        """按名称排序返回全部工具定义（供清单展示 / 测试断言）。"""
        return sorted(self._tools.values(), key=lambda spec: spec.name)


# 全局默认注册表（进程内单例，惰性初始化）
_default_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """获取全局工具注册表（首次调用时自动注册内置的 RAG / 搜索工具）。"""
    global _default_registry
    if _default_registry is None:
        registry = ToolRegistry()
        from app.tools.research_tools import register_research_tools

        register_research_tools(registry)
        _default_registry = registry
    return _default_registry


def reset_tool_registry_for_tests(registry: ToolRegistry | None = None) -> None:
    """测试专用：重置全局注册表（可注入替身注册表，保证测试隔离）。"""
    global _default_registry
    _default_registry = registry
