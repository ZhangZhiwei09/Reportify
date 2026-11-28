"""Structured Report Schema diff (M9).

Pure functions over the validated schema dictionaries stored on ``report_ref``.
Nothing here parses HTML: the contract is the schema, so a revision diff is a
deterministic comparison of the same structure the renderer consumed.
"""

from __future__ import annotations

from typing import Any

from reportify.modules.reports.schemas import (
    ChartChange,
    KpiChange,
    ReportDiff,
    TableChange,
    TextChange,
)


def diff_schemas(
    base: dict[str, Any],
    target: dict[str, Any],
    *,
    base_version: int,
    target_version: int,
) -> ReportDiff:
    diff = ReportDiff(base_version=base_version, target_version=target_version)
    if base.get("title") != target.get("title"):
        diff.title_before = base.get("title")
        diff.title_after = target.get("title")
    if base.get("summary") != target.get("summary"):
        diff.summary_before = base.get("summary")
        diff.summary_after = target.get("summary")

    base_sections = {section["id"]: section for section in base.get("sections", [])}
    target_sections = {section["id"]: section for section in target.get("sections", [])}
    diff.sections_added = [
        section_id
        for section_id in target_sections
        if section_id not in base_sections
    ]
    diff.sections_removed = [
        section_id
        for section_id in base_sections
        if section_id not in target_sections
    ]
    for section_id, target_section in target_sections.items():
        base_section = base_sections.get(section_id)
        if base_section is None:
            continue
        _diff_section(section_id, base_section, target_section, diff)

    diff.identical = not (
        diff.title_before is not None
        or diff.summary_before is not None
        or diff.sections_added
        or diff.sections_removed
        or diff.kpis
        or diff.charts
        or diff.tables
        or diff.texts
    )
    return diff


def _diff_section(
    section_id: str,
    base: dict[str, Any],
    target: dict[str, Any],
    diff: ReportDiff,
) -> None:
    base_blocks = _block_index(base)
    target_blocks = _block_index(target)
    for key in sorted(set(base_blocks) | set(target_blocks)):
        before = base_blocks.get(key)
        after = target_blocks.get(key)
        kind = key[0]
        name = key[1]
        if kind == "kpi":
            _diff_kpi(section_id, name, before, after, diff)
        elif kind == "chart":
            _diff_chart(section_id, name, before, after, diff)
        elif kind == "table":
            _diff_table(section_id, name, before, after, diff)
        else:
            _diff_text(section_id, name, before, after, diff)


def _block_index(section: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for position, block in enumerate(section.get("blocks", [])):
        kind = str(block.get("type", "unknown"))
        # A text block has no name; match it by position within the section.
        name = block.get("label") or block.get("title") or f"#{position}"
        index[(kind, str(name))] = block
    return index


def _diff_kpi(
    section_id: str,
    label: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    diff: ReportDiff,
) -> None:
    before_value = before.get("value") if before else None
    after_value = after.get("value") if after else None
    if before is not None and after is not None and before_value == after_value:
        return
    diff.kpis.append(
        KpiChange(
            section=section_id,
            label=label,
            before=before_value,
            after=after_value,
        )
    )


def _diff_chart(
    section_id: str,
    title: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    diff: ReportDiff,
) -> None:
    before_series = _series_count(before)
    after_series = _series_count(after)
    before_points = _point_count(before)
    after_points = _point_count(after)
    if (before_series, before_points) == (after_series, after_points):
        return
    diff.charts.append(
        ChartChange(
            section=section_id,
            title=title,
            series_before=before_series,
            series_after=after_series,
            points_before=before_points,
            points_after=after_points,
        )
    )


def _diff_table(
    section_id: str,
    title: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    diff: ReportDiff,
) -> None:
    before_rows = len(before.get("rows", [])) if before else 0
    after_rows = len(after.get("rows", [])) if after else 0
    if before_rows == after_rows:
        return
    diff.tables.append(
        TableChange(
            section=section_id,
            title=title,
            rows_before=before_rows,
            rows_after=after_rows,
        )
    )


def _diff_text(
    section_id: str,
    name: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    diff: ReportDiff,
) -> None:
    before_text = str(before.get("text", "")) if before else ""
    after_text = str(after.get("text", "")) if after else ""
    if before_text == after_text:
        return
    diff.texts.append(
        TextChange(
            section=section_id,
            before=before_text,
            after=after_text,
        )
    )


def _series_count(block: dict[str, Any] | None) -> int:
    return len(block.get("series", [])) if block else 0


def _point_count(block: dict[str, Any] | None) -> int:
    if not block:
        return 0
    return sum(len(series.get("points", [])) for series in block.get("series", []))
