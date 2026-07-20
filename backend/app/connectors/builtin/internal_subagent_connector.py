from __future__ import annotations

import asyncio
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.connectors.base import BaseConnector, ConnectorContext, ConnectorResult

DEFAULT_SYSTEM_PROMPT = (
    "你是一个研究助理子 Agent。请基于给定问题，产出简洁、准确、"
    "可直接用于深度调研报告的回答。只输出内容本身，不要寒暄或重复问题。"
)


class InternalSubAgentConnector(BaseConnector):
    """使用 IRIS 自身的 LLM 充当「子 Agent」的 Connector。

    当没有配置外部第三方 Agent 端点时，可用它把子问题交给本系统的
    smart/fast 模型处理，实现「大 Agent 内嵌小 Agent」的委派式研究。
    """

    def __init__(
        self,
        name: str = "internal_subagent",
        *,
        model_type: str = "smart",
        description: str = "",
        capabilities: tuple[str, ...] = ("summarize", "draft", "analyze", "extract"),
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            name,
            description=description or "使用 IRIS 自身 LLM 作为子 Agent 处理子问题。",
            capabilities=capabilities,
            config=config,
            connector_type="internal_subagent",
        )
        self.model_type = model_type

    async def invoke(
        self,
        prompt: str,
        *,
        context: Optional[ConnectorContext] = None,
        system_prompt: Optional[str] = None,
        model_type: Optional[str] = None,
        **kwargs: Any,
    ) -> ConnectorResult:
        mt = model_type or self.model_type or "smart"
        system = system_prompt or DEFAULT_SYSTEM_PROMPT

        def _call() -> str:
            from app.utils.llm import get_llm

            llm = get_llm(mt)
            return llm.invoke(
                [SystemMessage(content=system), HumanMessage(content=prompt)]
            ).content

        try:
            # LLM 客户端是同步阻塞调用，放到线程避免阻塞事件循环。
            content = await asyncio.to_thread(_call)
            return ConnectorResult(
                content=content or "",
                connector=self.name,
                success=True,
                meta={"model_type": mt},
            )
        except Exception as exc:  # best-effort
            return ConnectorResult(
                content="",
                connector=self.name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
