"""Week05 governed KPI query endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.internal_auth import InternalPrincipal, require_internal_request
from app.kpi_query import query_support_kpis

router = APIRouter(tags=["kpis"])


@router.post("/query_support_kpis")
async def query_support_kpis_endpoint(
    payload: dict[str, Any],
    request: Request,
    principal: InternalPrincipal = Depends(require_internal_request),
) -> dict[str, Any]:
    payload.setdefault("actor_id", principal.actor_id or request.headers.get("X-Actor-ID"))
    if principal.actor_role:
        payload["actor_role"] = principal.actor_role
    if principal.tenant_id:
        payload["tenant_id"] = principal.tenant_id
    return await query_support_kpis(payload)
