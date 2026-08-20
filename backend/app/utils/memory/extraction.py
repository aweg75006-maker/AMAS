"""结构化知识抽取：从对话记忆里提炼三元组写入图谱。

思路：
- 记忆的"温层/冷层"承载完整事实，但都是非结构化文本；图谱记忆负责
  把其中值得长期复用的"稳定知识"（用户偏好、人际关系、明确态度）提炼为
  可查询的 (实体)-[关系]->(实体) 三元组；
- 抽取用 LLM 完成（规则式难以覆盖开放关系），但带"准入标准"严格过滤：
  只抽稳定知识，不抽问答/闲聊/一次性任务，避免图谱被噪音污染。

设计：
- consolidate() 为异步后台任务（fire-and-forget），不阻塞主流程；
- LLM 抽取失败 / JSON 解析失败均静默降级，只记日志；
- 抽取成功后把来源记忆标记为 protected（受保护，永不归档删除），
  保证图谱知识的"事实底座"不丢失。
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.utils.memory.graph_store import GraphMemoryStore
from app.utils.memory.cold_store import ColdMemoryStore

logger = logging.getLogger("iris.memory")

# 同一会话两次抽取的最短间隔（秒）：避免每回合都触发 LLM，控制成本
CONSOLIDATE_COOLDOWN_SECONDS = 600

# 抽取准入标准（注入 LLM 的 prompt）
EXTRACT_PROMPT = """你是记忆整理助手。分析下面的对话记录，判断是否有值得存入知识图谱的结构化信息。

准入标准（满足任一即抽取）：
1. 用户偏好 / 好恶 / 习惯 / 禁忌（如"用户不喜欢弹窗""习惯晚上跑步"）
2. 人际关系 / 归属 / 身份（如"我是前端组长""张三是李四的上级"）
3. 对事物的明确态度或评价（如"用户觉得这个方案太复杂了"）

不抽取（输出 []）：
- 普通问答、查询、搜索
- 闲聊、问候、敷衍
- 一次性任务（如"打开网页""创建文件"）
- 实体模糊或关系无法确定的陈述

只输出 JSON，格式：[{"subject": "实体", "relation": "关系", "object": "对象"}]
无匹配时输出：[]

对话记录：
{conversation}
"""


class KnowledgeExtractor:
    """图谱知识抽取器：LLM 抽取 + 写库 + 来源保护。"""

    def __init__(
        self,
        graph_store: Optional[GraphMemoryStore] = None,
        cold_store: Optional[ColdMemoryStore] = None,
    ):
        self.graph = graph_store or GraphMemoryStore()
        self.cold = cold_store or ColdMemoryStore()
        # 冷却表：thread_id → 上次抽取时间戳（进程内存态，重启即清零，可接受）
        self._last_consolidate: Dict[str, float] = {}

    # ─── 主流程 ───

    async def consolidate_thread(self, thread_id: str) -> Dict[str, Any]:
        """对某个会话的记忆做一次结构化抽取。

        Args:
            thread_id: 会话 id（thread）

        Returns:
            {"consolidated": 抽取成功条数, "triples": [...], "skipped": bool}
        """
        result: Dict[str, Any] = {"consolidated": 0, "triples": [], "skipped": False}

        # 0. 冷却检查：同一会话短时间内不重复抽取
        now = time.time()
        if now - self._last_consolidate.get(thread_id, 0) < CONSOLIDATE_COOLDOWN_SECONDS:
            result["skipped"] = True
            return result
        self._last_consolidate[thread_id] = now

        # 1. 取最近记忆作为抽取素材
        recent = self.cold.search(thread_id=thread_id, limit=10)
        if not recent:
            result["skipped"] = True
            return result

        # 2. 回合数门槛：太少不值得抽
        from app.core.config import settings
        if len(recent) < settings.memory_consolidate_min_turns:
            result["skipped"] = True
            return result

        # 3. 拼对话文本（query → 用户话；事实/结论 → 系统话）
        lines: List[str] = []
        for r in recent:
            content = r.get("content") or {}
            query = str(content.get("query_gist", ""))[:200]
            facts = content.get("key_facts", []) or []
            concl = content.get("conclusions", []) or []
            if query:
                lines.append(f"用户: {query}")
            for f in facts[:3]:
                lines.append(f"系统: {str(f)[:200]}")
            for c in concl[:2]:
                lines.append(f"系统: {str(c)[:200]}")
        if not lines:
            result["skipped"] = True
            return result
        conversation = "\n".join(lines)

        # 4. LLM 抽取
        triples = await self._extract_triples(conversation)
        if not triples:
            return result

        # 5. 写图谱
        for t in triples:
            subject = str(t.get("subject", "")).strip()
            relation = str(t.get("relation", "")).strip()
            obj = str(t.get("object", "")).strip()
            if not (subject and relation and obj):
                continue
            try:
                self.graph.add_relationship(
                    subject=subject, relation=relation, obj=obj,
                    thread_id=thread_id,
                )
                result["triples"].append(t)
                result["consolidated"] += 1
            except Exception as e:
                logger.warning("图谱写入失败 %s -%s-> %s: %s", subject, relation, obj, e)

        # 6. 抽取成功的素材记忆打保护标（作为图谱的事实底座，永不归档删除）
        if result["consolidated"] > 0:
            for r in recent:
                try:
                    self.cold.mark_protected(r["id"])
                except Exception:
                    pass

        return result

    # ─── LLM 调用 ───

    async def _extract_triples(self, conversation: str) -> List[Dict[str, Any]]:
        """调用 LLM 抽取三元组，解析失败返回空列表。"""
        try:
            from langchain_core.messages import HumanMessage
            from app.utils.llm import get_llm

            llm = get_llm("fast")
            prompt = EXTRACT_PROMPT.replace("{conversation}", conversation)
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            text = resp.content if hasattr(resp, "content") else str(resp)
            # 提取首个 JSON 数组（模型可能带解释文字）
            match = re.search(r"\[.*\]", str(text), re.DOTALL)
            if not match:
                return []
            triples = json.loads(match.group())
            if not isinstance(triples, list):
                return []
            return [t for t in triples if isinstance(t, dict)]
        except Exception as e:
            logger.warning("三元组抽取失败: %s", e)
            return []


# 全局单例
_extractor: Optional[KnowledgeExtractor] = None


def get_extractor() -> KnowledgeExtractor:
    """获取全局 KnowledgeExtractor 单例。"""
    global _extractor
    if _extractor is None:
        _extractor = KnowledgeExtractor()
    return _extractor
