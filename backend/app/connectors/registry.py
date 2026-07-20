from __future__ import annotations

from typing import Any, Optional

from app.connectors.base import BaseConnector
from app.core.exceptions import ConfigurationError


class ConnectorRegistry:
    """内存中的第三方 Agent Connector 目录。

    与 ``app.tools.registry.ToolRegistry`` 同构，但注册的是 ``BaseConnector`` 实例
    （而非纯函数 handler），因为 Connector 通常持有配置 / 客户端。
    """

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        if not getattr(connector, "name", ""):
            raise ConfigurationError("Connector 注册失败：name 不能为空。")
        if connector.name in self._connectors:
            raise ConfigurationError(f"Connector 重复注册：{connector.name}")
        self._connectors[connector.name] = connector

    def get(self, name: str) -> BaseConnector:
        try:
            return self._connectors[name]
        except KeyError as exc:
            raise ConfigurationError(
                f"Connector 未注册：{name}（已注册：{self.names()}）"
            ) from exc

    def has(self, name: str) -> bool:
        return name in self._connectors

    def names(self) -> list[str]:
        return sorted(self._connectors)

    def list_connectors(self) -> list[BaseConnector]:
        return [self._connectors[n] for n in sorted(self._connectors)]

    def specs(self) -> list[dict[str, Any]]:
        return [c.to_spec() for c in self.list_connectors()]


_default_registry: Optional[ConnectorRegistry] = None


def get_connector_registry() -> ConnectorRegistry:
    """返回进程级单例，并在首次访问时注册内置 + 配置驱动的 Connector。"""
    global _default_registry
    if _default_registry is None:
        registry = ConnectorRegistry()
        from app.connectors.builtin import register_builtin_connectors

        register_builtin_connectors(registry)
        _default_registry = registry
    return _default_registry


def reset_connector_registry_for_tests(
    registry: Optional[ConnectorRegistry] = None,
) -> None:
    """测试用：替换 / 清空单例。"""
    global _default_registry
    _default_registry = registry
