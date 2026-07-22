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
    ("international_requirements", ("admissions", "international_requirements")),
    ("application_periods", ("admissions", "application_periods")),
    ("fees", ("fees",)),
    ("english_requirements", ("admissions", "english_requirements")),
    ("accepted_qualifications", ("admissions", "accepted_qualifications")),
    ("required_documents", ("admissions", "required_documents")),
    ("standardized_tests", ("admissions", "standardized_tests")),
    ("selection_tests_or_interviews", ("admissions", "selection_tests_or_interviews")),
    ("scholarships", ("scholarships",)),
    ("visa", ("visa",)),
    ("housing", ("housing",)),
    ("contacts", ("contacts",)),
)

STRUCTURED_RECORD_TYPES: tuple[str, ...] = (
    "programme_catalog",
    "international_requirements",
    "application_periods",
    "fees",
    "english_requirements",
    "accepted_qualifications",
    "required_documents",
    "standardized_tests",
    "selection_tests_or_interviews",
    "scholarships",
    "visa",
    "housing",
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
) + tuple(
    (
        f"all_{record_type}",
        f"all_{record_type}.jsonl",
        Path("structured") / "records" / f"{record_type}.jsonl",
    )
    for record_type, _path in STRUCTURED_REQUIREMENT_RECORD_SPECS
)

_BATCH_RECORD_TYPE_BY_KEY: dict[str, str] = {
    "all_programme_catalog": "programme_catalog",
    **{
        f"all_{record_type}": record_type
        for record_type, _path in STRUCTURED_REQUIREMENT_RECORD_SPECS
    },
}

_BATCH_RECORD_REQUIRED_FIELD_TYPES: dict[str, type] = {
    "run_id": str,
    "record_id": str,
    "value": dict,
    "source_refs": list,
    "evidence_refs": list,
}

