import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SessionStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    EXPIRED = "expired"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    INDEXED = "indexed"
    FAILED = "failed"
    ARCHIVED = "archived"


class KnowledgeBaseVisibility(str, Enum):
    PRIVATE = "private"
    TEAM = "team"
    PUBLIC = "public"


class TenantStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class TenantRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class AuditAction(str, Enum):
    LOGIN_SUCCEEDED = "login.succeeded"
    LOGIN_FAILED = "login.failed"
    RATE_LIMIT_EXCEEDED = "rate_limit.exceeded"
    KNOWLEDGE_BASE_CREATED = "knowledge_base.created"
    KNOWLEDGE_BASE_CLEARED = "knowledge_base.cleared"
    DOCUMENTS_UPLOADED = "documents.uploaded"
    MEMBER_CREATED = "member.created"
    MEMBER_ROLE_UPDATED = "member.role_updated"
    MEMBER_DISABLED = "member.disabled"
    WORKFLOW_RUN_CANCELLED = "workflow_run.cancelled"


class ChatSessionStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class WorkflowRunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class WorkflowNodeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WorkflowToolStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class SessionMeta:
    """Session metadata persisted by the session store."""

    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    turns_count: int = 0
    total_budget: int = 128_000
    total_estimated_tokens: int = 0
    total_actual_tokens: int = 0
    compression_savings: int = 0
    status: str = SessionStatus.ACTIVE.value

    def to_dict(self) -> Dict[str, str]:
        return {
            "session_id": self.session_id,
            "created_at": str(self.created_at),
            "last_active": str(self.last_active),
            "turns_count": str(self.turns_count),
            "total_budget": str(self.total_budget),
            "total_estimated_tokens": str(self.total_estimated_tokens),
            "total_actual_tokens": str(self.total_actual_tokens),
            "compression_savings": str(self.compression_savings),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "SessionMeta":
        return cls(
            session_id=d.get("session_id", ""),
            created_at=float(d.get("created_at", 0)),
            last_active=float(d.get("last_active", 0)),
            turns_count=int(d.get("turns_count", 0)),
            total_budget=int(d.get("total_budget", 128_000)),
            total_estimated_tokens=int(d.get("total_estimated_tokens", 0)),
            total_actual_tokens=int(d.get("total_actual_tokens", 0)),
            compression_savings=int(d.get("compression_savings", 0)),
            status=d.get("status", SessionStatus.ACTIVE.value),
        )


@dataclass
class TurnRecord:
    """A single research turn stored in episodic memory."""

    turn_id: str
    turn_number: int
    query: str
    plan: List[str] = field(default_factory=list)
    search_results: List[str] = field(default_factory=list)
    final_report: str = ""
    critique: str = ""
    review_status: str = ""
    search_mode: str = "hybrid"
    token_usage: Dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "turn_number": str(self.turn_number),
            "query": self.query,
            "plan": json.dumps(self.plan, ensure_ascii=False),
            "search_results": json.dumps(self.search_results, ensure_ascii=False),
            "final_report": self.final_report,
            "critique": self.critique,
            "review_status": self.review_status,
            "search_mode": self.search_mode,
            "token_usage": json.dumps(self.token_usage),
            "timestamp": str(self.timestamp),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "TurnRecord":
        return cls(
            turn_id=d.get("turn_id", ""),
            turn_number=int(d.get("turn_number", 0)),
            query=d.get("query", ""),
            plan=json.loads(d.get("plan", "[]")),
            search_results=json.loads(d.get("search_results", "[]")),
            final_report=d.get("final_report", ""),
            critique=d.get("critique", ""),
            review_status=d.get("review_status", ""),
            search_mode=d.get("search_mode", "hybrid"),
            token_usage=json.loads(d.get("token_usage", "{}")),
            timestamp=float(d.get("timestamp", 0)),
        )


@dataclass
class Tenant:
    """Enterprise tenant/account container."""

    tenant_id: str
    name: str
    slug: str
    status: str = TenantStatus.ACTIVE.value
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "slug": self.slug,
            "status": self.status,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "Tenant":
        return cls(
            tenant_id=d.get("tenant_id", ""),
            name=d.get("name", ""),
            slug=d.get("slug", ""),
            status=d.get("status", TenantStatus.ACTIVE.value),
            created_at=float(d.get("created_at", 0) or 0),
            updated_at=float(d.get("updated_at", 0) or 0),
        )


@dataclass
class UserAccount:
    """Login account metadata. Password hashes are stored, never plain text."""

    user_id: str
    username: str
    email: str
    display_name: str = ""
    password_hash: str = ""
    status: str = UserStatus.ACTIVE.value
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_login_at: Optional[float] = None

    def to_dict(self) -> Dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "password_hash": self.password_hash,
            "status": self.status,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "last_login_at": "" if self.last_login_at is None else str(self.last_login_at),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "UserAccount":
        last_login_at = d.get("last_login_at", "")
        return cls(
            user_id=d.get("user_id", ""),
            username=d.get("username", ""),
            email=d.get("email", ""),
            display_name=d.get("display_name", ""),
            password_hash=d.get("password_hash", ""),
            status=d.get("status", UserStatus.ACTIVE.value),
            created_at=float(d.get("created_at", 0) or 0),
            updated_at=float(d.get("updated_at", 0) or 0),
            last_login_at=float(last_login_at) if last_login_at else None,
        )


@dataclass
class TenantMembership:
    """Role assignment for a user inside one tenant."""

    membership_id: str
    tenant_id: str
    user_id: str
    role: str = TenantRole.MEMBER.value
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, str]:
        return {
            "membership_id": self.membership_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "role": self.role,
            "status": self.status,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "TenantMembership":
        return cls(
            membership_id=d.get("membership_id", ""),
            tenant_id=d.get("tenant_id", ""),
            user_id=d.get("user_id", ""),
            role=d.get("role", TenantRole.MEMBER.value),
            status=d.get("status", "active"),
            created_at=float(d.get("created_at", 0) or 0),
            updated_at=float(d.get("updated_at", 0) or 0),
        )


@dataclass
class AuditLog:
    """Security and compliance event emitted by protected business actions."""

    audit_id: str
    action: str
    tenant_id: str = ""
    actor_user_id: str = ""
    actor_username: str = ""
    target_type: str = ""
    target_id: str = ""
    status: str = "success"
    request_id: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "action": self.action,
            "tenant_id": self.tenant_id,
            "actor_user_id": self.actor_user_id,
            "actor_username": self.actor_username,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "status": self.status,
            "request_id": self.request_id,
            "details": self.details,
            "created_at": str(self.created_at),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AuditLog":
        details = d.get("details", {})
        if isinstance(details, str):
            details = json.loads(details or "{}")
        return cls(
            audit_id=d.get("audit_id", ""),
            action=d.get("action", ""),
            tenant_id=d.get("tenant_id", ""),
            actor_user_id=d.get("actor_user_id", ""),
            actor_username=d.get("actor_username", ""),
            target_type=d.get("target_type", ""),
            target_id=d.get("target_id", ""),
            status=d.get("status", "success"),
            request_id=d.get("request_id", ""),
            details=details or {},
            created_at=float(d.get("created_at", 0) or 0),
        )


@dataclass
class ChatSessionRecord:
    """Long-lived PostgreSQL record for a chat session asset."""

    session_id: str
    tenant_id: str
    user_id: str = ""
    username: str = ""
    knowledge_base_id: str = ""
    title: str = ""
    status: str = ChatSessionStatus.ACTIVE.value
    turns_count: int = 0
    total_budget: int = 128_000
    total_estimated_tokens: int = 0
    total_actual_tokens: int = 0
    compression_savings: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "username": self.username,
            "knowledge_base_id": self.knowledge_base_id,
            "title": self.title,
            "status": self.status,
            "turns_count": str(self.turns_count),
            "total_budget": str(self.total_budget),
            "total_estimated_tokens": str(self.total_estimated_tokens),
            "total_actual_tokens": str(self.total_actual_tokens),
            "compression_savings": str(self.compression_savings),
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "last_active": str(self.last_active),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChatSessionRecord":
        return cls(
            session_id=d.get("session_id", ""),
            tenant_id=d.get("tenant_id", ""),
            user_id=d.get("user_id", ""),
            username=d.get("username", ""),
            knowledge_base_id=d.get("knowledge_base_id", ""),
            title=d.get("title", ""),
            status=d.get("status", ChatSessionStatus.ACTIVE.value),
            turns_count=int(d.get("turns_count", 0) or 0),
            total_budget=int(d.get("total_budget", 128_000) or 128_000),
            total_estimated_tokens=int(d.get("total_estimated_tokens", 0) or 0),
            total_actual_tokens=int(d.get("total_actual_tokens", 0) or 0),
            compression_savings=int(d.get("compression_savings", 0) or 0),
            created_at=float(d.get("created_at", 0) or 0),
            updated_at=float(d.get("updated_at", 0) or 0),
            last_active=float(d.get("last_active", 0) or 0),
        )


@dataclass
class ChatTurnRecord:
    """Long-lived PostgreSQL record for one completed chat turn."""

    turn_id: str
    session_id: str
    tenant_id: str
    user_id: str = ""
    username: str = ""
    knowledge_base_id: str = ""
    turn_number: int = 0
    query: str = ""
    search_mode: str = "hybrid"
    plan: List[str] = field(default_factory=list)
    search_results: List[str] = field(default_factory=list)
    final_report: str = ""
    critique: str = ""
    review_status: str = ""
    token_usage: Dict[str, int] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "username": self.username,
            "knowledge_base_id": self.knowledge_base_id,
            "turn_number": str(self.turn_number),
            "query": self.query,
            "search_mode": self.search_mode,
            "plan": self.plan,
            "search_results": self.search_results,
            "final_report": self.final_report,
            "critique": self.critique,
            "review_status": self.review_status,
            "token_usage": self.token_usage,
            "created_at": str(self.created_at),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChatTurnRecord":
        def parse_jsonish(value, default):
            if isinstance(value, str):
                return json.loads(value or "[]")
            return value if value is not None else default

        return cls(
            turn_id=d.get("turn_id", ""),
            session_id=d.get("session_id", ""),
            tenant_id=d.get("tenant_id", ""),
            user_id=d.get("user_id", ""),
            username=d.get("username", ""),
            knowledge_base_id=d.get("knowledge_base_id", ""),
            turn_number=int(d.get("turn_number", 0) or 0),
            query=d.get("query", ""),
            search_mode=d.get("search_mode", "hybrid"),
            plan=parse_jsonish(d.get("plan"), []),
            search_results=parse_jsonish(d.get("search_results"), []),
            final_report=d.get("final_report", ""),
            critique=d.get("critique", ""),
            review_status=d.get("review_status", ""),
            token_usage=parse_jsonish(d.get("token_usage"), {}),
            created_at=float(d.get("created_at", 0) or 0),
        )


@dataclass
class WorkflowRunRecord:
    """Trace for one end-to-end Agent workflow execution."""

    run_id: str
    tenant_id: str
    user_id: str = ""
    username: str = ""
    session_id: str = ""
    turn_id: str = ""
    knowledge_base_id: str = ""
    request_id: str = ""
    query: str = ""
    search_mode: str = "hybrid"
    status: str = WorkflowRunStatus.RUNNING.value
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    duration_ms: int = 0
    error_code: str = ""
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "username": self.username,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "knowledge_base_id": self.knowledge_base_id,
            "request_id": self.request_id,
            "query": self.query,
            "search_mode": self.search_mode,
            "status": self.status,
            "started_at": str(self.started_at),
            "finished_at": "" if self.finished_at is None else str(self.finished_at),
            "duration_ms": str(self.duration_ms),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkflowRunRecord":
        metadata = d.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata or "{}")
        finished_at = d.get("finished_at", "")
        return cls(
            run_id=d.get("run_id", ""),
            tenant_id=d.get("tenant_id", ""),
            user_id=d.get("user_id", ""),
            username=d.get("username", ""),
            session_id=d.get("session_id", ""),
            turn_id=d.get("turn_id", ""),
            knowledge_base_id=d.get("knowledge_base_id", ""),
            request_id=d.get("request_id", ""),
            query=d.get("query", ""),
            search_mode=d.get("search_mode", "hybrid"),
            status=d.get("status", WorkflowRunStatus.RUNNING.value),
            started_at=float(d.get("started_at", 0) or 0),
            finished_at=float(finished_at) if finished_at else None,
            duration_ms=int(d.get("duration_ms", 0) or 0),
            error_code=d.get("error_code", ""),
            error_message=d.get("error_message", ""),
            metadata=metadata or {},
        )


