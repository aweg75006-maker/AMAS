from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DOCUMENT_IRRELEVANT_MESSAGE = (
    "[系统提示]: 检索了本地文档，但发现内容与问题不相关，已自动忽略。"
)
DOCUMENT_ONLY_STOP_MESSAGE = (
    "【严重警告】：用户选择了 Document Only 模式，但上传的文档与问题完全无关。"
    "请直接在报告中诚实地告诉用户：“您上传的文档中没有关于此问题的说明”，不要编造答案。"
)


@dataclass(frozen=True)
class RagRetrievalDecision:
    should_grade: bool
    reason: str


@dataclass(frozen=True)
class RagGradeDecision:
    is_relevant: bool
    should_use_documents: bool
    message: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PostRagDecision:
    should_stop: bool
    should_web_search: bool
    message: str = ""
    log_event: str = ""


class ResearcherPolicy:
    """Business policy for Researcher tool orchestration."""

    def decide_after_retrieval(self, docs: list | None) -> RagRetrievalDecision:
        if docs:
            return RagRetrievalDecision(should_grade=True, reason="documents_found")
        return RagRetrievalDecision(should_grade=False, reason="no_documents")

    def decide_after_grade(self, grade: str, *, grade_ok: bool = True) -> RagGradeDecision:
        normalized = (grade or "").strip().upper()
        if grade_ok and "YES" in normalized:
            return RagGradeDecision(
                is_relevant=True,
                should_use_documents=True,
                reason="grade_yes",
            )
        return RagGradeDecision(
            is_relevant=False,
            should_use_documents=False,
            message=DOCUMENT_IRRELEVANT_MESSAGE,
            reason="grade_no" if grade_ok else "grade_failed",
        )

    def decide_after_rag(
        self,
        *,
        search_mode: str,
        is_doc_relevant: bool,
    ) -> PostRagDecision:
        normalized_mode = self.normalize_search_mode(search_mode)
        if normalized_mode == "document":
            if is_doc_relevant:
                return PostRagDecision(
                    should_stop=False,
                    should_web_search=False,
                    log_event="document_only_relevant",
                )
            return PostRagDecision(
                should_stop=True,
                should_web_search=False,
                message=DOCUMENT_ONLY_STOP_MESSAGE,
                log_event="document_only_irrelevant",
            )

        return PostRagDecision(
            should_stop=False,
            should_web_search=True,
            log_event=(
                "hybrid_doc_relevant"
                if is_doc_relevant
                else "hybrid_doc_irrelevant_auto_web"
            ),
        )

    def normalize_search_mode(self, search_mode: str) -> Literal["document", "hybrid"]:
        return "document" if search_mode == "document" else "hybrid"
