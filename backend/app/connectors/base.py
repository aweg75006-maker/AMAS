from __future__ import annotations

import asyncio
import concurrent.futures
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class ConnectorContext:
    """调用 Connector 时透传的运行上下文。"""

    node_name: str = ""
    state: Mapping[str, Any] = field(default_factory=dict)
    session_id: str = ""
    request_id: str = ""
    model_hint: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorResult:
    """一次 Connector 调用的结果。"""

    content: str
    connector: str = ""
    success: bool = True
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.success

    def to_text(self) -> str:
        """转为可嵌入研究状态的文本；失败时给出可读的错误说明。"""
        if self.success:
            return self.content
        return f"[connector:{self.connector}] 调用失败：{self.error}"


def run_coroutine(coro: Any) -> Any:
    """在独立线程中以 ``asyncio.run`` 执行协程。

    工具运行时在同步线程中调用 Connector，单测又可能在事件循环内调用，
    因此统一「起一个专用线程跑 asyncio.run」以保证两种上下文都安全。
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()


class BaseConnector(ABC):
    """第三方 Agent Connector 的统一抽象。

    子类只需实现 :meth:`invoke`（协程）。同步场景通过 :meth:`run` 调用，
    :meth:`run` 内部用独立线程跑事件循环，避免「已有运行中的事件循环」冲突。
    """

    name: str
    description: str
    capabilities: tuple[str, ...]
    connector_type: str

    def __init__(
        self,
        name: str,
        *,
        description: str = "",
        capabilities: tuple[str, ...] = (),
        config: Optional[dict[str, Any]] = None,
        connector_type: str = "base",
    ) -> None:
        self.name = name
        self.description = description
        self.capabilities = tuple(capabilities)
        self.config = dict(config or {})
        self.connector_type = connector_type

    @abstractmethod
    async def invoke(
        self,
        prompt: str,
        *,
        context: Optional[ConnectorContext] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> ConnectorResult:
        """执行一次子任务委派，返回结构化结果。"""
        raise NotImplementedError

    async def ainvoke(self, prompt: str, **kwargs: Any) -> ConnectorResult:
        """``invoke`` 的异步别名。"""
        return await self.invoke(prompt, **kwargs)

    def run(self, prompt: str, **kwargs: Any) -> ConnectorResult:
        """同步调用入口（工具层使用）。"""
        return run_coroutine(self.invoke(prompt, **kwargs))

    def to_spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.connector_type,
            "description": self.description,
            "capabilities": list(self.capabilities),
        }

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} type={self.connector_type!r}>"
