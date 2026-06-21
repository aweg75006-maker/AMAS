import time

import pytest

from app.core.exceptions import AppError
from app.core.security import create_access_token, decode_access_token


def test_access_token_round_trip():
    token = create_access_token(
        user_id="user_1",
        username="yzz",
        tenant_id="tenant_1",
        role="owner",
        expires_in=60,
    )

    payload = decode_access_token(token)

    assert payload["sub"] == "user_1"
    assert payload["username"] == "yzz"
    assert payload["tenant_id"] == "tenant_1"
    assert payload["role"] == "owner"


def test_access_token_rejects_tampering():
    token = create_access_token(
        user_id="user_1",
        username="yzz",
        tenant_id="tenant_1",
        role="owner",
        expires_in=60,
    )
    tampered = token.rsplit(".", 1)[0] + ".invalid"

    with pytest.raises(AppError):
        decode_access_token(tampered)


def test_access_token_rejects_expired_token():
    token = create_access_token(
        user_id="user_1",
        username="yzz",
        tenant_id="tenant_1",
        role="owner",
        expires_in=-1,
    )
    time.sleep(0.01)

    with pytest.raises(AppError):
        decode_access_token(token)
