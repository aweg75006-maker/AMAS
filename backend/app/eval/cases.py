from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    query: str
    search_mode: str = "hybrid"
    expected_keywords: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    min_length: int = 0
    min_citations: int = 0
    sample_output: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


BUILTIN_EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        case_id="agent_eval_llm_trends",
        query="2026 年大语言模型的主要技术趋势是什么？",
        expected_keywords=("MoE", "推理", "多模态", "上下文", "部署"),
        forbidden_terms=("无法回答", "不知道"),
        min_length=120,
        min_citations=0,
        sample_output=(
            "2026 年大语言模型的趋势集中在 MoE 架构、推理效率提升、多模态融合、"
            "长上下文能力和低成本部署。MoE 让模型容量扩大但保持推理成本可控；"
            "推理优化降低延迟；多模态模型开始统一处理文本、图像和视频；上下文窗口"
            "继续扩大；蒸馏和量化推动企业私有化部署。"
        ),
    ),
    EvalCase(
        case_id="agent_eval_rag_grounding",
        query="本地知识库问答如何降低幻觉？",
        search_mode="document",
        expected_keywords=("知识库", "引用", "检索", "相关性", "拒答"),
        forbidden_terms=("编造", "随便"),
        min_length=90,
        min_citations=1,
        sample_output=(
            "本地知识库问答应先做知识库检索，再进行相关性判断，并在答案中保留引用 [1]。"
            "当检索结果不足或相关性较低时，系统应拒答或提示需要更多资料，而不是自由发挥。"
            "同时可以用重排序和 Reviewer 节点检查证据覆盖度，降低幻觉风险。"
        ),
    ),
    EvalCase(
        case_id="agent_eval_hybrid_rag",
        query="本地知识库与全网搜索结果如何统一重排？",
        expected_keywords=("候选池", "重排", "本地", "全网"),
        forbidden_terms=("无法回答",),
        min_length=90,
        sample_output=(
            "先将本地知识库和全网搜索结果归一化为同一个候选池，再由重排模型按问题"
            "计算语义相关性。保留来源类型、链接和原始召回分数，最后选择排序靠前的"
            "证据生成带引用的回答，并在证据不足时继续检索或明确说明局限。"
        ),
    ),
)


def get_builtin_cases() -> tuple[EvalCase, ...]:
    return BUILTIN_EVAL_CASES
