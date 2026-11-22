from __future__ import annotations

import pytest

from reportify.core.errors import (
    ApiError,
    ConversationBusy,
    InvalidArgument,
    ModelNotConfigured,
    NotFound,
    ValidationFailed,
)


def test_body_has_stable_shape() -> None:
    error = NotFound("conversation not found")
    body = error.body(instance="/api/v1/conversations/x")

    assert body["code"] == "not_found"
    assert body["status"] == 404
    assert body["title"] == "Not found"
    assert body["type"].startswith("https://reportify.local/errors/")
    assert body["detail"] == "conversation not found"
    assert body["retryable"] is False
    assert body["instance"] == "/api/v1/conversations/x"


def test_instance_is_optional() -> None:
    assert "instance" not in InvalidArgument("bad").body()


def test_conversation_busy_uses_409() -> None:
    error = ConversationBusy()
    assert error.status_code == 409
    assert error.code == "conversation_busy"


def test_validation_failed_uses_422() -> None:
    assert ValidationFailed("x").status_code == 422


def test_model_not_configured_is_retryable_service_error() -> None:
    error = ModelNotConfigured()
    assert error.status_code == 503
    assert error.code == "model_not_configured"


def test_unknown_code_falls_back_to_internal_error() -> None:
    error = ApiError("something_new", "boom")
    body = error.body()
    assert body["status"] == 500
    assert body["type"].endswith("/internal-error")


def test_extra_metadata_is_exposed_under_meta() -> None:
    error = ApiError("invalid_argument", "bad", extra={"field": "content"})
    assert error.body()["meta"] == {"field": "content"}


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (InvalidArgument("x"), 400),
        (NotFound("x"), 404),
        (ConversationBusy(), 409),
        (ValidationFailed("x"), 422),
        (ModelNotConfigured(), 503),
    ],
)
def test_status_mapping(error: ApiError, status: int) -> None:
    assert error.status_code == status
