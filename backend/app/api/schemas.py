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


# ─── P3 被动触发：Webhook + Cron ───


class TriggerWebhookRequest(BaseModel):
    """外部系统调用 POST /api/triggers/webhook 触发一次研究任务。"""

    token: str
    query: str
    search_mode: str = "hybrid"
    session_id: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    # 研究完成后是否通过飞书推送结果。
    notify: bool = True
    # 覆盖默认飞书 webhook（用于测试或不同接收群）。
    notify_webhook_url: Optional[str] = None
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None


class CronJobCreateRequest(BaseModel):
    """创建定时研究任务。"""

    job_id: Optional[str] = None
    query: str
    # 调度配置：{"type":"interval","seconds":3600} | {"type":"daily","hour":9,"minute":0}
    #            | {"type":"cron","expr":"0 9 * * *"}
    schedule: dict
    search_mode: str = "hybrid"
    knowledge_base_id: Optional[str] = None
    session_id: Optional[str] = None
    notify: bool = True
    enabled: bool = True
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None


class CronJobUpdateRequest(BaseModel):
    """更新定时研究任务（仅传需要修改的字段）。"""

    query: Optional[str] = None
    schedule: Optional[dict] = None
    search_mode: Optional[str] = None
    knowledge_base_id: Optional[str] = None
    session_id: Optional[str] = None
    notify: Optional[bool] = None
    enabled: Optional[bool] = None
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
