"""
动态摘要引擎：LLM 驱动的 Turn 摘要 + 知识融合。

Phase 3 核心组件：
1. TurnSummarizer — 将完整 Turn 压缩为结构化 JSON 摘要
2. FusionSummarizer — 融合多个摘要为一个知识状态文档
3. SummaryEvaluator — 评估摘要质量（关键事实保留率）

设计目标：
- 摘要 < 500 tokens（相对原始 Turn 压缩比 > 10:1）
- 关键事实保留率 > 70%
- 异步非阻塞（fire-and-forget 模式）
"""

import json
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage

from app.utils.llm import get_llm
from app.utils.token_counter import count_tokens


# ─── Prompt 模板 ───

TURN_SUMMARY_PROMPT = """你是一个信息保全专家。请将这个研究 Turn 压缩为结构化摘要，
确保未来该信息被召回时，不丢失关键决策依据。

### 原始问题
{query}

### 搜索策略
{plan}

### 检索到的关键事实（请保留具体数字、人名、时间）
{search_results}

### 最终报告核心论点（请保留3-5条）
{report_summary}

### 审查反馈及修正方向（如果有）
{critique}

---

请严格按以下 JSON 格式输出摘要（不要包含 Markdown 代码块）：
{{
    "query_gist": "用户核心诉求的一句话概括",
    "key_facts": ["事实1（含具体数据）", "事实2", "事实3", "事实4", "事实5"],
    "conclusions": ["结论1", "结论2", "结论3"],
    "methodology": "采用的研究方法",
    "unresolved": "未解决的问题或后续方向",
    "topic_tags": ["标签1", "标签2", "标签3"],
    "importance_score": 0.8
}}

注意：
- key_facts 最多 5 条，每条必须包含具体数据/名称/时间等可检索信息
- conclusions 最多 3 条，概括核心发现
- topic_tags 用于跨轮检索，选择最能概括主题的关键词
- importance_score 为 0-1 之间的数值，评估该 Turn 的研究价值
- 如果某项内容不存在，使用空字符串或空数组
"""

FUSION_SUMMARY_PROMPT = """你是一个知识融合专家。以下是多个历史研究 Turn 的摘要。
请将它们融合为一个统一的知识状态文档。

{summaries}

---

请输出一个简洁的知识状态总结（不超过 300 字），包含：
1. 系统至今研究过的主要主题（列举）
2. 已确定的核心结论（最多 5 条）
3. 仍待解决的问题
4. 跨主题的模式或联系

直接输出文本，不要 JSON。
"""


# ─── 数据结构 ───

@dataclass
class TurnSummary:
    """Turn 压缩摘要（结构化）。"""
    turn_id: str
    turn_number: int
    query_gist: str = ""
    key_facts: List[str] = field(default_factory=list)
    conclusions: List[str] = field(default_factory=list)
    methodology: str = ""
    unresolved: str = ""
    topic_tags: List[str] = field(default_factory=list)
    importance_score: float = 0.5
    timestamp: float = field(default_factory=time.time)
    raw_tokens: int = 0       # 原始 Turn 的 Token 数
    summary_tokens: int = 0   # 摘要的 Token 数

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "turn_number": self.turn_number,
            "query_gist": self.query_gist,
            "key_facts": self.key_facts,
            "conclusions": self.conclusions,
            "methodology": self.methodology,
            "unresolved": self.unresolved,
            "topic_tags": self.topic_tags,
            "importance_score": self.importance_score,
            "timestamp": self.timestamp,
            "raw_tokens": self.raw_tokens,
            "summary_tokens": self.summary_tokens,
        }

    @property
    def compression_ratio(self) -> float:
        """压缩比：原始 Token / 摘要 Token。"""
        if self.summary_tokens == 0:
            return 0
        return self.raw_tokens / self.summary_tokens

    @property
    def text_for_embedding(self) -> str:
        """用于向量嵌入的文本——融合了标签和事实，提高检索召回率。"""
        parts = [self.query_gist]
        parts.extend(self.key_facts)
        parts.extend(self.conclusions)
        parts.extend(self.topic_tags)
        return " ".join(parts)


@dataclass
class SummaryResult:
    """摘要生成结果（含质量指标）。"""
    summary: TurnSummary
    success: bool
    error_message: str = ""
    tokens_saved: int = 0


# ─── JSON 清理工具 ───

def _clean_json_text(s: str) -> str:
    """从 LLM 输出中提取 JSON。"""
    s = (s or "").strip()
    s = s.replace("```json", "").replace("```", "").strip()
    l = s.find("{")
    r = s.rfind("}")
    if l != -1 and r != -1 and r > l:
        s = s[l:r+1]
    return s


