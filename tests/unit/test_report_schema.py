from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from reportify.modules.reports.schemas import ReportSchema


def _kpi(**overrides):
    block = {
        "type": "kpi",
        "label": "总数",
        "value": 10,
        "definition": "全表计数",
        "lineage_refs": [str(uuid.uuid4())],
    }
    block.update(overrides)
    return block


def _schema(**overrides) -> dict:
    payload = {
        "title": "测试报告",
        "summary": "总结",
        "sections": [{"id": "overview", "title": "概览", "blocks": [_kpi()]}],
    }
    payload.update(overrides)
    return payload


def test_minimal_report_is_valid() -> None:
    report = ReportSchema.model_validate(_schema())
    assert report.title == "测试报告"
    assert len(report.sections) == 1
    assert len(report.lineage_refs()) == 1


def test_blocks_require_lineage() -> None:
    block = _kpi()
    block.pop("lineage_refs")
    with pytest.raises(ValidationError):
        ReportSchema.model_validate(
            _schema(sections=[{"id": "a", "title": "A", "blocks": [block]}])
        )


def test_unknown_block_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReportSchema.model_validate(
            _schema(
                sections=[
                    {
                        "id": "a",
                        "title": "A",
                        "blocks": [{"type": "iframe", "html": "<script>"}],
                    }
                ]
            )
        )


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        ReportSchema.model_validate(_schema(rendered_html="<b>x</b>"))


def test_duplicate_section_ids_are_rejected() -> None:
    section = {"id": "same", "title": "A", "blocks": [_kpi()]}
    with pytest.raises(ValidationError):
        ReportSchema.model_validate(_schema(sections=[section, section]))


def test_section_id_pattern() -> None:
    with pytest.raises(ValidationError):
        ReportSchema.model_validate(
            _schema(sections=[{"id": "Bad Id", "title": "A", "blocks": [_kpi()]}])
        )


def test_requires_at_least_one_section() -> None:
    with pytest.raises(ValidationError):
        ReportSchema.model_validate(_schema(sections=[]))


def test_table_width_must_match_columns() -> None:
    block = {
        "type": "table",
        "title": "明细",
        "columns": ["a", "b"],
        "rows": [["only-one"]],
        "lineage_refs": [str(uuid.uuid4())],
    }
    with pytest.raises(ValidationError):
        ReportSchema.model_validate(
            _schema(sections=[{"id": "a", "title": "A", "blocks": [block]}])
        )


def test_chart_requires_series_points() -> None:
    block = {
        "type": "chart",
        "title": "趋势",
        "chart_type": "line",
        "x_label": "date",
        "series": [{"name": "s", "points": []}],
        "definition": "按日累计",
        "lineage_refs": [str(uuid.uuid4())],
    }
    with pytest.raises(ValidationError):
        ReportSchema.model_validate(
            _schema(sections=[{"id": "a", "title": "A", "blocks": [block]}])
        )


def test_lineage_refs_are_deduplicated() -> None:
    shared = str(uuid.uuid4())
    report = ReportSchema.model_validate(
        _schema(
            sections=[
                {
                    "id": "a",
                    "title": "A",
                    "blocks": [_kpi(lineage_refs=[shared]), _kpi(lineage_refs=[shared])],
                }
            ]
        )
    )
    assert len(report.lineage_refs()) == 1


def test_text_block_needs_no_lineage() -> None:
    report = ReportSchema.model_validate(
        _schema(
            sections=[
                {"id": "a", "title": "A", "blocks": [{"type": "text", "text": "说明"}]}
            ]
        )
    )
    assert report.lineage_refs() == []
