"""Deterministic controlled Agent orchestration for Week10.

This is not an LLM wrapper. It is the control plane around tool execution:
contract validation, role checks, idempotency, HITL checkpointing, fallback, and
action lineage emission.
"""

from __future__ import annotations

import inspect
import uuid
from typing import Any, Callable

import jsonschema

from agent.hitl import HITLCheckpointStore, HITLPolicy
from agent.lineage import ActionLineageEvent, build_action_lineage_event
from tools.fallback import FallbackChain
from tools.idempotency import (
    IdempotencyConflict,
    InMemoryIdempotencyStore,
    derive_idempotency_key,
)
from tools.registry import ToolContractRegistry


ToolExecutor = Callable[[dict[str, Any]], Any]


class ControlledAgent:
    def __init__(
        self,
        *,
        registry: ToolContractRegistry | None = None,
        hitl_store: HITLCheckpointStore | None = None,
        idempotency_store: InMemoryIdempotencyStore | None = None,
        release_id: str = "dev-local",
    ) -> None:
        self.registry = registry or ToolContractRegistry()
        self.hitl_store = hitl_store or HITLCheckpointStore()
        self.idempotency_store = idempotency_store or InMemoryIdempotencyStore()
        self.hitl_policy = HITLPolicy()
        self.release_id = release_id
        self.lineage_events: list[ActionLineageEvent] = []

    async def invoke(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        actor_role: str,
        executor: ToolExecutor | FallbackChain | None = None,
    ) -> dict[str, Any]:
        contract = self.registry.get(tool_name)
        normalized = dict(payload)
        normalized.setdefault("trace_id", f"trace_{uuid.uuid4().hex[:16]}")

        jsonschema.validate(normalized, contract.payload["input_schema"])

        if actor_role not in contract.allowed_roles:
            return self._denied(contract, normalized, "PERMISSION_DENIED")

        hitl_eval = self.hitl_policy.evaluate(contract.payload, normalized)
        if hitl_eval.required:
            approval = self.hitl_store.create(
                trace_id=normalized["trace_id"],
                tool_name=tool_name,
                action=hitl_eval.action or "require_approval",
                payload=normalized,
                reason_codes=hitl_eval.reason_codes,
            )
            event = self._record_lineage(
                contract=contract.payload,
                payload=normalized,
                status="awaiting_approval",
                approval_id=approval.approval_id,
            )
            return {
                "ticket_id": normalized.get("ticket_id"),
                "operation": normalized.get("operation"),
                "status": "awaiting_approval",
                "approval_id": approval.approval_id,
                "hitl_required": True,
                "reason_codes": approval.reason_codes,
                "trace_id": normalized["trace_id"],
                "lineage_event_id": event.event_id,
                "release_id": self.release_id,
            }

        return await self._execute(contract.payload, normalized, executor=executor)

    async def resume_approved(
        self,
        approval_id: str,
        *,
        executor: ToolExecutor | FallbackChain | None = None,
    ) -> dict[str, Any]:
        approval = self.hitl_store.get(approval_id)
        contract = self.registry.get(approval.tool_name)
        if approval.status != "approved":
            event = self._record_lineage(
                contract=contract.payload,
                payload=approval.payload,
                status="denied",
                approval_id=approval_id,
            )
            return {
                "ticket_id": approval.payload.get("ticket_id"),
                "operation": approval.payload.get("operation"),
                "status": "denied",
                "approval_id": approval_id,
                "trace_id": approval.trace_id,
                "lineage_event_id": event.event_id,
                "release_id": self.release_id,
            }
        return await self._execute(contract.payload, approval.payload, executor=executor, approval_id=approval_id)

    async def _execute(
        self,
        contract: dict[str, Any],
        payload: dict[str, Any],
        *,
        executor: ToolExecutor | FallbackChain | None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        idem_key = derive_idempotency_key(contract, payload)
        if idem_key:
            try:
                cached = self.idempotency_store.get(contract["name"], idem_key, payload)
            except IdempotencyConflict:
                return self._denied(contract, payload, "IDEMPOTENCY_CONFLICT")
            if cached is not None:
                cached_result = dict(cached.result)
                cached_result["status"] = "cached"
                cached_result["cached_from"] = cached.created_at
                return cached_result

        result = await self._call_executor(contract, payload, executor)
        result.setdefault("status", "completed")
        result.setdefault("trace_id", payload["trace_id"])
        result.setdefault("release_id", self.release_id)
        event = self._record_lineage(
            contract=contract,
            payload=payload,
            status=result["status"],
            approval_id=approval_id,
            output_ref=result.get("ticket_id") or result.get("output_ref"),
        )
        result["lineage_event_id"] = event.event_id

        if idem_key:
            self.idempotency_store.remember(contract["name"], idem_key, payload, result)
        return result

    async def _call_executor(
        self,
        contract: dict[str, Any],
        payload: dict[str, Any],
        executor: ToolExecutor | FallbackChain | None,
    ) -> dict[str, Any]:
        if isinstance(executor, FallbackChain):
            return (await executor.run(payload)).to_dict()
        if executor is None:
            return self._default_executor(contract, payload)
        result = executor(payload)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise TypeError("tool executor must return a dict")
        return result

    def _default_executor(self, contract: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        if contract["name"] == "ticket_update":
            return {
                "ticket_id": payload["ticket_id"],
                "operation": payload["operation"],
                "status": "completed",
                "trace_id": payload["trace_id"],
                "release_id": self.release_id,
            }
        return {
            "status": "completed",
            "trace_id": payload["trace_id"],
            "release_id": self.release_id,
        }

    def _denied(self, contract: Any, payload: dict[str, Any], code: str) -> dict[str, Any]:
        contract_payload = contract.payload if hasattr(contract, "payload") else contract
        event = self._record_lineage(contract=contract_payload, payload=payload, status="denied")
        return {
            "ticket_id": payload.get("ticket_id"),
            "operation": payload.get("operation"),
            "status": "denied",
            "denial_code": code,
            "message": contract_payload.get("failure_codes", {}).get(code, code),
            "trace_id": payload.get("trace_id"),
            "lineage_event_id": event.event_id,
            "release_id": self.release_id,
        }

    def _record_lineage(
        self,
        *,
        contract: dict[str, Any],
        payload: dict[str, Any],
        status: str,
        approval_id: str | None = None,
        output_ref: str | None = None,
    ) -> ActionLineageEvent:
        event = build_action_lineage_event(
            trace_id=payload["trace_id"],
            tool_name=contract["name"],
            tool_version=contract["version"],
            status=status,
            payload=payload,
            actor_id=payload.get("actor_id"),
            approval_id=approval_id,
            output_ref=output_ref,
        )
        self.lineage_events.append(event)
        return event
