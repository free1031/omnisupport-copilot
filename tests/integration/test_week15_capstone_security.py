from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_service_snippet(service: str, code: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(ROOT / f"services/{service}") + os.pathsep + str(ROOT),
            "OTEL_ENABLED": "false",
            **overrides,
        }
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_password_hash_and_signed_access_token_roundtrip_in_product_runtime():
    code = r'''
from app.security import Principal, create_access_token, decode_access_token, hash_password, verify_password

encoded = hash_password("Agent@2026", salt=b"0123456789abcdef")
assert verify_password("Agent@2026", encoded)
assert not verify_password("wrong-password", encoded)
principal = Principal("usr_test", "tenant_test", "agent@example.test", "Test Agent", "support_agent")
token = create_access_token(principal)
payload = decode_access_token(token)
assert payload["sub"] == "usr_test"
assert payload["tenant_id"] == "tenant_test"
assert payload["role"] == "support_agent"
print("security-roundtrip-pass")
'''
    result = _run_service_snippet("copilot_api", code)
    assert result.returncode == 0, result.stderr
    assert "security-roundtrip-pass" in result.stdout


def test_rag_and_tool_internal_auth_fail_closed_in_product_mode():
    code = r'''
import asyncio
from fastapi import HTTPException
from app.internal_auth import require_internal_request

async def main():
    try:
        await require_internal_request(None, None, None, None)
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "invalid_service_token"
    else:
        raise AssertionError("missing service token was accepted")

    principal = await require_internal_request(
        "internal-test-token", "actor-1", "support_agent", "tenant-1"
    )
    assert principal.actor_id == "actor-1"
    assert principal.actor_role == "support_agent"
    assert principal.tenant_id == "tenant-1"
    print("internal-auth-pass")

asyncio.run(main())
'''
    for service in ("rag_api", "tool_api"):
        result = _run_service_snippet(
            service,
            code,
            REQUIRE_INTERNAL_AUTH="true",
            INTERNAL_SERVICE_TOKEN="internal-test-token",
        )
        assert result.returncode == 0, f"{service}: {result.stderr}"
        assert "internal-auth-pass" in result.stdout


def test_tool_idempotency_lock_is_deterministic_and_tenant_scoped():
    code = r'''
from app.routers.tickets import _idempotency_lock_id

first = _idempotency_lock_id("tenant-a", "ticket_update", "same-key")
assert first == _idempotency_lock_id("tenant-a", "ticket_update", "same-key")
assert first != _idempotency_lock_id("tenant-b", "ticket_update", "same-key")
assert first != _idempotency_lock_id("tenant-a", "create_ticket", "same-key")
print("tenant-lock-pass")
'''
    result = _run_service_snippet("tool_api", code)
    assert result.returncode == 0, result.stderr
    assert "tenant-lock-pass" in result.stdout
