from app.models.domain import (
    DocumentRecord,
    DocumentStatus,
    KnowledgeBase,
    KnowledgeBaseVisibility,
    SessionMeta,
    SessionStatus,
    Tenant,
    TenantMembership,
    TenantRole,
    UserAccount,
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
