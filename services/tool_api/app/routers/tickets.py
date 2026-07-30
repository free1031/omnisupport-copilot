"""Persistent governed ticket tools used by the Week15 product control plane."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import jsonschema
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from agent.hitl import HITLPolicy
from app.config import settings
from app.db import acquire
from app.internal_auth import InternalPrincipal, require_internal_request
from observability.runtime import current_trace_id, traced_span

router = APIRouter(tags=["ticket-tools"])
approval_router = APIRouter(tags=["approvals"])


class GetTicketRequest(BaseModel):
    ticket_id: str = Field(..., pattern=r"^TKT-[0-9]{8}-[0-9A-Z]{6}$")
    include_comments: bool = False


class CreateTicketRequest(BaseModel):
    subject: str = Field(..., max_length=512)
    description: str = Field(..., max_length=8192)
    priority: str = Field(..., pattern=r"^p[1-4]_(critical|high|medium|low)$")
    product_line: str
    category: str
    product_version: str | None = None
    error_codes: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=8, max_length=160)


class TicketUpdateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    ticket_id: str
    operation: Literal[
        "add_internal_note",
        "update_status",
        "change_priority",
        "assign_agent",
        "grant_service_credit",
        "refund_payment",
    ]
    reason: str
    actor_id: str | None = None
    actor_role: str
    risk_level: str
    new_status: str | None = None
    new_priority: str | None = None
    assignee_id: str | None = None
    amount_cents: int | None = None
    currency: str = "USD"
    evidence_ids: list[str] = Field(default_factory=list)
    data_snapshot_id: str | None = None
    data_release_id: str | None = None
    prompt_release_id: str | None = None
    model_version: str | None = None
    skill_release_id: str | None = None
    idempotency_key: str
    trace_id: str


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = Field(min_length=5, max_length=1000)


def _contract(name: str) -> dict[str, Any]:
    path = Path(settings.tool_contracts_path) / f"{name}.json"
    if not path.exists():
        local = Path(__file__).resolve().parents[4] / "contracts" / "tools" / "tools" / f"{name}.json"
        path = local
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_digest(payload: dict[str, Any]) -> str:
    stable = {key: value for key, value in payload.items() if key not in {"trace_id"}}
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _idempotency_lock_id(tenant_id: str, tool_name: str, key: str) -> int:
    digest = hashlib.sha256(f"{tenant_id}\0{tool_name}\0{key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def _lock_idempotency_key(
    conn,
    *,
    tenant_id: str,
    tool_name: str,
    key: str,
) -> None:
    # Serialize identical tenant/tool/key requests for the current transaction.
    await conn.execute(
        "SELECT pg_advisory_xact_lock($1)",
        _idempotency_lock_id(tenant_id, tool_name, key),
    )


def _actor_context(
    principal: InternalPrincipal,
    *,
    fallback_actor_id: str | None = None,
    fallback_actor_role: str | None = None,
) -> tuple[str, str, str]:
    actor_id = principal.actor_id or fallback_actor_id
    actor_role = principal.actor_role or fallback_actor_role
    tenant_id = principal.tenant_id or settings.default_tenant_id
    if not actor_id or not actor_role:
        raise HTTPException(status_code=400, detail="missing_actor_context")
    return actor_id, actor_role, tenant_id


async def _write_audit(
    conn,
    *,
    request_id: str,
    actor: str,
    tool_name: str,
    payload: dict[str, Any],
    result_code: str,
    hitl: bool,
    trace_id: str,
    tenant_id: str,
) -> str:
    audit_id = f"audit_{uuid.uuid4().hex}"
    await conn.execute(
        """
        INSERT INTO audit_log (
            log_id, request_id, actor, tool_name, args_hash, result_code,
            hitl_triggered, release_id, trace_id, tenant_id
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """,
        audit_id,
        request_id,
        actor,
        tool_name,
        _canonical_digest(payload),
        result_code,
        hitl,
        settings.release_id,
        trace_id,
        tenant_id,
    )
    return audit_id


async def _write_lineage(
    conn,
    *,
    payload: dict[str, Any],
    tenant_id: str,
    status_value: str,
    approval_id: str | None = None,
    audit_id: str | None = None,
    output_ref: str | None = None,
) -> str:
    with traced_span(
        "agent.lineage.persist",
        kind="CHAIN",
        attributes={
            "tool.name": "ticket_update",
            "omni.action.status": status_value,
            "omni.business_trace_id": payload["trace_id"],
        },
    ):
        event_id = f"act_{uuid.uuid4().hex[:20]}"
        await conn.execute(
            """
            INSERT INTO agent_action_lineage (
                event_id, trace_id, actor_id, tool_name, tool_version, status,
                approval_id, audit_id, data_snapshot_id, evidence_ids,
                prompt_release_id, model_version, skill_release_id, payload_digest,
                output_ref, release_id, tenant_id
            ) VALUES ($1,$2,$3,'ticket_update','v1.0',$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            """,
            event_id,
            payload["trace_id"],
            payload.get("actor_id"),
            status_value,
            approval_id,
            audit_id,
            payload.get("data_snapshot_id") or payload.get("data_release_id"),
            payload.get("evidence_ids", []),
            payload.get("prompt_release_id"),
            payload.get("model_version"),
            payload.get("skill_release_id"),
            _canonical_digest(payload),
            output_ref,
            settings.release_id,
            tenant_id,
        )
    return event_id


async def _cached_result(
    conn,
    payload: dict[str, Any],
    *,
    tenant_id: str,
) -> dict[str, Any] | None:
    with traced_span(
        "tool.idempotency.check",
        kind="TOOL",
        attributes={"tool.name": "ticket_update"},
    ):
        row = await conn.fetchrow(
            """
            SELECT args_digest, result_payload, created_at
            FROM tool_idempotency
            WHERE tenant_id = $1
              AND tool_name = 'ticket_update'
              AND idempotency_key = $2
            """,
            tenant_id,
            payload["idempotency_key"],
        )
    if row is None:
        return None
    if row["args_digest"] != _canonical_digest(payload):
        raise HTTPException(status_code=409, detail="idempotency_conflict")
    stored_result = row["result_payload"]
    if isinstance(stored_result, str):
        stored_result = json.loads(stored_result)
    result = dict(stored_result)
    if result.get("status") == "completed":
        result["status"] = "cached"
        result["cached_from"] = row["created_at"].isoformat()
    return result


async def _remember_result(
    conn,
    payload: dict[str, Any],
    result: dict[str, Any],
    *,
    tenant_id: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO tool_idempotency (
            tenant_id, tool_name, idempotency_key, args_digest, result_payload,
            trace_id, release_id
        ) VALUES ($1,'ticket_update',$2,$3,$4::jsonb,$5,$6)
        ON CONFLICT (tenant_id, tool_name, idempotency_key) DO UPDATE SET
            result_payload = EXCLUDED.result_payload,
            trace_id = EXCLUDED.trace_id,
            release_id = EXCLUDED.release_id
        """,
        tenant_id,
        payload["idempotency_key"],
        _canonical_digest(payload),
        result,
        payload["trace_id"],
        settings.release_id,
    )


async def _perform_action(
    conn,
    *,
    payload: dict[str, Any],
    tenant_id: str,
    approval_id: str | None,
    request_id: str,
) -> dict[str, Any]:
    with traced_span(
        "tool.execute.ticket_update",
        kind="TOOL",
        attributes={
            "tool.name": "ticket_update",
            "omni.operation": payload["operation"],
            "omni.business_trace_id": payload["trace_id"],
        },
    ):
        return await _perform_action_inner(
            conn,
            payload=payload,
            tenant_id=tenant_id,
            approval_id=approval_id,
            request_id=request_id,
        )


async def _perform_action_inner(
    conn,
    *,
    payload: dict[str, Any],
    tenant_id: str,
    approval_id: str | None,
    request_id: str,
) -> dict[str, Any]:
    ticket = await conn.fetchrow(
        "SELECT ticket_id FROM ticket_fact WHERE ticket_id = $1 AND tenant_id = $2 FOR UPDATE",
        payload["ticket_id"],
        tenant_id,
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket_not_found")

    operation = payload["operation"]
    if operation == "add_internal_note":
        await conn.execute(
            """
            INSERT INTO ticket_comment_fact (comment_id, ticket_id, author_id, author_role, body)
            VALUES ($1,$2,$3,$4,$5)
            """,
            f"comment_{uuid.uuid4().hex}",
            payload["ticket_id"],
            payload.get("actor_id"),
            payload.get("actor_role"),
            payload["reason"],
        )
    elif operation == "update_status":
        if not payload.get("new_status"):
            raise HTTPException(status_code=422, detail="new_status_required")
        await conn.execute(
            """
            UPDATE ticket_fact SET status = $1::ticket_status, updated_at = NOW(),
                resolved_at = CASE WHEN $1 IN ('resolved','closed') THEN NOW() ELSE resolved_at END
            WHERE ticket_id = $2 AND tenant_id = $3
            """,
            payload["new_status"],
            payload["ticket_id"],
            tenant_id,
        )
    elif operation == "change_priority":
        if not payload.get("new_priority"):
            raise HTTPException(status_code=422, detail="new_priority_required")
        await conn.execute(
            "UPDATE ticket_fact SET priority = $1::ticket_priority, updated_at = NOW() WHERE ticket_id = $2 AND tenant_id = $3",
            payload["new_priority"],
            payload["ticket_id"],
            tenant_id,
        )
    elif operation == "assign_agent":
        if not payload.get("assignee_id"):
            raise HTTPException(status_code=422, detail="assignee_id_required")
        await conn.execute(
            "UPDATE ticket_fact SET assignee_id = $1, updated_at = NOW() WHERE ticket_id = $2 AND tenant_id = $3",
            payload["assignee_id"],
            payload["ticket_id"],
            tenant_id,
        )
    elif operation in {"grant_service_credit", "refund_payment"}:
        if payload.get("amount_cents") is None:
            raise HTTPException(status_code=422, detail="amount_cents_required")
        await conn.execute(
            """
            INSERT INTO financial_adjustment (
                adjustment_id, tenant_id, ticket_id, operation, amount_cents,
                currency, reason, actor_id, approval_id, trace_id
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            f"adj_{uuid.uuid4().hex}",
            tenant_id,
            payload["ticket_id"],
            operation,
            payload["amount_cents"],
            payload.get("currency", "USD"),
            payload["reason"],
            payload.get("actor_id") or "unknown",
            approval_id,
            payload["trace_id"],
        )

    audit_id = await _write_audit(
        conn,
        request_id=request_id,
        actor=payload.get("actor_id") or "unknown",
        tool_name="ticket_update",
        payload=payload,
        result_code="COMPLETED",
        hitl=bool(approval_id),
        trace_id=payload["trace_id"],
        tenant_id=tenant_id,
    )
    event_id = await _write_lineage(
        conn,
        payload=payload,
        tenant_id=tenant_id,
        status_value="completed",
        approval_id=approval_id,
        audit_id=audit_id,
        output_ref=payload["ticket_id"],
    )
    result = {
        "ticket_id": payload["ticket_id"],
        "operation": operation,
        "status": "completed",
        "trace_id": payload["trace_id"],
        "lineage_event_id": event_id,
        "release_id": settings.release_id,
        "approval_id": approval_id,
        "hitl_required": bool(approval_id),
    }
    await _remember_result(conn, payload, result, tenant_id=tenant_id)
    return result


@router.post("/get_ticket_status", summary="Query a governed ticket")
async def get_ticket_status(
    req: GetTicketRequest,
    http_request: Request,
    principal: InternalPrincipal = Depends(require_internal_request),
):
    request_id = getattr(http_request.state, "request_id", str(uuid.uuid4()))
    trace_id = current_trace_id() or request_id
    with traced_span(
        "tool.execute.get_ticket_status",
        kind="TOOL",
        attributes={"tool.name": "get_ticket_status", "omni.request_id": request_id},
    ):
        tenant_id = principal.tenant_id or settings.default_tenant_id
        async with acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT ticket_id, status::text, priority::text, category, product_line::text,
                       assignee_id, sla_due_at, created_at, updated_at, resolved_at
                FROM ticket_fact WHERE ticket_id = $1 AND tenant_id = $2
                """,
                req.ticket_id,
                tenant_id,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="ticket_not_found")
            comments = []
            if req.include_comments:
                comments = await conn.fetch(
                    """
                    SELECT comment_id, author_role, body_preview, created_at
                    FROM ticket_comment_fact WHERE ticket_id = $1 ORDER BY created_at DESC LIMIT 5
                    """,
                    req.ticket_id,
                )
    result = dict(row)
    result["comments"] = [dict(comment) for comment in comments]
    result.update({"trace_id": trace_id, "release_id": settings.release_id})
    return result


@router.post("/create_ticket", summary="Create a governed ticket", status_code=201)
async def create_ticket(
    req: CreateTicketRequest,
    http_request: Request,
    principal: InternalPrincipal = Depends(require_internal_request),
):
    actor_id, actor_role, tenant_id = _actor_context(principal)
    if actor_role not in {"support_agent", "support_lead", "support_ops", "admin"}:
        raise HTTPException(status_code=403, detail="role_denied")
    now = datetime.now(timezone.utc)
    ticket_id = f"TKT-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    trace_id = current_trace_id() or f"trace_{uuid.uuid4().hex}"
    request_payload = req.model_dump()
    request_digest = _canonical_digest(request_payload)
    tenant_suffix = hashlib.sha256(tenant_id.encode()).hexdigest()[:12]
    customer_id = f"cust-walkin-{tenant_suffix}"
    org_id = f"org-walkin-{tenant_suffix}"
    sla_hours = {"p1_critical": 1, "p2_high": 4, "p3_medium": 12, "p4_low": 48}
    async with acquire() as conn:
        async with conn.transaction():
            await _lock_idempotency_key(
                conn,
                tenant_id=tenant_id,
                tool_name="create_ticket",
                key=req.idempotency_key,
            )
            cached = await conn.fetchrow(
                """
                SELECT args_digest, result_payload FROM tool_idempotency
                WHERE tenant_id = $1
                  AND tool_name = 'create_ticket'
                  AND idempotency_key = $2
                """,
                tenant_id,
                req.idempotency_key,
            )
            if cached:
                if cached["args_digest"] != request_digest:
                    raise HTTPException(status_code=409, detail="idempotency_conflict")
                return dict(cached["result_payload"])
            await conn.execute(
                """
                INSERT INTO customer_dim (
                    customer_id, tenant_id, org_id, org_name, sla_tier
                ) VALUES ($1,$2,$3,'Walk-in Customer','standard')
                ON CONFLICT (customer_id) DO NOTHING
                """,
                customer_id,
                tenant_id,
                org_id,
            )
            await conn.execute(
                """
                INSERT INTO ticket_fact (
                    ticket_id, tenant_id, customer_id, org_id, status, priority,
                    category, product_line, product_version, subject, error_codes,
                    asset_ids, sla_tier, sla_due_at, created_at, updated_at,
                    pii_redacted, data_release_id, ingest_batch_id
                ) VALUES ($1,$2,$3,$4,'open',$5,$6,$7,$8,$9,$10,$11,
                          'standard',$12,$13,$13,TRUE,$14,'product-api')
                """,
                ticket_id,
                tenant_id,
                customer_id,
                org_id,
                req.priority,
                req.category,
                req.product_line,
                req.product_version,
                req.subject,
                req.error_codes,
                req.asset_ids,
                now + timedelta(hours=sla_hours[req.priority]),
                now,
                settings.data_release_id,
            )
            await conn.execute(
                """
                INSERT INTO ticket_comment_fact (comment_id, ticket_id, author_id, author_role, body)
                VALUES ($1,$2,$3,$4,$5)
                """,
                f"comment_{uuid.uuid4().hex}",
                ticket_id,
                actor_id,
                actor_role,
                req.description,
            )
            result = {
                "ticket_id": ticket_id,
                "status": "open",
                "sla_due_at": (now + timedelta(hours=sla_hours[req.priority])).isoformat(),
                "created_at": now.isoformat(),
                "hitl_triggered": req.priority in {"p1_critical", "p2_high"},
                "trace_id": trace_id,
                "release_id": settings.release_id,
            }
            await conn.execute(
                """
                INSERT INTO tool_idempotency (
                    tenant_id, tool_name, idempotency_key, args_digest,
                    result_payload, trace_id, release_id
                ) VALUES ($1,'create_ticket',$2,$3,$4::jsonb,$5,$6)
                """,
                tenant_id,
                req.idempotency_key,
                request_digest,
                result,
                trace_id,
                settings.release_id,
            )
    return result


@router.post("/ticket_update", summary="Execute a contract-governed ticket action")
async def ticket_update(
    req: TicketUpdateRequest,
    http_request: Request,
    principal: InternalPrincipal = Depends(require_internal_request),
):
    actor_id, actor_role, tenant_id = _actor_context(
        principal,
        fallback_actor_id=req.actor_id,
        fallback_actor_role=req.actor_role,
    )
    payload = req.model_dump(exclude_none=True)
    payload["actor_id"] = actor_id
    normalized_header_role = "support_ops" if actor_role == "support_lead" else actor_role
    payload["actor_role"] = normalized_header_role
    contract = _contract("ticket_update")
    try:
        jsonschema.validate(payload, contract["input_schema"])
    except jsonschema.ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"contract_validation_failed:{exc.message}") from exc
    if normalized_header_role not in contract["allowed_roles"]:
        raise HTTPException(status_code=403, detail="role_denied")

    request_id = getattr(http_request.state, "request_id", str(uuid.uuid4()))
    with traced_span(
        "agent.invoke.ticket_update",
        kind="AGENT",
        attributes={
            "tool.name": "ticket_update",
            "omni.actor.role": normalized_header_role,
            "omni.tenant_id": tenant_id,
        },
    ):
        async with acquire() as conn:
            async with conn.transaction():
                await _lock_idempotency_key(
                    conn,
                    tenant_id=tenant_id,
                    tool_name="ticket_update",
                    key=payload["idempotency_key"],
                )
                if cached := await _cached_result(conn, payload, tenant_id=tenant_id):
                    return cached
                with traced_span("hitl.evaluate", kind="CHAIN"):
                    hitl = HITLPolicy().evaluate(contract, payload)
                if hitl.required:
                    with traced_span("hitl.wait", kind="CHAIN"):
                        approval_id = f"apr_{uuid.uuid4().hex[:20]}"
                        await conn.execute(
                            """
                            INSERT INTO hitl_approval_request (
                                approval_id, trace_id, tool_name, action, reason_codes,
                                payload_digest, payload, release_id, tenant_id, actor_id
                            ) VALUES ($1,$2,'ticket_update',$3,$4,$5,$6::jsonb,$7,$8,$9)
                            """,
                            approval_id,
                            payload["trace_id"],
                            hitl.action or "require_approval",
                            hitl.reason_codes,
                            _canonical_digest(payload),
                            payload,
                            settings.release_id,
                            tenant_id,
                            actor_id,
                        )
                        event_id = await _write_lineage(
                            conn,
                            payload=payload,
                            tenant_id=tenant_id,
                            status_value="awaiting_approval",
                            approval_id=approval_id,
                        )
                        result = {
                            "ticket_id": payload["ticket_id"],
                            "operation": payload["operation"],
                            "status": "awaiting_approval",
                            "approval_id": approval_id,
                            "hitl_required": True,
                            "reason_codes": hitl.reason_codes,
                            "trace_id": payload["trace_id"],
                            "lineage_event_id": event_id,
                            "release_id": settings.release_id,
                        }
                        await _remember_result(conn, payload, result, tenant_id=tenant_id)
                        return result
                return await _perform_action(
                    conn,
                    payload=payload,
                    tenant_id=tenant_id,
                    approval_id=None,
                    request_id=request_id,
                )


@approval_router.post("/approvals/{approval_id}/decision", summary="Approve and resume a governed action")
async def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    http_request: Request,
    principal: InternalPrincipal = Depends(require_internal_request),
):
    actor_id, actor_role, tenant_id = _actor_context(principal)
    if actor_role not in {"support_lead", "support_ops", "billing_ops", "admin"}:
        raise HTTPException(status_code=403, detail="role_denied")
    request_id = getattr(http_request.state, "request_id", str(uuid.uuid4()))
    async with acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT * FROM hitl_approval_request
                WHERE approval_id = $1 AND tenant_id = $2 FOR UPDATE
                """,
                approval_id,
                tenant_id,
            )
            if row is None:
                raise HTTPException(status_code=404, detail="approval_not_found")
            if row["status"] != "pending":
                return {
                    "approval_id": approval_id,
                    "status": row["status"],
                    "trace_id": row["trace_id"],
                    "release_id": settings.release_id,
                }
            status_value = "approved" if decision.approved else "rejected"
            with traced_span(
                "hitl.resume",
                kind="CHAIN",
                attributes={
                    "omni.approval.decision": status_value,
                    "omni.business_trace_id": row["trace_id"],
                },
            ):
                await conn.execute(
                    """
                    UPDATE hitl_approval_request
                    SET status = $1, reviewer = $2, decision_reason = $3, decided_at = NOW()
                    WHERE approval_id = $4
                    """,
                    status_value,
                    actor_id,
                    decision.reason,
                    approval_id,
                )
                payload = dict(row["payload"])
                if not decision.approved:
                    event_id = await _write_lineage(
                        conn,
                        payload=payload,
                        tenant_id=tenant_id,
                        status_value="denied",
                        approval_id=approval_id,
                    )
                    result = {
                        "ticket_id": payload["ticket_id"],
                        "operation": payload["operation"],
                        "status": "denied",
                        "approval_id": approval_id,
                        "trace_id": payload["trace_id"],
                        "lineage_event_id": event_id,
                        "release_id": settings.release_id,
                    }
                    await _remember_result(conn, payload, result, tenant_id=tenant_id)
                    return result
                return await _perform_action(
                    conn,
                    payload=payload,
                    tenant_id=tenant_id,
                    approval_id=approval_id,
                    request_id=request_id,
                )
