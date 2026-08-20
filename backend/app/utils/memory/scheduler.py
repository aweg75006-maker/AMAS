"""记忆维护调度：周期执行冷热迁移与遗忘。

职责：
- run_archive()：把超过 warm_days 未访问的热记忆统一归档到冷层；
- run_forget()：把超过 cold_retention_days 的冷归档永久删除（受保护除外）；
- run_consolidate_all()：对积累足够的会话做一次结构化抽取（图谱）。

设计：
- 通过 asyncio 后台任务周期执行（间隔由配置 memory_maintenance_interval_seconds 控制）；
- 每个周期任务独立 try/except，单步失败不影响其他步骤；
- 全部为"尽力而为"维护：可随时跳过，不阻塞主服务。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.utils.memory.lifecycle import MemoryLifecycleManager
from app.utils.memory.cold_store import ColdMemoryStore
from app.utils.memory.extraction import KnowledgeExtractor

logger = logging.getLogger("iris.memory")


class MemoryMaintenanceScheduler:
    """周期记忆维护调度器。"""

    def __init__(self, cold_store: Optional[ColdMemoryStore] = None):
        self.lifecycle = MemoryLifecycleManager(cold_store=cold_store)
        self.cold = self.lifecycle.cold
        self._extractor: Optional[KnowledgeExtractor] = None
        self._task: Optional[asyncio.Task] = None

    def _get_extractor(self) -> KnowledgeExtractor:
        """懒加载抽取器。"""
        if self._extractor is None:
            self._extractor = KnowledgeExtractor(cold_store=self.cold)
        return self._extractor

    # ─── 单次维护 ───

    async def run_once(self) -> Dict[str, Any]:
        """执行一轮完整维护：归档 → 遗忘 → 图谱抽取。"""
        result: Dict[str, Any] = {"archived": [], "forgotten": [], "consolidated": []}

        # 1. 冷热迁移：热 → 冷
        try:
            result["archived"] = self.lifecycle.scheduled_archive()
        except Exception as e:
            logger.warning("归档维护失败: %s", e)

        # 2. 遗忘：冷 → 删除
        try:
            result["forgotten"] = self.lifecycle.scheduled_forget()
        except Exception as e:
            logger.warning("遗忘维护失败: %s", e)

        # 3. 图谱抽取：对活跃会话做结构化知识提炼
        try:
            for thread_id in self._active_thread_ids():
                r = await self._get_extractor().consolidate_thread(thread_id)
                if r.get("consolidated", 0) > 0:
                    result["consolidated"].append(thread_id)
        except Exception as e:
            logger.warning("图谱抽取维护失败: %s", e)

        if result["archived"] or result["forgotten"] or result["consolidated"]:
            logger.info(
                "记忆维护完成 | archived=%d forgotten=%d consolidated=%d",
                len(result["archived"]), len(result["forgotten"]),
                len(result["consolidated"]),
            )
        return result

    def _active_thread_ids(self) -> List[str]:
        """取最近有记忆写入的会话 id（供图谱抽取遍历）。"""
        try:
            rows = self.cold.search(limit=20)
            seen: List[str] = []
            for r in rows:
                tid = r.get("thread_id")
                if tid and tid not in seen:
                    seen.append(tid)
            return seen
        except Exception:
            return []

    # ─── 周期循环 ───

    async def _loop(self, interval: float) -> None:
        """周期执行维护（启动后先等一个周期，避免冷启动抢资源）。"""
        await asyncio.sleep(interval)
        while True:
            try:
                await self.run_once()
            except Exception as e:
                logger.warning("记忆维护循环异常: %s", e)
            await asyncio.sleep(interval)

    def start(self, interval: Optional[float] = None) -> asyncio.Task:
        """启动后台维护循环（幂等，已启动则复用）。"""
        if self._task and not self._task.done():
            return self._task
        interval = interval or self._interval_seconds()
        self._task = asyncio.create_task(self._loop(interval))
        return self._task

    def stop(self) -> None:
        """停止后台维护循环。"""
        if self._task and not self._task.done():
            self._task.cancel()

    @staticmethod
    def _interval_seconds() -> float:
        from app.core.config import settings
        return settings.memory_maintenance_interval_seconds


# 全局单例
_scheduler: Optional[MemoryMaintenanceScheduler] = None


def get_maintenance_scheduler() -> MemoryMaintenanceScheduler:
    """获取全局维护调度器单例。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = MemoryMaintenanceScheduler()
    return _scheduler