@dataclass
class WorkflowNodeRunRecord:
    """Trace for one node update produced during a workflow run."""

    node_run_id: str
    run_id: str
    node_name: str
    tenant_id: str
    session_id: str = ""
    turn_id: str = ""
    status: str = WorkflowNodeStatus.SUCCEEDED.value
    started_at: float = field(default_factory=time.time)
    finished_at: float = field(default_factory=time.time)
    duration_ms: int = 0
    input_summary: str = ""
    output_summary: str = ""
    token_usage: Dict[str, int] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_run_id": self.node_run_id,
            "run_id": self.run_id,
            "node_name": self.node_name,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "started_at": str(self.started_at),
            "finished_at": str(self.finished_at),
            "duration_ms": str(self.duration_ms),
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "token_usage": self.token_usage,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkflowNodeRunRecord":
        def parse_jsonish(value, default):
            if isinstance(value, str):
                return json.loads(value or "{}")
            return value if value is not None else default

        return cls(
            node_run_id=d.get("node_run_id", ""),
            run_id=d.get("run_id", ""),
            node_name=d.get("node_name", ""),
            tenant_id=d.get("tenant_id", ""),
            session_id=d.get("session_id", ""),
            turn_id=d.get("turn_id", ""),
            status=d.get("status", WorkflowNodeStatus.SUCCEEDED.value),
            started_at=float(d.get("started_at", 0) or 0),
            finished_at=float(d.get("finished_at", 0) or 0),
            duration_ms=int(d.get("duration_ms", 0) or 0),
            input_summary=d.get("input_summary", ""),
            output_summary=d.get("output_summary", ""),
            token_usage=parse_jsonish(d.get("token_usage"), {}),
            error_code=d.get("error_code", ""),
            error_message=d.get("error_message", ""),
            metadata=parse_jsonish(d.get("metadata"), {}),
        )


