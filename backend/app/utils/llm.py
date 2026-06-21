from functools import lru_cache

from langchain_openai import ChatOpenAI
from app.core.config import settings

@lru_cache
def get_llm(model_type="fast"):
    """
    模型工厂函数。
    :param model_type: "fast" (用于生成) 或 "smart" (用于审查)
    """
    
    # --- 配置 A: 快速模型 (DeepSeek-V3 / GPT-4o-mini) ---
    # 用于：Planner, Writer (需要速度和流利度)
    if model_type == "fast":
        return ChatOpenAI(
            model=settings.llm_fast_model,
            temperature=settings.llm_fast_temperature, # 稍微有点创造力
            base_url=settings.openai_api_base,
            api_key=settings.require_openai_api_key()
        )
    
    # --- 配置 B: 聪明模型 (DeepSeek-R1 / GPT-4o / Claude-3.5) ---
    # 阿里云百炼（DashScope）确实支持通过兼容 OpenAI 格式的接口调用 DeepSeek-R1 和 DeepSeek-V3 模型
    # 用于：Reviewer (需要严谨逻辑)
    elif model_type == "smart":
        return ChatOpenAI(
            # 建议用 DeepSeek-R1 (推理能力强) 或 GPT-4o
            model=settings.llm_smart_model,
            temperature=settings.llm_smart_temperature,   # 绝对理性，不要创造力
            base_url=settings.openai_api_base,
            api_key=settings.require_openai_api_key()
        )

    raise ValueError(f"未知模型类型: {model_type}")
