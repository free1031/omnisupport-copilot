"""Fallback chain primitives for Week10 Agent tools."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from observability.runtime import traced_span

ToolCallable = Callable[[dict[str, Any]], Any]


class FallbackExhausted(RuntimeError):  # noqa: N818 - preserve the public Week10 API
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
        for level, (name, step) in enumerate(self.steps):
            with traced_span(
                "tool.fallback.attempt",
                kind="TOOL",
                attributes={"omni.fallback.name": name, "omni.fallback.level": level},
            ) as span:
                try:
                    result = step(payload)
                    if inspect.isawaitable(result):
                        result = await result
                    if not isinstance(result, dict):
                        raise TypeError(
                            f"fallback step {name} returned {type(result).__name__}, expected dict"
                        )
                    attempts.append(FallbackAttempt(name=name, status="ok"))
                    span.set_attribute("omni.fallback.status", "ok")
                    return FallbackResult(result=result, attempts=attempts, fallback_level=name)
                except Exception as exc:  # noqa: BLE001 - fallback records and continues.
                    from opentelemetry.trace import Status, StatusCode

                    span.set_attribute("omni.fallback.status", "failed")
                    span.set_attribute("error.type", type(exc).__name__)
                    span.set_status(Status(StatusCode.ERROR, str(exc)[:256]))
                    attempts.append(FallbackAttempt(name=name, status="failed", error=str(exc)))

        if self.graceful_response is not None:
            with traced_span(
                "tool.fallback.graceful",
                kind="TOOL",
                attributes={"omni.fallback.level": len(self.steps)},
            ):
                attempts.append(FallbackAttempt(name="graceful_response", status="ok"))
                return FallbackResult(
                    result=dict(self.graceful_response),
                    attempts=attempts,
                    fallback_level="graceful_response",
                )

        raise FallbackExhausted("; ".join(f"{item.name}: {item.error}" for item in attempts))
