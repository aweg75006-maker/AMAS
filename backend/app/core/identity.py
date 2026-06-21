from dataclasses import dataclass


DEFAULT_TENANT_ID = "default"
DEFAULT_USER_ID = "anonymous"
MAX_CONTEXT_ID_LENGTH = 64


@dataclass(frozen=True)
class RequestContext:
    tenant_id: str = DEFAULT_TENANT_ID
    user_id: str = DEFAULT_USER_ID
    username: str = ""
    role: str = ""
    auth_source: str = "headers"


def clean_context_id(value: str | None, default: str) -> str:
    raw = (value or default).strip()
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw)
    return (safe or default)[:MAX_CONTEXT_ID_LENGTH]
