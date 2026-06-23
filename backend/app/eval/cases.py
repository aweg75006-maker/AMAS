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
        query="企业知识库问答如何降低幻觉？",
        search_mode="document",
        expected_keywords=("知识库", "引用", "检索", "相关性", "拒答"),
        forbidden_terms=("编造", "随便"),
        min_length=100,
        min_citations=1,
        sample_output=(
            "企业知识库问答应先做知识库检索，再进行相关性判断，并在答案中保留引用 [1]。"
            "当检索结果不足或相关性较低时，系统应拒答或提示需要更多资料，而不是自由发挥。"
            "同时可以结合审计日志、检索 trace 和 Reviewer 节点降低幻觉风险。"
        ),
    ),
    EvalCase(
        case_id="agent_eval_workflow_governance",
        query="企业级 Agent 为什么需要工作流治理？",
        expected_keywords=("trace", "权限", "审计", "超时", "取消"),
        forbidden_terms=("不需要治理",),
        min_length=100,
        min_citations=0,
        sample_output=(
            "企业级 Agent 需要工作流治理，因为任务执行必须可追踪 trace、可审计、可取消，"
            "并且要具备超时和失败收口能力。权限控制能保证只有授权成员管理运行记录，"
            "审计日志可以记录关键操作，帮助团队定位问题和复盘输出质量。"
        ),
    ),
)


def get_builtin_cases() -> tuple[EvalCase, ...]:
    return BUILTIN_EVAL_CASES
