"""记忆记录器：将已生成的回合摘要"路由"进记忆系统冷层。

职责（对应记忆写入链路）：
1. 分类：调用 classification 判定记忆类型；
2. 落冷层：以 turn_id 为记忆 id 写入 SQLite events 表（content 保留完整摘要结构，
   供后期"升温重建向量索引 / 冷层模糊检索"使用）；
3. 重要度映射：importance_score（0-1）→ low / medium / high 三档。

与温层的协作：
- Chroma 向量索引仍由 CompressionScheduler 统一负责（本模块不做重复索引）；
- 冷层记录与温层索引共享同一 id（turn_id），保证 archive/warm_up 能对齐。

设计：纯同步、零外部依赖，异常静默降级（记录失败不影响主流程）。
"""

import logging
from typing import Optional

from app.utils.memory.cold_store import ColdMemoryStore
from app.utils.memory.classification import classify_memory

logger = logging.getLogger("iris.memory")


class MemoryRecorder:
    """把回合摘要路由进冷层记忆库。"""

    def __init__(self, cold_store: Optional[ColdMemoryStore] = None):
        self.cold = cold_store or ColdMemoryStore()

    @staticmethod
    def _importance_level(score: float) -> str:
        """0-1 分数 → 三档重要度标签。"""
        if score >= 0.7:
            return "high"
        if score >= 0.4:
            return "medium"
        return "low"

    def record_summary(self, session_id: str, summary) -> str:
        """记录一条回合摘要到冷层。

        Args:
            session_id: 所属会话（thread）
            summary: TurnSummary 对象（含 to_dict()）

        Returns:
            记忆 id（即 turn_id）；失败返回空串。
        """
        try:
            content = summary.to_dict()
            text = summary.text_for_embedding or summary.query_gist
            memory_type = classify_memory(text, getattr(summary, "topic_tags", None))
            importance = self._importance_level(
                float(getattr(summary, "importance_score", 0.5) or 0.5)
            )
            self.cold.add(
                memory_id=summary.turn_id,
                thread_id=session_id,
                event_type=memory_type,
                content=content,
                importance=importance,
            )
            return summary.turn_id
        except Exception as e:
            logger.warning("记忆记录失败 turn=%s: %s", getattr(summary, "turn_id", "?"), e)
            return ""


# 全局单例（与 get_scheduler 同风格，供各接入点复用）
_recorder: Optional[MemoryRecorder] = None


def get_recorder() -> MemoryRecorder:
    """获取全局 MemoryRecorder 单例。"""
    global _recorder
    if _recorder is None:
        _recorder = MemoryRecorder()
    return _recorder
