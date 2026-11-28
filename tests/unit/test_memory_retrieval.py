from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from reportify.db.models import Memory
from reportify.modules.memory.retrieval import rank, tokenize


def _memory(content: str, *, age_minutes: int = 0, tags: list[str] | None = None) -> Memory:
    return Memory(
        id=uuid4(),
        scope="global",
        scope_id=None,
        kind="fact",
        content=content,
        tags=tags or [],
        created_by="user",
        created_at=datetime.now(UTC) - timedelta(minutes=age_minutes),
    )


def test_tokenize_latin_and_cjk_bigrams() -> None:
    tokens = tokenize("Sales 2026 销售报告")
    assert "sales" in tokens
    assert "2026" in tokens
    assert "销售" in tokens
    assert "售报" in tokens


def test_rank_prefers_more_overlap() -> None:
    weak = _memory("时间范围默认 7 天")
    strong = _memory("分析默认使用最近 30 天的时间范围")
    items = rank("分析最近 30 天销售数据", [weak, strong])
    assert [item.content for item in items][0] == strong.content


def test_rank_drops_unrelated_notes() -> None:
    items = rank("分析销售数据", [_memory("配色偏好：深色背景")])
    assert items == []


def test_rank_empty_query_returns_nothing() -> None:
    assert rank("", [_memory("任意内容")]) == []


def test_rank_respects_limit_and_ties_use_newest() -> None:
    older = _memory("销售数据口径", age_minutes=10)
    newer = _memory("销售数据口径（更新）", age_minutes=0)
    items = rank("销售数据", [older, newer], limit=1)
    assert len(items) == 1
    assert items[0].id == newer.id


def test_rank_includes_tag_matches() -> None:
    tagged = _memory("季度汇报口径", tags=["销售"])
    items = rank("销售分析", [tagged])
    assert [item.id for item in items] == [tagged.id]
