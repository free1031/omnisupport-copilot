"""RAG API adapter for the shared Week12 telemetry runtime."""

from observability.runtime import (
    TelemetryConfig,
    configure_telemetry,
    force_flush,
    instrument_fastapi_app,
)


def setup_telemetry(service_name: str = "rag_api"):
    from app.config import settings

    return configure_telemetry(
        TelemetryConfig(
            service_name=service_name,
            release_id=settings.release_id,
            environment=settings.otel_environment,
            endpoint=settings.otel_exporter_otlp_endpoint,
            project_name=settings.otel_project_name,
            enabled=settings.otel_enabled,
            sample_ratio=settings.otel_sample_ratio,
        )
    )


__all__ = ["force_flush", "instrument_fastapi_app", "setup_telemetry"]
