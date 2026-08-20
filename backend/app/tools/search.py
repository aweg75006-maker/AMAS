"""Tavily 网络搜索封装。

职责：
- 统一封装 Tavily 客户端的惰性初始化（全局单例，避免重复创建连接）；
- 提供两种粒度：
    search_tavily             —— 直接返回拼接好的文本内容（省 token，适合当上下文用）；
    search_tavily_candidates  —— 返回带来源元数据的候选列表（供统一去重 + 全局重排）；
- 搜索深度与返回条数由配置（tavily_search_depth / tavily_max_results）控制。
"""

from tavily import TavilyClient
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("iris.tools.search")

# Tavily 客户端（进程内惰性单例）
_tavily = None


def get_tavily_client() -> TavilyClient:
    """获取 Tavily 客户端（首次调用时创建并校验 API Key）。"""
    global _tavily
    if _tavily is None:
        _tavily = TavilyClient(api_key=settings.require_tavily_api_key())
    return _tavily


def search_tavily(query: str):
    """联网搜索，返回拼接的纯文本内容（只取 content，为节省 token）。"""
    response = _search_tavily(query)

    # 提取我们关心的内容（为了节省 Token，只取 content）
    context = [result["content"] for result in response["results"]]
    logger.info("tavily_search_completed", extra={"result_count": len(context)})
    return "\n".join(context)


def search_tavily_candidates(query: str) -> list[dict[str, object]]:
    """联网搜索，返回带来源元数据的候选（供统一去重与全局重排）。

    每个候选携带 text / title / source_uri / retrieval_score / source_rank，
    与本地检索候选统一成 RetrievalCandidateDict 的语义，方便下游融合。
    """
    response = _search_tavily(query)
    candidates = []
    for rank, result in enumerate(response.get("results", []), start=1):
        content = str(result.get("content", "")).strip()
        if not content:
            # 过滤掉没有正文的脏结果
            continue
        candidates.append(
            {
                "text": content,
                "title": str(result.get("title", "")),
                "source_uri": str(result.get("url", "")),
                "retrieval_score": float(result.get("score", 0.0) or 0.0),
                "source_rank": rank,  # 搜索引擎给的原始排名，重排时作为保底排序依据
                "query": query,
            }
        )
    logger.info("tavily_candidate_search_completed", extra={"result_count": len(candidates)})
    return candidates


def _search_tavily(query: str) -> dict:
    """底层搜索调用：按配置的搜索深度与条数执行，并记录日志。"""
    logger.info("tavily_search_started", extra={"query_length": len(query)})
    return get_tavily_client().search(
        query=query,
        search_depth=settings.tavily_search_depth,
        max_results=settings.tavily_max_results,
    )
