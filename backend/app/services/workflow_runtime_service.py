from __future__ import annotations

from app.core.config import settings
from app.harness.registry import harness_fingerprint
from app.tools.registry import get_tool_registry


def workflow_runtime_fingerprint() -> dict[str, object]:
    """Current workflow/prompt/node runtime fingerprint for traceability."""

    harness = harness_fingerprint()
    return {
        "workflow_version": settings.workflow_version,
        "prompt_version": settings.prompt_version,
        "node_policy_version": settings.node_policy_version,
        "workflow_engine": settings.workflow_engine,
        "primary_engine": "python",
        "legacy_fallback_engine": "langgraph",
        "harness": harness,
        "models": {
            "fast": settings.llm_fast_model,
            "smart": settings.llm_smart_model,
        },
        "node_execution": {
            "timeout_seconds": settings.workflow_node_timeout_seconds,
            "max_retries": settings.workflow_node_max_retries,
            "retry_backoff_seconds": settings.workflow_retry_backoff_seconds,
        },
        "run_execution": {
            "timeout_seconds": settings.workflow_run_timeout_seconds,
        },
        "loop_policy": {
            "max_revisions": harness["max_revisions"],
            "review_fail_next": "planner",
            "review_replan_next": "planner",
            "review_rewrite_next": "writer",
            "research_stop_next": "__end__",
        },
        "rag": {
            "embedding_model": settings.rag_embedding_model,
            "chunk_size": settings.rag_chunk_size,
            "chunk_overlap": settings.rag_chunk_overlap,
            "top_k": settings.rag_top_k,
            "fetch_k": settings.rag_fetch_k,
        },
    }


def workflow_runtime_metadata(extra: dict | None = None) -> dict[str, object]:
    metadata = workflow_runtime_fingerprint()
    if extra:
        metadata = {**metadata, **extra}
    return metadata


def workflow_runtime_diagnostics() -> dict[str, object]:
    """Human-oriented workflow runtime diagnostics for rollout checks."""

    runtime = workflow_runtime_fingerprint()
    tool_specs = get_tool_registry().list_specs()
    legacy_fallback_active = settings.workflow_engine == "langgraph"
    warnings = []
    if legacy_fallback_active:
        warnings.append(
            {
                "warning_code": "LEGACY_WORKFLOW_ENGINE_ACTIVE",
                "message": (
                    "LangGraph is a legacy fallback; python is the primary "
                    "production engine."
                ),
                "production_recommended": False,
            }
        )
    return {
        **runtime,
        "diagnostics": {
            "active_engine": settings.workflow_engine,
            "primary_engine": "python",
            "legacy_fallback_engine": "langgraph",
            "legacy_fallback_active": legacy_fallback_active,
            "production_recommended": not legacy_fallback_active,
            "warnings": warnings,
            "available_engines": ["python", "langgraph"],
            "route_decision_trace_enabled": settings.workflow_engine == "python",
            "tool_trace_enabled": True,
            "node_trace_enabled": True,
            "rollback_engine": "langgraph",
            "python_engine_ready": True,
        },
        "registered_tools": [
            {
                "name": spec.name,
                "description": spec.description,
                "version": spec.version,
                "input_schema": spec.input_schema,
                "output_schema": spec.output_schema,
                "tags": list(spec.tags),
            }
            for spec in tool_specs
        ],
    }
