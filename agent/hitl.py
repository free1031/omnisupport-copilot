"""Human-in-the-loop checkpointing for high-risk Agent actions."""

from __future__ import annotations

import operator
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from tools.idempotency import stable_digest


COMPARATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}
CONDITION_RE = re.compile(
    r"^\s*(?P<field>[a-zA-Z_][a-zA-Z0-9_]*)\s*"
    r"(?P<op>==|!=|>=|<=|>|<)\s*"
    r"(?P<value>'.*?'|\".*?\"|-?[0-9]+(?:\.[0-9]+)?)\s*$"
)


@dataclass(frozen=True)
class HITLMatch:
    condition: str
    action: str


@dataclass(frozen=True)
class HITLEvaluation:
    required: bool
    action: str | None = None
    matches: list[HITLMatch] = field(default_factory=list)

    @property
    def reason_codes(self) -> list[str]:
        return [match.condition for match in self.matches]


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    trace_id: str
    tool_name: str
    action: str
    payload: dict[str, Any]
    payload_digest: str
    reason_codes: list[str]
    status: str = "pending"
    reviewer: str | None = None
    decision_reason: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    decided_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("payload")
        return data


class HITLCheckpointStore:
    """In-memory checkpoint store for deterministic demos and tests."""

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}

    def create(
        self,
        *,
        trace_id: str,
        tool_name: str,
        action: str,
        payload: dict[str, Any],
        reason_codes: list[str],
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            approval_id=f"apr_{uuid.uuid4().hex[:12]}",
            trace_id=trace_id,
            tool_name=tool_name,
            action=action,
            payload=dict(payload),
            payload_digest=stable_digest(payload),
            reason_codes=list(reason_codes),
        )
        self._requests[request.approval_id] = request
        return request

    def get(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise KeyError(f"approval request not found: {approval_id}") from exc

    def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        reviewer: str,
        reason: str,
    ) -> ApprovalRequest:
        request = self.get(approval_id)
        if request.status != "pending":
            return request
        updated = ApprovalRequest(
            approval_id=request.approval_id,
            trace_id=request.trace_id,
            tool_name=request.tool_name,
            action=request.action,
            payload=request.payload,
            payload_digest=request.payload_digest,
            reason_codes=request.reason_codes,
            status="approved" if approved else "rejected",
            reviewer=reviewer,
            decision_reason=reason,
            created_at=request.created_at,
            decided_at=datetime.now(timezone.utc).isoformat(),
        )
        self._requests[approval_id] = updated
        return updated


class HITLPolicy:
    """Evaluate the small condition language used in tool contracts."""

    ACTION_PRIORITY = {
        "reject": 3,
        "require_approval": 2,
        "pause_and_notify": 1,
    }

    def evaluate(self, contract: dict[str, Any], payload: dict[str, Any]) -> HITLEvaluation:
        matches: list[HITLMatch] = []
        for item in contract.get("hitl_conditions", []):
            condition = str(item.get("condition", ""))
            if self._matches(condition, payload):
                matches.append(HITLMatch(condition=condition, action=str(item["action"])))

        if not matches:
            return HITLEvaluation(required=False)

        action = max(matches, key=lambda item: self.ACTION_PRIORITY.get(item.action, 0)).action
        return HITLEvaluation(required=True, action=action, matches=matches)

    def _matches(self, condition: str, payload: dict[str, Any]) -> bool:
        parts = [part.strip() for part in re.split(r"\bAND\b", condition) if part.strip()]
        if not parts:
            return False
        return all(self._matches_simple(part, payload) for part in parts)

    def _matches_simple(self, condition: str, payload: dict[str, Any]) -> bool:
        match = CONDITION_RE.match(condition)
        if not match:
            return False
        field = match.group("field")
        op = match.group("op")
        expected = _parse_literal(match.group("value"))
        actual = payload.get(field)
        if isinstance(expected, (int, float)) and actual is None:
            actual = 0
        return bool(COMPARATORS[op](actual, expected))


def _parse_literal(value: str) -> Any:
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    if "." in value:
        return float(value)
    return int(value)
