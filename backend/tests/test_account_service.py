import pytest
from uuid import uuid4

from app.core.config import settings
from app.models.domain import TenantRole
from app.repositories.account_repository import PostgresAccountRepository
from app.services.account_service import (
    AccountService,
    hash_password,
    normalize_email,
    normalize_username,
    slugify_tenant_name,
    verify_password,
)


def test_normalize_email_and_slugify_tenant_name():
    assert normalize_email(" USER@Example.COM ") == "user@example.com"
    assert normalize_username(" YZZ ") == "yzz"
    assert slugify_tenant_name("Acme Research Team") == "acme-research-team"


def test_hash_password_verifies_without_plaintext_storage():
    password_hash = hash_password("secret")

    assert password_hash.startswith("pbkdf2_sha256$")
    assert "secret" not in password_hash
    assert verify_password("secret", password_hash)
    assert not verify_password("wrong", password_hash)


@pytest.mark.asyncio
async def test_bootstrap_tenant_owner_with_postgres_repository():
    dsn = settings.secret_value(settings.postgres_dsn)
    assert dsn

    repository = PostgresAccountRepository(dsn)
    await repository.connect()
    service = AccountService(repository)

    tenant, user, membership = await service.bootstrap_tenant_owner(
        tenant_name=f"测试租户-{id(repository)}",
        username=f"owner_{id(repository)}",
        email=f"owner-{id(repository)}@example.com",
        display_name="Owner",
        password_hash="hash-placeholder",
    )

    restored_user = await service.get_user_by_email(user.email)
    memberships = await service.list_memberships_for_user(user.user_id)

    assert tenant.name.startswith("测试租户-")
    assert restored_user is not None
    assert restored_user.user_id == user.user_id
    assert restored_user.password_hash == "hash-placeholder"
    assert membership.role == TenantRole.OWNER.value
    assert any(item.tenant_id == tenant.tenant_id for item in memberships)


@pytest.mark.asyncio
async def test_authenticate_user_with_hashed_password():
    dsn = settings.secret_value(settings.postgres_dsn)
    assert dsn

    repository = PostgresAccountRepository(dsn)
    await repository.connect()
    service = AccountService(repository)
    suffix = uuid4().hex[:10]
    username = f"login_{suffix}"

    _tenant, user, _membership = await service.bootstrap_tenant_owner(
        tenant_name=f"登录测试租户-{suffix}",
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("correct-password"),
    )

    assert await service.authenticate_user(
        username=username,
        password="wrong-password",
    ) is None
    result = await service.authenticate_user(
        username=username,
        password="correct-password",
    )

    assert result is not None
    restored_user, memberships = result
    assert restored_user.user_id == user.user_id
    assert memberships


@pytest.mark.asyncio
async def test_member_lifecycle_with_postgres_repository():
    dsn = settings.secret_value(settings.postgres_dsn)
    assert dsn

    repository = PostgresAccountRepository(dsn)
    await repository.connect()
    service = AccountService(repository)
    suffix = uuid4().hex[:10]

    tenant, _owner, _owner_membership = await service.bootstrap_tenant_owner(
        tenant_name=f"成员测试租户-{suffix}",
        username=f"member_owner_{suffix}",
        email=f"member-owner-{suffix}@example.com",
        password_hash=hash_password("owner-password"),
    )

    member_user, member_membership = await service.create_or_attach_member(
        tenant_id=tenant.tenant_id,
        username=f"member_{suffix}",
        email=f"member-{suffix}@example.com",
        display_name="Member",
        role=TenantRole.VIEWER.value,
    )
    members = await service.list_members_for_tenant(tenant.tenant_id)

    assert member_membership.role == TenantRole.VIEWER.value
    assert any(user.user_id == member_user.user_id for user, _membership in members)

    updated = await service.change_member_role(
        tenant_id=tenant.tenant_id,
        user_id=member_user.user_id,
        role=TenantRole.ADMIN.value,
    )
    disabled = await service.disable_member(
        tenant_id=tenant.tenant_id,
        user_id=member_user.user_id,
    )

    assert updated.role == TenantRole.ADMIN.value
    assert disabled.status == "disabled"
