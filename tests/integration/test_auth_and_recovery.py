from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from reportify.api.app import create_app
from tests.support import event_names, scripted_model, text_step


def test_auth_token_required_when_configured(settings) -> None:
    secured = settings.model_copy(update={"auth_token": SecretStr("s3cret")})
    app = create_app(secured, model=scripted_model([text_step("ok")]))
    with TestClient(app) as client:
        anonymous = client.get("/api/v1/conversations")
        assert anonymous.status_code == 401

        wrong = client.get(
            "/api/v1/conversations",
            headers={"Authorization": "Bearer nope"},
        )
        assert wrong.status_code == 401

        authorized = client.get(
            "/api/v1/conversations",
            headers={"Authorization": "Bearer s3cret"},
        )
        assert authorized.status_code == 200


def test_auth_open_when_token_absent(client_factory) -> None:
    client = client_factory([text_step("ok")])
    assert client.get("/api/v1/conversations").status_code == 200


def _insert_stale_run(database_url: str) -> dict[str, str]:
    conversation_id = uuid.uuid4()
    task_id = uuid.uuid4()
    run_id = uuid.uuid4()

    async def setup() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO conversation (id, title, workspace_key, status, metadata) "
                        "VALUES (:id, 'stale', 'default', 'active', '{}'::jsonb)"
                    ),
                    {"id": conversation_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO analysis_task "
                        "(id, conversation_id, goal, status, skill_names, "
                        " data_source_refs, plan) "
                        "VALUES (:id, :conversation, 'stale goal', 'running', "
                        "        '{}'::text[], '[]'::jsonb, '{}'::jsonb)"
                    ),
                    {"id": task_id, "conversation": conversation_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO task_run "
                        "(id, task_id, conversation_id, trigger, status, model_name, "
                        " model_settings, limits, usage, created_at, updated_at) "
                        "VALUES (:id, :task, :conversation, 'interactive', 'running', "
                        "        'deepseek-flash', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
                        "        now() - interval '2 hours', now() - interval '2 hours')"
                    ),
                    {"id": run_id, "task": task_id, "conversation": conversation_id},
                )
        finally:
            await engine.dispose()

    asyncio.run(setup())
    return {
        "conversation_id": str(conversation_id),
        "task_id": str(task_id),
        "run_id": str(run_id),
    }


def test_startup_recovery_marks_stale_runs_failed(settings, database_url) -> None:
    ids = _insert_stale_run(database_url)

    app = create_app(settings, model=scripted_model([text_step("ok")]))
    with TestClient(app) as client:
        run = client.get(f"/api/v1/runs/{ids['run_id']}")
        assert run.status_code == 200
        body = run.json()
        assert body["status"] == "failed"
        assert body["error"]["code"] == "stale_run"

        task = client.get(f"/api/v1/tasks/{ids['task_id']}").json()
        assert task["status"] == "failed"

        assert "error" in event_names(client, ids["run_id"])
