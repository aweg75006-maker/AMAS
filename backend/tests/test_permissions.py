import pytest

from app.api.permissions import READ_ROLES, WRITE_ROLES, require_roles
from app.core.exceptions import AppError
from app.core.identity import RequestContext


@pytest.mark.asyncio
async def test_require_roles_allows_header_fallback_for_local_dev():
    dependency = require_roles(WRITE_ROLES)
    context = RequestContext(tenant_id="default", user_id="local", auth_source="headers")

    assert await dependency(context) == context


@pytest.mark.asyncio
async def test_require_roles_rejects_missing_jwt_role():
    dependency = require_roles(WRITE_ROLES)
    context = RequestContext(
        tenant_id="tenant_1",
        user_id="user_1",
        role="viewer",
        auth_source="jwt",
    )

    with pytest.raises(AppError) as exc:
        await dependency(context)

    assert exc.value.code == "FORBIDDEN"


def test_rbac_role_sets_are_distinct():
    assert "owner" in WRITE_ROLES
    assert "admin" in WRITE_ROLES
    assert "viewer" not in WRITE_ROLES
    assert "viewer" in READ_ROLES
