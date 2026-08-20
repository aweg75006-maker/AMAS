"""记忆生命周期管理器：冷热迁移 + 保护 + 遗忘。

职责：
- archive：热记忆 → 冷归档（从 Chroma 向量索引移除，SQLite 记录保留并标 cold）；
- warm_up：冷归档 → 热记忆（重新写入 Chroma 向量索引，标回 hot）；
- scheduled_archive：定期扫描超期未访问的热记忆统一归档；
- scheduled_forget：定期清理超期冷归档（受保护的不动）；
- mark_protected：给重要记忆打保护标，永不归档、永不删除。

设计：所有外部依赖（Chroma 向量库）都可降级——连不上时静默跳过，
仅保证 SQLite 冷层记录一致，不向调用方抛异常。
"""

import logging
from typing import List, Optional

from app.utils.memory.cold_store import ColdMemoryStore, LABEL_HOT, LABEL_COLD

logger = logging.getLogger("iris.memory")


class MemoryLifecycleManager:
    """记忆生命周期管理：管理热/冷两层之间的迁移。"""

    def __init__(self, cold_store: Optional[ColdMemoryStore] = None):
        self.cold = cold_store or ColdMemoryStore()
        # 温层（Chroma 向量索引）懒加载：异常时置 None，调用处统一判空
        self._retriever = None
        self._retriever_ok = True

    # ─── 温层访问 ───

    def _get_retriever(self):
        """懒加载跨轮检索器（Chroma 温层）。失败时缓存失败状态避免反复重试。"""
        if not self._retriever_ok:
            return None
        if self._retriever is None:
            try:
                from app.utils.cross_turn_retriever import CrossTurnRetriever
                self._retriever = CrossTurnRetriever()
            except Exception as e:
                self._retriever_ok = False
                logger.warning("温层（Chroma）初始化失败，冷热迁移将仅更新冷层: %s", e)
        return self._retriever

    # ─── 冷热迁移 ───

    def archive(self, memory_id: str) -> None:
        """热 → 冷：移除 Chroma 索引，SQLite 记录标 cold。"""
        retriever = self._get_retriever()
        if retriever is not None:
            try:
                retriever.delete_turn(memory_id)
            except Exception as e:
                logger.warning("归档移除向量索引失败 %s: %s", memory_id, e)
        self.cold.mark_cold(memory_id)

    def warm_up(self, memory_id: str) -> None:
        """冷 → 热：按冷层记录重建 Chroma 索引，标回 hot。"""
        record = self.cold.get_by_id(memory_id)
        if not record:
            return
        content = record.get("content") or {}

        retriever = self._get_retriever()
        if retriever is not None:
            try:
                from app.utils.summarizer import TurnSummary
                # 从冷层保存的字段恢复 TurnSummary（text_for_embedding 为 property，自动生成）
                summary = TurnSummary(
                    turn_id=memory_id,
                    turn_number=int(content.get("turn_number", 0) or 0),
                    query_gist=content.get("query_gist", ""),
                    key_facts=content.get("key_facts", []),
                    conclusions=content.get("conclusions", []),
                    methodology=content.get("methodology", ""),
                    unresolved=content.get("unresolved", ""),
                    topic_tags=content.get("topic_tags", []),
                    importance_score=float(content.get("importance_score", 0.5)),
                )
                text = summary.text_for_embedding
                if text:
                    retriever.index(summary)
            except Exception as e:
                logger.warning("升温重建向量索引失败 %s: %s", memory_id, e)
        self.cold.mark_hot(memory_id)

    # ─── 批量调度 ───

    def scheduled_archive(self) -> List[str]:
        """归档超过 warm_days 未访问的热记忆。返回被归档的 id 列表。"""
        candidates = self.cold.get_cold_candidates(days=self._warm_days())
        to_archive = [c["id"] for c in candidates]
        for mid in to_archive:
            try:
                self.archive(mid)
            except Exception as e:
                logger.warning("归档失败 %s: %s", mid, e)
        return to_archive

    def scheduled_forget(self) -> List[str]:
        """删除超过 cold_retention_days 的冷归档。返回被删除的 id 列表。"""
        old = self.cold.get_cold_records(days=self._retention_days())
        to_delete = [c["id"] for c in old]
        for mid in to_delete:
            try:
                self.cold.delete(mid)
            except Exception as e:
                logger.warning("遗忘删除失败 %s: %s", mid, e)
        return to_delete

    def mark_protected(self, memory_id: str) -> None:
        """标记受保护：永不归档、永不删除。"""
        self.cold.mark_protected(memory_id)

    # ─── 配置读取（延迟 import 避免循环依赖）───

    @staticmethod
    def _warm_days() -> int:
        from app.core.config import settings
        return settings.memory_warm_days

    @staticmethod
    def _retention_days() -> int:
        from app.core.config import settings
        return settings.memory_cold_retention_days
