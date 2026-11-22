from __future__ import annotations

import pytest
from sqlalchemy import select, update

from reportify.db.models import ToolDefinition, ToolGrant
from reportify.modules.tools.registry import BUILTIN_SPECS, ToolRegistry


@pytest.fixture
async def tool_registry(session_factory):
    registry = ToolRegistry(session_factory)
    count = await registry.sync_builtins()
    assert count == len(BUILTIN_SPECS)
    return registry


async def test_sync_builtins_is_idempotent(session_factory, tool_registry) -> None:
    await tool_registry.sync_builtins()
    async with session_factory() as session:
        definitions = (
            await session.execute(select(ToolDefinition))
        ).scalars().all()
        grants = (
            await session.execute(select(ToolGrant).where(ToolGrant.scope == "global"))
        ).scalars().all()

    names = sorted(item.name for item in definitions if item.name.startswith("builtin."))
    assert names == sorted(spec.name for spec in BUILTIN_SPECS)
    definition_ids = {item.id for item in definitions}
    global_grants = [
        grant for grant in grants if grant.tool_definition_id in definition_ids
    ]
    assert len(global_grants) >= len(BUILTIN_SPECS)


async def test_authorize_allows_builtin_read_tool(tool_registry) -> None:
    decision = await tool_registry.authorize(
        "query_dataset",
        task_id=None,
        conversation_id=None,
    )
    assert decision.allowed is True
    assert decision.reason == "granted"
    assert decision.effective_scope == "global"


async def test_unknown_tool_is_denied(tool_registry) -> None:
    decision = await tool_registry.authorize(
        "mcp_github_search_issues",
        task_id=None,
        conversation_id=None,
    )
    assert decision.allowed is False
    assert decision.reason == "unknown_tool"
    assert decision.effective_scope == "none"


async def test_disabled_definition_is_denied(session_factory, tool_registry) -> None:
    async with session_factory() as session:
        await session.execute(
            update(ToolDefinition)
            .where(ToolDefinition.name == "builtin.load_skill")
            .values(enabled=False)
        )
        await session.commit()

    decision = await tool_registry.authorize(
        "load_skill",
        task_id=None,
        conversation_id=None,
    )
    assert decision.allowed is False
    assert decision.reason == "denied"

    async with session_factory() as session:
        await session.execute(
            update(ToolDefinition)
            .where(ToolDefinition.name == "builtin.load_skill")
            .values(enabled=True)
        )
        await session.commit()


async def test_revoked_grant_is_denied(session_factory, tool_registry) -> None:
    async with session_factory() as session:
        definition = await session.scalar(
            select(ToolDefinition).where(ToolDefinition.name == "builtin.profile_dataset")
        )
        assert definition is not None
        await session.execute(
            update(ToolGrant)
            .where(
                ToolGrant.tool_definition_id == definition.id,
                ToolGrant.scope == "global",
            )
            .values(allowed=False)
        )
        await session.commit()

    decision = await tool_registry.authorize(
        "profile_dataset",
        task_id=None,
        conversation_id=None,
    )
    assert decision.allowed is False
    assert decision.reason == "denied"

    async with session_factory() as session:
        await session.execute(
            update(ToolGrant)
            .where(
                ToolGrant.tool_definition_id == definition.id,
                ToolGrant.scope == "global",
            )
            .values(allowed=True)
        )
        await session.commit()


async def test_write_tool_needs_risk_acknowledgement(session_factory, tool_registry) -> None:
    async with session_factory() as session:
        definition = await session.scalar(
            select(ToolDefinition).where(ToolDefinition.name == "builtin.generate_report")
        )
        assert definition is not None
        await session.execute(
            update(ToolGrant)
            .where(
                ToolGrant.tool_definition_id == definition.id,
                ToolGrant.scope == "global",
            )
            .values(risk_acknowledged=False)
        )
        await session.commit()

    decision = await tool_registry.authorize(
        "generate_report",
        task_id=None,
        conversation_id=None,
    )
    assert decision.allowed is False
    assert decision.reason == "risk_unacknowledged"

    async with session_factory() as session:
        await session.execute(
            update(ToolGrant)
            .where(
                ToolGrant.tool_definition_id == definition.id,
                ToolGrant.scope == "global",
            )
            .values(risk_acknowledged=True)
        )
        await session.commit()


async def test_list_for_run_returns_authorized_specs(tool_registry) -> None:
    specs = await tool_registry.list_for_run(task_id=None, conversation_id=None)
    assert {spec.model_name for spec in specs} == {
        spec.model_name for spec in BUILTIN_SPECS
    }


async def test_list_for_run_hides_disabled_tool(session_factory, tool_registry) -> None:
    async with session_factory() as session:
        await session.execute(
            update(ToolDefinition)
            .where(ToolDefinition.name == "builtin.inspect_dataset")
            .values(enabled=False)
        )
        await session.commit()

    specs = await tool_registry.list_for_run(task_id=None, conversation_id=None)
    assert "inspect_dataset" not in {spec.model_name for spec in specs}

    async with session_factory() as session:
        await session.execute(
            update(ToolDefinition)
            .where(ToolDefinition.name == "builtin.inspect_dataset")
            .values(enabled=True)
        )
        await session.commit()
