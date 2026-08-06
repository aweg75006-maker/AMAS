from typing import TypedDict, List, Optional, Dict, Any
import operator


class TurnRecordDict(TypedDict, total=False):
    """Turn 完整记录（Episodic Memory 中的数据单元）。"""
    turn_id: str
    turn_number: int
    query: str
    plan: List[str]
    search_results: List[str]
    final_report: str
    critique: str
    review_status: str
    search_mode: str
    token_usage: Dict[str, int]
    timestamp: float


class TurnSummaryDict(TypedDict, total=False):
    """Turn 压缩摘要（Semantic Memory 中的数据单元）。"""
    turn_id: str
    turn_number: int
    query_gist: str              # 用户核心诉求的一句话概括
    key_facts: List[str]         # 关键事实（最多 5 条）
    conclusions: List[str]       # 核心结论（最多 3 条）
    methodology: str             # 研究方法
    unresolved: str              # 未解决问题
    topic_tags: List[str]        # 用于跨轮检索的主题标签
    importance_score: float      # 0-1，Turn 重要度


class TokenUsageDict(TypedDict, total=False):
    """单次 Turn 的 Token 使用统计。"""
    estimated_input: int
    actual_input: int
    actual_output: int
    overflow_triggered: bool
    compression_applied: bool


class BudgetStateDict(TypedDict, total=False):
    """预算快照。"""
    total_budget: int
    total_used: int
    remaining: int
    session_estimated_total: int
    session_actual_total: int
    compression_savings: int


class RetrievalCandidateDict(TypedDict, total=False):
    """Normalized local or web evidence before and after global reranking."""
    id: str
    text: str
    title: str
    source_type: str
    source_uri: str
    retrieval_score: float
    rerank_score: float
    source_rank: int
    query: str
    metadata: Dict[str, Any]


class AgentState(TypedDict, total=False):
    """
    Agent 的状态定义。
    这就好比一个共享的文件夹，每个步骤都可以往里面存取东西。

    原有字段（必填，向后兼容）：
        query, plan, search_results, final_report, critique,
        revision_number, review_status, search_mode, should_stop

    上下文工程新增字段（可选，Phase 1）：
        session_id, turn_id, turn_number,
        episodic_memory, semantic_memory,
        budget_state, token_usage_current_turn, token_usage_session_total

    内部观测字段（可选）：
        _tool_runs, _route_decisions
    """

    # ─── 原有字段 ───
    query: str                      # 用户原始问题
    plan: List[str]                 # 规划的搜索步骤
    search_results: List[str]       # 搜索到的具体内容
    final_report: str               # 最终生成的报告
    critique: str                   # 审查意见
    revision_number: int            # 当前修改到了第几版 (防止死循环)
    review_status: str              # "PASS" 或 "FAIL"
    review_action: str              # "none" / "replan" / "rewrite"
    search_mode: str                # 取值: "document" 或 "hybrid"
    should_stop: bool               # 控制位

    # ─── 新增：上下文工程字段（Phase 1 — 全部 Optional）───
    session_id: str                 # 持久化会话 ID（服务端生成）
    turn_id: str                    # 当前 Turn 的唯一标识
    turn_number: int                # 会话内第几个 Turn
    request_id: str                 # 当前请求 ID

    # 分层记忆
    episodic_memory: List[TurnRecordDict]     # 最近 K 个 Turn（完整记录）
    semantic_memory: List[TurnSummaryDict]    # 历史 Turn 的压缩摘要
    knowledge_fusion: str                     # 全局知识融合文本（极端压缩时使用）

    # 预算状态
    budget_state: BudgetStateDict             # 当前预算快照
    token_usage_current_turn: TokenUsageDict  # 当前 Turn 累计
    token_usage_session_total: TokenUsageDict  # 会话累计
    _tool_runs: List[Dict[str, Any]]           # 当前节点产生的工具调用快照
    _route_decisions: List[Dict[str, Any]]     # 当前节点关联的路由决策快照

    # Agentic RAG evidence state
    candidate_pool: List[RetrievalCandidateDict]
    ranked_evidence: List[RetrievalCandidateDict]
    retrieval_iteration: int
    retrieval_hints: List[str]
    coverage_gap: str
    follow_up_queries: List[str]
