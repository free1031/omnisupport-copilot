"""Process-level OpenTelemetry setup for API, worker, and demo runtimes."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelemetryConfig:
    service_name: str
    release_id: str = "dev-local"
    environment: str = "dev"
    endpoint: str = "http://localhost:4318"
    project_name: str = "omnisupport-copilot"
    enabled: bool = True
    sample_ratio: float = 1.0


_lock = threading.Lock()
_provider: Any | None = None


def _trace_endpoint(endpoint: str) -> str:
    value = endpoint.rstrip("/")
    return value if value.endswith("/v1/traces") else f"{value}/v1/traces"


def configure_telemetry(
    config: TelemetryConfig,
    *,
    span_exporter: Any | None = None,
    synchronous: bool = False,
) -> Any | None:
    """Configure one tracer provider per process.

    ``span_exporter`` and ``synchronous`` are test hooks. Production services use
    the OTLP HTTP exporter and batch processor so exporting never blocks the
    request path.
    """

    global _provider
    if not config.enabled:
        logger.info("OpenTelemetry disabled for %s", config.service_name)
        return None

    with _lock:
        if _provider is not None:
            return _provider

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import SpanLimits, TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
            from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

            if span_exporter is None:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                span_exporter = OTLPSpanExporter(endpoint=_trace_endpoint(config.endpoint))

            ratio = min(max(float(config.sample_ratio), 0.0), 1.0)
            resource = Resource.create(
                {
                    "service.name": config.service_name,
                    "service.version": "0.1.0",
                    "deployment.environment.name": config.environment,
                    "openinference.project.name": config.project_name,
                    "omni.release_id": config.release_id,
                }
            )
            provider = TracerProvider(
                resource=resource,
                sampler=ParentBased(TraceIdRatioBased(ratio)),
                span_limits=SpanLimits(
                    max_attributes=20,
                    max_attribute_length=512,
                    max_events=16,
                    max_links=8,
                ),
            )
            processor = (
                SimpleSpanProcessor(span_exporter)
                if synchronous
                else BatchSpanProcessor(span_exporter)
            )
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            _provider = provider
            logger.info(
                "OpenTelemetry ready service=%s project=%s endpoint=%s sample_ratio=%s",
                config.service_name,
                config.project_name,
                _trace_endpoint(config.endpoint),
                ratio,
            )
            return provider
        except ImportError as exc:
            logger.warning("OpenTelemetry disabled because a dependency is missing: %s", exc)
        except Exception:
            logger.exception("OpenTelemetry setup failed; service will continue without exporting")
        return None


def instrument_fastapi_app(app: Any, *, excluded_urls: str = "/health") -> bool:
    if _provider is None:
        return False
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=_provider,
            excluded_urls=excluded_urls,
        )
        return True
    except Exception:
        logger.exception("FastAPI instrumentation failed")
        return False


def force_flush(timeout_millis: int = 5000) -> bool:
    if _provider is None:
        return True
    try:
        return bool(_provider.force_flush(timeout_millis=timeout_millis))
    except Exception:
        logger.exception("OpenTelemetry flush failed")
        return False
