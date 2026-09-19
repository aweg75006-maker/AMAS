"""OpenAI 兼容供应商（S5）：把原 app/utils/llm.py 的实现原样搬进来。

【为什么是"搬家"而不是"重写"】
迁移原则是**行为零变更**：base_url / api_key / temperature / 模型名的取值
与原实现逐字一致。这样切换 provider 抽象对线上行为没有任何影响 ——
`get_llm("fast")` 返回的东西和改造前一模一样。

【兼容范围】
任何暴露 OpenAI 兼容接口的服务都能用：阿里云百炼（DashScope）、DeepSeek 官方 API、
OpenAI 官方、以及各类自建网关。切换只需要改 `.env` 里的 OPENAI_API_BASE。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.utils.providers.base import ProviderError


class OpenAICompatibleProvider:
    """走 OPENAI_API_BASE 的默认供应商。"""

    name = "openai_compatible"

    def chat_model(self, model_type: str = "fast") -> ChatOpenAI:
        """按档位构造 ChatModel（取值与原 app/utils/llm.py 完全一致）。"""
        # --- 档位 A：快速模型（Planner / Writer，要速度和流利度）---
        if model_type == "fast":
            return ChatOpenAI(
                model=settings.llm_fast_model,
                temperature=settings.llm_fast_temperature,
                base_url=settings.openai_api_base,
                api_key=settings.require_openai_api_key(),
            )

        # --- 档位 B：强推理模型（Reviewer / 证据评估，要严谨逻辑）---
        # 阿里云百炼支持通过 OpenAI 兼容接口调用 DeepSeek-R1 / DeepSeek-V3
        if model_type == "smart":
            return ChatOpenAI(
                model=settings.llm_smart_model,
                temperature=settings.llm_smart_temperature,
                base_url=settings.openai_api_base,
                api_key=settings.require_openai_api_key(),
            )

        # 与原实现保持一致：未知档位直接报错，不做静默降级
        raise ProviderError(f"未知模型类型: {model_type}")
