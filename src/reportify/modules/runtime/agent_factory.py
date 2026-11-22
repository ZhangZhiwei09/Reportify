"""Model and Agent construction (02 §5).

Model construction is isolated here so tests can inject a ``FunctionModel`` and
production reads the DeepSeek settings.
"""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from reportify.core.config import Settings
from reportify.modules.runtime.schemas import RuntimeDeps

AGENT_RETRIES = {"output": 2, "tools": 1}


def build_model(settings: Settings) -> Model | None:
    """Return the configured chat model, or ``None`` when no key is set."""
    if settings.deepseek_api_key is None:
        return None
    return OpenAIChatModel(
        settings.deepseek_model,
        provider=DeepSeekProvider(
            api_key=settings.deepseek_api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
        ),
    )


def build_agent(model: Model, settings: Settings) -> Agent[RuntimeDeps, str]:
    """Single reusable Agent; every run-scoped concern is passed to ``run_*``."""
    return Agent[RuntimeDeps, str](
        model,
        deps_type=RuntimeDeps,
        output_type=str,
        retries=AGENT_RETRIES,
        tool_timeout=float(settings.run_tool_timeout_seconds),
        end_strategy="graceful",
        name="reportify-analyst",
    )
