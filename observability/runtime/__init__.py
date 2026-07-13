"""Shared OpenTelemetry/OpenInference runtime used by Week12."""

from observability.runtime.privacy import hash_text, safe_preview
from observability.runtime.setup import (
    TelemetryConfig,
    configure_telemetry,
    force_flush,
    instrument_fastapi_app,
)
from observability.runtime.spans import (
    current_trace_id,
    set_span_attributes,
    traced_span,
)

__all__ = [
    "TelemetryConfig",
    "configure_telemetry",
    "current_trace_id",
    "force_flush",
    "hash_text",
    "instrument_fastapi_app",
    "safe_preview",
    "set_span_attributes",
    "traced_span",
]
