from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


LoopNext = Literal["planner", "writer", "__end__"]


@dataclass(frozen=True)
class LoopDecision:
    next_node: LoopNext
    reason: str
    metadata: dict[str, Any]


class WorkflowLoopPolicy:
    """Centralized routing policy for the Agent workflow loop."""

    def __init__(self, *, max_revisions: int = 3) -> None:
        self.max_revisions = max(0, max_revisions)

    def after_research(self, state: Mapping[str, Any]) -> LoopDecision:
        should_stop = bool(state.get("should_stop", False))
        if should_stop:
            return LoopDecision(
                next_node="__end__",
                reason="research_requested_stop",
                metadata={"should_stop": True},
            )
        return LoopDecision(
            next_node="writer",
            reason="research_completed",
            metadata={"should_stop": False},
        )

    def after_review(self, state: Mapping[str, Any]) -> LoopDecision:
        current_revision = int(state.get("revision_number", 0) or 0)
        review_status = state.get("review_status", "PASS")
        critique = state.get("critique", "")
        action = self._normalize_review_action(state.get("review_action", ""), critique)
        metadata = {
            "revision_number": current_revision,
            "review_status": review_status,
            "review_action": action,
            "critique_length": len(critique),
            "max_revisions": self.max_revisions,
        }

        if current_revision >= self.max_revisions:
            return LoopDecision(
                next_node="__end__",
                reason="review_max_revisions_reached",
                metadata=metadata,
            )

        if review_status == "FAIL":
            if action == "rewrite":
                return LoopDecision(
                    next_node="writer",
                    reason="review_failed_routing_to_writer",
                    metadata=metadata,
                )
            return LoopDecision(
                next_node="planner",
                reason="review_failed_routing_to_planner",
                metadata=metadata,
            )

        return LoopDecision(
            next_node="__end__",
            reason="review_passed",
            metadata=metadata,
        )

    def _normalize_review_action(self, action: str, critique: str) -> str:
        normalized = (action or "").strip().lower()
        if normalized in {"replan", "rewrite", "none"}:
            return normalized

        critique_text = (critique or "").lower()
        replan_markers = (
            "资料",
            "证据",
            "检索",
            "搜索",
            "来源",
            "引用",
            "数据",
            "fact",
            "evidence",
            "source",
            "search",
        )
        if any(marker in critique_text for marker in replan_markers):
            return "replan"
        return "rewrite"
