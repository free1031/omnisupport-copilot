"""Idempotency helpers for governed Agent tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class IdempotencyConflict(ValueError):
    """Raised when a key is reused with a different request payload."""


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_digest(value: Any, *, length: int = 32) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()[:length]


def derive_idempotency_key(contract: dict[str, Any], payload: dict[str, Any]) -> str | None:
    fields = contract.get("idempotency_key_fields") or []
    if not fields:
        return None
    values = {field: payload.get(field) for field in fields}
    if any(value in (None, "") for value in values.values()):
        return None
    return stable_digest({"tool": contract["name"], "fields": values}, length=48)


@dataclass(frozen=True)
class IdempotencyRecord:
    tool_name: str
    key: str
    args_digest: str
    result: dict[str, Any]
    created_at: str


class InMemoryIdempotencyStore:
    """Small deterministic store used by tests and classroom demos.

    Production deployments should persist the same tuple in PostgreSQL
    ``tool_idempotency``. The behavior is intentionally identical: same key and
    same args returns cached output; same key with different args is rejected.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], IdempotencyRecord] = {}

    def get(self, tool_name: str, key: str, payload: dict[str, Any]) -> IdempotencyRecord | None:
        record = self._records.get((tool_name, key))
        if record is None:
            return None
        args_digest = stable_digest(payload)
        if record.args_digest != args_digest:
            raise IdempotencyConflict(
                f"idempotency key {key!r} for {tool_name} was reused with different arguments"
            )
        return record

    def remember(
        self,
        tool_name: str,
        key: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> IdempotencyRecord:
        existing = self.get(tool_name, key, payload)
        if existing is not None:
            return existing
        record = IdempotencyRecord(
            tool_name=tool_name,
            key=key,
            args_digest=stable_digest(payload),
            result=result,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._records[(tool_name, key)] = record
        return record