_BATCH_REQUIRED_FIELD_TYPES: dict[str, dict[str, type]] = {
    "all_sources": {
        "run_id": str,
        "source_id": str,
        "source_url": str,
    },
    "all_missing_fields": {
        "run_id": str,
        "field_key": str,
        "status": str,
        "source_urls": list,
    },
    "all_programme_catalog": _BATCH_RECORD_REQUIRED_FIELD_TYPES,
    **{
        f"all_{record_type}": _BATCH_RECORD_REQUIRED_FIELD_TYPES
        for record_type, _path in STRUCTURED_REQUIREMENT_RECORD_SPECS
    },
}


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
        "international_requirements_jsonl": records_dir / "international_requirements.jsonl",
        "application_periods_jsonl": records_dir / "application_periods.jsonl",
        "fees_jsonl": records_dir / "fees.jsonl",
        "english_requirements_jsonl": records_dir / "english_requirements.jsonl",
        "accepted_qualifications_jsonl": records_dir / "accepted_qualifications.jsonl",
        "required_documents_jsonl": records_dir / "required_documents.jsonl",
        "standardized_tests_jsonl": records_dir / "standardized_tests.jsonl",
        "selection_tests_or_interviews_jsonl": records_dir / "selection_tests_or_interviews.jsonl",
        "scholarships_jsonl": records_dir / "scholarships.jsonl",
        "visa_jsonl": records_dir / "visa.jsonl",
        "housing_jsonl": records_dir / "housing.jsonl",
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

    university_dirs = [Path(university_dir) for university_dir in university_output_dirs]
    paths = {
        "manifest": out_dir / "manifest.json",
        **{key: out_dir / filename for key, filename, _ in STRUCTURED_BATCH_FILE_SPECS},
    }
    counts: dict[str, int] = {}
    input_coverage: dict[str, dict[str, Any]] = {}
    input_validation: dict[str, dict[str, Any]] = {}
    jsonl_cache: dict[Path, list[Any]] = {}
    reference_indexes, reference_index_coverage = _batch_reference_indexes(
        university_dirs,
        jsonl_cache,
    )
    duplicate_record_ids = _batch_duplicate_record_ids(university_dirs, jsonl_cache)
    evidence_validation = _batch_evidence_validation(
        university_dirs,
        jsonl_cache,
        reference_indexes,
    )
    for key, _, relative_path in STRUCTURED_BATCH_FILE_SPECS:
        rows: list[Any] = []
        missing_directory_names: list[str] = []
        nonempty_directory_names: list[str] = []
        empty_directory_names: list[str] = []
        invalid_directory_names: list[str] = []
        invalid_files: list[dict[str, Any]] = []
        valid_row_count = 0
        invalid_row_count = 0
        reason_counts: dict[str, int] = {}
        for university_dir in university_dirs:
            source_path = university_dir / relative_path
            if not source_path.exists():
                missing_directory_names.append(university_dir.name)
                continue
            source_rows = _read_jsonl_cached(source_path, jsonl_cache)
            file_valid_row_count = 0
            file_invalid_row_count = 0
            file_reason_counts: dict[str, int] = {}
            for row in source_rows:
                reasons = _batch_row_validation_reasons(
                    row,
                    table_key=key,
                    expected_university_id=university_dir.name,
                    expected_record_type=_BATCH_RECORD_TYPE_BY_KEY.get(key),
                    reference_index=reference_indexes[university_dir],
                    duplicate_record_ids=duplicate_record_ids[university_dir],
                )
                if reasons:
                    file_invalid_row_count += 1
                    invalid_row_count += 1
                    for reason in reasons:
                        file_reason_counts[reason] = file_reason_counts.get(reason, 0) + 1
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
                else:
                    file_valid_row_count += 1
                    valid_row_count += 1
            if file_invalid_row_count:
                invalid_directory_names.append(university_dir.name)
                invalid_files.append(
                    {
                        "input_directory_name": university_dir.name,
                        "source_file": relative_path.as_posix(),
                        "row_count": len(source_rows),
                        "valid_row_count": file_valid_row_count,
                        "invalid_row_count": file_invalid_row_count,
                        "reason_counts": dict(sorted(file_reason_counts.items())),
                    }
                )
            if source_rows:
                nonempty_directory_names.append(university_dir.name)
                rows.extend(source_rows)
            else:
                empty_directory_names.append(university_dir.name)
        _write_jsonl(paths[key], rows)
        counts[key] = len(rows)
        input_coverage[key] = {
            "expected_file_count": len(university_dirs),
            "present_file_count": len(nonempty_directory_names) + len(empty_directory_names),
            "missing_file_count": len(missing_directory_names),
            "nonempty_file_count": len(nonempty_directory_names),
            "empty_file_count": len(empty_directory_names),
            "missing_input_directory_names": missing_directory_names,
            "nonempty_input_directory_names": nonempty_directory_names,
            "empty_input_directory_names": empty_directory_names,
            "all_input_files_present": not missing_directory_names,
        }
        input_validation[key] = {
            "row_count": len(rows),
            "valid_row_count": valid_row_count,
            "invalid_row_count": invalid_row_count,
            "invalid_file_count": len(invalid_files),
            "invalid_input_directory_names": invalid_directory_names,
            "reason_counts": dict(sorted(reason_counts.items())),
            "invalid_files": invalid_files,
            "all_rows_valid": invalid_row_count == 0,
        }
    validation_summary = {
        "table_count": len(input_validation),
        "row_count": sum(item["row_count"] for item in input_validation.values()),
        "valid_row_count": sum(item["valid_row_count"] for item in input_validation.values()),
        "invalid_row_count": sum(item["invalid_row_count"] for item in input_validation.values()),
        "invalid_file_count": sum(item["invalid_file_count"] for item in input_validation.values()),
        "invalid_table_count": sum(not item["all_rows_valid"] for item in input_validation.values()),
        "all_rows_valid": all(item["all_rows_valid"] for item in input_validation.values()),
    }
    batch_validation = _batch_validation_verdict(
        university_output_count=len(university_dirs),
        input_coverage=input_coverage,
        input_validation_summary=validation_summary,
        reference_index_coverage=reference_index_coverage,
        evidence_validation=evidence_validation,
    )
    _write_json(
        paths["manifest"],
        {
            "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
            "output_type": "batch",
            "university_output_count": len(university_dirs),
            "input_directory_names": [university_dir.name for university_dir in university_dirs],
            "counts": counts,
            "input_coverage": input_coverage,
            "input_validation": input_validation,
            "input_validation_summary": validation_summary,
            "reference_index_coverage": reference_index_coverage,
            "evidence_validation": evidence_validation,
            "batch_validation": batch_validation,
            "files": {
                key: path.name
                for key, path in sorted(paths.items())
                if key != "manifest"
            },
            "notes": [
                "Batch tables concatenate per-university structured JSONL files.",
                "Rows are not refetched, deduplicated, inferred, or rewritten.",
            ],
        },
    )
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
    evidence_by_claim_path = _evidence_by_claim_path(data)
    field_evidence_by_row = _programme_catalog_field_evidence(data)
    for row in data.programme_catalog:
        source = _source_by_url(data).get(row.source_url)
        evidence = evidence_by_claim_path.get(row.evidence_path)
        evidence_refs = []
        if evidence is not None:
            evidence_refs.append(
                {
                    "evidence_id": context["evidence_ids"][_evidence_key(evidence)],
                    "claim_path": evidence.claim_path,
                }
            )
        field_evidence_paths = field_evidence_by_row.get(row.evidence_path, {})
        for field_name, field_claim_path in sorted(field_evidence_paths.items()):
            field_evidence = evidence_by_claim_path.get(field_claim_path)
            if field_evidence is None:
                continue
            evidence_refs.append(
                {
                    "evidence_id": context["evidence_ids"][_evidence_key(field_evidence)],
                    "claim_path": field_evidence.claim_path,
                    "field": field_name,
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
        raw = {
            "evidence_snippet": row.evidence_snippet,
            "evidence_path": row.evidence_path,
        }
        if field_evidence_paths:
            raw["field_evidence_paths"] = field_evidence_paths
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
                "raw": raw,
                "source_refs": source_refs,
                "evidence_refs": evidence_refs,
                "warnings_count": len(row.warnings),
                "warnings": [warning.to_dict() for warning in row.warnings],
                "retrieved_at": source.retrieved_at if source else data.run.retrieved_at,
            }
        )
    return rows


