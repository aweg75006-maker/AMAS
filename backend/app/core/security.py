import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.core.config import settings
from app.core.exceptions import AppError


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _json_b64(data: dict[str, Any]) -> str:
    return _b64url_encode(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def create_access_token(
    *,
    user_id: str,
    username: str,
    tenant_id: str,
    role: str,
    expires_in: int | None = None,
) -> str:
    now = int(time.time())
    ttl = expires_in or settings.jwt_access_token_ttl_seconds
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "username": username,
        "tenant_id": tenant_id,
        "role": role,
        "iat": now,
        "exp": now + ttl,
    }
    signing_input = f"{_json_b64(header)}.{_json_b64(payload)}"
    signature = hmac.new(
        settings.jwt_secret().encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".", 2)
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(
            settings.jwt_secret().encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = _b64url_decode(signature_b64)
        if not hmac.compare_digest(actual, expected):
            raise ValueError("invalid signature")
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            raise ValueError("unsupported alg")
        payload = json.loads(_b64url_decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("token expired")
        return payload
    except Exception as exc:
        raise AppError(
            code="INVALID_ACCESS_TOKEN",
            message="登录令牌无效或已过期",
            status_code=401,
        ) from exc
