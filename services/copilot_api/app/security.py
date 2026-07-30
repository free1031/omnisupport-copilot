from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, status

from app.config import settings
from app.db import acquire

PASSWORD_ITERATIONS = 310_000


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _b64decode(salt), int(iterations)
        )
        return hmac.compare_digest(_b64encode(actual), expected)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    email: str
    display_name: str
    role: str


def create_access_token(principal: Principal) -> str:
    now = int(time.time())
    payload = {
        "sub": principal.user_id,
        "tenant_id": principal.tenant_id,
        "email": principal.email,
        "name": principal.display_name,
        "role": principal.role,
        "iat": now,
        "exp": now + settings.auth_token_ttl_seconds,
        "jti": secrets.token_hex(12),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64encode(
        hmac.new(settings.auth_signing_key.encode(), body.encode(), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        body, signature = token.split(".", 1)
        expected = _b64encode(
            hmac.new(settings.auth_signing_key.encode(), body.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(_b64decode(body))
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("expired token")
        return payload
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from exc


async def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_token")
    payload = decode_access_token(authorization[7:])
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, tenant_id, email, display_name, role
            FROM app_user
            WHERE user_id = $1 AND active = TRUE
            """,
            payload["sub"],
        )
    if row is None or row["tenant_id"] != payload["tenant_id"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="inactive_user")
    return Principal(**dict(row))


def require_roles(principal: Principal, *roles: str) -> None:
    if principal.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="role_denied")


async def ensure_demo_users() -> None:
    users = [
        (
            "usr_demo_agent",
            settings.demo_agent_email,
            "Lin Chen",
            "support_agent",
            settings.demo_agent_password,
        ),
        (
            "usr_demo_admin",
            settings.demo_admin_email,
            "Morgan Lee",
            "admin",
            settings.demo_admin_password,
        ),
    ]
    async with acquire() as conn:
        for user_id, email, display_name, role, password in users:
            exists = await conn.fetchval("SELECT 1 FROM app_user WHERE user_id = $1", user_id)
            if not exists:
                await conn.execute(
                    """
                    INSERT INTO app_user (
                        user_id, tenant_id, email, display_name, role, password_hash
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    user_id,
                    settings.demo_tenant_id,
                    email,
                    display_name,
                    role,
                    hash_password(password),
                )