def _programme_catalog_field_evidence(data: AdmissionsData) -> dict[str, dict[str, str]]:
    raw = data.run.config.get("programme_catalog_field_evidence")
    if not isinstance(raw, dict):
        return {}
    return {
        row_path: {
            field_name: field_path
            for field_name, field_path in field_paths.items()
            if isinstance(field_name, str) and isinstance(field_path, str)
        }
        for row_path, field_paths in raw.items()
        if isinstance(row_path, str) and isinstance(field_paths, dict)
    }


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
        "programme_catalog_candidate_diagnostics",
        "programme_catalog_field_evidence",
        "programme_catalog_api_discovery_summary",
        "programme_catalog_api_capture",
        "programme_catalog_browser_capture",
        "programme_catalog_static_asset_discovery",
        "programme_catalog_targeted_detail_selection",
        "programme_frontier_summary",
        "source_strategy_summary",
        "extraction_diagnostics_summary",
        "missing_reasons_contract",
        "field_capability_matrix",
        "llm_runtime",
        "diff",
    )
    payload = {
        "schema_version": context["schema_version"],
        "run_id": context["run_id"],
        "university_id": context["university_id"],
        "diagnostics": {key: config[key] for key in keys if key in config},
        "note": "Diagnostics describe crawler/extractor behavior and are not admissions facts.",
    }
    completeness = _programme_catalog_completeness(config.get("programme_catalog_summary"))
    if completeness is not None:
        payload["programme_catalog_completeness"] = completeness
    return payload


