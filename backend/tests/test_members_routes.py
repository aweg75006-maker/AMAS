from uuid import uuid4

from app.core.config import settings
from app.core.security import create_access_token
from app.models.domain import TenantRole


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


def test_owner_can_manage_members_without_leaking_password(client):
    login = _login_seed_user(client)
    token = login["access_token"]
    suffix = uuid4().hex[:10]

    created = client.post(
        "/api/members",
        json={
            "username": f"api_member_{suffix}",
            "email": f"api-member-{suffix}@example.com",
            "display_name": "API Member",
            "role": TenantRole.VIEWER.value,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "success"
    assert body["member"]["membership"]["role"] == TenantRole.VIEWER.value
    assert "password" not in str(body).lower()
    user_id = body["member"]["user"]["user_id"]

    listed = client.get(
        "/api/members",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert listed.status_code == 200
    listed_body = listed.json()
    assert any(
        item["user"]["user_id"] == user_id
        for item in listed_body["members"]
    )
    assert "password" not in str(listed_body).lower()

    updated = client.patch(
        f"/api/members/{user_id}/role",
        json={"role": TenantRole.ADMIN.value},
        headers={"Authorization": f"Bearer {token}"},
    )
    disabled = client.post(
        f"/api/members/{user_id}/disable",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert updated.status_code == 200
    assert updated.json()["membership"]["role"] == TenantRole.ADMIN.value
    assert disabled.status_code == 200
    assert disabled.json()["membership"]["status"] == "disabled"


def test_member_management_requires_jwt_not_header_fallback(client):
    response = client.get(
        "/api/members",
        headers={
            "X-Tenant-ID": "tenant_header_only",
            "X-User-ID": "user_header_only",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_viewer_token_cannot_manage_members(client):
    token = create_access_token(
        user_id="user_viewer",
        username="viewer",
        tenant_id="tenant_rbac",
        role=TenantRole.VIEWER.value,
        expires_in=60,
    )

    response = client.post(
        "/api/members",
        json={
            "username": "blocked_member",
            "email": "blocked-member@example.com",
            "role": TenantRole.MEMBER.value,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
