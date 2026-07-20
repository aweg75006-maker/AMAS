from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.builtin.http_agent_connector import HttpAgentConnector
from app.connectors.builtin.internal_subagent_connector import InternalSubAgentConnector

# connector type -> 实现类。
_TYPE_MAP: dict[str, type[BaseConnector]] = {
    "http_agent": HttpAgentConnector,
    "openai_compatible": HttpAgentConnector,  # 别名：默认按 OpenAI 兼容协议
    "internal_subagent": InternalSubAgentConnector,
}


def _build(spec: dict[str, Any]) -> BaseConnector:
    """根据配置字典构造一个 Connector 实例。"""
    ctype = spec.get("type", "http_agent")
    cls = _TYPE_MAP.get(ctype)
    if cls is None:
        raise ValueError(
            f"未知 connector 类型：{ctype!r}（可选：{sorted(_TYPE_MAP)}）"
        )

    name = spec.get("name")
    if not name:
        raise ValueError("connector 配置缺少 name。")

    cfg = dict(spec.get("config") or {})
    # 顶层可选字段透传。
    if "description" in spec:
        cfg.setdefault("description", spec["description"])
    if "capabilities" in spec:
        cfg.setdefault("capabilities", spec["capabilities"])

    if ctype in ("http_agent", "openai_compatible"):
        base_url = cfg.pop("base_url", None)
        if not base_url:
            raise ValueError(f"connector {name!r} 需要 config.base_url。")
        return HttpAgentConnector(
            name=name,
            base_url=base_url,
            model=cfg.pop("model", None),
            kind=spec.get("kind", "openai_compatible"),
            **cfg,
        )

    if ctype == "internal_subagent":
        return InternalSubAgentConnector(
            name=name,
            model_type=cfg.pop("model_type", "smart"),
            **cfg,
        )

    raise ValueError(f"未处理的 connector 类型：{ctype!r}")


def register_connectors_from_config(
    registry: Any,
    configs: list[dict[str, Any]],
) -> int:
    """从配置列表批量注册 Connector，返回成功注册数量。"""
    count = 0
    for spec in configs or []:
        connector = _build(spec)
        registry.register(connector)
        count += 1
    return count
