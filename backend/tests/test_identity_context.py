import pytest

from app.api.context import get_request_context
from app.core.identity import DEFAULT_TENANT_ID, DEFAULT_USER_ID, clean_context_id
from app.core.security import create_access_token


def test_clean_context_id_defaults_and_sanitizes():
    assert clean_context_id(None, DEFAULT_TENANT_ID) == DEFAULT_TENANT_ID
    assert clean_context_id(" tenant/a b ", DEFAULT_TENANT_ID) == "tenant_a_b"
    assert clean_context_id("x" * 80, DEFAULT_TENANT_ID) == "x" * 64


@pytest.mark.asyncio
async def test_get_request_context_from_headers():
    context = await get_request_context(
        x_tenant_id="tenant-a",
        x_user_id="user/one",
    )

    assert context.tenant_id == "tenant-a"
    assert context.user_id == "user_one"


@pytest.mark.asyncio
async def test_get_request_context_defaults():
    context = await get_request_context(x_tenant_id=None, x_user_id=None)

    assert context.tenant_id == DEFAULT_TENANT_ID
    assert context.user_id == DEFAULT_USER_ID


@pytest.mark.asyncio
async def test_get_request_context_prefers_bearer_token():
    token = create_access_token(
        user_id="user_token",
        username="token-user",
        tenant_id="tenant_token",
        role="owner",
        expires_in=60,
    )

    context = await get_request_context(
        authorization=f"Bearer {token}",
        x_tenant_id="tenant_header",
        x_user_id="user_header",
    )

    assert context.tenant_id == "tenant_token"
    assert context.user_id == "user_token"
    assert context.username == "token-user"
    assert context.role == "owner"
    assert context.auth_source == "jwt"
