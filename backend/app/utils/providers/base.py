"""LLM 供应商抽象层（S5）。

【一句话目标】
按配置名 lazy import 具体实现，把 `mock` 做成一等公民 →
**测试与演示不再烧 API Key、不再受网络抖动影响**。

【为什么 `chat_model()` 返回 LangChain 的 ChatModel 实例】
而不是自己再定义一层 chat 接口。因为 AMAS 现有代码到处在用
``.invoke()`` / ``.ainvoke()`` / ``.content``：
    planner.py:40、research_tools.py:127、writer.py、reviewer.py、refiner.py、router.py
返回 LangChain 对象可以做到这 6 处调用点**一行都不用改**。
这是"零侵入接入"的关键设计取舍。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ProviderError(Exception):
    """供应商未配置或不可用（例如密钥缺失、配置名拼错）。"""


@runtime_checkable
class LLMProvider(Protocol):
    """LLM 供应商需要满足的最小接口。

    只需要一个方法：给定模型档位，返回一个 LangChain ChatModel。
    档位目前有两档（与 app/utils/llm.py 的既有约定一致）：
        "fast"  → Planner / Writer，要速度和流利度
        "smart" → Reviewer / 证据评估，要严谨推理
    """

    name: str

    def chat_model(self, model_type: str = "fast"):  # pragma: no cover - 协议声明
        ...