@dataclass
class WorkflowToolRunRecord:
    """Trace for one tool call made inside a workflow node."""

    tool_run_id: str
    run_id: str
    node_name: str
    tool_name: str
    tenant_id: str
    session_id: str = ""
    turn_id: str = ""
    status: str = WorkflowToolStatus.SUCCEEDED.value
    started_at: float = field(default_factory=time.time)
    finished_at: float = field(default_factory=time.time)
    duration_ms: int = 0
    input_summary: str = ""
    output_summary: str = ""
    error_code: str = ""
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_run_id": self.tool_run_id,
            "run_id": self.run_id,
            "node_name": self.node_name,
            "tool_name": self.tool_name,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "status": self.status,
            "started_at": str(self.started_at),
            "finished_at": str(self.finished_at),
            "duration_ms": str(self.duration_ms),
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkflowToolRunRecord":
        metadata = d.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata or "{}")
        return cls(
            tool_run_id=d.get("tool_run_id", ""),
            run_id=d.get("run_id", ""),
            node_name=d.get("node_name", ""),
            tool_name=d.get("tool_name", ""),
            tenant_id=d.get("tenant_id", ""),
            session_id=d.get("session_id", ""),
            turn_id=d.get("turn_id", ""),
            status=d.get("status", WorkflowToolStatus.SUCCEEDED.value),
            started_at=float(d.get("started_at", 0) or 0),
            finished_at=float(d.get("finished_at", 0) or 0),
            duration_ms=int(d.get("duration_ms", 0) or 0),
            input_summary=d.get("input_summary", ""),
            output_summary=d.get("output_summary", ""),
            error_code=d.get("error_code", ""),
            error_message=d.get("error_message", ""),
            metadata=metadata or {},
        )