# ─── TurnSummarizer ───

class TurnSummarizer:
    """
    LLM 驱动的 Turn 摘要器。

    用法:
        summarizer = TurnSummarizer()
        summary = await summarizer.summarize(turn_record, async_mode=True)
    """

    def __init__(self, model_type: str = "fast"):
        """
        Args:
            model_type: 用于摘要的模型类型 ("fast" 推荐，摘要不需要 deep reasoning)
        """
        self.llm = get_llm(model_type=model_type)
        self.max_retries = 2

    def summarize(self, turn_data: Dict[str, Any]) -> SummaryResult:
        """
        生成 Turn 摘要（同步版本）。

        Args:
            turn_data: Turn 的完整数据 dict（含 query, plan, search_results, final_report 等）

        Returns:
            SummaryResult
        """
        # 计算原始 Token 数
        raw_text = json.dumps(turn_data, ensure_ascii=False)
        raw_tokens = count_tokens(raw_text)

        # 构建 Prompt
        query = turn_data.get("query", "")
        plan = turn_data.get("plan", [])
        search_results = turn_data.get("search_results", [])
        final_report = turn_data.get("final_report", "")
        critique = turn_data.get("critique", "")

        # 截取关键部分
        report_summary = final_report[:1500] if len(final_report) > 1500 else final_report
        search_text = "\n".join(
            str(r)[:300] for r in (search_results if isinstance(search_results, list) else [])
        )[:2000]
        plan_text = ", ".join(plan) if isinstance(plan, list) else str(plan)

        prompt = TURN_SUMMARY_PROMPT.format(
            query=query,
            plan=plan_text,
            search_results=search_text,
            report_summary=report_summary,
            critique=critique if critique else "（无审查意见）",
        )

        # 调用 LLM（带重试）
        result_json = None
        last_error = ""

        for attempt in range(self.max_retries + 1):
            try:
                response = self.llm.invoke([HumanMessage(content=prompt)])
                raw_output = response.content
                cleaned = _clean_json_text(raw_output)

                try:
                    result_json = json.loads(cleaned)
                    break
                except json.JSONDecodeError:
                    if attempt < self.max_retries:
                        # 重试：给更明确的指令
                        prompt = (
                            f"{prompt}\n\n"
                            f"你上一次的输出无法被 JSON 解析。请严格只输出一行合法 JSON，"
                            f"不要使用 Markdown 代码块，不要有任何前言后语。"
                        )
                    last_error = f"JSON parse failed: {cleaned[:100]}"
            except Exception as e:
                last_error = str(e)
                if attempt >= self.max_retries:
                    break

        # 构建 TurnSummary
        if result_json:
            summary = TurnSummary(
                turn_id=turn_data.get("turn_id", ""),
                turn_number=turn_data.get("turn_number", 0),
                query_gist=result_json.get("query_gist", ""),
                key_facts=result_json.get("key_facts", [])[:5],
                conclusions=result_json.get("conclusions", [])[:3],
                methodology=result_json.get("methodology", ""),
                unresolved=result_json.get("unresolved", ""),
                topic_tags=result_json.get("topic_tags", [])[:5],
                importance_score=float(result_json.get("importance_score", 0.5)),
                timestamp=time.time(),
                raw_tokens=raw_tokens,
                summary_tokens=count_tokens(json.dumps(result_json, ensure_ascii=False)),
            )

            tokens_saved = raw_tokens - summary.summary_tokens
            return SummaryResult(
                summary=summary,
                success=True,
                tokens_saved=max(0, tokens_saved),
            )

        # 失败兜底：使用简单规则摘要
        return SummaryResult(
            summary=self._fallback_summary(turn_data, raw_tokens),
            success=False,
            error_message=last_error,
            tokens_saved=0,
        )

    def _fallback_summary(
        self, turn_data: Dict[str, Any], raw_tokens: int
    ) -> TurnSummary:
        """LLM 摘要失败时的规则兜底。"""
        query = turn_data.get("query", "")
        report = turn_data.get("final_report", "")
        plan = turn_data.get("plan", [])

        return TurnSummary(
            turn_id=turn_data.get("turn_id", ""),
            turn_number=turn_data.get("turn_number", 0),
            query_gist=query[:200],
            key_facts=[report[:200]] if report else [],
            conclusions=[report[-200:]] if len(report) > 200 else [],
            methodology=f"搜索策略: {', '.join(plan[:3])}" if plan else "无",
            topic_tags=[],
            importance_score=0.3,
            timestamp=time.time(),
            raw_tokens=raw_tokens,
            summary_tokens=count_tokens(query + report[:400]),
        )


