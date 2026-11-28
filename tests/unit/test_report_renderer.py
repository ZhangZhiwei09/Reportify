from __future__ import annotations

from datetime import UTC, datetime

import pytest

from reportify.modules.reports import renderer


def _chart(chart_type: str = "bar") -> dict:
    return {
        "type": "chart",
        "title": "状态分布",
        "chart_type": chart_type,
        "x_label": "status",
        "y_label": "count",
        "definition": "按 status 分组计数",
        "series": [
            {"name": "ok", "points": [{"x": "a", "y": 1}, {"x": "b", "y": 2}]},
            {"name": "error", "points": [{"x": "a", "y": 3}, {"x": "b", "y": 4}]},
        ],
    }


def _render(**overrides) -> str:
    payload = {
        "report_id": "00000000-0000-0000-0000-000000000001",
        "title": "测试报告",
        "summary": "总结",
        "sections": [
            {
                "id": "overview",
                "title": "概览",
                "blocks": [
                    {
                        "type": "kpi",
                        "label": "总数",
                        "value": 10,
                        "unit": "次",
                        "definition": "全表计数",
                    },
                    _chart("bar"),
                    {
                        "type": "table",
                        "title": "明细",
                        "columns": ["a", "b"],
                        "rows": [["x", 1]],
                    },
                    {"type": "text", "text": "说明文本"},
                ],
            }
        ],
        "lineage": {"snapshots": []},
        "generated_at": datetime.now(UTC),
        "template_name": None,
    }
    payload.update(overrides)
    return renderer.render_report(**payload)


def test_bar_option_shape() -> None:
    option = renderer.chart_option(_chart("bar"))
    assert option["xAxis"]["type"] == "category"
    assert option["xAxis"]["data"] == ["a", "b"]
    assert [series["type"] for series in option["series"]] == ["bar", "bar"]
    assert option["series"][0]["data"] == [1, 2]


def test_line_option_uses_categories() -> None:
    option = renderer.chart_option(_chart("line"))
    assert option["series"][0]["type"] == "line"
    assert option["tooltip"]["trigger"] == "axis"


def test_pie_option_shape() -> None:
    option = renderer.chart_option(_chart("pie"))
    series = option["series"][0]
    assert series["type"] == "pie"
    assert series["data"][0] == {"name": "a", "value": 1}


def test_scatter_option_shape() -> None:
    option = renderer.chart_option(_chart("scatter"))
    assert option["xAxis"]["type"] == "value"
    assert option["series"][0]["data"] == [["a", 1], ["b", 2]]


def test_unknown_chart_type_falls_back_to_bar() -> None:
    chart = _chart("radar")
    option = renderer.chart_option(chart)
    assert option["series"][0]["type"] == "bar"


def test_script_json_neutralises_closing_tags() -> None:
    encoded = renderer.script_json({"text": "</script><img src=x onerror=alert(1)>"})
    assert "</script>" not in encoded
    assert "<\\/script>" in encoded


def test_report_is_self_contained() -> None:
    html = _render()
    assert 'name="reportify-renderer" content="echarts-v1"' in html
    assert "echarts.init" in html
    assert "data-chart=" in html
    # the vendored bundle is inlined, not linked
    assert len(html) > 1_000_000
    assert "Apache ECharts" in html or "echarts" in html.lower()


def test_report_escapes_user_text() -> None:
    html = _render(
        title="<script>alert(1)</script>",
        summary="<img src=x onerror=alert(1)>",
        sections=[
            {
                "id": "a",
                "title": "<b>粗体</b>",
                "blocks": [
                    {"type": "text", "text": "<iframe src=javascript:alert(1)></iframe>"}
                ],
            }
        ],
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "<iframe" not in html


def test_report_renders_all_block_types() -> None:
    html = _render()
    assert "kpi-value" in html
    assert "chart-fallback" in html
    assert "明细" in html
    assert "说明文本" in html
    assert "数据来源与口径" in html


def test_report_has_no_placeholder_banner() -> None:
    html = _render()
    assert "占位渲染" not in html


@pytest.mark.parametrize("chart_type", ["line", "bar", "pie", "scatter"])
def test_every_chart_type_renders(chart_type: str) -> None:
    html = _render(
        sections=[
            {
                "id": "c",
                "title": "图表",
                "blocks": [_chart(chart_type)],
            }
        ]
    )
    assert 'data-chart="chart-0-0"' in html
    assert f'"type": "{chart_type}"' in html
