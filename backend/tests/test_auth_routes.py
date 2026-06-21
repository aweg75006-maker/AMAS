import asyncio

from app.core.config import settings
from app.core.security import create_access_token, decode_access_token
from app.models.domain import AuditAction
from app.repositories.audit_repository import PostgresAuditRepository


def _load_audit_logs(tenant_id: str, limit: int = 50):
    dsn = settings.secret_value(settings.postgres_dsn)
    assert dsn

    async def load_logs():
        repository = PostgresAuditRepository(dsn)
        await repository.connect()
        try:
            return await repository.list_audit_logs_for_tenant(tenant_id, limit=limit)
        finally:
            await repository.close()

    return asyncio.run(load_logs())


def test_login_rejects_invalid_credentials(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "missing-user", "password": "wrong-password"},
        headers={"X-Request-ID": "test-invalid-login"},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "INVALID_CREDENTIALS"
    assert body["error"]["request_id"] == "test-invalid-login"


def test_seed_default_user_can_login_without_leaking_password(client):
    username = settings.seed_default_username
    password = settings.secret_value(settings.seed_default_password)
    assert username
    assert password

    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"X-Request-ID": "test-seed-login"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == username
    assert body["memberships"]
    payload = decode_access_token(body["access_token"])
    assert payload["sub"] == body["user"]["user_id"]
    assert payload["tenant_id"] == body["active_tenant_id"]
    assert "password" not in str(body).lower()
    assert password not in str(body)

    logs = _load_audit_logs(body["active_tenant_id"])
    assert any(log.action == AuditAction.LOGIN_SUCCEEDED.value for log in logs)


def test_bearer_token_controls_request_context(client):
    username = settings.seed_default_username
    password = settings.secret_value(settings.seed_default_password)
    assert username
    assert password

    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    tenant_id = login.json()["active_tenant_id"]

    response = client.post(
        "/api/knowledge-bases",
        json={"name": "JWT 租户资料"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": "forged_tenant",
            "X-User-ID": "forged_user",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant_id
    assert body["created_by"] == login.json()["user"]["user_id"]


def test_viewer_token_cannot_create_knowledge_base(client):
    token = create_access_token(
        user_id="user_viewer",
        username="viewer",
        tenant_id="tenant_rbac",
        role="viewer",
        expires_in=60,
    )

    response = client.post(
        "/api/knowledge-bases",
        json={"name": "Should be blocked"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-ID": "test-viewer-forbidden",
        },
    )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "FORBIDDEN"
    assert body["error"]["request_id"] == "test-viewer-forbidden"


def test_owner_token_can_create_knowledge_base(client):
    token = create_access_token(
        user_id="user_owner",
        username="owner",
        tenant_id="tenant_rbac_owner",
        role="owner",
        expires_in=60,
    )

    response = client.post(
        "/api/knowledge-bases",
        json={"name": "Owner KB"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_rbac_owner"
    assert body["created_by"] == "user_owner"
