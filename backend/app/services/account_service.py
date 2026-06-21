import base64
import hashlib
import hmac
import os
import re
import time
from uuid import uuid4

from app.core.config import settings
from app.core.exceptions import AppError
from app.models.domain import (
    Tenant,
    TenantMembership,
    TenantRole,
    UserAccount,
    UserStatus,
)
from app.repositories.account_repository import AccountRepository, get_account_repository


DEFAULT_INITIAL_ROLE = TenantRole.OWNER.value
MEMBERSHIP_STATUS_ACTIVE = "active"
MEMBERSHIP_STATUS_DISABLED = "disabled"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_tenant_role(role: str) -> str:
    normalized = role.strip().lower()
    allowed_roles = {item.value for item in TenantRole}
    if normalized not in allowed_roles:
        raise AppError(
            code="INVALID_TENANT_ROLE",
            message="成员角色无效",
            status_code=400,
            details={"allowed_roles": sorted(allowed_roles), "role": role},
        )
    return normalized


def slugify_tenant_name(name: str) -> str:
    raw = name.strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
    return slug or f"tenant-{uuid4().hex[:8]}"


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hash_password(
            password,
            salt=base64.b64decode(salt.encode("ascii")),
        ).split("$", 3)[3]
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


class AccountService:
    """Account identity service for tenants, users, and memberships."""

    def __init__(self, repository: AccountRepository):
        self.repository = repository

    async def create_tenant(self, name: str, slug: str | None = None) -> Tenant:
        now = time.time()
        tenant = Tenant(
            tenant_id=f"tenant_{uuid4().hex[:12]}",
            name=name.strip(),
            slug=slug or slugify_tenant_name(name),
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_tenant(tenant)
        return tenant

    async def create_user(
        self,
        *,
        username: str,
        email: str,
        display_name: str = "",
        password_hash: str = "",
    ) -> UserAccount:
        now = time.time()
        user = UserAccount(
            user_id=f"user_{uuid4().hex[:12]}",
            username=normalize_username(username),
            email=normalize_email(email),
            display_name=display_name.strip(),
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_user(user)
        return user

    async def add_membership(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: str = TenantRole.MEMBER.value,
    ) -> TenantMembership:
        now = time.time()
        membership = TenantMembership(
            membership_id=f"membership_{uuid4().hex[:12]}",
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_membership(membership)
        return membership

    async def create_or_attach_member(
        self,
        *,
        tenant_id: str,
        username: str,
        email: str,
        display_name: str = "",
        role: str = TenantRole.MEMBER.value,
    ) -> tuple[UserAccount, TenantMembership]:
        normalized_username = normalize_username(username)
        normalized_email = normalize_email(email)
        if not normalized_username:
            raise AppError(
                code="USERNAME_REQUIRED",
                message="用户名不能为空",
                status_code=400,
            )
        if not normalized_email:
            raise AppError(
                code="EMAIL_REQUIRED",
                message="邮箱不能为空",
                status_code=400,
            )

        role = validate_tenant_role(role)
        user_by_username = await self.get_user_by_username(normalized_username)
        user_by_email = await self.get_user_by_email(normalized_email)
        if user_by_username and user_by_email and user_by_username.user_id != user_by_email.user_id:
            raise AppError(
                code="ACCOUNT_IDENTITY_CONFLICT",
                message="用户名和邮箱已分别绑定不同账号",
                status_code=409,
            )

        user = user_by_username or user_by_email
        if user is None:
            user = await self.create_user(
                username=normalized_username,
                email=normalized_email,
                display_name=display_name,
            )

        membership = await self.repository.get_membership(
            tenant_id=tenant_id,
            user_id=user.user_id,
        )
        now = time.time()
        if membership is None:
            membership = TenantMembership(
                membership_id=f"membership_{uuid4().hex[:12]}",
                tenant_id=tenant_id,
                user_id=user.user_id,
                role=role,
                status=MEMBERSHIP_STATUS_ACTIVE,
                created_at=now,
                updated_at=now,
            )
        else:
            membership.role = role
            membership.status = MEMBERSHIP_STATUS_ACTIVE
            membership.updated_at = now

        await self.repository.save_membership(membership)
        return user, membership

    async def list_members_for_tenant(
        self,
        tenant_id: str,
    ) -> list[tuple[UserAccount, TenantMembership]]:
        memberships = await self.repository.list_memberships_for_tenant(tenant_id)
        results: list[tuple[UserAccount, TenantMembership]] = []
        for membership in memberships:
            user = await self.repository.get_user(membership.user_id)
            if user is not None:
                results.append((user, membership))
        return results

    async def change_member_role(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: str,
    ) -> TenantMembership:
        membership = await self.repository.get_membership(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if membership is None:
            raise AppError(
                code="MEMBERSHIP_NOT_FOUND",
                message="成员关系不存在",
                status_code=404,
            )
        membership.role = validate_tenant_role(role)
        membership.status = MEMBERSHIP_STATUS_ACTIVE
        membership.updated_at = time.time()
        await self.repository.save_membership(membership)
        return membership

    async def disable_member(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> TenantMembership:
        membership = await self.repository.get_membership(
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if membership is None:
            raise AppError(
                code="MEMBERSHIP_NOT_FOUND",
                message="成员关系不存在",
                status_code=404,
            )
        membership.status = MEMBERSHIP_STATUS_DISABLED
        membership.updated_at = time.time()
        await self.repository.save_membership(membership)
        return membership

    async def bootstrap_tenant_owner(
        self,
        *,
        tenant_name: str,
        username: str,
        email: str,
        display_name: str = "",
        password_hash: str = "",
    ) -> tuple[Tenant, UserAccount, TenantMembership]:
        tenant = await self.create_tenant(tenant_name)
        user = await self.create_user(
            username=username,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
        )
        membership = await self.add_membership(
            tenant_id=tenant.tenant_id,
            user_id=user.user_id,
            role=DEFAULT_INITIAL_ROLE,
        )
        return tenant, user, membership

    async def get_user_by_email(self, email: str) -> UserAccount | None:
        return await self.repository.get_user_by_email(normalize_email(email))

    async def get_user_by_username(self, username: str) -> UserAccount | None:
        return await self.repository.get_user_by_username(normalize_username(username))

    async def authenticate_user(
        self,
        *,
        username: str,
        password: str,
    ) -> tuple[UserAccount, list[TenantMembership]] | None:
        user = await self.get_user_by_username(username)
        if user is None or user.status != UserStatus.ACTIVE.value:
            return None
        if not verify_password(password, user.password_hash):
            return None
        memberships = await self.list_memberships_for_user(user.user_id)
        return user, memberships

    async def list_memberships_for_user(self, user_id: str) -> list[TenantMembership]:
        return await self.repository.list_memberships_for_user(user_id)

    async def ensure_seed_default_user(self) -> UserAccount | None:
        if not settings.seed_default_user_enabled:
            return None
        username = settings.seed_default_username
        password = settings.secret_value(settings.seed_default_password)
        if not username or not password:
            raise AppError(
                code="SEED_DEFAULT_USER_CONFIG_INVALID",
                message="默认测试账号配置不完整",
                status_code=500,
            )

        existing = await self.get_user_by_username(username)
        if existing is not None:
            return existing

        tenant, user, _membership = await self.bootstrap_tenant_owner(
            tenant_name=settings.seed_default_tenant_name,
            username=username,
            email=f"{normalize_username(username)}@local.test",
            display_name=username,
            password_hash=hash_password(password),
        )
        return user


async def get_account_service() -> AccountService:
    repository = await get_account_repository()
    return AccountService(repository)
