"""Fallback chain primitives for Week10 Agent tools."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


ToolCallable = Callable[[dict[str, Any]], Any]


class FallbackExhausted(RuntimeError):
    """Raised when every fallback step fails and no graceful response exists."""


@dataclass(frozen=True)
class FallbackAttempt:
    name: str
    status: str
    error: str | None = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class FallbackResult:
    result: dict[str, Any]
    attempts: list[FallbackAttempt]
    fallback_level: str

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.result)
        payload["fallback_level"] = self.fallback_level
        payload["fallback_attempts"] = [attempt.__dict__ for attempt in self.attempts]
        return payload


class FallbackChain:
    """Run primary/retry/cache/graceful steps without hiding failures."""

    def __init__(
        self,
        steps: list[tuple[str, ToolCallable]],
        *,
        graceful_response: dict[str, Any] | None = None,
    ) -> None:
        if not steps:
            raise ValueError("FallbackChain requires at least one step")
        self.steps = steps
        self.graceful_response = graceful_response

    async def run(self, payload: dict[str, Any]) -> FallbackResult:
        attempts: list[FallbackAttempt] = []
        for name, step in self.steps:
            try:
                result = step(payload)
                if inspect.isawaitable(result):
                    result = await result
                if not isinstance(result, dict):
                    raise TypeError(f"fallback step {name} returned {type(result).__name__}, expected dict")
                attempts.append(FallbackAttempt(name=name, status="ok"))
                return FallbackResult(result=result, attempts=attempts, fallback_level=name)
            except Exception as exc:  # noqa: BLE001 - fallback must preserve all step failures.
                attempts.append(FallbackAttempt(name=name, status="failed", error=str(exc)))

        if self.graceful_response is not None:
            attempts.append(FallbackAttempt(name="graceful_response", status="ok"))
            return FallbackResult(
                result=dict(self.graceful_response),
                attempts=attempts,
                fallback_level="graceful_response",
            )

        raise FallbackExhausted("; ".join(f"{item.name}: {item.error}" for item in attempts))
