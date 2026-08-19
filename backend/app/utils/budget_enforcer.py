"""
预算执行器：每个 LLM 调用前的预检 + 溢出策略执行 + 事后记录。

Phase 4 核心组件——将策略矩阵（BudgetLedger.DEFAULT_NODE_POLICIES）真正落地到每一次 LLM 调用。

生命周期：
    enforcer = BudgetEnforcer(ledger)

    # 调用前
    prompt, ok = enforcer.pre_check("writer", prompt, state)
    # 如果 !ok，prompt 已被溢出策略处理过

    # 调用后
    enforcer.record("writer", estimated_input, actual_input, actual_output)

每个节点只需 2 行代码即可接入预算管控。
"""

from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass
import logging

from app.utils.budget_ledger import (
    BudgetLedger, NodeBudgetPolicy, OverflowPolicy, BudgetSnapshot,
    DEFAULT_NODE_POLICIES,
)
from app.utils.token_counter import count_tokens
from app.utils.text_sanitize import strip_surrogates

logger = logging.getLogger("iris.budget")


# ─── 溢出策略实现 ───

def _truncate_oldest(text: str, max_tokens: int, model: str = "fast") -> str:
    """截断策略：保留最后的内容（最新最重要）。"""
    if not text:
        return text
    # 逐字符截断，直到满足预算
    while count_tokens(text, model) > max_tokens and len(text) > 100:
        # 删除前面 20% 的内容
        cut_point = max(1, len(text) // 5)
        text = text[cut_point:]
    return text


def _summarize_critique(text: str, max_tokens: int, model: str = "fast") -> str:
    """压缩审查意见：缩减 critique 部分的长度。"""
    if not text:
        return text
    # 将 critique 部分从完整文本压缩为关键点
    import re
    # 匹配 "【重要提示】..." 或 "审查意见..." 段落
    critique_pattern = r'(【重要提示】.*?)(?:\n\n|$)'
    match = re.search(critique_pattern, text, re.DOTALL)
    if match and count_tokens(text, model) > max_tokens:
        original = match.group(1)
        # 压缩为简短版本
        short = original[:300] + "..." if len(original) > 300 else original
        text = text.replace(original, short)
    # 如果还是超了，用截断兜底
    if count_tokens(text, model) > max_tokens:
        text = _truncate_oldest(text, max_tokens, model)
    return text


def _rerank_and_truncate(text: str, max_tokens: int, model: str = "fast") -> str:
    """Rerank 后截断：保留高相关性的内容，去掉低相关的。"""
    if not text or count_tokens(text, model) <= max_tokens:
        return text

    # 按段落拆分，每个段落打分（简单的启发式：含有关键词的段落分数高）
    paragraphs = text.split("\n\n")
    if len(paragraphs) <= 1:
        return _truncate_oldest(text, max_tokens, model)

    # 关键词：数字、专有名词（英文大写词）、引号内容
    import re
    def score_paragraph(p: str) -> float:
        score = 0.0
        score += len(re.findall(r'\d+', p)) * 0.5          # 含数字
        score += len(re.findall(r'[A-Z][a-z]+', p)) * 0.3  # 含专有名词
        score += len(re.findall(r'["""].*?["'']', p)) * 0.2  # 含引用
        score += len(re.findall(r'关键|重要|核心|突破|发现', p)) * 0.5  # 重要性标记词
        return score

    scored = [(p, score_paragraph(p)) for p in paragraphs]
    scored.sort(key=lambda x: x[1], reverse=True)

    # 按分数从高到低选取段落
    result_parts = []
    current_tokens = 0
    for para, score in scored:
        para_tokens = count_tokens(para, model)
        if current_tokens + para_tokens <= max_tokens:
            result_parts.append(para)
            current_tokens += para_tokens
        elif current_tokens < max_tokens * 0.8:
            # 如果还没满 80%，截断当前段落
            remaining = max_tokens - current_tokens
            truncated = _truncate_oldest(para, remaining, model)
            if truncated:
                result_parts.append(truncated)
            break

    return "\n\n".join(result_parts)


def _compress_search_results(text: str, max_tokens: int, model: str = "fast") -> str:
    """压缩搜索结果：保留每条结果的核心信息。"""
    if not text or count_tokens(text, model) <= max_tokens:
        return text

    # 找到搜索结果的分隔标记
    import re
    # 匹配 "### 网络搜索结果" 或 "### 文档资料" 等
    sections = re.split(r'(###\s+)', text)
    if len(sections) <= 2:
        return _rerank_and_truncate(text, max_tokens, model)

    # 对每个搜索结果条目：保留前 150 字
    lines = text.split("\n")
    compressed = []
    for line in lines:
        if len(line) > 200:
            line = line[:150] + "..."
        compressed.append(line)

    result = "\n".join(compressed)
    if count_tokens(result, model) > max_tokens:
        result = _rerank_and_truncate(result, max_tokens, model)

    return result


def _summarize_report_sections(text: str, max_tokens: int, model: str = "fast") -> str:
    """分章节压缩报告：保留每章的首段（通常含核心论点）。"""
    if not text or count_tokens(text, model) <= max_tokens:
        return text

    import re
    # 按 Markdown 标题拆分
    sections = re.split(r'(?=^#{1,3}\s)', text, flags=re.MULTILINE)

    if len(sections) <= 1:
        return _truncate_oldest(text, max_tokens, model)

    # 每章只保留标题 + 第一段
    compressed_sections = []
    for section in sections:
        lines = section.strip().split("\n")
        if not lines:
            continue
        # 保留：标题行 + 第一段正文（最多 3 行）
        kept = lines[:4]
        compressed_sections.append("\n".join(kept))

    result = "\n\n".join(compressed_sections)
    if count_tokens(result, model) > max_tokens:
        result = _truncate_oldest(result, max_tokens, model)

    return result


# ─── 溢出策略分发表 ───

OVERFLOW_HANDLERS = {
    OverflowPolicy.TRUNCATE_OLDEST: _truncate_oldest,
    OverflowPolicy.SUMMARIZE_CRITIQUE: _summarize_critique,
    OverflowPolicy.RERANK_AND_TRUNCATE: _rerank_and_truncate,
    OverflowPolicy.COMPRESS_SEARCH: _compress_search_results,
    OverflowPolicy.SUMMARIZE_REPORT: _summarize_report_sections,
    OverflowPolicy.NONE: lambda text, max_tokens, model: text[:max_tokens * 4],  # 硬截断
}


# ─── BudgetEnforcer ───

@dataclass
class EnforcerResult:
    """预算执行结果。"""
    node_name: str
    within_budget: bool
    input_tokens: int
    max_allowed: int
    overflow_applied: bool = False
    overflow_policy: str = ""
    tokens_before_overflow: int = 0
    tokens_after_overflow: int = 0
    tokens_saved: int = 0


class BudgetEnforcer:
    """
    预算执行器——嵌入到每个 Graph Node 的 LLM 调用前后。

    用法（在 node 函数中）:
        enforcer = BudgetEnforcer(ledger=state.get("_ledger"))

        # 调用前
        prompt, result = enforcer.pre_check("writer", prompt, state)
        if result.overflow_applied:
            logger.info(f"Writer 溢出: {result.tokens_saved} tokens saved")

        # LLM 调用
        response = llm.invoke(prompt)

        # 调用后
        enforcer.record("writer", result.input_tokens,
                        actual_input=response.usage_metadata.get("input_tokens", 0),
                        actual_output=response.usage_metadata.get("output_tokens", 0))
    """

    def __init__(self, ledger: Optional[BudgetLedger] = None):
        """
        Args:
            ledger: BudgetLedger 实例。为 None 时自动创建（降级模式：不做限制）。
        """
        self.ledger = ledger
        self._disabled = ledger is None

    # ─── 预检 ───

    def pre_check(
        self,
        node_name: str,
        input_text: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, EnforcerResult]:
        """
        LLM 调用前的预算预检。

        如果输入超过节点预算，自动应用溢出策略处理 input_text。

        Args:
            node_name: 节点名称（"router", "planner", "researcher", "writer", "reviewer", "refiner"）
            input_text: 准备发送给 LLM 的完整 Prompt 文本
            state: 当前 AgentState（可选，用于上下文感知的溢出处理）

        Returns:
            (processed_text, enforcer_result)
            - processed_text: 处理后的文本（可能已被压缩/截断）
            - enforcer_result: 执行结果详情
        """
        input_tokens = count_tokens(input_text)

        # 降级模式：不做预算限制
        if self._disabled:
            return input_text, EnforcerResult(
                node_name=node_name,
                within_budget=True,
                input_tokens=input_tokens,
                max_allowed=999_999,
            )

        # 获取节点策略
        policy = self.ledger.get_policy(node_name)
        max_allowed = policy.max_input_tokens
        within = input_tokens <= max_allowed

        result = EnforcerResult(
            node_name=node_name,
            within_budget=within,
            input_tokens=input_tokens,
            max_allowed=max_allowed,
            overflow_policy=policy.overflow_policy.value,
        )

        if within:
            return input_text, result

        # ─── 超出预算：执行溢出策略 ───
        logger.warning(
            f"[Budget] {node_name}: {input_tokens}/{max_allowed} tokens "
            f"(超出 {input_tokens - max_allowed}) → 执行 {policy.overflow_policy.value}"
        )

        handler = OVERFLOW_HANDLERS.get(
            policy.overflow_policy, _truncate_oldest
        )

        result.tokens_before_overflow = input_tokens
        processed_text = handler(input_text, max_allowed, policy.model_type)
        result.tokens_after_overflow = count_tokens(processed_text)
        result.tokens_saved = input_tokens - result.tokens_after_overflow
        result.overflow_applied = True

        if result.tokens_after_overflow > max_allowed:
            # 兜底：硬截断
            logger.warning(
                f"[Budget] {node_name}: 溢出策略后仍超出 "
                f"({result.tokens_after_overflow}/{max_allowed}) → 硬截断"
            )
            processed_text = processed_text[:max_allowed * 4]
            result.tokens_after_overflow = count_tokens(processed_text)
            result.tokens_saved = input_tokens - result.tokens_after_overflow

        return processed_text, result

    # ─── 事后记录 ───

    def record(
        self,
        node_name: str,
        estimated_input: int,
        actual_input: int = 0,
        actual_output: int = 0,
        overflow_applied: bool = False,
        tokens_saved: int = 0,
    ) -> None:
        """
        LLM 调用后记录实际 Token 消耗。

        Args:
            node_name: 节点名称
            estimated_input: 预估输入 Token（tiktoken）
            actual_input: API 返回的实际输入 Token
            actual_output: API 返回的实际输出 Token
            overflow_applied: 是否触发了溢出策略
            tokens_saved: 溢出策略节省的 Token 数
        """
        if self._disabled or self.ledger is None:
            return

        self.ledger.record(
            node_name=node_name,
            estimated=estimated_input,
            actual_input=actual_input or estimated_input,
            actual_output=actual_output,
            overflow_triggered=overflow_applied,
            compression_applied=overflow_applied,
            tokens_saved=tokens_saved,
        )

    # ─── 便捷方法：一站式 pre_check + record ───

    def wrap_llm_call(
        self,
        node_name: str,
        llm,
        input_text: str,
        state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, EnforcerResult]:
        """
        一站式 LLM 调用包装：预检 → 调用 → 记录。

        这是最简单的接入方式——替换 llm.invoke(prompt) 为
        enforcer.wrap_llm_call("writer", llm, prompt)。

        Returns:
            (llm_response, enforcer_result)
        """
        # 1. 入口清洗：剥离开场 prompt 里可能混入的孤立代理字符。
        #    （用户输入/检索结果里的脏字符会让 openai SDK 在序列化请求体时
        #      抛 UnicodeEncodeError: surrogates not allowed，且重试必然失败）
        input_text = strip_surrogates(input_text)

        # 2. 预检
        processed_text, result = self.pre_check(node_name, input_text, state)

        # 3. LLM 调用
        response = llm.invoke(processed_text)

        # 4. 出口清洗：LLM 偶尔会返回含孤立代理字符的内容，
        #    不剥掉的话会随 state 流入下游（json.dumps / sha256 等编码点全都会炸）
        _content = getattr(response, "content", None)
        if isinstance(_content, str):
            _cleaned = strip_surrogates(_content)
            if _cleaned is not _content:  # 快速路径下干净文本返回原对象
                try:
                    response.content = _cleaned
                except Exception:
                    # 消息对象不可写时忽略（下游消费点各自还有兜底清洗）
                    pass

        # 5. 记录
        actual_input = 0
        actual_output = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            actual_input = response.usage_metadata.get("input_tokens", 0)
            actual_output = response.usage_metadata.get("output_tokens", 0)

        self.record(
            node_name=node_name,
            estimated_input=result.input_tokens,
            actual_input=actual_input,
            actual_output=actual_output,
            overflow_applied=result.overflow_applied,
            tokens_saved=result.tokens_saved,
        )

        # 日志
        if result.overflow_applied:
            logger.info(
                f"[Budget] {node_name}: {result.tokens_before_overflow} → "
                f"{result.tokens_after_overflow} tokens "
                f"(saved {result.tokens_saved}, policy={result.overflow_policy})"
            )

        return response, result

    # ─── 快照 ───

    def get_snapshot(self) -> Optional[BudgetSnapshot]:
        """获取当前预算快照。"""
        if self._disabled or self.ledger is None:
            return None
        return self.ledger.snapshot()

    @property
    def disabled(self) -> bool:
        return self._disabled


# ─── 工厂函数 ───

def create_enforcer_from_state(
    state: Dict[str, Any],
    total_budget: int = 128_000,
) -> BudgetEnforcer:
    """
    从 AgentState 创建 BudgetEnforcer。

    如果 state 中有 session_id，则创建关联的 BudgetLedger；
    否则创建一个独立的 ledger（降级模式）。
    """
    session_id = state.get("session_id", "unknown")
    turn_number = state.get("turn_number", 1)

    ledger = BudgetLedger(
        session_id=session_id,
        total_budget=total_budget,
    )
    ledger.begin_turn(turn_number, state.get("turn_id", "unknown"))

    return BudgetEnforcer(ledger=ledger)
