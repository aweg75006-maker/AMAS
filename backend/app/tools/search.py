from tavily import TavilyClient
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("iris.tools.search")

# 初始化 Tavily 客户端
_tavily = None


def get_tavily_client() -> TavilyClient:
    global _tavily
    if _tavily is None:
        _tavily = TavilyClient(api_key=settings.require_tavily_api_key())
    return _tavily

def search_tavily(query: str):
    """
    使用 Tavily 搜索网络。
    返回最相关的 3 条内容。
    """
    logger.info("tavily_search_started", extra={"query_length": len(query)})
    response = get_tavily_client().search(
        query=query,
        search_depth=settings.tavily_search_depth,
        max_results=settings.tavily_max_results,
    )
    
    # 提取我们关心的内容（为了节省 Token，只取 content）
    context = [result["content"] for result in response["results"]]
    logger.info("tavily_search_completed", extra={"result_count": len(context)})
    return "\n".join(context)
