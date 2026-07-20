from __future__ import annotations

from typing import Any, Optional

import httpx

from app.connectors.base import BaseConnector, ConnectorContext, ConnectorResult

DEFAULT_TIMEOUT_SECONDS = 60.0


class HttpAgentConnector(BaseConnector):
    """调用外部第三方 Agent 端点的 Connector。

    支持两种协议：
    - ``openai_compatible``（默认）：POST ``{base_url}/chat/completions``，OpenAI 格式。
    - ``generic_json``：POST ``{base_url}``，发送 ``{prompt, system_prompt, context}``，
      从响应中取 ``content`` / ``output`` / ``result`` 任一字段作为结果。

    best-effort：网络 / 解析异常统一转为 ``ConnectorResult(success=False)``，
    不抛出，便于研究流程对失败做降级处理。
    """

    def __init__(
        self,
        name: str,
        *,
        base_url: str,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        kind: str = "openai_compatible",
        description: str = "",
        capabilities: tuple[str, ...] = (),
        timeout: Optional[float] = None,
        headers: Optional[dict[str, str]] = None,
        config: Optional[dict[str, Any]] = None,
        transport: Optional[Any] = None,
    ) -> None:
        super().__init__(
            name,
            description=description or f"外部 Agent 端点（{kind}）：{base_url}",
            capabilities=capabilities,
            config=config,
            connector_type="http_agent",
        )
        if not base_url:
            raise ValueError("HttpAgentConnector 需要 base_url。")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.kind = kind
        self.timeout = float(timeout or DEFAULT_TIMEOUT_SECONDS)
        self.extra_headers = dict(headers or {})
        # transport 仅用于测试注入 MockTransport；生产环境为 None。
        self._transport = transport

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        return headers

    async def invoke(
        self,
        prompt: str,
        *,
        context: Optional[ConnectorContext] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> ConnectorResult:
        ctx = context or ConnectorContext()
        try:
            if self.kind == "openai_compatible":
                return await self._invoke_openai(prompt, system_prompt, ctx, kwargs)
            return await self._invoke_generic(prompt, system_prompt, ctx, kwargs)
        except Exception as exc:  # best-effort
            return ConnectorResult(
                content="",
                connector=self.name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _invoke_openai(
        self, prompt: str, system_prompt, ctx: ConnectorContext, kwargs: dict
    ) -> ConnectorResult:
        url = f"{self.base_url}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model or "gpt-4o-mini",
            "messages": messages,
            "temperature": float(kwargs.get("temperature", 0.3)),
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport
        ) as client:
            resp = await client.post(url, json=payload, headers=self._auth_headers())
            data = resp.json()
            if resp.status_code >= 400:
                return ConnectorResult(
                    content="",
                    connector=self.name,
                    success=False,
                    error=f"HTTP {resp.status_code}: {data}",
                    meta={"status": resp.status_code},
                )
            content = data["choices"][0]["message"]["content"]
            return ConnectorResult(
                content=content or "",
                connector=self.name,
                success=True,
                meta={"model": self.model, "usage": data.get("usage")},
            )

    async def _invoke_generic(
        self, prompt: str, system_prompt, ctx: ConnectorContext, kwargs: dict
    ) -> ConnectorResult:
        url = self.base_url
        payload = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "context": {
                "node_name": ctx.node_name,
                "session_id": ctx.session_id,
                "request_id": ctx.request_id,
            },
        }
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self._transport
        ) as client:
            resp = await client.post(url, json=payload, headers=self._auth_headers())
            data = resp.json()
            if resp.status_code >= 400:
                return ConnectorResult(
                    content="",
                    connector=self.name,
                    success=False,
                    error=f"HTTP {resp.status_code}: {data}",
                    meta={"status": resp.status_code},
                )
            content = (
                data.get("content") or data.get("output") or data.get("result") or ""
            )
            return ConnectorResult(
                content=str(content),
                connector=self.name,
                success=True,
                meta={"raw": data},
            )
