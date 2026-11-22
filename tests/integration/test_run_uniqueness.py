"""One active run per conversation, enforced by the database (05 §7.3)."""

from __future__ import annotations

import pytest

from reportify.core.errors import ConversationBusy
from reportify.db.repositories import conversations as conversations_repo
from reportify.db.repositories import tasks as tasks_repo


async def test_second_active_run_is_rejected(session_factory) -> None:
    async with session_factory() as session:
        conversation = await conversations_repo.create_conversation(
            session, title="concurrency"
        )
        task = await tasks_repo.create_task(
            session,
            conversation_id=conversation.id,
            goal="first",
        )
        first = await tasks_repo.create_run(
            session,
            task_id=task.id,
            conversation_id=conversation.id,
            model_name="deepseek-flash",
        )
        assert first.status == "queued"

        with pytest.raises(ConversationBusy):
            await tasks_repo.create_run(
                session,
                task_id=task.id,
                conversation_id=conversation.id,
                model_name="deepseek-flash",
            )


async def test_run_allowed_again_after_terminal(session_factory) -> None:
    async with session_factory() as session:
        conversation = await conversations_repo.create_conversation(
            session, title="sequential"
        )
        task = await tasks_repo.create_task(
            session,
            conversation_id=conversation.id,
            goal="second",
        )
        first = await tasks_repo.create_run(
            session,
            task_id=task.id,
            conversation_id=conversation.id,
            model_name="deepseek-flash",
        )
        await tasks_repo.finish_run(session, first.id, status="succeeded")

        second = await tasks_repo.create_run(
            session,
            task_id=task.id,
            conversation_id=conversation.id,
            model_name="deepseek-flash",
        )
        assert second.id != first.id


async def test_waiting_approval_still_blocks(session_factory) -> None:
    async with session_factory() as session:
        conversation = await conversations_repo.create_conversation(
            session, title="parked"
        )
        task = await tasks_repo.create_task(
            session,
            conversation_id=conversation.id,
            goal="third",
        )
        first = await tasks_repo.create_run(
            session,
            task_id=task.id,
            conversation_id=conversation.id,
            model_name="deepseek-flash",
        )
        await tasks_repo.mark_waiting_approval(
            session,
            first.id,
            approvals=[{"approval_id": "a1", "decision": "pending"}],
            history_blob=None,
        )

        with pytest.raises(ConversationBusy):
            await tasks_repo.create_run(
                session,
                task_id=task.id,
                conversation_id=conversation.id,
                model_name="deepseek-flash",
            )
