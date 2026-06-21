from app.core.config import settings
from app.core.security import create_access_token
from app.models.domain import AuditAction, TenantRole


def _login_seed_user(client):
    username = settings.seed_default_username
    password = settings.secret_value(settings.seed_default_password)
    assert username
    assert password

    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()


def test_owner_can_list_audit_logs(client):
    login = _login_seed_user(client)
    token = login["access_token"]

    response = client.get(
        "/api/audit-logs",
        params={"limit": 20, "action": AuditAction.LOGIN_SUCCEEDED.value},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == login["active_tenant_id"]
    assert any(
        item["action"] == AuditAction.LOGIN_SUCCEEDED.value
        for item in body["items"]
    )


def test_audit_logs_require_jwt_not_header_fallback(client):
    response = client.get(
        "/api/audit-logs",
        headers={
            "X-Tenant-ID": "tenant_header_only",
            "X-User-ID": "user_header_only",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_viewer_token_cannot_list_audit_logs(client):
    token = create_access_token(
        user_id="user_viewer",
        username="viewer",
        tenant_id="tenant_rbac",
        role=TenantRole.VIEWER.value,
        expires_in=60,
    )

    response = client.get(
        "/api/audit-logs",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
