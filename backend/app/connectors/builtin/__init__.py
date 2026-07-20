"""内置 Connector 与注册入口。"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.builtin.http_agent_connector import HttpAgentConnector
from app.connectors.builtin.internal_subagent_connector import (
    InternalSubAgentConnector,
)
from app.connectors.registration import register_connectors_from_config
from app.core.config import settings


def register_builtin_connectors(registry: Any) -> None:
    """向注册中心装入内置 Connector：

    1. ``internal_subagent``：始终可用，用本系统 LLM 当子 Agent。
    2. 配置驱动：从 ``settings.connectors`` 注册外部第三方 Agent 端点。
    """
    registry.register(
        InternalSubAgentConnector(
            name="internal_subagent",
            description="使用 IRIS 自身 LLM 作为子 Agent 处理子问题（默认可用）。",
        )
    )
    configs = list(getattr(settings, "connectors", []) or [])
    if configs:
        registered = register_connectors_from_config(registry, configs)
        # 便于在日志 / 测试中确认配置驱动注册数量。
        setattr(registry, "config_connectors_loaded", registered)


__all__ = [
    "HttpAgentConnector",
    "InternalSubAgentConnector",
    "register_builtin_connectors",
]
