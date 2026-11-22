"""Placeholder HTML renderer.

M2 only proves the contract: a validated ``ReportSchema`` becomes a static HTML
file. Real chart rendering belongs to the §12+ Report Engine; the output is
explicitly marked as non-final (09 §14-3).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"
TEMPLATE_NAME = "report_placeholder.html.j2"
RENDERER_ID = "placeholder-v1"


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(("html", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_placeholder(
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
        sections=sections,
        lineage=lineage,
        generated_at=generated_at,
        template_name=template_name,
        renderer_id=RENDERER_ID,
    )