@dataclass
class WorkflowRouteDecisionRecord:
    """Trace for one workflow routing decision between nodes."""

    decision_id: str
    run_id: str
    from_node: str
    to_node: str
    reason: str
    tenant_id: str
    session_id: str = ""
    turn_id: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "reason": self.reason,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "created_at": str(self.created_at),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkflowRouteDecisionRecord":
        metadata = d.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata or "{}")
        return cls(
            decision_id=d.get("decision_id", ""),
            run_id=d.get("run_id", ""),
            from_node=d.get("from_node", ""),
            to_node=d.get("to_node", ""),
            reason=d.get("reason", ""),
            tenant_id=d.get("tenant_id", ""),
            session_id=d.get("session_id", ""),
            turn_id=d.get("turn_id", ""),
            created_at=float(d.get("created_at", 0) or 0),
            metadata=metadata or {},
        )


@dataclass
class ErrorEventRecord:
    """Durable error event for API and Agent workflow failures."""

    error_event_id: str
    error_code: str
    message: str
    source: str = "api"
    severity: str = "error"
    tenant_id: str = ""
    user_id: str = ""
    username: str = ""
    request_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    run_id: str = ""
    node_name: str = ""
    path: str = ""
    status_code: int = 500
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_event_id": self.error_event_id,
            "error_code": self.error_code,
            "message": self.message,
            "source": self.source,
            "severity": self.severity,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "username": self.username,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "run_id": self.run_id,
            "node_name": self.node_name,
            "path": self.path,
            "status_code": str(self.status_code),
            "details": self.details,
            "created_at": str(self.created_at),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ErrorEventRecord":
        details = d.get("details", {})
        if isinstance(details, str):
            details = json.loads(details or "{}")
        return cls(
            error_event_id=d.get("error_event_id", ""),
            error_code=d.get("error_code", ""),
            message=d.get("message", ""),
            source=d.get("source", "api"),
            severity=d.get("severity", "error"),
            tenant_id=d.get("tenant_id", ""),
            user_id=d.get("user_id", ""),
            username=d.get("username", ""),
            request_id=d.get("request_id", ""),
            session_id=d.get("session_id", ""),
            turn_id=d.get("turn_id", ""),
            run_id=d.get("run_id", ""),
            node_name=d.get("node_name", ""),
            path=d.get("path", ""),
            status_code=int(d.get("status_code", 500) or 500),
            details=details or {},
            created_at=float(d.get("created_at", 0) or 0),
        )


