"""离线 Mock 模型（S5）：让全流程不烧额度即可跑通。

【设计原则：mock 不是"返回空"，而是"返回格式正确、内容可辨认的假数据"】
这一点很关键。如果 mock 返回空字符串，那么：
  · Planner 解析出的 plan 是空列表 → 下游走"没有检索方向"的分支 → 测试失去意义；
  · 证据评估拿到空内容 → 走到 JSON 解析失败的兜底分支 → 测的不是主路径。
所以下面的 mock 响应**显式对齐下游的解析契约**，保证 mock 模式下走的是主路径。

【用的是 langchain_core 自带的 FakeListChatModel，不引入新依赖】

⚠️ 生产误用防护（全局风险 R9）：
配置项 `llm_provider` 默认是 `openai_compatible`，且它被写进
`settings.safe_summary()`，健康检查/启动日志里能直接看到当前用的是哪个 provider。
"""

from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel

# fast 档的假响应：Planner 期望拿到"检索方向"。
# 用逗号分隔，是为了同时兼容两条解析路径：
#   · 新的结构化路径（S7 的 _parse_plan 会先尝试 JSON，失败后才退回逗号切分）
#   · 旧的逗号切分路径（nodes/planner.py 原来的实现）
_MOCK_FAST_RESPONSE = "检索方向一,检索方向二,检索方向三"

# smart 档的假响应：必须能被 research_tools._parse_evidence_assessment 解析成
# {"sufficient": True, "coverage_gap": "", "follow_up_queries": []}
# 结构对齐它期望的 JSON 契约 —— 这样 mock 下也能跑通"证据充分 → 进 Writer"的主分支。
_MOCK_SMART_RESPONSE = (
    '{"sufficient": true, "coverage_gap": "", "follow_up_queries": []}'
)


class MockLLMProvider:
    """离线供应商：按档位返回预设内容的假模型。"""

    name = "mock"

    def chat_model(self, model_type: str = "fast") -> FakeListChatModel:
        """返回假 ChatModel。

        注意 FakeListChatModel 的 responses 是**轮询消费**的：调用次数超过列表长度后
        会从头循环。所以这里只放一条，保证行为稳定可预期。
        """
        if model_type == "smart":
            return FakeListChatModel(responses=[_MOCK_SMART_RESPONSE])
        # fast（含未知档位）：给 Planner/Writer 用的通用响应
        return FakeListChatModel(responses=[_MOCK_FAST_RESPONSE])
