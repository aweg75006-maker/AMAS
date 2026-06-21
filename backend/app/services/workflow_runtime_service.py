from __future__ import annotations

from app.core.config import settings


def workflow_runtime_fingerprint() -> dict[str, object]:
    """Current workflow/prompt/node runtime fingerprint for traceability."""

    return {
        "workflow_version": settings.workflow_version,
        "prompt_version": settings.prompt_version,
        "node_policy_version": settings.node_policy_version,
        "models": {
            "fast": settings.llm_fast_model,
            "smart": settings.llm_smart_model,
        },
        "node_execution": {
            "timeout_seconds": settings.workflow_node_timeout_seconds,
            "max_retries": settings.workflow_node_max_retries,
            "retry_backoff_seconds": settings.workflow_retry_backoff_seconds,
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
