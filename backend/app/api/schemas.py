from typing import List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    query: str
    search_mode: str = "hybrid"
    thread_id: Optional[str] = None
    session_id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    pinned_turn_ids: Optional[List[str]] = None
    # HITL：在执行该节点之前暂停，等待人工确认/补充指令（如 "reviewer"）。
    hitl_pause_before: Optional[str] = None


class ResumeChatRequest(BaseModel):
    """断点续跑 / 人工介入续跑请求。"""

    thread_id: str
    # 续跑时追加的补充说明（追加到 query）。
    resume_instruction: Optional[str] = None
    # HITL 人工输入：注入到断点状态，供续跑节点消费（如人工修订意见）。
    human_input: Optional[str] = None


class SessionResponse(BaseModel):
    session_id: str
    created_at: float
    last_active: float
    turns_count: int
    total_budget: int
    total_estimated_tokens: int
    total_actual_tokens: int
    compression_savings: int
    status: str
    recent_turn_ids: List[str] = []


class HistoryResponse(BaseModel):
    session_id: str
    turns_count: int
    total_budget: int
    window_k: int
    window_stats: dict
    episodic: List[dict] = []
    semantic: List[dict] = []
    memory_context: str = ""


class TurnDetailResponse(BaseModel):
    session_id: str
    turn_id: str = ""
    turn_number: int = 0
    query: str = ""
    plan: List[str] = []
    search_results: List[str] = []
    final_report: str = ""
    critique: str = ""
    review_status: str = ""
    search_mode: str = "hybrid"
    token_usage: dict = {}
    timestamp: float = 0
    full_data: dict = {}


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    description: str = ""
    visibility: str = "private"


class LoginRequest(BaseModel):
    username: str
    password: str


class InviteMemberRequest(BaseModel):
    username: str
    email: str
    display_name: str = ""
    role: str = "member"


class UpdateMemberRoleRequest(BaseModel):
    role: str


class CancelWorkflowRunRequest(BaseModel):
    reason: str = ""
