import pytest


def test_session_not_found_error_shape(client):
    response = client.get(
        "/api/sessions/not-exist",
        headers={"X-Request-ID": "test-session-not-found"},
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "test-session-not-found"

    body = response.json()
    assert body["error"]["code"] == "SESSION_NOT_FOUND"
    assert body["error"]["message"] == "会话不存在"
    assert body["error"]["request_id"] == "test-session-not-found"
    assert body["error"]["details"]["session_id"] == "not-exist"


def test_upload_too_many_files_error_shape(client):
    files = [
        ("files", (f"f{i}.pdf", b"x", "application/pdf"))
        for i in range(6)
    ]
    response = client.post(
        "/api/upload",
        files=files,
        headers={"X-Request-ID": "test-too-many-files"},
    )

    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == "test-too-many-files"

    body = response.json()
    assert body["error"]["code"] == "TOO_MANY_FILES"
    assert body["error"]["request_id"] == "test-too-many-files"
    assert body["error"]["details"] == {
        "max_files": 5,
        "actual_files": 6,
    }


def test_upload_rejects_unsupported_extension(client):
    response = client.post(
        "/api/upload",
        files=[("files", ("note.txt", b"hello", "text/plain"))],
        headers={"X-Request-ID": "test-unsupported-extension"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert body["error"]["request_id"] == "test-unsupported-extension"


def test_upload_rejects_unsupported_content_type(client):
    response = client.post(
        "/api/upload",
        files=[("files", ("report.pdf", b"%PDF-1.4", "text/plain"))],
        headers={"X-Request-ID": "test-unsupported-content-type"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_CONTENT_TYPE"
    assert body["error"]["request_id"] == "test-unsupported-content-type"


def test_upload_rejects_unknown_knowledge_base(client):
    response = client.post(
        "/api/upload",
        files=[("files", ("report.pdf", b"%PDF-1.4", "application/pdf"))],
        data={"knowledge_base_id": "kb_missing"},
        headers={"X-Request-ID": "test-missing-kb-upload"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"
    assert body["error"]["request_id"] == "test-missing-kb-upload"
    assert body["error"]["details"]["knowledge_base_id"] == "kb_missing"


def test_clear_rejects_unknown_knowledge_base(client):
    response = client.post(
        "/api/clear?knowledge_base_id=kb_missing",
        headers={"X-Request-ID": "test-missing-kb-clear"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"
    assert body["error"]["request_id"] == "test-missing-kb-clear"
    assert body["error"]["details"]["knowledge_base_id"] == "kb_missing"


def test_generated_request_id_is_returned(client):
    response = client.get("/api/sessions/not-exist")

    assert response.status_code == 404
    assert response.headers.get("X-Request-ID")
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_list_knowledge_bases_includes_default(client):
    response = client.get(
        "/api/knowledge-bases",
        headers={"X-Request-ID": "test-list-kb"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert any(item["knowledge_base_id"] == "kb_default" for item in body["items"])


def test_create_knowledge_base_validates_name(client):
    response = client.post(
        "/api/knowledge-bases",
        json={"name": "   "},
        headers={"X-Request-ID": "test-invalid-kb-name"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_KNOWLEDGE_BASE_NAME"
    assert body["error"]["request_id"] == "test-invalid-kb-name"


def test_knowledge_bases_are_filtered_by_tenant(client):
    create_response = client.post(
        "/api/knowledge-bases",
        json={"name": "租户 A 资料"},
        headers={
            "X-Request-ID": "test-create-tenant-kb",
            "X-Tenant-ID": "tenant_a",
            "X-User-ID": "user_a",
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["tenant_id"] == "tenant_a"
    assert created["created_by"] == "user_a"

    tenant_a_response = client.get(
        "/api/knowledge-bases",
        headers={"X-Tenant-ID": "tenant_a"},
    )
    tenant_b_response = client.get(
        "/api/knowledge-bases",
        headers={"X-Tenant-ID": "tenant_b"},
    )

    assert any(
        item["knowledge_base_id"] == created["knowledge_base_id"]
        for item in tenant_a_response.json()["items"]
    )
    assert not any(
        item["knowledge_base_id"] == created["knowledge_base_id"]
        for item in tenant_b_response.json()["items"]
    )


def test_cross_tenant_knowledge_base_access_is_hidden(client):
    create_response = client.post(
        "/api/knowledge-bases",
        json={"name": "租户隔离资料"},
        headers={"X-Tenant-ID": "tenant_owner"},
    )
    assert create_response.status_code == 200
    knowledge_base_id = create_response.json()["knowledge_base_id"]

    response = client.get(
        f"/api/knowledge-bases/{knowledge_base_id}/documents",
        headers={
            "X-Request-ID": "test-cross-tenant-docs",
            "X-Tenant-ID": "tenant_other",
        },
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"


def test_chat_rejects_unknown_knowledge_base(client):
    response = client.post(
        "/api/chat",
        json={
            "query": "hello",
            "search_mode": "hybrid",
            "knowledge_base_id": "kb_missing",
        },
        headers={"X-Request-ID": "test-chat-missing-kb"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "KNOWLEDGE_BASE_NOT_FOUND"
    assert body["error"]["request_id"] == "test-chat-missing-kb"


def test_chat_initializes_default_knowledge_base(client, monkeypatch):
    class DummyAssembler:
        async def prepare(self, **kwargs):
            raise AssertionError("chat should pass knowledge base validation first")

    async def fake_get_assembler():
        return DummyAssembler()

    import app.api.routes_chat as routes_chat

    monkeypatch.setattr(routes_chat, "get_assembler", fake_get_assembler)

    with pytest.raises(AssertionError):
        client.post(
            "/api/chat",
            json={"query": "hello", "search_mode": "hybrid"},
            headers={"X-Request-ID": "test-chat-default-kb"},
        )

    response = client.get("/api/knowledge-bases")
    assert any(
        item["knowledge_base_id"] == "kb_default"
        for item in response.json()["items"]
    )