def _programme_catalog_completeness(summary: object) -> dict[str, Any] | None:
    if not isinstance(summary, dict) or not isinstance(summary.get("catalog_completeness_status"), str):
        return None
    return {
        "status": summary["catalog_completeness_status"],
        "catalog_complete": bool(summary.get("catalog_complete")),
        "probable_incomplete": bool(summary.get("probable_incomplete_catalog")),
        "canonical_catalog": {
            "captured": bool(summary.get("canonical_catalog_captured")),
            "accepted": bool(summary.get("canonical_catalog_accepted")),
        },
        "candidate_conservation": {
            "expected_count": summary.get("candidate_conservation_expected_count", 0),
            "observed_count": summary.get("candidate_conservation_observed_count", 0),
            "unknown_decision_count": summary.get("candidate_unknown_decision_count", 0),
            "proven": bool(summary.get("candidate_conservation_proven")),
        },
        "section_conservation": {
            "identified_count": summary.get("identified_catalog_section_count", 0),
            "processed_count": summary.get("processed_catalog_section_count", 0),
            "proven": bool(summary.get("catalog_section_conservation_proven")),
        },
        "row_yield": {
            "candidate_source_count": summary.get("candidate_source_count", 0),
            "accepted_row_count": summary.get("accepted_row_count", summary.get("accepted_count", 0)),
            "accepted_to_candidate_source_ratio": summary.get("accepted_to_candidate_source_ratio"),
            "quality_adjustment_applied": bool(summary.get("quality_adjustment_applied")),
            "quality_adjusted_accepted_row_count": summary.get("quality_adjusted_accepted_row_count", 0),
            "quality_excluded_accepted_row_count": summary.get("quality_excluded_accepted_row_count", 0),
            "quality_exclusion_reason_counts": summary.get("quality_exclusion_reason_counts", {}),
            "quality_adjusted_accepted_to_candidate_source_ratio": summary.get(
                "quality_adjusted_accepted_to_candidate_source_ratio"
            ),
            "raw_low_row_yield": bool(summary.get("raw_low_row_yield")),
            "low_row_yield": bool(summary.get("low_row_yield")),
        },
        "quarantined_candidate_count": summary.get("quarantined_candidate_count", 0),
        "source_role_counts": summary.get("source_role_counts", {}),
        "accepted_by_source_role": summary.get("accepted_by_source_role", {}),
        "basis": summary.get("catalog_completeness_basis", []),
        "failure_reasons": summary.get("catalog_completeness_failure_reasons", []),
        "failure_stages": summary.get("catalog_completeness_failure_stages", []),
        "failure_stage_counts": summary.get("catalog_completeness_failure_stage_counts", {}),
        "recommended_next_action": summary.get("recommended_next_action", "none"),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def _read_jsonl(path: Path) -> list[Any]:
    if not path.exists():
        return []
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_jsonl_cached(path: Path, cache: dict[Path, list[Any]]) -> list[Any]:
    if path not in cache:
        cache[path] = _read_jsonl(path)
    return cache[path]


def _batch_validation_verdict(
    *,
    university_output_count: int,
    input_coverage: dict[str, dict[str, Any]],
    input_validation_summary: dict[str, Any],
    reference_index_coverage: dict[str, dict[str, Any]],
    evidence_validation: dict[str, Any],
) -> dict[str, Any]:
    metrics = {
        "university_output_count": university_output_count,
        "missing_input_file_count": sum(
            item["missing_file_count"] for item in input_coverage.values()
        ),
        "invalid_input_file_count": input_validation_summary["invalid_file_count"],
        "invalid_input_row_count": input_validation_summary["invalid_row_count"],
        "missing_reference_index_file_count": sum(
            item["missing_file_count"] for item in reference_index_coverage.values()
        ),
        "unreadable_reference_index_file_count": sum(
            item["unreadable_file_count"] for item in reference_index_coverage.values()
        ),
        "invalid_reference_identifier_row_count": sum(
            item["invalid_identifier_row_count"] for item in reference_index_coverage.values()
        ),
        "duplicate_reference_identifier_count": sum(
            item["duplicate_identifier_count"] for item in reference_index_coverage.values()
        ),
        "duplicate_reference_identifier_row_count": sum(
            item["duplicate_identifier_row_count"] for item in reference_index_coverage.values()
        ),
        "invalid_evidence_file_count": evidence_validation["invalid_file_count"],
        "invalid_evidence_row_count": evidence_validation["invalid_row_count"],
    }
    reason_metrics = {
        "missing_input_files": "missing_input_file_count",
        "invalid_input_rows": "invalid_input_row_count",
        "missing_reference_index_files": "missing_reference_index_file_count",
        "unreadable_reference_index_files": "unreadable_reference_index_file_count",
        "invalid_reference_identifier_rows": "invalid_reference_identifier_row_count",
        "duplicate_reference_identifiers": "duplicate_reference_identifier_count",
        "invalid_evidence_rows": "invalid_evidence_row_count",
    }
    reason_codes = [
        reason_code
        for reason_code, metric_name in reason_metrics.items()
        if metrics[metric_name] > 0
    ]
    if university_output_count == 0:
        reason_codes.append("no_university_inputs")
    reason_codes.sort()

    invalid_reason_codes = {
        "duplicate_reference_identifiers",
        "invalid_evidence_rows",
        "invalid_input_rows",
        "invalid_reference_identifier_rows",
        "unreadable_reference_index_files",
    }
    if invalid_reason_codes.intersection(reason_codes):
        status = "invalid"
    elif reason_codes:
        status = "incomplete"
    else:
        status = "valid"
    return {
        "status": status,
        "ready_for_structured_consumption": status == "valid",
        "reason_codes": reason_codes,
        "metrics": metrics,
        "note": (
            "This verdict covers structured artifact integrity, not crawl or "
            "admissions-data completeness."
        ),
    }


def _batch_reference_indexes(
    university_dirs: list[Path],
    jsonl_cache: dict[Path, list[Any]],
) -> tuple[dict[Path, dict[str, dict[str, Any]]], dict[str, dict[str, Any]]]:
    indexes = {
        university_dir: {
            "sources": {"available": False, "ids": set(), "ambiguous_ids": set()},
            "evidence": {"available": False, "ids": set(), "ambiguous_ids": set()},
        }
        for university_dir in university_dirs
    }
    coverage: dict[str, dict[str, Any]] = {}
    index_specs = (
        ("sources", Path("structured") / "sources.jsonl", "source_id"),
        ("evidence", Path("structured") / "evidence.jsonl", "evidence_id"),
    )
    for index_name, relative_path, identifier_field in index_specs:
        missing_directory_names: list[str] = []
        unreadable_directory_names: list[str] = []
        invalid_identifier_directory_names: list[str] = []
        duplicate_identifier_directory_names: list[str] = []
        present_file_count = 0
        readable_file_count = 0
        usable_identifier_count = 0
        invalid_identifier_row_count = 0
        duplicate_identifier_count = 0
        duplicate_identifier_row_count = 0
        for university_dir in university_dirs:
            index_path = university_dir / relative_path
            if not index_path.exists():
                missing_directory_names.append(university_dir.name)
                continue
            present_file_count += 1
            try:
                rows = _read_jsonl_cached(index_path, jsonl_cache)
            except json.JSONDecodeError:
                unreadable_directory_names.append(university_dir.name)
                continue
            readable_file_count += 1
            identifier_counts: dict[str, int] = {}
            file_invalid_identifier_row_count = 0
            for row in rows:
                identifier = row.get(identifier_field) if isinstance(row, dict) else None
                usable = (
                    isinstance(row, dict)
                    and row.get("schema_version") == STRUCTURED_OUTPUT_SCHEMA_VERSION
                    and row.get("university_id") == university_dir.name
                    and isinstance(identifier, str)
                    and bool(identifier.strip())
                )
                if usable:
                    identifier_counts[identifier] = identifier_counts.get(identifier, 0) + 1
                else:
                    file_invalid_identifier_row_count += 1
            ambiguous_identifiers = {
                identifier
                for identifier, count in identifier_counts.items()
                if count > 1
            }
            identifiers = set(identifier_counts) - ambiguous_identifiers
            indexes[university_dir][index_name] = {
                "available": True,
                "ids": identifiers,
                "ambiguous_ids": ambiguous_identifiers,
            }
            usable_identifier_count += len(identifiers)
            invalid_identifier_row_count += file_invalid_identifier_row_count
            duplicate_identifier_count += len(ambiguous_identifiers)
            duplicate_identifier_row_count += sum(
                identifier_counts[identifier]
                for identifier in ambiguous_identifiers
            )
            if file_invalid_identifier_row_count:
                invalid_identifier_directory_names.append(university_dir.name)
            if ambiguous_identifiers:
                duplicate_identifier_directory_names.append(university_dir.name)
        coverage[index_name] = {
            "expected_file_count": len(university_dirs),
            "present_file_count": present_file_count,
            "readable_file_count": readable_file_count,
            "missing_file_count": len(missing_directory_names),
            "unreadable_file_count": len(unreadable_directory_names),
            "missing_input_directory_names": missing_directory_names,
            "unreadable_input_directory_names": unreadable_directory_names,
            "invalid_identifier_input_directory_names": invalid_identifier_directory_names,
            "duplicate_identifier_input_directory_names": duplicate_identifier_directory_names,
            "usable_identifier_count": usable_identifier_count,
            "invalid_identifier_row_count": invalid_identifier_row_count,
            "duplicate_identifier_count": duplicate_identifier_count,
            "duplicate_identifier_row_count": duplicate_identifier_row_count,
            "all_index_files_readable": readable_file_count == len(university_dirs),
        }
    return indexes, coverage


def _batch_duplicate_record_ids(
    university_dirs: list[Path],
    jsonl_cache: dict[Path, list[Any]],
) -> dict[Path, set[str]]:
    duplicate_ids_by_directory: dict[Path, set[str]] = {}
    record_specs = [
        (key, relative_path)
        for key, _filename, relative_path in STRUCTURED_BATCH_FILE_SPECS
        if key in _BATCH_RECORD_TYPE_BY_KEY
    ]
    for university_dir in university_dirs:
        identifier_counts: dict[str, int] = {}
        for key, relative_path in record_specs:
            source_path = university_dir / relative_path
            if not source_path.exists():
                continue
            for row in _read_jsonl_cached(source_path, jsonl_cache):
                identifier = row.get("record_id") if isinstance(row, dict) else None
                usable = (
                    isinstance(row, dict)
                    and row.get("schema_version") == STRUCTURED_OUTPUT_SCHEMA_VERSION
                    and row.get("university_id") == university_dir.name
                    and row.get("record_type") == _BATCH_RECORD_TYPE_BY_KEY[key]
                    and isinstance(identifier, str)
                    and bool(identifier.strip())
                )
                if usable:
                    identifier_counts[identifier] = identifier_counts.get(identifier, 0) + 1
        duplicate_ids_by_directory[university_dir] = {
            identifier
            for identifier, count in identifier_counts.items()
            if count > 1
        }
    return duplicate_ids_by_directory


def _batch_evidence_validation(
    university_dirs: list[Path],
    jsonl_cache: dict[Path, list[Any]],
    reference_indexes: dict[Path, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    row_count = 0
    valid_row_count = 0
    invalid_row_count = 0
    invalid_directory_names: list[str] = []
    reason_counts: dict[str, int] = {}
    for university_dir in university_dirs:
        evidence_index = reference_indexes[university_dir]["evidence"]
        if not evidence_index["available"]:
            continue
        evidence_path = university_dir / "structured" / "evidence.jsonl"
        rows = _read_jsonl_cached(evidence_path, jsonl_cache)
        row_count += len(rows)
        file_invalid_row_count = 0
        for row in rows:
            reasons = _batch_evidence_row_validation_reasons(
                row,
                expected_university_id=university_dir.name,
                evidence_index=evidence_index,
                source_index=reference_indexes[university_dir]["sources"],
            )
            if reasons:
                file_invalid_row_count += 1
                invalid_row_count += 1
                for reason in reasons:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
            else:
                valid_row_count += 1
        if file_invalid_row_count:
            invalid_directory_names.append(university_dir.name)
    return {
        "row_count": row_count,
        "valid_row_count": valid_row_count,
        "invalid_row_count": invalid_row_count,
        "invalid_file_count": len(invalid_directory_names),
        "invalid_input_directory_names": invalid_directory_names,
        "reason_counts": dict(sorted(reason_counts.items())),
        "all_rows_valid": invalid_row_count == 0,
    }


def _batch_evidence_row_validation_reasons(
    row: Any,
    *,
    expected_university_id: str,
    evidence_index: dict[str, Any],
    source_index: dict[str, Any],
) -> list[str]:
    if not isinstance(row, dict):
        return ["row_not_object"]

    reasons: list[str] = []
    schema_version = row.get("schema_version")
    if schema_version is None or (isinstance(schema_version, str) and not schema_version.strip()):
        reasons.append("missing_schema_version")
    elif not isinstance(schema_version, str):
        reasons.append("invalid_schema_version")
    elif schema_version != STRUCTURED_OUTPUT_SCHEMA_VERSION:
        reasons.append("schema_version_mismatch")

    university_id = row.get("university_id")
    if university_id is None or (isinstance(university_id, str) and not university_id.strip()):
        reasons.append("missing_university_id")
    elif not isinstance(university_id, str):
        reasons.append("invalid_university_id")
    elif university_id != expected_university_id:
        reasons.append("university_id_mismatch")

    for field_name in ("run_id", "evidence_id"):
        value = row.get(field_name)
        if field_name not in row or value is None:
            reasons.append(f"missing_required_field:{field_name}")
        elif not isinstance(value, str):
            reasons.append(f"invalid_required_field_type:{field_name}")
        elif not value.strip():
            reasons.append(f"empty_required_string:{field_name}")
    if reasons:
        return reasons

    evidence_id = row["evidence_id"]
    if evidence_id in evidence_index["ambiguous_ids"]:
        reasons.append("duplicate_evidence_id")

    source_id = row.get("source_id")
    if source_id is None or (isinstance(source_id, str) and not source_id.strip()):
        reasons.append("missing_source_ref_id")
    elif not isinstance(source_id, str):
        reasons.append("invalid_source_ref_id")
    elif not source_index["available"]:
        reasons.append("source_reference_index_unavailable")
    elif source_id in source_index["ambiguous_ids"]:
        reasons.append("ambiguous_source_ref")
    elif source_id not in source_index["ids"]:
        reasons.append("unresolved_source_ref")
    return reasons


def _batch_row_validation_reasons(
    row: Any,
    *,
    table_key: str,
    expected_university_id: str,
    expected_record_type: str | None,
    reference_index: dict[str, dict[str, Any]],
    duplicate_record_ids: set[str],
) -> list[str]:
    if not isinstance(row, dict):
        return ["row_not_object"]

    reasons: list[str] = []
    schema_version = row.get("schema_version")
    if schema_version is None or (isinstance(schema_version, str) and not schema_version.strip()):
        reasons.append("missing_schema_version")
    elif not isinstance(schema_version, str):
        reasons.append("invalid_schema_version")
    elif schema_version != STRUCTURED_OUTPUT_SCHEMA_VERSION:
        reasons.append("schema_version_mismatch")

    university_id = row.get("university_id")
    if university_id is None or (isinstance(university_id, str) and not university_id.strip()):
        reasons.append("missing_university_id")
    elif not isinstance(university_id, str):
        reasons.append("invalid_university_id")
    elif university_id != expected_university_id:
        reasons.append("university_id_mismatch")

    if expected_record_type is not None:
        record_type = row.get("record_type")
        if record_type is None or (isinstance(record_type, str) and not record_type.strip()):
            reasons.append("missing_record_type")
        elif not isinstance(record_type, str):
            reasons.append("invalid_record_type")
        elif record_type != expected_record_type:
            reasons.append("record_type_mismatch")
    if reasons:
        return reasons

    for field_name, expected_type in _BATCH_REQUIRED_FIELD_TYPES[table_key].items():
        if field_name not in row or row[field_name] is None:
            reasons.append(f"missing_required_field:{field_name}")
            continue
        value = row[field_name]
        if not isinstance(value, expected_type):
            reasons.append(f"invalid_required_field_type:{field_name}")
        elif expected_type is str and not value.strip():
            reasons.append(f"empty_required_string:{field_name}")

    if table_key == "all_sources":
        source_id = row.get("source_id")
        if isinstance(source_id, str) and source_id in reference_index["sources"]["ambiguous_ids"]:
            reasons.append("duplicate_source_id")

    if table_key in _BATCH_RECORD_TYPE_BY_KEY:
        record_id = row.get("record_id")
        if isinstance(record_id, str) and record_id in duplicate_record_ids:
            reasons.append("duplicate_record_id")
        reasons.extend(
            _batch_reference_validation_reasons(
                row.get("source_refs"),
                reference_name="source",
                identifier_field="source_id",
                index=reference_index["sources"],
            )
        )
        reasons.extend(
            _batch_reference_validation_reasons(
                row.get("evidence_refs"),
                reference_name="evidence",
                identifier_field="evidence_id",
                index=reference_index["evidence"],
            )
        )
    return reasons


def _batch_reference_validation_reasons(
    refs: Any,
    *,
    reference_name: str,
    identifier_field: str,
    index: dict[str, Any],
) -> list[str]:
    if not isinstance(refs, list):
        return []
    reasons: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            reasons.append(f"invalid_{reference_name}_ref")
            continue
        identifier = ref.get(identifier_field)
        if identifier is None or (isinstance(identifier, str) and not identifier.strip()):
            reasons.append(f"missing_{reference_name}_ref_id")
            continue
        if not isinstance(identifier, str):
            reasons.append(f"invalid_{reference_name}_ref_id")
            continue
        if not index["available"]:
            reasons.append(f"{reference_name}_reference_index_unavailable")
        elif identifier in index["ambiguous_ids"]:
            reasons.append(f"ambiguous_{reference_name}_ref")
        elif identifier not in index["ids"]:
            reasons.append(f"unresolved_{reference_name}_ref")
    return reasons


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
