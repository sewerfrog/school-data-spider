"""CSV output for high-cardinality programme catalog rows."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from university_admissions_crawler.extractor.schema import AdmissionsData, ProgrammeCatalogRecord


PROGRAMME_CATALOG_CSV_FIELDS: tuple[str, ...] = (
    "university_id",
    "university_name",
    "programme_id",
    "name",
    "faculty_or_school",
    "degree_or_award",
    "category",
    "mode",
    "duration_or_units",
    "admissions_choice_name",
    "specialisations_or_majors",
    "source_url",
    "source_title",
    "evidence_snippet",
    "evidence_confidence",
    "parse_status",
    "warnings",
    "retrieved_at",
)


def render_programme_catalog_csv(data: AdmissionsData) -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=PROGRAMME_CATALOG_CSV_FIELDS)
    writer.writeheader()
    for index, row in enumerate(data.programme_catalog):
        writer.writerow(_csv_row(data, row, index))
    return out.getvalue()


def write_programme_catalog_csv(data: AdmissionsData, output_dir: str | Path) -> Path | None:
    if not data.programme_catalog:
        return None
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "programme_catalog.csv"
    path.write_text(render_programme_catalog_csv(data), encoding="utf-8")
    return path


def _csv_row(data: AdmissionsData, row: ProgrammeCatalogRecord, index: int) -> dict[str, str]:
    source = _source_by_url(data).get(row.source_url)
    return {
        "university_id": str(data.run.config.get("university_id") or ""),
        "university_name": _institution_name(data),
        "programme_id": f"programme-catalog-{index + 1:03d}",
        "name": row.name,
        "faculty_or_school": row.faculty_or_school or "",
        "degree_or_award": row.degree_or_award or "",
        "category": row.category or "",
        "mode": row.mode or "",
        "duration_or_units": row.duration_or_units or "",
        "admissions_choice_name": row.admissions_choice_name or "",
        "specialisations_or_majors": "; ".join(row.specialisations_or_majors),
        "source_url": row.source_url,
        "source_title": source.title if source and source.title else "",
        "evidence_snippet": row.evidence_snippet,
        "evidence_confidence": str(row.evidence_confidence),
        "parse_status": row.parse_status,
        "warnings": _warnings_json(row),
        "retrieved_at": source.retrieved_at if source else "",
    }


def _source_by_url(data: AdmissionsData):
    return {source.source_url: source for source in data.sources}


def _institution_name(data: AdmissionsData) -> str:
    if data.institution.name.is_unknownish:
        return ""
    return str(data.institution.name.value)


def _warnings_json(row: ProgrammeCatalogRecord) -> str:
    if not row.warnings:
        return ""
    warnings: list[dict[str, Any]] = [warning.to_dict() for warning in row.warnings]
    return json.dumps(warnings, ensure_ascii=False, separators=(",", ":"))
