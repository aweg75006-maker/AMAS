from app.models.domain import (
    AuditAction,
    AuditLog,
    ChatSessionRecord,
    ChatTurnRecord,
    DocumentRecord,
    DocumentStatus,
    ErrorEventRecord,
    KnowledgeBase,
    KnowledgeBaseVisibility,
    SessionMeta,
    SessionStatus,
    Tenant,
    TenantMembership,
    TenantRole,
    UserAccount,
    WorkflowNodeRunRecord,
    WorkflowRunRecord,
    WorkflowRunStatus,
    TurnRecord,
)


def test_session_meta_round_trip():
    session = SessionMeta(
        session_id="iris_test",
        turns_count=3,
        total_budget=42_000,
        status=SessionStatus.ACTIVE.value,
    )

    restored = SessionMeta.from_dict(session.to_dict())

    assert restored.session_id == "iris_test"
    assert restored.turns_count == 3
    assert restored.total_budget == 42_000
    assert restored.status == SessionStatus.ACTIVE.value


def test_turn_record_round_trip_preserves_lists_and_usage():
    turn = TurnRecord(
        turn_id="turn_test",
        turn_number=2,
        query="测试问题",
        plan=["a", "b"],
        search_results=["result"],
        token_usage={"estimated_input": 12},
    )

    restored = TurnRecord.from_dict(turn.to_dict())

    assert restored.turn_id == "turn_test"
    assert restored.plan == ["a", "b"]
    assert restored.search_results == ["result"]
    assert restored.token_usage == {"estimated_input": 12}


def test_knowledge_base_round_trip():
    kb = KnowledgeBase(
        knowledge_base_id="kb_1",
        tenant_id="tenant_1",
        name="研发知识库",
        visibility=KnowledgeBaseVisibility.TEAM.value,
    )

    restored = KnowledgeBase.from_dict(kb.to_dict())

    assert restored.knowledge_base_id == "kb_1"
    assert restored.tenant_id == "tenant_1"
    assert restored.name == "研发知识库"
    assert restored.visibility == KnowledgeBaseVisibility.TEAM.value


def test_tenant_round_trip():
    tenant = Tenant(
        tenant_id="tenant_1",
        name="Acme",
        slug="acme",
    )

    restored = Tenant.from_dict(tenant.to_dict())

    assert restored.tenant_id == "tenant_1"
    assert restored.slug == "acme"


def test_user_account_round_trip_without_plain_password():
    user = UserAccount(
        user_id="user_1",
        username="user1",
        email="USER@Example.com",
        display_name="User One",
        password_hash="hash-value",
    )

    data = user.to_dict()
    restored = UserAccount.from_dict(data)

    assert "password" not in data
    assert restored.user_id == "user_1"
    assert restored.username == "user1"
    assert restored.password_hash == "hash-value"


def test_tenant_membership_round_trip():
    membership = TenantMembership(
        membership_id="membership_1",
        tenant_id="tenant_1",
        user_id="user_1",
        role=TenantRole.OWNER.value,
    )

    restored = TenantMembership.from_dict(membership.to_dict())

    assert restored.tenant_id == "tenant_1"
    assert restored.user_id == "user_1"
    assert restored.role == TenantRole.OWNER.value


def test_audit_log_round_trip_preserves_details():
    event = AuditLog(
        audit_id="audit_1",
        action=AuditAction.MEMBER_ROLE_UPDATED.value,
        tenant_id="tenant_1",
        actor_user_id="user_owner",
        target_type="user",
        target_id="user_member",
        request_id="req_1",
        details={"role": "admin"},
    )

    restored = AuditLog.from_dict(event.to_dict())

    assert restored.audit_id == "audit_1"
    assert restored.action == AuditAction.MEMBER_ROLE_UPDATED.value
    assert restored.details == {"role": "admin"}


def test_audit_action_includes_rate_limit_event():
    assert AuditAction.RATE_LIMIT_EXCEEDED.value == "rate_limit.exceeded"


def test_chat_session_record_round_trip():
    session = ChatSessionRecord(
        session_id="iris_test",
        tenant_id="tenant_1",
        user_id="user_1",
        username="owner",
        knowledge_base_id="kb_1",
        title="测试会话",
        turns_count=2,
        total_estimated_tokens=12,
    )

    restored = ChatSessionRecord.from_dict(session.to_dict())

    assert restored.session_id == "iris_test"
    assert restored.tenant_id == "tenant_1"
    assert restored.title == "测试会话"
    assert restored.turns_count == 2


def test_chat_turn_record_round_trip():
    turn = ChatTurnRecord(
        turn_id="turn_1",
        session_id="iris_test",
        tenant_id="tenant_1",
        query="hello",
        plan=["step"],
        search_results=["result"],
        token_usage={"estimated_input": 1},
    )

    restored = ChatTurnRecord.from_dict(turn.to_dict())

    assert restored.turn_id == "turn_1"
    assert restored.session_id == "iris_test"
    assert restored.plan == ["step"]
    assert restored.token_usage == {"estimated_input": 1}


def test_workflow_run_and_node_round_trip():
    run = WorkflowRunRecord(
        run_id="run_1",
        tenant_id="tenant_1",
        session_id="iris_1",
        turn_id="turn_1",
        query="hello",
        status=WorkflowRunStatus.SUCCEEDED.value,
        metadata={"thread_id": "turn_1"},
    )
    node = WorkflowNodeRunRecord(
        node_run_id="node_1",
        run_id="run_1",
        node_name="writer",
        tenant_id="tenant_1",
        output_summary="done",
        token_usage={"estimated": 1},
    )

    restored_run = WorkflowRunRecord.from_dict(run.to_dict())
    restored_node = WorkflowNodeRunRecord.from_dict(node.to_dict())

    assert restored_run.run_id == "run_1"
    assert restored_run.metadata == {"thread_id": "turn_1"}
    assert WorkflowRunStatus.CANCELLED.value == "cancelled"
    assert AuditAction.WORKFLOW_RUN_CANCELLED.value == "workflow_run.cancelled"
    assert restored_node.node_name == "writer"
    assert restored_node.token_usage == {"estimated": 1}


def test_error_event_round_trip():
    event = ErrorEventRecord(
        error_event_id="err_1",
        error_code="TEST_ERROR",
        message="failed",
        tenant_id="tenant_1",
        details={"reason": "boom"},
    )

    restored = ErrorEventRecord.from_dict(event.to_dict())

    assert restored.error_event_id == "err_1"
    assert restored.error_code == "TEST_ERROR"
    assert restored.details == {"reason": "boom"}


def test_document_record_round_trip_with_optional_page_count():
    doc = DocumentRecord(
        document_id="doc_1",
        knowledge_base_id="kb_1",
        tenant_id="tenant_1",
        filename="report.pdf",
        size_bytes=1024,
        status=DocumentStatus.INDEXED.value,
        page_count=7,
    )

    restored = DocumentRecord.from_dict(doc.to_dict())

    assert restored.document_id == "doc_1"
    assert restored.knowledge_base_id == "kb_1"
    assert restored.status == DocumentStatus.INDEXED.value
    assert restored.page_count == 7
    assert restored.size_bytes == 1024


def test_document_record_round_trip_without_page_count():
    doc = DocumentRecord(
        document_id="doc_2",
        knowledge_base_id="kb_1",
        tenant_id="tenant_1",
        filename="empty.pdf",
    )

    restored = DocumentRecord.from_dict(doc.to_dict())

    assert restored.page_count is None
