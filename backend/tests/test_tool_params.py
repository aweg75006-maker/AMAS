"""工具参数契约测试（S1）。

覆盖三件事：
1. ``validate_params`` 的校验行为（拒绝缺失 / 拒绝空串 / 未声明模型时放行 / 输出 JSON 原生类型）；
2. 5 个研究工具确实声明了预期的参数模型；
3. ★ 核心收益：同一份模型能直接生成 LLM function schema，
   且 **server_filled 参数绝不出现在模型可见的 schema 里**。

第 3 点是整个 S1 存在的意义：它证明"一份模型驱动校验 + function schema"真的成立，
而不是又造了一个只能用于校验、跟模型签名无关的新东西。
"""

import pytest
from langchain_core.utils.function_calling import convert_to_openai_function
from pydantic import BaseModel, Field

from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.research_tools import register_research_tools
from app.tools.runtime import ToolRuntime
from app.tools.schemas import RagRelevanceGradeIn, RagRetrieveIn, WebSearchIn
from app.tools.validation import InvalidToolParams, validate_params


class _EchoIn(BaseModel):
    """测试用的最简参数模型：一个必填、非空字符串字段。"""

    value: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# 1. validate_params 行为
# ---------------------------------------------------------------------------


def test_validate_params_rejects_missing_required_field():
    """缺必填字段 → 报错，且错误信息里点名了是哪个字段。"""
    spec = ToolSpec(name="unit.echo", handler=lambda p, c: p, params=_EchoIn)
    with pytest.raises(InvalidToolParams) as exc:
        validate_params(spec, {})
    assert "value" in str(exc.value)


def test_validate_params_rejects_empty_string():
    """min_length=1 生效 —— 这是原来字符串 schema 完全守不住的。"""
    spec = ToolSpec(name="unit.echo", handler=lambda p, c: p, params=_EchoIn)
    with pytest.raises(InvalidToolParams):
        validate_params(spec, {"value": ""})


def test_validate_params_rejects_wrong_type():
    """类型不符也要拦住（字符串 schema 时代这类错误会一路漂到 handler 里炸）。"""
    spec = ToolSpec(name="unit.echo", handler=lambda p, c: p, params=_EchoIn)
    with pytest.raises(InvalidToolParams):
        validate_params(spec, {"value": ["not", "a", "string"]})


def test_validate_params_passes_through_when_no_model_declared():
    """没声明 params 的工具原样放行 —— 保证 S1 期间新旧工具共存。

    这是向后兼容的关键：不需要一次性把 5 个工具全改完才能启动进程。
    """
    spec = ToolSpec(name="unit.raw", handler=lambda p, c: p)
    assert validate_params(spec, {"anything": 1}) == {"anything": 1}


def test_validate_params_normalizes_to_json_types():
    """返回值是可 JSON 序列化的原生类型（后续进快照/日志不会炸）。"""
    spec = ToolSpec(name="unit.echo", handler=lambda p, c: p, params=_EchoIn)
    assert validate_params(spec, {"value": "hello"}) == {"value": "hello"}


def test_validate_params_drops_unknown_fields():
    """模型里没声明的字段不会透传下去。

    这一步顺带把一个隐患变成好事：模型如果瞎编了一个 ``knowledge_base_id``，
    会在校验阶段就被丢掉，而不是悄悄改掉检索范围。
    """
    spec = ToolSpec(name="unit.echo", handler=lambda p, c: p, params=_EchoIn)
    result = validate_params(spec, {"value": "hello", "knowledge_base_id": "kb_hacked"})
    assert result == {"value": "hello"}


# ---------------------------------------------------------------------------
# 2. 研究工具的参数模型声明
# ---------------------------------------------------------------------------


def test_research_tools_declare_params_models():
    """5 个研究工具各自声明了预期的参数模型（不是 None，也不是别的模型）。"""
    registry = ToolRegistry()
    register_research_tools(registry)
    expected = {
        "rag.retrieve": RagRetrieveIn,
        "rag.retrieve_candidates": RagRetrieveIn,
        "rag.relevance_grade": RagRelevanceGradeIn,
        "web.search": WebSearchIn,
        "web.retrieve_candidates": WebSearchIn,
    }
    for name, model in expected.items():
        assert registry.get(name).params is model


def test_rag_tools_declare_knowledge_base_id_as_server_filled():
    """两个 RAG 检索工具都把 knowledge_base_id 标为服务端注入。"""
    registry = ToolRegistry()
    register_research_tools(registry)
    assert registry.get("rag.retrieve").server_filled == ("knowledge_base_id",)
    assert registry.get("rag.retrieve_candidates").server_filled == ("knowledge_base_id",)


def test_toolspec_is_still_hashable_after_adding_fields():
    """新增字段必须可哈希 —— ToolSpec 是 frozen dataclass，会进集合/字典做去重。"""
    spec = ToolSpec(
        name="unit.echo",
        handler=lambda p, c: p,
        params=_EchoIn,
        server_filled=("token",),
    )
    assert {spec, spec} == {spec}


