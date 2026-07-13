"""Small span API with OpenInference-compatible kinds and bounded attributes."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping


def _trace_api():
    from opentelemetry import trace

    return trace


def set_span_attributes(span: Any, attributes: Mapping[str, Any] | None) -> None:
    if not attributes:
        return
    written = 0
    for key, value in attributes.items():
        if written >= 19:
            break
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            normalized = [str(item)[:128] for item in list(value)[:10]]
        elif isinstance(value, (bool, int, float, str)):
            normalized = value if not isinstance(value, str) else value[:512]
        else:
            normalized = str(value)[:512]
        span.set_attribute(str(key), normalized)
        written += 1


@contextmanager
def traced_span(
    name: str,
    *,
    kind: str = "CHAIN",
    attributes: Mapping[str, Any] | None = None,
    tracer_name: str = "omnisupport.copilot",
) -> Iterator[Any]:
    trace = _trace_api()
    tracer = trace.get_tracer(tracer_name)
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("openinference.span.kind", kind.upper())
        set_span_attributes(span, attributes)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)[:256]))
            raise
        else:
            status = getattr(span, "status", None)
            if span.is_recording() and (
                status is None or status.status_code == trace.StatusCode.UNSET
            ):
                span.set_status(trace.Status(trace.StatusCode.OK))


def current_trace_id() -> str:
    span_context = _trace_api().get_current_span().get_span_context()
    if not span_context.is_valid:
        return ""
    return f"{span_context.trace_id:032x}"
