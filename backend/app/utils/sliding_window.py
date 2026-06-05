"""
滑动窗口管理器：混合窗口 + 动态 K 值 + FIFO 驱逐。

窗口策略（架构设计 4.1 节）：
   当前位置 → │  Turn N    │  Turn N-1  │  Turn N-2  │  Turn N-3  │ ... │  Turn 1   │
             │  (完整)    │  (完整)    │  (完整)    │  (摘要)    │     │  (融合)   │
             │←— 全保真窗口 (K 动态) —→│←—— 压缩窗口 ———→│←— 知识融合 —→│
             │  Episodic              │  Semantic         │  Fusion       │

核心规则：
1. K 初始 = 3，全保真窗口总 Token > 60K 时缩至 K=2/K=1
2. 超出 K 的 Turn 标记为 semantic（待 Phase 3 摘要引擎压缩）
3. 用户 pin 的 Turn 永不被驱逐
4. 驱逐优先级：importance_score 低的先被压
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import time

from app.utils.token_counter import count_tokens


# ─── 常量 ───

DEFAULT_WINDOW_K = 3                # 默认全保真窗口大小
MAX_EPISODIC_TOKENS = 60_000        # 全保真窗口的 Token 上限
MIN_WINDOW_K = 1                    # 最小窗口（至少保留最近 1 个完整 Turn）
TURN_SUMMARY_ESTIMATE = 500         # 一个 Turn 摘要的预估 Token 数


# ─── 数据结构 ───

@dataclass
class MemoryLayer:
    """分层记忆的某一层。"""
    turns: List[Dict]               # 该层的 Turn 列表（完整记录或摘要 dict）
    layer_type: str                 # "episodic" | "semantic" | "fusion"
    total_tokens: int = 0           # 该层的估算 Token 数


@dataclass
class WindowConfig:
    """滑动窗口的运行时配置。"""
    k: int = DEFAULT_WINDOW_K               # 当前全保真窗口大小
    max_episodic_tokens: int = MAX_EPISODIC_TOKENS
    min_k: int = MIN_WINDOW_K
    total_budget: int = 128_000


@dataclass
class AssembledMemory:
    """
    装配完成的记忆视图——直接注入 AgentState 和各节点 Prompt。

    episodic_memory: 完整保留的最近 K 个 Turn
    semantic_memory: 超出窗口的 Turn 的摘要（Phase 3 启用真实摘要）
    memory_context:  可直接拼接到 Prompt 中的文本块
    """
    episodic_memory: List[Dict] = field(default_factory=list)
    semantic_memory: List[Dict] = field(default_factory=list)
    memory_context: str = ""
    window_k: int = DEFAULT_WINDOW_K
    total_tokens: int = 0
    pinned_turn_ids: List[str] = field(default_factory=list)


# ─── 滑动窗口管理器 ───

class SlidingWindowManager:
    """
    滑动窗口管理器。

    用法:
        swm = SlidingWindowManager(config=WindowConfig(k=3))

        # 装配分层记忆
        memory = swm.assemble(
            all_turns=turns,            # 所有历史 Turn
            current_query="...",        # 当前 query（用于相关度排序）
            pinned_ids=["turn_abc"],    # 用户引用的 Turn
        )

        # 注入到 AgentState
        state["episodic_memory"] = memory.episodic_memory
        state["semantic_memory"] = memory.semantic_memory

        # 注入到 Prompt
        prompt = prompt_template.format(memory_context=memory.memory_context)
    """

    def __init__(self, config: Optional[WindowConfig] = None):
        self.config = config or WindowConfig()

    # ─── 核心：记忆装配 ───

    def assemble(
        self,
        all_turns: List[Dict],
        current_query: str = "",
        pinned_ids: Optional[List[str]] = None,
    ) -> AssembledMemory:
        """
        装配分层记忆：决定哪些 Turn 在 Episodic、哪些在 Semantic。

        Args:
            all_turns: 所有历史 Turn 记录（按时间升序）
            current_query: 当前用户问题
            pinned_ids: 用户显式引用的 Turn ID 列表

        Returns:
            AssembledMemory — 装配好的分层记忆
        """
        pinned_ids = pinned_ids or []
        if not all_turns:
            return AssembledMemory()

        # 1. 分离 pinned turns
        pinned_turns = []
        unpinned_turns = []
        for turn in all_turns:
            tid = turn.get("turn_id", "")
            if tid in pinned_ids:
                pinned_turns.append(turn)
            else:
                unpinned_turns.append(turn)

        # 2. 计算动态 K
        k = self._calculate_dynamic_k(unpinned_turns, pinned_turns)

        # 3. 划分 Episodic / Semantic
        episodic, semantic = self._split_layers(
            unpinned_turns, k, pinned_turns
        )

        # 4. 计算 Token 用量
        ep_tokens = self._estimate_layer_tokens(episodic)
        sem_tokens = self._estimate_layer_tokens(semantic)

        # 5. 构建 memory_context 文本
        memory_context = self._build_memory_context(
            episodic, semantic, current_query
        )

        return AssembledMemory(
            episodic_memory=episodic,
            semantic_memory=semantic,
            memory_context=memory_context,
            window_k=k,
            total_tokens=ep_tokens + sem_tokens,
            pinned_turn_ids=pinned_ids,
        )

    # ─── 动态 K 计算 ───

    def _calculate_dynamic_k(
        self,
        unpinned_turns: List[Dict],
        pinned_turns: List[Dict],
    ) -> int:
        """
        动态计算全保真窗口大小 K。

        规则：
        - 从 K=3 开始
        - 如果最近 K 个 Turn 的总 Token > max_episodic_tokens (60K)，缩至 K-1
        - 最小不低于 MIN_WINDOW_K (1)
        - Pinned turns 不参与 Token 计算（它们始终保留）
        """
        k = self.config.k
        total_turns = len(unpinned_turns)

        if total_turns == 0:
            return 0

        # 从大 K 往小试：找到 ≤ max_episodic_tokens 的最大 K
        for candidate_k in range(k, self.config.min_k - 1, -1):
            recent = unpinned_turns[-candidate_k:] if candidate_k > 0 else []
            tokens = self._estimate_layer_tokens(recent)
            if tokens <= self.config.max_episodic_tokens:
                return min(candidate_k, total_turns)

        return self.config.min_k

    # ─── 层次划分 ───

    def _split_layers(
        self,
        unpinned_turns: List[Dict],
        k: int,
        pinned_turns: List[Dict],
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        将 Turn 划分为 Episodic 和 Semantic 两层。

        Episodic:
        - 最近 K 个 unpinned Turn（完整保留）
        - 所有 pinned Turn（不管时间远近，完整保留）

        Semantic:
        - 其余超出 K 窗口的 Turn（Phase 3 会被真实摘要替代）
        """
        total = len(unpinned_turns)
        k = min(k, total)

        # Episodic: 最近 K 个 + 所有 pinned
        recent_unpinned = unpinned_turns[-k:] if k > 0 else []
        episodic = recent_unpinned + pinned_turns

        # 按时间排序
        episodic.sort(key=lambda t: t.get("timestamp", 0))

        # Semantic: 超出 K 窗口的旧 Turn
        if total > k:
            semantic_unpinned = unpinned_turns[: total - k]
            # Phase 2: 暂时生成简单摘要（Phase 3 替换为 LLM 摘要）
            semantic = [
                self._make_simple_summary(turn)
                for turn in semantic_unpinned
            ]
        else:
            semantic = []

        return episodic, semantic

    # ─── 简化摘要（Phase 2 占位，Phase 3 替换为 LLM 摘要）───

    def _make_simple_summary(self, turn: Dict) -> Dict:
        """
        为 Phase 2 生成简化摘要。
        Phase 3 将替换为 LLM 驱动的 TurnSummarizer。
        """
        query = turn.get("query", "")
        report = turn.get("final_report", "")
        plan = turn.get("plan", [])
        critique = turn.get("critique", "")
        review_status = turn.get("review_status", "")

        # 提取报告的前 200 字作为摘要
        report_summary = report[:200] + "..." if len(report) > 200 else report

        # 提取关键事实（简单规则：取报告中以数字/百分比/专有名词开头的句子）
        key_facts = []
        for line in report.split("\n"):
            line = line.strip()
            if len(line) > 20 and len(key_facts) < 3:
                key_facts.append(line[:150])

        return {
            "turn_id": turn.get("turn_id", ""),
            "turn_number": turn.get("turn_number", 0),
            "query_gist": query[:100],
            "key_facts": key_facts,
            "conclusions": [report_summary] if report_summary else [],
            "methodology": f"搜索策略: {', '.join(plan[:3])}" if plan else "",
            "unresolved": critique if review_status == "FAIL" else "",
            "topic_tags": self._extract_topic_tags(query),
            "importance_score": 0.5,
            "timestamp": turn.get("timestamp", 0),
        }

    def _extract_topic_tags(self, query: str) -> List[str]:
        """
        简单关键词提取（Phase 3 替换为 LLM 标注）。
        从 query 中取前 3 个有意义的词作为标签。
        """
        # 简单分词
        import re
        words = re.findall(r'[一-鿿\w]+', query)
        # 过滤短词和停用词
        stop_words = {
            "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一",
            "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
            "没有", "看", "好", "自己", "这", "他", "她", "它",
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "can", "shall",
        }
        tags = [w for w in words if len(w) > 1 and w.lower() not in stop_words]
        return tags[:3]

    # ─── 记忆上下文构建 ───

    def _build_memory_context(
        self,
        episodic: List[Dict],
        semantic: List[Dict],
        current_query: str = "",
    ) -> str:
        """
        构建可注入 Prompt 的记忆上下文文本。

        输出格式:
            ## 历史研究脉络

            ### 最近研究（完整记录）
            Turn N: [query] → [核心结论]
            Turn N-1: ...

            ### 早期研究（摘要）
            Turn 1: [query_gist] → [核心发现]
            ...

        注意：这段文本会被拼接到 Writer/Planner 的 Prompt 中。
        控制在 ~2000 tokens 以内，避免挤压 Working Memory 空间。
        """
        parts = []

        # Episodic 层
        if episodic:
            parts.append("## 历史研究脉络")
            parts.append("### 最近研究记录\n")
            for turn in reversed(episodic):
                q = turn.get("query", "")
                r = turn.get("final_report", "")
                # 只取核心结论（报告最后 300 字通常包含结论）
                conclusion = r[-300:] if len(r) > 300 else r
                critique = turn.get("critique", "")
                parts.append(f"**[Turn {turn.get('turn_number', '?')}]** 问题: {q[:200]}")
                if conclusion:
                    parts.append(f"  结论: {conclusion[:300]}")
                if critique:
                    parts.append(f"  审查意见: {critique[:200]}")
                parts.append("")

        # Semantic 层
        if semantic:
            parts.append("### 早期研究摘要\n")
            for turn in semantic:
                parts.append(
                    f"- **Turn {turn.get('turn_number', '?')}**: "
                    f"{turn.get('query_gist', '')[:150]}"
                )
                facts = turn.get("key_facts", [])
                if facts:
                    parts.append(f"  关键发现: {'; '.join(facts[:2])}")
                parts.append("")

        # Token 预算提示
        parts.append(
            f"---\n"
            f"*以上是历史研究脉络。共 {len(episodic)} 个近期完整记录 + "
            f"{len(semantic)} 个早期摘要。请基于这些积累，结合当前检索结果，"
            f"回答用户问题。如果历史研究中有相关内容，请引用和延续之前的分析。*"
        )

        return "\n".join(parts)

    # ─── 驱逐决策 ───

    def select_eviction_candidates(
        self,
        semantic_turns: List[Dict],
        tokens_to_free: int,
    ) -> List[str]:
        """
        选择需要从语义记忆中驱逐的 Turn（最低 importance_score 优先）。

        Args:
            semantic_turns: 语义记忆中的 Turn 列表
            tokens_to_free: 需要释放的 Token 数

        Returns:
            需要驱逐的 turn_id 列表
        """
        if not semantic_turns:
            return []

        # 按 importance_score 升序排列
        sorted_turns = sorted(
            semantic_turns,
            key=lambda t: t.get("importance_score", 0.5),
        )

        freed = 0
        candidates = []
        for turn in sorted_turns:
            if freed >= tokens_to_free:
                break
            candidates.append(turn.get("turn_id", ""))
            freed += TURN_SUMMARY_ESTIMATE

        return candidates

    # ─── 工具方法 ───

    def _estimate_layer_tokens(self, turns: List[Dict]) -> int:
        """估算一层记忆的 Token 数。"""
        total = 0
        for turn in turns:
            # 粗略估算：序列化后除以 4
            text = str(turn.get("query", ""))
            text += str(turn.get("final_report", ""))[:500]  # 只算前 500 字
            text += str(turn.get("plan", ""))
            total += count_tokens(text)
        return total

    def get_window_stats(self, all_turns: List[Dict]) -> Dict:
        """获取窗口统计信息（给前端展示）。"""
        k = self._calculate_dynamic_k(all_turns, [])
        total = len(all_turns)

        return {
            "total_turns": total,
            "window_k": k,
            "episodic_count": min(k, total),
            "semantic_count": max(0, total - k),
            "max_episodic_tokens": self.config.max_episodic_tokens,
            "total_budget": self.config.total_budget,
        }
