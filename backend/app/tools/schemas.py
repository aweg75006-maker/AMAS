"""研究类工具的参数模型（S1 工具参数契约升级）。

为什么需要这个文件
==================
改造前，一个工具的"参数长什么样"有**两套互相不认识的真相**：

1. ``ToolSpec.input_schema`` 只是一个字符串，例如 ``"query:string, knowledge_base_id:string"``。
   它只能塞进提示词给大模型看，**既不能校验、也不能生成 function calling 签名**。
2. handler 内部直接 ``payload["query"]`` 手动取值。
   模型一旦传错参数（少传、传空串、传成数字），就是 ``KeyError`` / 类型错乱 → 500。

本文件用一份 Pydantic 模型取代上面两套真相，同一份定义被两处消费：

- **服务端校验**：``app/tools/validation.py::validate_params`` 用它拒绝非法参数；
- **LLM function schema**：``convert_to_openai_function()`` 用它生成 Planner 看到的工具签名。

一处定义、两处使用，所以参数契约永远不会漂移。

字段设计约定
============
- 所有字段都加了 ``description``：这段文字会**直接进入模型可见的 function schema**，
  写清楚它等于提升模型调用工具的参数质量。
- ``min_length=1`` 之类的约束是字符串 schema 时代完全守不住的东西，现在是硬校验。
- **``knowledge_base_id`` 故意不出现在下面的模型里** —— 它属于"服务端注入参数"，
  在 ``ToolSpec.server_filled`` 里声明，由运行时从图状态注入。
  写进模型会让 Planner 有机会在参数里编造一个别的知识库 id，属于安全边界问题。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RagRetrieveIn(BaseModel):
    """本地知识库检索（``rag.retrieve`` / ``rag.retrieve_candidates`` 共用）。

    两个工具都是"给我 query，我给你文档"，参数形状完全一致，因此复用同一个模型。
    ``knowledge_base_id`` 不在此声明 —— 见文件头说明。
    """

    query: str = Field(
        min_length=1,
        max_length=500,
        description="检索用的自然语言查询，例如“小米汽车 2025 年交付量”",
    )


class RagRelevanceGradeIn(BaseModel):
    """LLM 证据评估（``rag.relevance_grade``）。

    这个工具本质是"把问题 + 已召回的证据一起丢给 LLM，让它判断证据够不够"，
    所以需要两个参数：待回答的问题，以及本轮检索到的文档上下文。
    """

    query: str = Field(
        min_length=1,
        max_length=500,
        description="需要被评估的原始用户问题",
    )
    document_context: str = Field(
        min_length=1,
        max_length=8000,
        description="本轮检索到的文档上下文（多篇文档拼接后的文本）",
    )


class WebSearchIn(BaseModel):
    """联网搜索（``web.search`` / ``web.retrieve_candidates`` 共用）。

    与 RAG 检索一样只需 query；两者的区别只在"返回精简文本"还是"返回带来源元数据的候选列表"，
    不体现在入参上，因此共用。
    """

    query: str = Field(
        min_length=1,
        max_length=500,
        description="联网搜索关键词或自然语言查询",
    )
