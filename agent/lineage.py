"""Action lineage event model for controlled Agent actions."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from tools.idempotency import stable_digest


@dataclass(frozen=True)
class ActionBindings:
    data_snapshot_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    prompt_release_id: str | None = None
    model_version: str | None = None
    skill_release_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionLineageEvent:
    event_id: str
    trace_id: str
    tool_name: str
    tool_version: str
    status: str
    bindings: ActionBindings
    payload_digest: str
    actor_id: str | None = None
    approval_id: str | None = None
    audit_id: str | None = None
    output_ref: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bindings"] = self.bindings.to_dict()
        return payload

    def to_openlineage_event(self) -> dict[str, Any]:
        return {
            "eventType": "COMPLETE" if self.status in {"completed", "cached"} else "START",
            "eventTime": self.created_at,
            "run": {"runId": self.trace_id},
            "job": {
                "namespace": "omnisupport.agent",
                "name": f"{self.tool_name}.{self.tool_version}",
            },
            "inputs": [
                {"namespace": "omnisupport.snapshot", "name": self.bindings.data_snapshot_id or "unknown"},
                *[
                    {"namespace": "omnisupport.evidence", "name": evidence_id}
                    for evidence_id in self.bindings.evidence_ids
                ],
            ],
            "outputs": [
                {"namespace": "omnisupport.action", "name": self.output_ref or self.event_id}
            ],
            "facets": {
                "prompt_release_id": {"_producer": "omnisupport", "value": self.bindings.prompt_release_id},
                "model_version": {"_producer": "omnisupport", "value": self.bindings.model_version},
                "skill_release_id": {"_producer": "omnisupport", "value": self.bindings.skill_release_id},
            },
        }


def build_action_lineage_event(
    *,
    trace_id: str,
    tool_name: str,
    tool_version: str,
    status: str,
    payload: dict[str, Any],
    actor_id: str | None = None,
    approval_id: str | None = None,
    audit_id: str | None = None,
    output_ref: str | None = None,
) -> ActionLineageEvent:
    bindings = ActionBindings(
        data_snapshot_id=payload.get("data_snapshot_id") or payload.get("data_release_id"),
        evidence_ids=list(payload.get("evidence_ids") or []),
        prompt_release_id=payload.get("prompt_release_id"),
        model_version=payload.get("model_version"),
        skill_release_id=payload.get("skill_release_id"),
    )
    return ActionLineageEvent(
        event_id=f"act_{uuid.uuid4().hex[:12]}",
        trace_id=trace_id,
        tool_name=tool_name,
        tool_version=tool_version,
        status=status,
        actor_id=actor_id,
        approval_id=approval_id,
        audit_id=audit_id,
        output_ref=output_ref,
        bindings=bindings,
        payload_digest=stable_digest(payload),
    )
