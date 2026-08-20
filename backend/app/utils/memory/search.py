"""多级记忆检索：热缓存 → 温层向量 → 图谱 → 冷层归档 → 兜底。

设计目标：让"查历史记忆"在不同场景都有合适的路径——
- 高频重复查询走 Redis 热缓存（快，不重复计算）；
- 常规语义查询走 Chroma 温层（向量召回）；
- 结构化知识查询（"用户偏好""谁负责什么"）走图谱（精确关系）；
- 向量/图谱都未命中时，冷层 LIKE 关键词兜底，命中即自动"升温"回温层；
- 最后兜底返回该会话最近记录。

返回统一结构：[{"id", "content", "type", "score"}]，方便上层拼接成 Prompt。
所有外部依赖（Redis / Chroma）均可降级：不可用时静默跳过该层。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.utils.memory.cold_store import ColdMemoryStore
from app.utils.memory.graph_store import GraphMemoryStore
from app.utils.memory.lifecycle import MemoryLifecycleManager

logger = logging.getLogger("iris.memory")


class MemorySearchService:
    """多级记忆检索服务。"""

    def __init__(
        self,
        cold_store: Optional[ColdMemoryStore] = None,
        graph_store: Optional[GraphMemoryStore] = None,
    ):
        self.cold = cold_store or ColdMemoryStore()
        self.graph = graph_store or GraphMemoryStore()
        self._lifecycle: Optional[MemoryLifecycleManager] = None

    def _get_lifecycle(self) -> MemoryLifecycleManager:
        """懒加载生命周期管理器（warm_up 需要）。"""
        if self._lifecycle is None:
            self._lifecycle = MemoryLifecycleManager(cold_store=self.cold)
        return self._lifecycle

    # ─── 主入口 ───

    async def search(
        self,
        query: str,
        thread_id: Optional[str] = None,
        top_k: int = 5,
        redis=None,
    ) -> List[Dict[str, Any]]:
        """多级检索。

        Args:
            query: 检索词
            thread_id: 会话 id（冷层兜底时按会话过滤）
            top_k: 返回条数上限
            redis: RedisClient 实例（可为 None，传入则启用热缓存）

        Returns:
            [{"id", "content", "type", "score"}]（type: semantic/graph/cold/episodic）
        """
        if not query:
            return []

        # 1. 热缓存命中直接返回
        cache_key = f"mem:search:{query}:{top_k}"
        if redis is not None:
            cached = await redis.get(cache_key)
            if cached:
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        # 2. 温层：向量语义召回
        results = self._search_vector(query, top_k)

        # 3. 图谱：结构化关系（向量未命中时优先走图谱）
        if not results:
            results = self._search_graph(query, top_k)

        # 4. 冷层：关键词模糊匹配（命中即升温回温层）
        if not results:
            results = self._search_cold(query, thread_id, top_k)

        # 5. 兜底：该会话最近记录
        if not results:
            results = self._search_recent(thread_id, top_k)

        # 回填热缓存（TTL 由配置控制，缓存层非事实源）
        if redis is not None and results:
            try:
                await redis.set(
                    cache_key, json.dumps(results, ensure_ascii=False),
                    ex=self._cache_ttl(),
                )
            except Exception:
                pass

        return results[:top_k]

    # ─── 各层检索 ───

    def _search_vector(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """温层：Chroma 向量召回。"""
        try:
            from app.utils.cross_turn_retriever import CrossTurnRetriever
            rr = CrossTurnRetriever().retrieve(query, top_k=top_k)
            return [
                {
                    "id": t.turn_id,
                    "content": t.display_text,
                    "type": "semantic",
                    "score": round(t.relevance_score, 3),
                }
                for t in rr.retrieved_turns
            ]
        except Exception as e:
            logger.debug("温层检索不可用: %s", e)
            return []

    def _search_graph(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """图谱：实体/关系模糊匹配 + 邻接路径。"""
        try:
            paths = self.graph.search_relations(query, depth=2, limit=top_k)
            results = []
            for i, p in enumerate(paths):
                nodes = " → ".join(p["nodes"])
                relations = " → ".join(p["relations"])
                results.append({
                    "id": f"graph-{query}-{i}",
                    "content": f"{nodes}（关系: {relations}）",
                    "type": "graph",
                    "score": 1.0,
                })
            return results
        except Exception as e:
            logger.debug("图谱检索不可用: %s", e)
            return []

    def _search_cold(
        self, query: str, thread_id: Optional[str], top_k: int
    ) -> List[Dict[str, Any]]:
        """冷层：LIKE 关键词匹配；命中后自动升温。"""
        try:
            rows = self.cold.search_cold(query, limit=top_k)
            results = []
            for r in rows:
                content = r.get("content") or {}
                text = content.get("query_gist", "") if isinstance(content, dict) else str(content)
                results.append({
                    "id": r["id"],
                    "content": str(text)[:200],
                    "type": r.get("event_type", "cold"),
                    "score": 0.5,
                })
                # 命中冷归档 → 升温（重新向量索引），下次可被温层直接召回
                try:
                    self._get_lifecycle().warm_up(r["id"])
                except Exception:
                    pass
            return results
        except Exception as e:
            logger.debug("冷层检索不可用: %s", e)
            return []

    def _search_recent(
        self, thread_id: Optional[str], top_k: int
    ) -> List[Dict[str, Any]]:
        """兜底：该会话最近的记忆记录。"""
        try:
            rows = self.cold.search(thread_id=thread_id, limit=top_k)
            return [
                {
                    "id": r["id"],
                    "content": str((r.get("content") or {}).get("query_gist", ""))[:200],
                    "type": r.get("event_type", "episodic"),
                    "score": 0.0,
                }
                for r in rows
            ]
        except Exception:
            return []

    @staticmethod
    def _cache_ttl() -> int:
        from app.core.config import settings
        return settings.memory_cache_ttl


# 全局单例
_search: Optional[MemorySearchService] = None


def get_memory_search() -> MemorySearchService:
    """获取全局 MemorySearchService 单例（Redis 连接由调用方注入）。"""
    global _search
    if _search is None:
        _search = MemorySearchService()
    return _search
