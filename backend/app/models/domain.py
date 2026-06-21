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
