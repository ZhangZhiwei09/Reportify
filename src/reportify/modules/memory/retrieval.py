"""Lexical memory retrieval (M10).

Deliberately embedding-free: the platform has no vector store, and a lexical
overlap score is deterministic, explainable and testable. A note is only injected
when the current goal actually shares tokens with it, which keeps instructions
short and avoids irrelevant "memories" steering the agent.
"""

from __future__ import annotations

import re

from reportify.db.models import Memory
from reportify.modules.memory.schemas import MemoryItem

_WORD = re.compile(r"[a-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> set[str]:
    """Lowercased latin words plus CJK character bigrams."""
    lowered = text.lower()
    tokens = set(_WORD.findall(lowered))
    chars = _CJK.findall(lowered)
    tokens.update("".join(pair) for pair in zip(chars, chars[1:], strict=False))
    return tokens


def rank(
    query: str,
    memories: list[Memory],
    *,
    limit: int = 5,
) -> list[MemoryItem]:
    """Top memories by shared-token count, newest first on ties."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    scored: list[tuple[int, float, str, Memory]] = []
    for memory in memories:
        haystack = memory.content + " " + " ".join(memory.tags or ())
        overlap = len(query_tokens & tokenize(haystack))
        if overlap <= 0:
            continue
        # Ascending sort => negate overlap and timestamp so best/newest come first.
        scored.append(
            (
                -overlap,
                -memory.created_at.timestamp(),
                str(memory.id),
                memory,
            )
        )
    scored.sort()
    return [
        MemoryItem(id=row[3].id, kind=row[3].kind, content=row[3].content)
        for row in scored[: max(1, limit)]
    ]
