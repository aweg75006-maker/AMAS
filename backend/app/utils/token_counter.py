"""
Token 计数器：多模型 Tokenizer 映射 + 字符估算兜底。

支持的模型编码：
- Qwen3-Max / Qwen3-Plus → cl100k_base (近似)
- DeepSeek-R1 / DeepSeek-V3 → cl100k_base (近似)
- GPT-4o / GPT-4o-mini      → o200k_base
- GPT-4 / GPT-3.5           → cl100k_base

核心设计：准确度在 95%+ 即可满足预算管理需求，
偏差通过 BudgetLedger 的预估-vs-实际对比来持续校准。
"""

import tiktoken
from typing import List, Union, Optional, Dict
from dataclasses import dataclass


# ─── 模型 → encoding 映射 ───
MODEL_ENCODING_MAP: Dict[str, str] = {
    # Qwen 系列 (DashScope) — 使用 cl100k_base 近似
    "qwen3-max": "cl100k_base",
    "qwen3-plus": "cl100k_base",
    "qwen-max": "cl100k_base",
    "qwen-plus": "cl100k_base",
    # DeepSeek 系列 — 使用 cl100k_base 近似
    "deepseek-r1": "cl100k_base",
    "deepseek-v3": "cl100k_base",
    "deepseek-chat": "cl100k_base",
    # OpenAI 系列
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
}

# 默认 encoding（通用）
DEFAULT_ENCODING = "cl100k_base"

# 字符估算常数：大多数模型 ~4 字符/token
CHARS_PER_TOKEN = 4


class TokenCounter:
    """
    多模型 Token 计数器。

    用法:
        counter = TokenCounter("qwen3-max")
        count = counter.count("你好世界")
        count = counter.count_messages([{"role": "user", "content": "..."}])
        ok, current = counter.check_budget("...", max_tokens=4000)
    """

    def __init__(self, model_name: Optional[str] = None):
        """
        Args:
            model_name: 模型名（如 "qwen3-max", "deepseek-r1"）。
                       为 None 时使用默认 encoding。
        """
        self.model_name = model_name or "default"
        encoding_name = MODEL_ENCODING_MAP.get(
            self.model_name.lower(), DEFAULT_ENCODING
        )
        try:
            self.encoding = tiktoken.get_encoding(encoding_name)
            self._use_fallback = False
        except Exception:
            # tiktoken 不支持的 encoding 时，退回字符估算
            self.encoding = None
            self._use_fallback = True

    def count(self, text: str) -> int:
        """计算文本的 token 数量。"""
        if not text:
            return 0
        if self._use_fallback:
            return self._estimate_chars(text)
        try:
            return len(self.encoding.encode(text))
        except Exception:
            return self._estimate_chars(text)

    def count_messages(self, messages: List[Dict[str, str]]) -> int:
        """
        计算消息列表的 token 数量（近似）。

        参考 OpenAI 的计数方式：每条消息有固定开销 (~4 tokens)，
        content 按 tiktoken 编码计算。
        """
        total = 0
        for msg in messages:
            # 每条消息的格式开销
            total += 4
            for key, value in msg.items():
                total += self.count(str(value))
        # 回复的 priming 开销
        total += 2
        return total

    def count_batch(self, texts: List[str]) -> int:
        """批量计算文本总 token 数。"""
        return sum(self.count(t) for t in texts)

    def check_budget(
        self, text: str, max_tokens: int
    ) -> "BudgetCheckResult":
        """
        预算检查：判断文本是否在预算内。

        Returns:
            BudgetCheckResult(token_count, within_budget, headroom)
        """
        count = self.count(text)
        return BudgetCheckResult(
            token_count=count,
            within_budget=count <= max_tokens,
            headroom=max_tokens - count,
        )

    def _estimate_chars(self, text: str) -> int:
        """字符级估算：4 字符 ≈ 1 token。"""
        return max(1, len(text) // CHARS_PER_TOKEN)

    def __repr__(self) -> str:
        mode = "fallback(chars/4)" if self._use_fallback else self.encoding.name
        return f"TokenCounter(model={self.model_name}, mode={mode})"


@dataclass
class BudgetCheckResult:
    """预算检查结果。"""
    token_count: int
    within_budget: bool
    headroom: int  # 正数 = 剩余空间，负数 = 超出量


# ─── 便捷函数 ───

# 预建常用计数器（懒加载）
_counters: Dict[str, TokenCounter] = {}


def get_counter(model_name: str = "qwen3-max") -> TokenCounter:
    """获取指定模型的 TokenCounter（带缓存）。"""
    key = model_name.lower()
    if key not in _counters:
        _counters[key] = TokenCounter(model_name)
    return _counters[key]


def count_tokens(text: str, model: str = "qwen3-max") -> int:
    """快速计数。"""
    return get_counter(model).count(text)