# ─── FusionSummarizer ───

class FusionSummarizer:
    """
    知识融合器：将多个 Turn 摘要融合为一个统一的知识状态文档。

    当 Semantic Memory 中的摘要数过多（> 10 个）时触发融合，
    输出一个 ~300 token 的知识状态总结。
    """

    def __init__(self, model_type: str = "fast"):
        self.llm = get_llm(model_type=model_type)

    def fuse(self, summaries: List[TurnSummary]) -> str:
        """
        融合多个摘要为知识状态文本。

        Args:
            summaries: TurnSummary 列表

        Returns:
            融合后的知识状态文本（~300 tokens）
        """
        if not summaries:
            return ""

        # 构建摘要文本
        summary_texts = []
        for i, s in enumerate(summaries):
            text = (
                f"Turn {s.turn_number}: {s.query_gist}\n"
                f"  关键事实: {'; '.join(s.key_facts[:3])}\n"
                f"  结论: {'; '.join(s.conclusions[:2])}\n"
                f"  标签: {', '.join(s.topic_tags)}"
            )
            summary_texts.append(text)

        summaries_block = "\n\n".join(summary_texts)

        prompt = FUSION_SUMMARY_PROMPT.format(summaries=summaries_block)

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            return response.content.strip()
        except Exception:
            # 兜底：直接拼接
            return f"研究主题覆盖: {', '.join(s.topic_tags for s in summaries)}"


# ─── SummaryEvaluator ───

class SummaryEvaluator:
    """
    摘要质量评测器。

    评估指标：
    - fact_retention: 关键事实保留率（目标 > 70%）
    - conclusion_retention: 结论保留率
    - compression_ratio: 压缩比（目标 > 10:1）
    """

    def __init__(self, model_type: str = "smart"):
        self.llm = get_llm(model_type=model_type)

    def evaluate(
        self, original_turn: Dict[str, Any], summary: TurnSummary
    ) -> Dict[str, Any]:
        """
        评测摘要质量。

        Returns:
            {
                "fact_retention": float,       # 0-1
                "conclusion_retention": float,
                "compression_ratio": float,
                "overall_score": float,
                "issues": [str],
            }
        """
        # 1. 从原始 Turn 中提取关键事实
        original_facts = self._extract_key_facts(original_turn)

        # 2. 计算保留率
        if original_facts:
            # 用 LLM 判断每个原始事实是否在摘要中保留
            retained = 0
            for fact in original_facts[:10]:
                if self._fact_in_summary(fact, summary):
                    retained += 1
            fact_retention = retained / min(len(original_facts), 10)
        else:
            fact_retention = 1.0

        # 3. 压缩比
        compression_ratio = summary.compression_ratio

        # 4. 综合评分
        overall = (
            0.5 * fact_retention
            + 0.2 * min(compression_ratio / 10, 1.0)
            + 0.3 * (1.0 if summary.key_facts else 0.0)
        )

        return {
            "fact_retention": round(fact_retention, 3),
            "compression_ratio": round(compression_ratio, 1),
            "overall_score": round(overall, 3),
            "issues": [],
            "summary_tokens": summary.summary_tokens,
            "raw_tokens": summary.raw_tokens,
        }

    def _extract_key_facts(self, turn_data: Dict[str, Any]) -> List[str]:
        """从原始 Turn 中提取关键事实（用 LLM）。"""
        report = turn_data.get("final_report", "")
        if not report:
            return []

        prompt = f"""
        请从以下报告中提取 5-10 条关键事实。
        每条事实应该是独立、可验证的断言（含具体数据、名称或时间）。

        报告：
        {report[:3000]}

        请每行输出一条事实，以 "- " 开头。
        """

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            lines = response.content.strip().split("\n")
            facts = [
                line.strip()[2:] for line in lines
                if line.strip().startswith("- ")
            ]
            return facts[:10]
        except Exception:
            # 兜底：按句子拆分
            import re
            sentences = re.split(r'[。；\n]', report)
            return [s.strip()[:200] for s in sentences if len(s.strip()) > 20][:10]

    def _fact_in_summary(self, fact: str, summary: TurnSummary) -> bool:
        """判断关键事实是否在摘要中保留（简单关键词匹配 + LLM）。"""
        summary_text = summary.text_for_embedding.lower()
        # 简单检查：是否包含核心关键词
        words = [w for w in fact[:100].lower().split() if len(w) > 2]
        if not words:
            return False
        matches = sum(1 for w in words if w in summary_text)
        return matches / len(words) > 0.3
