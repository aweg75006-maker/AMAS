"""LLM 供应商注册与解析（S5）。

【一行配置切换 mock 与真实模型】
    LLM_PROVIDER=mock              → 离线跑通全流程，不烧额度
    LLM_PROVIDER=openai_compatible → 默认，走 OPENAI_API_BASE

【新增供应商要改哪里】
在 `get_llm_provider()` 里登记一行即可，调用方（6 处 get_llm 调用点）无需改动。

⚠️ 两个坑：
1. `@lru_cache`：改了 `settings.llm_provider` 之后必须 `get_llm_provider.cache_clear()`，
   否则测试里改了配置也不生效（假绿/假红）。测试用例里已有示范。
2. `lazy import`：mock 与真实实现**按需导入**，避免只想用 mock 时也去加载
   langchain_openai 那套依赖（也让 mock 路径不依赖任何 API Key 配置）。
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.utils.providers.base import LLMProvider, ProviderError

__all__ = [
    "LLMProvider",
    "ProviderError",
    "get_llm_provider",
]


@lru_cache
def get_llm_provider() -> LLMProvider:
    """按配置解析当前供应商（进程内单例）。

    注意返回值类型标注是 Protocol `LLMProvider`，
    实际返回的是 MockLLMProvider / OpenAICompatibleProvider 实例。
    """
    name = settings.llm_provider

    if name == "mock":
        from app.utils.providers.mock import MockLLMProvider

        return MockLLMProvider()

    if name == "openai_compatible":
        from app.utils.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider()

    raise ProviderError(f"未知的 LLM_PROVIDER：{name}")


# ---------------------------------------------------------------------------
# S5 待接线清单（Demo 阶段：provider 已就绪，接入点尚未切换）
# ---------------------------------------------------------------------------
# ① app/core/config.py —— 在 llm_smart_temperature 附近新增配置：
#        # LLM 供应商：openai_compatible（默认，走 OPENAI_API_BASE）| mock（离线演示/测试）
#        llm_provider: Literal["openai_compatible", "mock"] = "openai_compatible"
#    并在 safe_summary() 里加一行 "llm_provider": self.llm_provider
#    （目的：健康检查里能一眼看出当前是否误用了 mock —— 全局风险 R9）
#
# ② app/utils/llm.py —— 保持函数签名不变，内部改走 provider：
#        @lru_cache
#        def get_llm(model_type="fast"):
#            from app.utils.providers import get_llm_provider
#            return get_llm_provider().chat_model(model_type)
#    这一改动是"零侵入"的：现有 6 处调用点一行都不用改。
