"""Self-contained HTML report renderer (07 §7.2, §9).

The output is one file: ECharts is inlined so a report can be opened offline and
shared as-is. Every value coming from the Report Schema is escaped by Jinja2; the
only ``safe`` insertions are the vendored ECharts bundle and JSON that the
renderer itself serialised (with ``</`` neutralised).
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = PACKAGE_ROOT / "templates"
ECHARTS_PATH = PACKAGE_ROOT / "static" / "vendor" / "echarts.min.js"
TEMPLATE_NAME = "report.html.j2"
RENDERER_ID = "echarts-v1"

SUPPORTED_CHARTS = {"line", "bar", "pie", "scatter"}


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(("html", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )


@lru_cache(maxsize=1)
def echarts_bundle() -> str:
    """Vendored ECharts source, inlined into every report."""
    return ECHARTS_PATH.read_text(encoding="utf-8")


def script_json(payload: Any) -> str:
    """Serialise JSON for a <script> block without allowing ``</script>``."""
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    return encoded.replace("</", "<\\/")


def chart_option(chart: dict[str, Any]) -> dict[str, Any]:
    """Translate a ChartBlock payload into an ECharts option."""
    chart_type = chart.get("chart_type", "bar")
    if chart_type not in SUPPORTED_CHARTS:
        chart_type = "bar"

    series_payload = chart.get("series") or []
    names = [
        str(item.get("name") or f"series-{index}")
        for index, item in enumerate(series_payload)
    ]

    if chart_type == "pie":
        points = series_payload[0].get("points", []) if series_payload else []
        return {
            "tooltip": {"trigger": "item"},
            "legend": {"bottom": 0},
            "series": [
                {
                    "type": "pie",
                    "name": names[0] if names else "value",
                    "radius": ["35%", "65%"],
                    "data": [
                        {"name": str(point.get("x", "")), "value": point.get("y")}
                        for point in points
                    ],
                }
            ],
        }

    if chart_type == "scatter":
        return {
            "tooltip": {"trigger": "item"},
            "legend": {"bottom": 0} if len(series_payload) > 1 else {"show": False},
            "xAxis": {"type": "value", "name": chart.get("x_label", "")},
            "yAxis": {"type": "value", "name": chart.get("y_label") or ""},
            "series": [
                {
                    "type": "scatter",
                    "name": names[index],
                    "data": [
                        [point.get("x"), point.get("y")] for point in item.get("points", [])
                    ],
                }
                for index, item in enumerate(series_payload)
            ],
        }

    categories = [
        str(point.get("x", ""))
        for point in (series_payload[0].get("points", []) if series_payload else [])
    ]
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0} if len(series_payload) > 1 else {"show": False},
        "grid": {"left": 48, "right": 24, "top": 32, "bottom": 56},
        "xAxis": {
            "type": "category",
            "name": chart.get("x_label", ""),
            "data": categories,
            "axisLabel": {"rotate": 30 if len(categories) > 8 else 0},
        },
        "yAxis": {"type": "value", "name": chart.get("y_label") or ""},
        "series": [
            {
                "type": chart_type,
                "name": names[index],
                "data": [point.get("y") for point in item.get("points", [])],
            }
            for index, item in enumerate(series_payload)
        ],
    }


def _prepare_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections):
        blocks: list[dict[str, Any]] = []
        for block_index, block in enumerate(section.get("blocks", [])):
            entry = dict(block)
            if block.get("type") == "chart":
                chart_id = f"chart-{section_index}-{block_index}"
                entry["chart_id"] = chart_id
                entry["option_json"] = script_json(chart_option(block))
                entry["chart_type"] = block.get("chart_type", "bar")
            blocks.append(entry)
        prepared.append({**section, "blocks": blocks})
    return prepared


def render_report(
    *,
    report_id: str,
    title: str,
    summary: str,
    sections: list[dict[str, Any]],
    lineage: dict[str, Any],
    generated_at: datetime,
    template_name: str | None,
) -> str:
    template = _environment().get_template(TEMPLATE_NAME)
    return template.render(
        report_id=report_id,
        title=title,
        summary=summary,
        sections=_prepare_sections(sections),
        lineage=lineage,
        generated_at=generated_at,
        template_name=template_name,
        renderer_id=RENDERER_ID,
        echarts_js=echarts_bundle(),
    )
