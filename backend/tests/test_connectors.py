"""P5 第三方 Agent Connector 框架相关测试。

覆盖：注册中心、配置驱动注册、内置 Connector（HTTP / 内部子 Agent）、
以及作为研究工具 delegate_to_connector 的桥接与降级行为。
"""
import httpx
import pytest

from app.connectors.base import BaseConnector, ConnectorContext, ConnectorResult
from app.connectors.builtin.http_agent_connector import HttpAgentConnector
from app.connectors.builtin.internal_subagent_connector import (
    InternalSubAgentConnector,
)
from app.connectors.registry import (
    ConnectorRegistry,
    get_connector_registry,
    reset_connector_registry_for_tests,
)
from app.connectors.registration import register_connectors_from_config, _build
from app.core.exceptions import ConfigurationError
from app.tools.registry import ToolContext


class MockConnector(BaseConnector):
    """测试用确定性 Connector。"""

    def __init__(self, name="mock1", result=None, fail=False):
        super().__init__(name, connector_type="mock")
        self.result = result
        self.fail = fail
        self.calls = []

    async def invoke(self, prompt, *, context=None, system_prompt=None, **kwargs):
        self.calls.append((prompt, system_prompt))
        if self.fail:
            return ConnectorResult(
                content="", connector=self.name, success=False, error="boom"
            )
        return ConnectorResult(
            content=self.result or f"echo:{prompt}", connector=self.name
        )


# ─── 注册中心 ───


def test_registry_basics():
    reg = ConnectorRegistry()
    c = MockConnector(name="m")
    reg.register(c)
    assert reg.has("m")
    assert reg.get("m") is c
    assert "m" in reg.names()
    assert any(s["name"] == "m" for s in reg.specs())
    with pytest.raises(ConfigurationError):
        reg.register(MockConnector(name="m"))  # 重复注册
    with pytest.raises(ConfigurationError):
        reg.get("nope")


def test_get_connector_registry_has_builtin():
    reset_connector_registry_for_tests(None)
    try:
        reg = get_connector_registry()
        assert reg.has("internal_subagent")
    finally:
        reset_connector_registry_for_tests(None)


# ─── 配置驱动注册 ───


def test_register_connectors_from_config():
    reg = ConnectorRegistry()
    n = register_connectors_from_config(
        reg,
        [
            {"name": "a", "type": "http_agent", "config": {"base_url": "https://a.test", "model": "m1"}},
            {"name": "b", "type": "internal_subagent", "config": {"model_type": "fast"}},
        ],
    )
    assert n == 2
    assert reg.has("a") and reg.has("b")
    assert reg.get("a").connector_type == "http_agent"
    assert reg.get("b").model_type == "fast"


def test_register_connectors_unknown_type():
    with pytest.raises(ValueError):
        _build({"name": "x", "type": "bogus"})


def test_register_connectors_missing_base_url():
    with pytest.raises(ValueError):
        _build({"name": "x", "type": "http_agent"})


# ─── HTTP Agent Connector（不触网，用 MockTransport）───


def test_http_agent_connector_openai_compatible():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200, json={"choices": [{"message": {"content": "agent-answer"}}]}
        )
    )
    c = HttpAgentConnector(name="ext1", base_url="https://example.test", transport=transport)
    res = c.run("hello", system_prompt="be brief")
    assert res.success
    assert res.content == "agent-answer"
    assert res.meta.get("model") is None or res.meta.get("model") in (None, "gpt-4o-mini")


def test_http_agent_connector_http_error_downgraded():
    transport = httpx.MockTransport(
        lambda req: httpx.Response(500, json={"error": "boom"})
    )
    c = HttpAgentConnector(name="ext1", base_url="https://example.test", transport=transport)
    res = c.run("hello")
    assert res.failed
    assert "500" in res.error


def test_http_agent_connector_generic_json():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["prompt"] == "hello"
        return httpx.Response(200, json={"content": "generic-answer"})

    transport = httpx.MockTransport(handler)
    c = HttpAgentConnector(
        name="ext2",
        base_url="https://example.test/api",
        kind="generic_json",
        transport=transport,
    )
    res = c.run("hello")
    assert res.success
    assert res.content == "generic-answer"


# ─── 内部子 Agent Connector（mock LLM）───


class _FakeLLM:
    def invoke(self, messages):
        class _R:
            content = "subagent-draft"

        return _R()


def test_internal_subagent_connector(monkeypatch):
    import app.utils.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda model_type: _FakeLLM())
    c = InternalSubAgentConnector(name="sub")
    res = c.run("some subtask")
    assert res.success
    assert "subagent-draft" in res.content


# ─── 研究工具桥接 delegate_to_connector ───


def _with_reg(connector, fn):
    reg = ConnectorRegistry()
    reg.register(connector)
    reset_connector_registry_for_tests(reg)
    try:
        return fn()
    finally:
        reset_connector_registry_for_tests(None)


def test_delegate_to_connector_success():
    from app.tools.research_tools import _delegate_to_connector

    def run():
        out = _delegate_to_connector(
            {"connector": "mock1", "prompt": "hi"},
            ToolContext(node_name="researcher"),
        )
        return out

    out = _with_reg(MockConnector(name="mock1", result="agent says hi"), run)
    assert out == "agent says hi"


def test_delegate_to_connector_missing_fields():
    from app.tools.research_tools import _delegate_to_connector

    out = _delegate_to_connector({"prompt": "hi"}, ToolContext(node_name="researcher"))
    assert "需要" in out


def test_delegate_to_connector_unknown():
    from app.tools.research_tools import _delegate_to_connector

    def run():
        out = _delegate_to_connector(
            {"connector": "nope", "prompt": "hi"},
            ToolContext(node_name="researcher"),
        )
        return out

    out = _with_reg(MockConnector(name="mock1"), run)
    assert "未找到" in out


def test_delegate_to_connector_failure_downgraded():
    from app.tools.research_tools import _delegate_to_connector

    def run():
        out = _delegate_to_connector(
            {"connector": "mock1", "prompt": "hi"},
            ToolContext(node_name="researcher"),
        )
        return out

    out = _with_reg(MockConnector(name="mock1", fail=True), run)
    assert "失败" in out
