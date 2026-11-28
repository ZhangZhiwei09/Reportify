from __future__ import annotations

from reportify.modules.reports.diff import diff_schemas


def _schema(
    *,
    title: str = "报告",
    summary: str = "",
    kpi: int = 20,
    chart_points: int = 2,
    table_rows: int = 1,
    text: str = "说明",
    extra_section: bool = False,
) -> dict:
    sections = [
        {
            "id": "overview",
            "title": "概览",
            "blocks": [
                {
                    "type": "kpi",
                    "label": "事件总数",
                    "value": kpi,
                    "definition": "全部行数",
                    "lineage_refs": [],
                },
                {
                    "type": "chart",
                    "title": "分布",
                    "chart_type": "bar",
                    "x_label": "status",
                    "series": [
                        {
                            "name": "count",
                            "points": [
                                {"x": f"p{index}", "y": index} for index in range(chart_points)
                            ],
                        }
                    ],
                    "definition": "分组计数",
                    "lineage_refs": [],
                },
                {
                    "type": "table",
                    "title": "明细",
                    "columns": ["status"],
                    "rows": [["ok"] for _ in range(table_rows)],
                    "lineage_refs": [],
                },
                {"type": "text", "text": text},
            ],
        }
    ]
    if extra_section:
        sections.append(
            {
                "id": "trend",
                "title": "趋势",
                "blocks": [{"type": "text", "text": "新章节"}],
            }
        )
    return {"title": title, "summary": summary, "sections": sections}


def test_identical_schemas() -> None:
    schema = _schema()
    diff = diff_schemas(schema, schema, base_version=1, target_version=2)
    assert diff.identical is True
    assert diff.kpis == []
    assert diff.sections_added == []
    assert diff.title_before is None


def test_kpi_value_change() -> None:
    diff = diff_schemas(
        _schema(kpi=20),
        _schema(kpi=25),
        base_version=1,
        target_version=2,
    )
    assert diff.identical is False
    assert [(item.label, item.before, item.after) for item in diff.kpis] == [
        ("事件总数", 20, 25)
    ]


def test_section_added_and_removed() -> None:
    added = diff_schemas(
        _schema(),
        _schema(extra_section=True),
        base_version=1,
        target_version=2,
    )
    assert added.sections_added == ["trend"]
    assert added.identical is False

    removed = diff_schemas(
        _schema(extra_section=True),
        _schema(),
        base_version=2,
        target_version=3,
    )
    assert removed.sections_removed == ["trend"]


def test_chart_and_table_changes() -> None:
    diff = diff_schemas(
        _schema(chart_points=2, table_rows=1),
        _schema(chart_points=5, table_rows=3),
        base_version=1,
        target_version=2,
    )
    assert diff.charts[0].points_before == 2
    assert diff.charts[0].points_after == 5
    assert diff.tables[0].rows_before == 1
    assert diff.tables[0].rows_after == 3


def test_text_and_header_changes() -> None:
    diff = diff_schemas(
        _schema(title="旧标题", summary="旧摘要", text="旧说明"),
        _schema(title="新标题", summary="新摘要", text="新说明"),
        base_version=1,
        target_version=2,
    )
    assert diff.title_before == "旧标题"
    assert diff.title_after == "新标题"
    assert diff.summary_after == "新摘要"
    assert diff.texts[0].before == "旧说明"
    assert diff.texts[0].after == "新说明"