@dataclass
class KnowledgeBase:
    """A logical collection of indexed enterprise documents."""

    knowledge_base_id: str
    tenant_id: str
    name: str
    description: str = ""
    visibility: str = KnowledgeBaseVisibility.PRIVATE.value
    embedding_model: str = "text-embedding-v4"
    chunking_strategy: str = "recursive_character"
    created_by: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"

    def to_dict(self) -> Dict[str, str]:
        return {
            "knowledge_base_id": self.knowledge_base_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "visibility": self.visibility,
            "embedding_model": self.embedding_model,
            "chunking_strategy": self.chunking_strategy,
            "created_by": self.created_by,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "KnowledgeBase":
        return cls(
            knowledge_base_id=d.get("knowledge_base_id", ""),
            tenant_id=d.get("tenant_id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            visibility=d.get("visibility", KnowledgeBaseVisibility.PRIVATE.value),
            embedding_model=d.get("embedding_model", "text-embedding-v4"),
            chunking_strategy=d.get("chunking_strategy", "recursive_character"),
            created_by=d.get("created_by", ""),
            created_at=float(d.get("created_at", 0) or 0),
            updated_at=float(d.get("updated_at", 0) or 0),
            status=d.get("status", "active"),
        )


@dataclass
class DocumentRecord:
    """Metadata for an uploaded document and its indexing lifecycle."""

    document_id: str
    knowledge_base_id: str
    tenant_id: str
    filename: str
    original_filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    file_hash: str = ""
    storage_path: str = ""
    status: str = DocumentStatus.UPLOADED.value
    parser_version: str = ""
    chunk_count: int = 0
    page_count: Optional[int] = None
    error_message: str = ""
    created_by: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, str]:
        return {
            "document_id": self.document_id,
            "knowledge_base_id": self.knowledge_base_id,
            "tenant_id": self.tenant_id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "size_bytes": str(self.size_bytes),
            "file_hash": self.file_hash,
            "storage_path": self.storage_path,
            "status": self.status,
            "parser_version": self.parser_version,
            "chunk_count": str(self.chunk_count),
            "page_count": "" if self.page_count is None else str(self.page_count),
            "error_message": self.error_message,
            "created_by": self.created_by,
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "DocumentRecord":
        page_count = d.get("page_count", "")
        return cls(
            document_id=d.get("document_id", ""),
            knowledge_base_id=d.get("knowledge_base_id", ""),
            tenant_id=d.get("tenant_id", ""),
            filename=d.get("filename", ""),
            original_filename=d.get("original_filename", ""),
            content_type=d.get("content_type", ""),
            size_bytes=int(d.get("size_bytes", 0) or 0),
            file_hash=d.get("file_hash", ""),
            storage_path=d.get("storage_path", ""),
            status=d.get("status", DocumentStatus.UPLOADED.value),
            parser_version=d.get("parser_version", ""),
            chunk_count=int(d.get("chunk_count", 0) or 0),
            page_count=int(page_count) if page_count else None,
            error_message=d.get("error_message", ""),
            created_by=d.get("created_by", ""),
            created_at=float(d.get("created_at", 0) or 0),
            updated_at=float(d.get("updated_at", 0) or 0),
        )
