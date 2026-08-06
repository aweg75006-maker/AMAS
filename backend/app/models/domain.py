import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    INDEXED = "indexed"
    FAILED = "failed"


class KnowledgeBaseVisibility(str, Enum):
    PRIVATE = "private"


class ChatSessionStatus(str, Enum):
    ACTIVE = "active"


@dataclass
class SessionMeta:
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    turns_count: int = 0
    total_budget: int = 128_000
    total_estimated_tokens: int = 0
    total_actual_tokens: int = 0
    compression_savings: int = 0
    status: str = SessionStatus.ACTIVE.value

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "SessionMeta":
        return cls(
            session_id=data.get("session_id", ""),
            created_at=float(data.get("created_at", 0)),
            last_active=float(data.get("last_active", 0)),
            turns_count=int(data.get("turns_count", 0)),
            total_budget=int(data.get("total_budget", 128_000)),
            total_estimated_tokens=int(data.get("total_estimated_tokens", 0)),
            total_actual_tokens=int(data.get("total_actual_tokens", 0)),
            compression_savings=int(data.get("compression_savings", 0)),
            status=data.get("status", SessionStatus.ACTIVE.value),
        )


@dataclass
class TurnRecord:
    turn_id: str
    turn_number: int
    query: str
    plan: list[str] = field(default_factory=list)
    search_results: list[str] = field(default_factory=list)
    final_report: str = ""
    critique: str = ""
    review_status: str = ""
    search_mode: str = "hybrid"
    token_usage: dict[str, int] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "turn_number": str(self.turn_number), "plan": json.dumps(self.plan, ensure_ascii=False), "search_results": json.dumps(self.search_results, ensure_ascii=False), "token_usage": json.dumps(self.token_usage), "timestamp": str(self.timestamp)}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "TurnRecord":
        return cls(
            turn_id=data.get("turn_id", ""), turn_number=int(data.get("turn_number", 0)), query=data.get("query", ""),
            plan=json.loads(data.get("plan", "[]")), search_results=json.loads(data.get("search_results", "[]")),
            final_report=data.get("final_report", ""), critique=data.get("critique", ""), review_status=data.get("review_status", ""),
            search_mode=data.get("search_mode", "hybrid"), token_usage=json.loads(data.get("token_usage", "{}")), timestamp=float(data.get("timestamp", 0)),
        )


@dataclass
class ChatSessionRecord:
    session_id: str
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

    def to_dict(self) -> dict[str, Any]:
        return {key: str(value) if isinstance(value, (int, float)) else value for key, value in self.__dict__.items()}


@dataclass
class ChatTurnRecord:
    turn_id: str
    session_id: str
    knowledge_base_id: str = ""
    turn_number: int = 0
    query: str = ""
    search_mode: str = "hybrid"
    plan: list[str] = field(default_factory=list)
    search_results: list[str] = field(default_factory=list)
    final_report: str = ""
    critique: str = ""
    review_status: str = ""
    token_usage: dict[str, int] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "turn_number": str(self.turn_number), "created_at": str(self.created_at)}


@dataclass
class KnowledgeBase:
    knowledge_base_id: str
    name: str
    description: str = ""
    visibility: str = KnowledgeBaseVisibility.PRIVATE.value
    embedding_model: str = "text-embedding-v4"
    chunking_strategy: str = "recursive_character"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "active"

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "KnowledgeBase":
        return cls(
            knowledge_base_id=data.get("knowledge_base_id", ""), name=data.get("name", ""), description=data.get("description", ""),
            visibility=data.get("visibility", KnowledgeBaseVisibility.PRIVATE.value), embedding_model=data.get("embedding_model", "text-embedding-v4"),
            chunking_strategy=data.get("chunking_strategy", "recursive_character"), created_at=float(data.get("created_at", 0) or 0),
            updated_at=float(data.get("updated_at", 0) or 0), status=data.get("status", "active"),
        )


@dataclass
class DocumentRecord:
    document_id: str
    knowledge_base_id: str
    filename: str
    original_filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    storage_path: str = ""
    status: str = DocumentStatus.UPLOADED.value
    chunk_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "DocumentRecord":
        return cls(
            document_id=data.get("document_id", ""), knowledge_base_id=data.get("knowledge_base_id", ""), filename=data.get("filename", ""),
            original_filename=data.get("original_filename", ""), content_type=data.get("content_type", ""), size_bytes=int(data.get("size_bytes", 0) or 0),
            storage_path=data.get("storage_path", ""), status=data.get("status", DocumentStatus.UPLOADED.value), chunk_count=int(data.get("chunk_count", 0) or 0),
            created_at=float(data.get("created_at", 0) or 0), updated_at=float(data.get("updated_at", 0) or 0),
        )
