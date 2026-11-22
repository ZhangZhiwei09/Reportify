"""Delivery contracts: Dockerfile and Compose invariants (09 §9).

The image build needs a container registry; these tests pin the properties the
build is *supposed* to have so a regression is caught without one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_dockerfile_is_multi_stage() -> None:
    from_lines = [
        line for line in DOCKERFILE.splitlines() if line.strip().startswith("FROM ")
    ]
    assert len(from_lines) >= 2
    assert " AS builder" in from_lines[0]
    assert " AS runtime" in from_lines[-1]


def test_runtime_runs_as_non_root() -> None:
    runtime_section = DOCKERFILE.split(" AS runtime", 1)[1]
    assert "USER appuser" in runtime_section
    assert "USER root" not in runtime_section
    assert "useradd" in runtime_section


def test_runtime_has_healthcheck_and_entrypoint() -> None:
    assert "HEALTHCHECK" in DOCKERFILE
    assert "/api/v1/health" in DOCKERFILE
    assert 'CMD ["uvicorn", "reportify.main:app"' in DOCKERFILE
    assert "EXPOSE 8000" in DOCKERFILE


def test_build_installs_without_dev_extras() -> None:
    assert "uv sync --frozen --no-dev" in DOCKERFILE
    assert "--no-install-project" in DOCKERFILE


def test_image_does_not_bake_in_secrets_or_env() -> None:
    assert "COPY . " not in DOCKERFILE
    assert ".env" not in DOCKERFILE
    assert "SECRET_KEY=" not in DOCKERFILE


def test_dockerignore_excludes_local_state() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in [".venv", ".env", "reports", "workspace", "__pycache__"]:
        assert entry in ignored, entry


def test_compose_declares_the_expected_services() -> None:
    services = COMPOSE["services"]
    assert set(services) == {"api", "postgres", "redis"}


def test_api_waits_for_healthy_dependencies() -> None:
    api = COMPOSE["services"]["api"]
    depends = api["depends_on"]
    assert depends["postgres"]["condition"] == "service_healthy"
    assert depends["redis"]["condition"] == "service_healthy"


def test_api_is_bound_to_loopback_only() -> None:
    ports = COMPOSE["services"]["api"]["ports"]
    assert all(str(port).startswith("127.0.0.1:") for port in ports), ports


@pytest.mark.parametrize("service", ["postgres", "redis"])
def test_stateful_services_have_healthchecks(service: str) -> None:
    assert "healthcheck" in COMPOSE["services"][service]


def test_compose_does_not_hardcode_secrets() -> None:
    api_env = COMPOSE["services"]["api"]["environment"]
    secret = api_env["REPORTIFY_SECRET_KEY"]
    assert secret.startswith("${REPORTIFY_SECRET_KEY"), secret
    assert "REPORTIFY_DEEPSEEK_API_KEY" in api_env
    assert str(api_env["REPORTIFY_SSRF_ALLOW_LOOPBACK"]) == "false"