# ---------------------------------------------------------------------------
# 3. 核心收益：同一份模型生成 LLM function schema
# ---------------------------------------------------------------------------


def test_openai_function_schema_is_generated_from_params_model():
    """★ 核心收益：同一份模型能直接生成 Planner 的 function calling 签名。

    改造前 input_schema 是字符串，这里根本无料可用；现在它是模型的纯函数。
    """
    function = convert_to_openai_function(RagRetrieveIn)
    assert set(function["parameters"]["properties"].keys()) == {"query"}
    assert function["parameters"]["required"] == ["query"]


def test_openai_function_schema_carries_field_description():
    """字段 description 会进入 schema —— 这是给模型看的"参数说明书"。"""
    function = convert_to_openai_function(WebSearchIn)
    description = function["parameters"]["properties"]["query"]["description"]
    assert description  # 非空即可，具体文案由 schemas.py 决定


def test_knowledge_base_id_is_not_exposed_to_the_model():
    """★ S2 的安全边界：服务端注入参数绝不能出现在模型可见 schema 里。

    如果哪天有人图省事把 knowledge_base_id 加进 RagRetrieveIn，
    这条测试会立刻红 —— 它守的是"模型不能自己指定检索哪个知识库"。
    """
    registry = ToolRegistry()
    register_research_tools(registry)
    spec = registry.get("rag.retrieve")
    assert spec.server_filled, "rag.retrieve 必须声明 server_filled，否则安全边界无从校验"

    schema = convert_to_openai_function(spec.params)
    properties = schema["parameters"]["properties"]
    required = schema["parameters"].get("required", [])
    for hidden in spec.server_filled:
        assert hidden not in properties
        assert hidden not in required


# ---------------------------------------------------------------------------
# 4. 服务端注参（S2）：模型看不到的参数，由 state 权威注入
# ---------------------------------------------------------------------------


def test_runtime_injects_server_filled_params_from_state():
    """模型传了个假库 id，服务端必须用 state 里的真值覆盖掉。

    这是 S2 的核心断言：即使调用方（或模型）硬塞 ``kb_attacker``，
    handler 实际收到的也必须是 state 里的 ``kb_official``。
    """
    registry = ToolRegistry()
    seen: dict = {}
    registry.register(
        ToolSpec(
            name="unit.filled",
            handler=lambda payload, context: seen.update(payload) or "ok",
            params=RagRetrieveIn,
            server_filled=("knowledge_base_id",),
        )
    )
    runtime = ToolRuntime(node_name="researcher", registry=registry)

    result = runtime.run_registered(
        "unit.filled",
        {"query": "q", "knowledge_base_id": "kb_attacker"},
        state={"knowledge_base_id": "kb_official"},
    )

    assert result.ok is True
    assert seen["knowledge_base_id"] == "kb_official"


def test_runtime_leaves_missing_state_value_untouched():
    """state 里没有该字段时不要去凭空造一个。

    注意：这里断言的是"注入环节不插手"，payload 里本来没有就不该被加上；
    至于 handler 侧的默认值兜底属于 handler 自己的职责，不在本测试范围。
    """
    registry = ToolRegistry()
    seen: dict = {}
    registry.register(
        ToolSpec(
            name="unit.filled",
            handler=lambda payload, context: seen.update(payload) or "ok",
            server_filled=("knowledge_base_id",),
        )
    )
    ToolRuntime(node_name="researcher", registry=registry).run_registered(
        "unit.filled",
        {"query": "q"},
        state={},
    )
    assert "knowledge_base_id" not in seen


def test_runtime_does_not_touch_payload_for_tools_without_server_filled():
    """未声明 server_filled 的工具：连复制都不做，直接返回原对象（零开销）。"""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="unit.plain", handler=lambda payload, context: "ok")
    )
    runtime = ToolRuntime(node_name="researcher", registry=registry)
    payload = {"query": "q"}

    returned = runtime._apply_server_filled(
        registry.get("unit.plain"), payload, {"knowledge_base_id": "kb_x"}
    )

    assert returned is payload  # 同一个对象，说明确实没做多余处理


def test_server_filled_injection_does_not_touch_metadata():
    """注入只改 payload，不能动 metadata —— test_tool_registry.py 直接断言了它。

    这里刻意用桩工具而不是真实研究工具：真实 handler 会发网络请求，
    单测不该依赖外部服务。
    """
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="unit.meta",
            handler=lambda payload, context: "ok",
            input_schema="query:string",
            output_schema="content:string",
            params=RagRetrieveIn,
            server_filled=("knowledge_base_id",),
        )
    )
    runtime = ToolRuntime(node_name="researcher", registry=registry)

    result = runtime.run_registered(
        "unit.meta",
        {"query": "q"},
        state={"knowledge_base_id": "kb_official"},
    )

    assert result.ok is True
    # 入参 schema 仍是注册时声明的那一份，说明 metadata 拼装逻辑没被注入步骤影响
    assert result.run.metadata["input_schema"] == "query:string"
    assert result.run.metadata["output_schema"] == "content:string"
