from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import ConfigurationError


ToolHandler = Callable[[dict[str, Any], "ToolContext"], Any]


@dataclass(frozen=True)
class ToolContext:
    """Runtime context passed to tool handlers."""

    node_name: str
    state: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    """Registered tool metadata and executable handler."""

    name: str
    handler: ToolHandler
    description: str = ""
    input_schema: str = ""
    output_schema: str = ""
    version: str = "v1"
    tags: tuple[str, ...] = ()


class ToolRegistry:
    """In-process catalog for pluggable Agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not spec.name:
            raise ConfigurationError("工具注册失败：name 不能为空。")
        if spec.name in self._tools:
            raise ConfigurationError(f"工具重复注册：{spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ConfigurationError(f"工具未注册：{name}") from exc

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_specs(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda spec: spec.name)


_default_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _default_registry
    if _default_registry is None:
        registry = ToolRegistry()
        from app.tools.research_tools import register_research_tools

        register_research_tools(registry)
        _default_registry = registry
    return _default_registry


def reset_tool_registry_for_tests(registry: ToolRegistry | None = None) -> None:
    global _default_registry
    _default_registry = registry
