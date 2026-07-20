"""第三方 Agent Connector 框架。

Connector 代表一个可被研究流程委派的「第三方智能体 / 服务端点」。
框架提供统一接口、注册中心与配置驱动注册，让 IRIS 能像调用工具一样把子问题
委派给外部 Agent（agent-to-agent 编排）或本系统内部的子 Agent。

设计参考已有的 ``app.tools.registry.ToolRegistry`` 模式，但 Connector 面向
「更高层的智能体能力」而非「原子工具」：一次 invoke 通常是一个完整的子任务。
"""

from app.connectors.base import (
    BaseConnector,
    ConnectorContext,
    ConnectorResult,
)
from app.connectors.registry import (
    ConnectorRegistry,
    get_connector_registry,
    reset_connector_registry_for_tests,
)

__all__ = [
    "BaseConnector",
    "ConnectorContext",
    "ConnectorResult",
    "ConnectorRegistry",
    "get_connector_registry",
    "reset_connector_registry_for_tests",
]
