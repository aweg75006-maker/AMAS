"""
压缩调度器：异步摘要 + 索引 + 融合编排。

Phase 3 核心组件——在每次 Turn 结束后异步运行：

1. 检测超出 Episodic 窗口的 Turn
2. 对未摘要的 Turn 调用 TurnSummarizer
3. 将生成的 TurnSummary 索引到 CrossTurnRetriever
4. 更新 Redis 中的 semantic_memory
5. 当 Semantic Memory 过大时触发 FusionSummarizer

所有操作均为 fire-and-forget，不阻塞用户响应。

用法:
    scheduler = CompressionScheduler(redis_client)
    # 在 finalize() 之后立即调用
    asyncio.create_task(scheduler.schedule(session_id))
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any

from app.utils.summarizer import (
    TurnSummarizer, FusionSummarizer, TurnSummary,
)
from app.utils.cross_turn_retriever import CrossTurnRetriever

logger = logging.getLogger("iris.compression")


class CompressionScheduler:
    """
    压缩调度器：管理 Turn 摘要的完整生命周期。

    触发条件：
    - Turn 数 > K（滑动窗口配置）
    - Semantic Memory 中的摘要数 > 10（触发融合）
    """

    # 触发融合的 Semantic Memory 大小阈值
    FUSION_THRESHOLD = 10

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._summarizer = TurnSummarizer(model_type="fast")
        self._fusion = FusionSummarizer(model_type="fast")
        self._retriever = CrossTurnRetriever()
        self._pending_tasks: set = set()

    # ─── 主入口 ───

    async def schedule(
        self,
        session_id: str,
        all_turns: List[Dict[str, Any]],
        window_k: int,
    ) -> Dict[str, Any]:
        """
        调度压缩任务（异步，fire-and-forget）。

        Args:
            session_id: 会话 ID
            all_turns: 所有历史 Turn 数据（按时间升序）
            window_k: 当前全保真窗口大小

        Returns:
            调度结果摘要
        """
        result = {
            "summarized": 0,
            "indexed": 0,
            "fusion_triggered": False,
            "tokens_saved": 0,
            "errors": [],
        }

        if not all_turns or len(all_turns) <= window_k:
            return result

        # 1. 找出需要压缩的 Turn（超出窗口的部分）
        turns_to_compress = all_turns[: len(all_turns) - window_k]

        # 2. 过滤已压缩的（检查是否已有 TurnSummary）
        uncompressed = []
        for turn in turns_to_compress:
            # 检查是否已有摘要（从 Redis 或本地缓存）
            if not self._is_already_summarized(session_id, turn.get("turn_id", "")):
                uncompressed.append(turn)

        if not uncompressed:
            return result

        # 3. 逐个压缩（同步执行以保证质量，但在独立 task 中）
        new_summaries = []
        for turn in uncompressed:
            try:
                summary_result = self._summarizer.summarize(turn)
                if summary_result.success:
                    new_summaries.append(summary_result.summary)
                    result["summarized"] += 1
                    result["tokens_saved"] += summary_result.tokens_saved
                else:
                    result["errors"].append(
                        f"Turn {turn.get('turn_id')}: {summary_result.error_message}"
                    )
            except Exception as e:
                result["errors"].append(f"Turn {turn.get('turn_id')}: {str(e)}")
                logger.warning(f"摘要生成失败: {e}")

        # 4. 索引到 CrossTurnRetriever
        for summary in new_summaries:
            try:
                if self._retriever.index(summary):
                    result["indexed"] += 1
            except Exception as e:
                logger.warning(f"索引失败: {e}")

        # 5. 持久化摘要到 Redis
        if self._redis and new_summaries:
            for summary in new_summaries:
                try:
                    await self._redis.hset(
                        f"session:{session_id}:turn:{summary.turn_id}",
                        {"summary": str(summary.to_dict())},
                    )
                except Exception:
                    pass

        # 6. 检查是否需要融合
        semantic_count = (
            len(all_turns) - window_k + result["summarized"]
        )
        if semantic_count > self.FUSION_THRESHOLD:
            result["fusion_triggered"] = True
            try:
                fusion_text = await self._trigger_fusion(session_id)
                if self._redis:
                    await self._redis.hset(
                        f"session:{session_id}:meta",
                        {"knowledge_fusion": fusion_text},
                    )
            except Exception as e:
                result["errors"].append(f"Fusion failed: {str(e)}")

        logger.info(
            f"压缩完成 | session={session_id} | "
            f"summarized={result['summarized']} | "
            f"indexed={result['indexed']} | "
            f"saved={result['tokens_saved']} tokens | "
            f"fusion={result['fusion_triggered']}"
        )

        return result

    # ─── 融合 ───

    async def _trigger_fusion(self, session_id: str) -> str:
        """
        触发知识融合：将所有 Semantic Memory 中的摘要融合为一个文档。

        Returns:
            融合后的知识状态文本
        """
        # 收集所有索引中的摘要
        all_summaries = self._retriever._summaries

        if len(all_summaries) < self.FUSION_THRESHOLD:
            return ""

        summaries_list = list(all_summaries.values())
        # 按重要度排序，优先保留高分摘要
        summaries_list.sort(key=lambda s: s.importance_score, reverse=True)

        # 只融合最重要的 15 个（避免 Prompt 过长）
        top_summaries = summaries_list[:15]

        return self._fusion.fuse(top_summaries)

    # ─── 工具方法 ───

    def _is_already_summarized(
        self, session_id: str, turn_id: str
    ) -> bool:
        """检查 Turn 是否已有摘要（在 CrossTurnRetriever 的缓存中）。"""
        return turn_id in self._retriever._summaries

    def get_retriever(self) -> CrossTurnRetriever:
        """获取 CrossTurnRetriever 实例（供 ContextAssembler 使用）。"""
        return self._retriever


# ─── 便捷函数：在 background task 中运行 ───

def schedule_compression(
    session_id: str,
    all_turns: List[Dict[str, Any]],
    window_k: int,
    redis_client=None,
) -> asyncio.Task:
    """
    创建后台压缩任务（fire-and-forget）。

    用法:
        task = schedule_compression(session_id, all_turns, window_k, redis)
        # 不 await task，让它后台运行
    """
    scheduler = CompressionScheduler(redis_client)
    return asyncio.create_task(
        scheduler.schedule(session_id, all_turns, window_k)
    )


# 全局单例（供 ContextAssembler 复用）
_global_scheduler: Optional[CompressionScheduler] = None


def get_scheduler(redis_client=None) -> CompressionScheduler:
    """获取全局 CompressionScheduler 单例。"""
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = CompressionScheduler(redis_client)
    elif redis_client and _global_scheduler._redis is None:
        _global_scheduler._redis = redis_client
    return _global_scheduler
