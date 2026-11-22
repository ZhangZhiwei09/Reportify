"""Optional OpenTelemetry wiring (09 §10).

No endpoint means no provider: tracing is a deployment choice, never a startup
requirement. Spans carry identifiers and status only — never prompts or results.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from reportify.core.config import Settings

logger = logging.getLogger(__name__)

_TRACER_NAME = "reportify"


class SpanHandle:
    """Small wrapper so callers never depend on an active provider."""

    def __init__(self, span: Any | None) -> None:
        self._span = span
        self._status = "running"

    def set_status(self, status: str) -> None:
        self._status = status
        if self._span is not None:
            self._span.set_attribute("status", status)

    def set_attribute(self, key: str, value: Any) -> None:
        if self._span is not None:
            self._span.set_attribute(key, value)

    def record_error(self, code: str) -> None:
        if self._span is not None:
            self._span.set_attribute("error_code", code)
            self._span.set_attribute("status", "failed")

    @property
    def enabled(self) -> bool:
        return self._span is not None


def configure_telemetry(settings: Settings) -> bool:
    """Install an OTLP tracer provider when an endpoint is configured."""
    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint:
        logger.debug("otel disabled: no endpoint configured")
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:  # pragma: no cover - optional dependency
        logger.warning("otel endpoint configured but the SDK is not installed")
        return False

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError:  # pragma: no cover - optional dependency
        logger.warning("otel endpoint configured but the OTLP exporter is missing")
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": "reportify"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    logger.info("otel tracing enabled")
    return True


def _tracer() -> Any | None:
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - optional dependency
        return None
    provider = trace.get_tracer_provider()
    # The SDK's proxy provider answers with a NoOp tracer until configured.
    if provider.__class__.__name__ in {"ProxyTracerProvider", "NoOpTracerProvider"}:
        return None
    return trace.get_tracer(_TRACER_NAME)


@contextmanager
def run_span(run_id: Any, model: str) -> Iterator[SpanHandle]:
    tracer = _tracer()
    if tracer is None:
        yield SpanHandle(None)
        return
    with tracer.start_as_current_span("run") as span:
        span.set_attribute("run_id", str(run_id))
        span.set_attribute("model", model)
        yield SpanHandle(span)
