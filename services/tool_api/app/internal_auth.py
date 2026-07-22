from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from app.config import settings


@dataclass(frozen=True)
class InternalPrincipal:
    actor_id: str | None
    actor_role: str | None
    tenant_id: str | None


async def require_internal_request(
    x_service_token: str | None = Header(default=None),
    x_actor_id: str | None = Header(default=None),
    x_actor_role: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
) -> InternalPrincipal:
    """Authenticate service-to-service tool calls in the product runtime.

    Week-specific unit tests can keep REQUIRE_INTERNAL_AUTH=false. The product
    Compose path sets it to true and therefore fails closed on missing actor or
    tenant context.
    """

    if settings.require_internal_auth:
        if not x_service_token or not hmac.compare_digest(
            x_service_token, settings.internal_service_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_service_token",
            )
        if not x_actor_id or not x_actor_role or not x_tenant_id:
            raise HTTPException(status_code=400, detail="missing_actor_context")
    elif x_tenant_id and (
        not x_service_token
        or not hmac.compare_digest(x_service_token, settings.internal_service_token)
    ):
        # Even in classroom mode, callers cannot spoof a tenant header.
        raise HTTPException(status_code=403, detail="invalid_service_token")

    return InternalPrincipal(x_actor_id, x_actor_role, x_tenant_id)
