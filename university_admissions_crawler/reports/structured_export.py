"""Cleaning-oriented structured output artifacts.

This module is intentionally a pure export layer. It does not change extraction
behavior or the legacy result/report/CSV contracts.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from university_admissions_crawler.evidence.provenance import content_hash
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    EvidenceItem,
    FieldValue,
    ProgrammeCatalogRecord,
    ProgrammeRecord,
    RequirementRecord,
    SourceRecord,
    WarningRecord,
    collect_nested_field_warnings,
)


STRUCTURED_OUTPUT_SCHEMA_VERSION = "structured-output-v1"

STRUCTURED_PROGRAMME_CATALOG_CSV_FIELDS: tuple[str, ...] = (
    "schema_version",
    "run_id",
    "university_id",
    "record_id",
    "name",
    "faculty_or_school",
    "degree_or_award",
    "category",
    "mode",
    "duration_or_units",
    "admissions_choice_name",
    "specialisations_or_majors",
    "status",
    "confidence",
    "parse_status",
    "quality_flags",
    "warnings_count",
    "needs_review",
    "source_id",
    "source_url",
    "evidence_id",
    "evidence_path",
    "retrieved_at",
)

STRUCTURED_REQUIREMENT_RECORD_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("application_periods", ("admissions", "application_periods")),
    ("fees", ("fees",)),
    ("english_requirements", ("admissions", "english_requirements")),
    ("accepted_qualifications", ("admissions", "accepted_qualifications")),
    ("required_documents", ("admissions", "required_documents")),
    ("scholarships", ("scholarships",)),
    ("contacts", ("contacts",)),
)

STRUCTURED_RECORD_TYPES: tuple[str, ...] = (
    "programme_catalog",
    "application_periods",
    "fees",
    "english_requirements",
    "accepted_qualifications",
    "required_documents",
    "scholarships",
    "contacts",
    "programmes_legacy",
)

STRUCTURED_BATCH_FILE_SPECS: tuple[tuple[str, str, Path], ...] = (
    (
        "all_programme_catalog",
        "all_programme_catalog.jsonl",
        Path("structured") / "records" / "programme_catalog.jsonl",
    ),
    ("all_missing_fields", "all_missing_fields.jsonl", Path("structured") / "missing_fields.jsonl"),
    ("all_sources", "all_sources.jsonl", Path("structured") / "sources.jsonl"),
)


def write_structured_outputs(data: AdmissionsData, output_dir: str | Path) -> dict[str, Path]:
    """Write cleaning-friendly structured artifacts and return created paths."""

    out_dir = Path(output_dir)
    records_dir = out_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    context = _export_context(data)
    source_rows = _source_rows(data, context)
    evidence_rows = _evidence_rows(data, context)
    missing_rows = _missing_field_rows(data, context)
    warning_rows = _warning_rows(data, context)
    programme_rows = _programme_catalog_rows(data, context)
    requirement_rows = {
        record_type: _requirement_rows(data, context, record_type, _records_at_path(data, path))
        for record_type, path in STRUCTURED_REQUIREMENT_RECORD_SPECS
    }
    legacy_programme_rows = _legacy_programme_rows(data, context)
    record_groups: dict[str, list[dict[str, Any]]] = {
        "programme_catalog": programme_rows,
        **requirement_rows,
        "programmes_legacy": legacy_programme_rows,
    }
    diagnostics = _diagnostics(data, context)
    facts_rows = [row for record_type in STRUCTURED_RECORD_TYPES for row in record_groups[record_type]]

    paths = {
        "manifest": out_dir / "manifest.json",
        "institution": out_dir / "institution.json",
        "facts": out_dir / "facts.jsonl",
        "sources": out_dir / "sources.jsonl",
        "evidence": out_dir / "evidence.jsonl",
        "missing_fields": out_dir / "missing_fields.jsonl",
        "warnings": out_dir / "warnings.jsonl",
        "diagnostics": out_dir / "diagnostics.json",
        "programme_catalog_jsonl": records_dir / "programme_catalog.jsonl",
        "programme_catalog_csv": records_dir / "programme_catalog.csv",
        "application_periods_jsonl": records_dir / "application_periods.jsonl",
        "fees_jsonl": records_dir / "fees.jsonl",
        "english_requirements_jsonl": records_dir / "english_requirements.jsonl",
        "accepted_qualifications_jsonl": records_dir / "accepted_qualifications.jsonl",
        "required_documents_jsonl": records_dir / "required_documents.jsonl",
        "scholarships_jsonl": records_dir / "scholarships.jsonl",
        "contacts_jsonl": records_dir / "contacts.jsonl",
        "programmes_legacy_jsonl": records_dir / "programmes_legacy.jsonl",
    }

    record_counts = {record_type: len(rows) for record_type, rows in record_groups.items()}
    manifest = _manifest(
        data,
        context,
        counts={
            "facts": len(facts_rows),
            "sources": len(source_rows),
            "evidence": len(evidence_rows),
            "missing_fields": len(missing_rows),
            "warnings": len(warning_rows),
            **record_counts,
        },
        files=paths,
        structured_root=out_dir,
    )
    _write_json(paths["manifest"], manifest)
    _write_json(paths["institution"], _institution(data, context))
    _write_json(paths["diagnostics"], diagnostics)
    _write_jsonl(paths["facts"], facts_rows)
    _write_jsonl(paths["sources"], source_rows)
    _write_jsonl(paths["evidence"], evidence_rows)
    _write_jsonl(paths["missing_fields"], missing_rows)
    _write_jsonl(paths["warnings"], warning_rows)
    _write_jsonl(paths["programme_catalog_jsonl"], programme_rows)
    for record_type, _ in STRUCTURED_REQUIREMENT_RECORD_SPECS:
        _write_jsonl(paths[f"{record_type}_jsonl"], record_groups[record_type])
    _write_jsonl(paths["programmes_legacy_jsonl"], legacy_programme_rows)
    _write_programme_catalog_csv(paths["programme_catalog_csv"], programme_rows)
    return paths


def write_structured_batch_outputs(
    university_output_dirs: Iterable[str | Path],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Merge selected per-university structured JSONL files for batch cleaning."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = {key: out_dir / filename for key, filename, _ in STRUCTURED_BATCH_FILE_SPECS}
    for key, _, relative_path in STRUCTURED_BATCH_FILE_SPECS:
        rows: list[dict[str, Any]] = []
        for university_dir in university_output_dirs:
            rows.extend(_read_jsonl(Path(university_dir) / relative_path))
        _write_jsonl(paths[key], rows)
    return paths


def _export_context(data: AdmissionsData) -> dict[str, Any]:
    source_ids = {source.source_url: _source_id(source) for source in data.sources}
    evidence_ids = {_evidence_key(evidence): _evidence_id(evidence) for evidence in data.evidence}
    university_id = _university_id(data)
    return {
        "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
        "run_id": _run_id(data, university_id),
        "university_id": university_id,
        "university_name": _institution_name(data),
        "source_ids": source_ids,
        "evidence_ids": evidence_ids,
    }


def _manifest(
    data: AdmissionsData,
    context: dict[str, Any],
    *,
    counts: dict[str, int],
    files: dict[str, Path],
    structured_root: Path,
) -> dict[str, Any]:
    file_map = {
        key: path.relative_to(structured_root).as_posix()
        for key, path in sorted(files.items())
        if path != files["manifest"]
    }
    return {
        "schema_version": context["schema_version"],
        "run_id": context["run_id"],
        "generated_at": data.run.retrieved_at,
        "input_url": data.run.input_url,
        "university_id": context["university_id"],
        "university_name": context["university_name"],
        "legacy_outputs_preserved": True,
        "counts": counts,
        "files": file_map,
        "notes": [
            "result.json remains the legacy full internal snapshot.",
            "structured/*.jsonl files are intended for downstream cleaning joins.",
        ],
    }


def _institution(data: AdmissionsData, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": context["schema_version"],
        "run_id": context["run_id"],
        "university_id": context["university_id"],
        "name": context["university_name"],
        "homepage_url": data.institution.homepage_url,
        "country_or_region": None if data.institution.country_or_region.is_unknownish else data.institution.country_or_region.value,
        "input_url": data.run.input_url,
        "retrieved_at": data.run.retrieved_at,
        "confidence": str(data.confidence),
    }


def _source_rows(data: AdmissionsData, context: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": context["schema_version"],
            "run_id": context["run_id"],
            "university_id": context["university_id"],
            "source_id": context["source_ids"][source.source_url],
            "source_url": source.source_url,
            "normalized_source_host": _normalized_source_host(source.source_url),
            "normalized_source_path": _normalized_source_path(source.source_url),
            "source_type": str(source.source_type),
            "title": source.title,
            "retrieved_at": source.retrieved_at,
            "academic_year": source.academic_year,
            "page_number": source.page_number,
            "content_hash": source.content_hash,
            "engine": source.engine,
            "is_official": source.is_official,
        }
        for source in data.sources
    ]


def _evidence_rows(data: AdmissionsData, context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for evidence in data.evidence:
        rows.append(
            {
                "schema_version": context["schema_version"],
                "run_id": context["run_id"],
                "university_id": context["university_id"],
                "evidence_id": context["evidence_ids"][_evidence_key(evidence)],
                "claim_path": evidence.claim_path,
                "source_id": _source_id_for_url(context, evidence.source_url),
                "source_url": evidence.source_url,
                "source_type": str(evidence.source_type),
                "title": evidence.title,
                "snippet": evidence.snippet,
                "confidence": str(evidence.confidence),
                "retrieved_at": evidence.retrieved_at,
                "academic_year": evidence.academic_year,
                "page_number": evidence.page_number,
                "warnings_count": len(evidence.warnings),
            }
        )
    return rows


def _missing_field_rows(data: AdmissionsData, context: dict[str, Any]) -> list[dict[str, Any]]:
    missing_reasons = data.run.config.get("missing_reasons")
    if not isinstance(missing_reasons, dict):
        return []
    rows: list[dict[str, Any]] = []
    for field_key, raw in sorted(missing_reasons.items()):
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "schema_version": context["schema_version"],
                "run_id": context["run_id"],
                "university_id": context["university_id"],
                "field_key": str(field_key),
                "status": "missing",
                "reason": raw.get("reason"),
                "canonical_reason": raw.get("canonical_reason"),
                "action_target": raw.get("action_target"),
                "attempt_count": raw.get("attempt_count"),
                "source_urls": raw.get("source_urls", []),
                "next_action": raw.get("next_action"),
                "note": raw.get("note"),
                "raw": raw,
            }
        )
    return rows


def _warning_rows(data: AdmissionsData, context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def append_warning(warning: WarningRecord, *, scope: str, record_id: str | None = None) -> None:
        key = (scope, str(warning.code), warning.message, warning.field or "")
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "schema_version": context["schema_version"],
                "run_id": context["run_id"],
                "university_id": context["university_id"],
                "warning_id": "warning__" + content_hash("|".join(key))[:12],
                "scope": scope,
                "record_id": record_id,
                "code": str(warning.code),
                "message": warning.message,
                "field": warning.field,
                "source_urls": list(warning.source_urls),
            }
        )

    for warning in data.warnings:
        append_warning(warning, scope="run")
    for warning in collect_nested_field_warnings(data):
        append_warning(warning, scope="field")
    for index, row in enumerate(data.programme_catalog):
        record_id = _programme_record_id(data, context, row)
        for warning in row.warnings:
            append_warning(warning, scope="programme_catalog", record_id=record_id)
    return rows


def _programme_catalog_rows(data: AdmissionsData, context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in data.programme_catalog:
        source = _source_by_url(data).get(row.source_url)
        evidence = _evidence_by_claim_path(data).get(row.evidence_path)
        evidence_refs = []
        if evidence is not None:
            evidence_refs.append(
                {
                    "evidence_id": context["evidence_ids"][_evidence_key(evidence)],
                    "claim_path": evidence.claim_path,
                }
            )
        source_refs = []
        if row.source_url:
            source_refs.append(
                {
                    "source_id": _source_id_for_url(context, row.source_url),
                    "source_url": row.source_url,
                    "source_type": str(source.source_type) if source else None,
                    "title": source.title if source else None,
                }
            )
        quality_flags = _quality_flags(row)
        rows.append(
            {
                "schema_version": context["schema_version"],
                "run_id": context["run_id"],
                "university_id": context["university_id"],
                "university_name": context["university_name"],
                "record_type": "programme_catalog",
                "record_id": _programme_record_id(data, context, row),
                "normalized_programme_name_key": _normalized_text_key(row.name),
                "status": "accepted",
                "confidence": str(row.evidence_confidence),
                "parse_status": row.parse_status,
                "quality_flags": quality_flags,
                "needs_review": bool(row.warnings or row.parse_status != "parsed"),
                "value": {
                    "name": row.name,
                    "faculty_or_school": row.faculty_or_school,
                    "degree_or_award": row.degree_or_award,
                    "category": row.category,
                    "mode": row.mode,
                    "duration_or_units": row.duration_or_units,
                    "admissions_choice_name": row.admissions_choice_name,
                    "specialisations_or_majors": list(row.specialisations_or_majors),
                },
                "raw": {
                    "evidence_snippet": row.evidence_snippet,
                    "evidence_path": row.evidence_path,
                },
                "source_refs": source_refs,
                "evidence_refs": evidence_refs,
                "warnings_count": len(row.warnings),
                "warnings": [warning.to_dict() for warning in row.warnings],
                "retrieved_at": source.retrieved_at if source else data.run.retrieved_at,
            }
        )
    return rows


def _requirement_rows(
    data: AdmissionsData,
    context: dict[str, Any],
    record_type: str,
    records: list[RequirementRecord],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        evidence_refs = _evidence_refs_for_claim_paths(data, context, _requirement_claim_paths(record))
        source_refs = _source_refs_for_evidence_refs(data, context, evidence_refs)
        warnings = _requirement_warnings(record)
        rows.append(
            {
                "schema_version": context["schema_version"],
                "run_id": context["run_id"],
                "university_id": context["university_id"],
                "university_name": context["university_name"],
                "record_type": record_type,
                "record_id": _requirement_record_id(data, context, record_type, record),
                "status": str(record.value.status),
                "confidence": str(record.value.confidence),
                "parse_status": record.value.parse_status,
                "quality_flags": _field_quality_flags(record.value, record.applicant_group, record.qualification),
                "needs_review": bool(record.value.is_unknownish or warnings or record.value.parse_status != "parsed"),
                "value": {
                    "label": record.label,
                    "value": None if record.value.is_unknownish else record.value.value,
                    "parsed": record.value.parsed,
                    "applicant_group": None if record.applicant_group.is_unknownish else record.applicant_group.value,
                    "qualification": None if record.qualification.is_unknownish else record.qualification.value,
                    "requires_applicant_group": record.requires_applicant_group,
                },
                "raw": {
                    "raw_text": record.value.raw_text,
                    "applicant_group_raw_text": record.applicant_group.raw_text,
                    "qualification_raw_text": record.qualification.raw_text,
                },
                "source_refs": source_refs,
                "evidence_refs": evidence_refs,
                "warnings_count": len(warnings),
                "warnings": [warning.to_dict() for warning in warnings],
                "retrieved_at": _retrieved_at_from_refs(data, source_refs),
            }
        )
    return rows


def _legacy_programme_rows(data: AdmissionsData, context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for programme in data.programmes:
        evidence_refs = _evidence_refs_for_claim_paths(data, context, _legacy_programme_claim_paths(programme))
        source_refs = _source_refs_for_evidence_refs(data, context, evidence_refs)
        if programme.source_url:
            source_refs = _merge_source_refs(
                source_refs,
                _source_refs_for_urls(data, context, [programme.source_url]),
            )
        warnings = _legacy_programme_warnings(programme)
        rows.append(
            {
                "schema_version": context["schema_version"],
                "run_id": context["run_id"],
                "university_id": context["university_id"],
                "university_name": context["university_name"],
                "record_type": "programmes_legacy",
                "record_id": _legacy_programme_record_id(data, context, programme),
                "normalized_programme_name_key": _normalized_text_key(
                    "" if programme.name.is_unknownish else str(programme.name.value)
                ),
                "status": str(programme.name.status),
                "confidence": str(programme.name.confidence),
                "parse_status": programme.name.parse_status,
                "quality_flags": _field_quality_flags(programme.name, programme.degree, programme.faculty_or_school),
                "needs_review": bool(programme.name.is_unknownish or warnings or programme.name.parse_status != "parsed"),
                "value": {
                    "name": None if programme.name.is_unknownish else programme.name.value,
                    "degree": None if programme.degree.is_unknownish else programme.degree.value,
                    "faculty_or_school": None if programme.faculty_or_school.is_unknownish else programme.faculty_or_school.value,
                    "source_url": programme.source_url,
                    "prerequisites": [_requirement_value_payload(record) for record in programme.prerequisites],
                    "legacy_semantics": "Compatibility programme record; use programme_catalog for high-cardinality catalog cleaning.",
                },
                "raw": {
                    "name_raw_text": programme.name.raw_text,
                    "degree_raw_text": programme.degree.raw_text,
                    "faculty_or_school_raw_text": programme.faculty_or_school.raw_text,
                },
                "source_refs": source_refs,
                "evidence_refs": evidence_refs,
                "warnings_count": len(warnings),
                "warnings": [warning.to_dict() for warning in warnings],
                "retrieved_at": _retrieved_at_from_refs(data, source_refs),
            }
        )
    return rows


def _records_at_path(data: AdmissionsData, path: tuple[str, ...]) -> list[RequirementRecord]:
    current: Any = data
    for part in path:
        current = getattr(current, part)
    return list(current)


def _requirement_claim_paths(record: RequirementRecord) -> list[str]:
    paths: list[str] = []
    paths.extend(record.value.evidence)
    paths.extend(record.applicant_group.evidence)
    paths.extend(record.qualification.evidence)
    return list(dict.fromkeys(paths))


def _legacy_programme_claim_paths(programme: ProgrammeRecord) -> list[str]:
    paths: list[str] = []
    paths.extend(programme.evidence)
    paths.extend(programme.name.evidence)
    paths.extend(programme.degree.evidence)
    paths.extend(programme.faculty_or_school.evidence)
    for prerequisite in programme.prerequisites:
        paths.extend(_requirement_claim_paths(prerequisite))
    return list(dict.fromkeys(paths))


def _evidence_refs_for_claim_paths(
    data: AdmissionsData,
    context: dict[str, Any],
    claim_paths: list[str],
) -> list[dict[str, Any]]:
    evidence_by_claim_path = _evidence_by_claim_path(data)
    rows: list[dict[str, Any]] = []
    for claim_path in claim_paths:
        evidence = evidence_by_claim_path.get(claim_path)
        row = {"claim_path": claim_path}
        if evidence is not None:
            row["evidence_id"] = context["evidence_ids"][_evidence_key(evidence)]
        else:
            row["evidence_id"] = None
        rows.append(row)
    return rows


def _source_refs_for_evidence_refs(
    data: AdmissionsData,
    context: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_by_claim_path = _evidence_by_claim_path(data)
    source_urls: list[str] = []
    for evidence_ref in evidence_refs:
        evidence = evidence_by_claim_path.get(evidence_ref["claim_path"])
        if evidence is not None:
            source_urls.append(evidence.source_url)
    return _source_refs_for_urls(data, context, source_urls)


def _source_refs_for_urls(
    data: AdmissionsData,
    context: dict[str, Any],
    source_urls: list[str],
) -> list[dict[str, Any]]:
    sources = _source_by_url(data)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_url in source_urls:
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        source = sources.get(source_url)
        rows.append(
            {
                "source_id": _source_id_for_url(context, source_url),
                "source_url": source_url,
                "source_type": str(source.source_type) if source else None,
                "title": source.title if source else None,
            }
        )
    return rows


def _merge_source_refs(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in first + second:
        source_url = row.get("source_url")
        if not source_url or source_url in seen:
            continue
        seen.add(source_url)
        rows.append(row)
    return rows


def _retrieved_at_from_refs(data: AdmissionsData, source_refs: list[dict[str, Any]]) -> str:
    sources = _source_by_url(data)
    for source_ref in source_refs:
        source = sources.get(source_ref.get("source_url"))
        if source is not None:
            return source.retrieved_at
    return data.run.retrieved_at


def _requirement_value_payload(record: RequirementRecord) -> dict[str, Any]:
    return {
        "label": record.label,
        "value": None if record.value.is_unknownish else record.value.value,
        "parsed": record.value.parsed,
        "applicant_group": None if record.applicant_group.is_unknownish else record.applicant_group.value,
        "qualification": None if record.qualification.is_unknownish else record.qualification.value,
        "requires_applicant_group": record.requires_applicant_group,
        "parse_status": record.value.parse_status,
        "confidence": str(record.value.confidence),
        "status": str(record.value.status),
    }


def _requirement_warnings(record: RequirementRecord) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    warnings.extend(record.value.warnings)
    warnings.extend(record.applicant_group.warnings)
    warnings.extend(record.qualification.warnings)
    return warnings


def _legacy_programme_warnings(programme: ProgrammeRecord) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    warnings.extend(programme.name.warnings)
    warnings.extend(programme.degree.warnings)
    warnings.extend(programme.faculty_or_school.warnings)
    for prerequisite in programme.prerequisites:
        warnings.extend(_requirement_warnings(prerequisite))
    return warnings


def _requirement_record_id(
    data: AdmissionsData,
    context: dict[str, Any],
    record_type: str,
    record: RequirementRecord,
) -> str:
    claim_paths = _requirement_claim_paths(record)
    snippets = _evidence_snippets_for_claim_paths(data, claim_paths)
    key = _stable_json(
        {
            "university_id": context["university_id"],
            "record_type": record_type,
            "label": record.label,
            "value": record.value.value,
            "applicant_group": record.applicant_group.value,
            "qualification": record.qualification.value,
            "snippets": snippets,
        }
    )
    return f"{record_type}__" + content_hash(key)[:12]


def _legacy_programme_record_id(
    data: AdmissionsData,
    context: dict[str, Any],
    programme: ProgrammeRecord,
) -> str:
    snippets = _evidence_snippets_for_claim_paths(data, _legacy_programme_claim_paths(programme))
    key = _stable_json(
        {
            "university_id": context["university_id"],
            "record_type": "programmes_legacy",
            "name": programme.name.value,
            "degree": programme.degree.value,
            "faculty_or_school": programme.faculty_or_school.value,
            "source_url": programme.source_url,
            "snippets": snippets,
        }
    )
    return "programmes_legacy__" + content_hash(key)[:12]


def _evidence_snippets_for_claim_paths(data: AdmissionsData, claim_paths: list[str]) -> list[str]:
    evidence_by_claim_path = _evidence_by_claim_path(data)
    return [evidence.snippet for claim_path in claim_paths if (evidence := evidence_by_claim_path.get(claim_path))]


def _field_quality_flags(primary: FieldValue, *supporting_fields: FieldValue) -> list[str]:
    flags: list[str] = []
    for index, field in enumerate((primary, *supporting_fields)):
        flags.extend(_warning_flags(field.warnings))
        if index > 0 and field.is_unknownish and not field.warnings:
            continue
        if field.parse_status != "parsed":
            flags.append(f"parse_status_{_slug(field.parse_status)}")
        if str(field.status) != "known":
            flags.append(f"status_{_slug(str(field.status))}")
    return sorted(set(flags))


def _warning_flags(warnings: list[WarningRecord]) -> list[str]:
    flags: list[str] = []
    for warning in warnings:
        message = warning.message.strip()
        prefix = message.split(":", 1)[0].strip().lower() if ":" in message else ""
        if prefix and re.fullmatch(r"[a-z0-9_]+", prefix):
            flags.append(prefix)
        else:
            flags.append(str(warning.code))
    return flags


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _diagnostics(data: AdmissionsData, context: dict[str, Any]) -> dict[str, Any]:
    config = data.run.config
    keys = (
        "coverage",
        "template_completeness",
        "programme_catalog_summary",
        "programme_catalog_api_discovery_summary",
        "programme_catalog_api_capture",
        "programme_catalog_browser_capture",
        "programme_catalog_static_asset_discovery",
        "source_strategy_summary",
        "extraction_diagnostics_summary",
        "missing_reasons_contract",
        "field_capability_matrix",
        "llm_runtime",
    )
    return {
        "schema_version": context["schema_version"],
        "run_id": context["run_id"],
        "university_id": context["university_id"],
        "diagnostics": {key: config[key] for key in keys if key in config},
        "note": "Diagnostics describe crawler/extractor behavior and are not admissions facts.",
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write_programme_catalog_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STRUCTURED_PROGRAMME_CATALOG_CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            value = row["value"]
            source_ref = row["source_refs"][0] if row["source_refs"] else {}
            evidence_ref = row["evidence_refs"][0] if row["evidence_refs"] else {}
            writer.writerow(
                {
                    "schema_version": row["schema_version"],
                    "run_id": row["run_id"],
                    "university_id": row["university_id"],
                    "record_id": row["record_id"],
                    "name": value.get("name") or "",
                    "faculty_or_school": value.get("faculty_or_school") or "",
                    "degree_or_award": value.get("degree_or_award") or "",
                    "category": value.get("category") or "",
                    "mode": value.get("mode") or "",
                    "duration_or_units": value.get("duration_or_units") or "",
                    "admissions_choice_name": value.get("admissions_choice_name") or "",
                    "specialisations_or_majors": "; ".join(value.get("specialisations_or_majors") or []),
                    "status": row["status"],
                    "confidence": row["confidence"],
                    "parse_status": row["parse_status"],
                    "quality_flags": "; ".join(row["quality_flags"]),
                    "warnings_count": str(row["warnings_count"]),
                    "needs_review": "true" if row["needs_review"] else "false",
                    "source_id": source_ref.get("source_id", ""),
                    "source_url": source_ref.get("source_url", ""),
                    "evidence_id": evidence_ref.get("evidence_id", ""),
                    "evidence_path": evidence_ref.get("claim_path", row["raw"].get("evidence_path", "")),
                    "retrieved_at": row["retrieved_at"],
                }
            )


def _university_id(data: AdmissionsData) -> str:
    explicit = data.run.config.get("university_id")
    if isinstance(explicit, str) and explicit.strip():
        return _slug(explicit)
    parsed = urlparse(data.institution.homepage_url or data.run.input_url)
    host = parsed.netloc.lower().removeprefix("www.")
    return _slug(host) or "unknown-university"


def _institution_name(data: AdmissionsData) -> str:
    if data.institution.name.is_unknownish:
        return ""
    return str(data.institution.name.value)


def _run_id(data: AdmissionsData, university_id: str) -> str:
    timestamp = re.sub(r"[^0-9A-Za-z]+", "-", data.run.retrieved_at).strip("-")
    return f"{timestamp}__{university_id}"


def _source_id(source: SourceRecord) -> str:
    key = f"{source.source_url}\n{source.content_hash or ''}"
    return content_hash(key)[:16]


def _source_id_for_url(context: dict[str, Any], source_url: str) -> str:
    source_ids = context["source_ids"]
    if source_url in source_ids:
        return source_ids[source_url]
    return content_hash(source_url)[:16]


def _evidence_id(evidence: EvidenceItem) -> str:
    key = "\n".join((evidence.claim_path, evidence.source_url, evidence.snippet))
    return "evidence__" + content_hash(key)[:12]


def _evidence_key(evidence: EvidenceItem) -> tuple[str, str, str]:
    return evidence.claim_path, evidence.source_url, evidence.snippet


def _programme_record_id(data: AdmissionsData, context: dict[str, Any], row: ProgrammeCatalogRecord) -> str:
    key = "\n".join(
        (
            context["university_id"],
            row.name,
            row.source_url,
            row.degree_or_award or "",
            row.faculty_or_school or "",
            row.evidence_snippet,
        )
    )
    return "programme_catalog__" + content_hash(key)[:12]


def _quality_flags(row: ProgrammeCatalogRecord) -> list[str]:
    flags: list[str] = []
    for warning in row.warnings:
        message = warning.message.strip()
        prefix = message.split(":", 1)[0].strip().lower() if ":" in message else ""
        if prefix and re.fullmatch(r"[a-z0-9_]+", prefix):
            flags.append(prefix)
        else:
            flags.append(str(warning.code))
    if row.parse_status != "parsed":
        flags.append(f"parse_status_{_slug(row.parse_status)}")
    return sorted(set(flags))


def _normalized_source_host(source_url: str) -> str:
    return urlparse(source_url).netloc.lower().removeprefix("www.")


def _normalized_source_path(source_url: str) -> str:
    path = re.sub(r"/+", "/", urlparse(source_url).path or "/")
    return path.rstrip("/").lower() or "/"


def _normalized_text_key(value: str) -> str:
    tokens: list[str] = []
    current: list[str] = []
    for char in value.casefold():
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return "-".join(tokens)


def _source_by_url(data: AdmissionsData) -> dict[str, SourceRecord]:
    return {source.source_url: source for source in data.sources}


def _evidence_by_claim_path(data: AdmissionsData) -> dict[str, EvidenceItem]:
    return {evidence.claim_path: evidence for evidence in data.evidence}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
