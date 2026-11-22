from __future__ import annotations

import pytest

from reportify.core.config import Settings
from reportify.core.telemetry import configure_telemetry, run_span


def _settings(**overrides) -> Settings:
    payload = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://user:pass@127.0.0.1:5432/db",
        "secret_key": "k",
    }
    payload.update(overrides)
    return Settings(**payload)


def test_telemetry_is_off_without_endpoint() -> None:
    assert configure_telemetry(_settings()) is False


def test_run_span_is_a_noop_without_provider() -> None:
    with run_span("run-1", "deepseek-flash") as span:
        assert span.enabled is False
        span.set_status("succeeded")
        span.set_attribute("k", "v")
        span.record_error("boom")


@pytest.mark.parametrize("endpoint", [None, ""])
def test_blank_endpoint_is_treated_as_unset(endpoint: str | None) -> None:
    assert configure_telemetry(_settings(otel_exporter_otlp_endpoint=endpoint)) is False


def test_telemetry_with_endpoint_installs_provider(monkeypatch) -> None:
    """No network: the OTLP exporter is replaced by an in-memory stub."""
    from opentelemetry.sdk.trace.export import SpanExportResult

    exported: list[object] = []

    class _StubExporter:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def export(self, spans):
            exported.extend(spans)
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            pass

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
        _StubExporter,
        raising=False,
    )

    settings = _settings(otel_exporter_otlp_endpoint="http://127.0.0.1:4318/v1/traces")
    assert configure_telemetry(settings) is True

    with run_span("run-2", "deepseek-flash") as handle:
        assert handle.enabled is True
        handle.set_status("succeeded")
        handle.set_attribute("tool", "query_dataset")
        handle.record_error("none")

    from opentelemetry import trace

    trace.get_tracer_provider().force_flush()
    assert exported
