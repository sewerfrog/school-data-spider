"""Normalization and warning policy for extracted admissions data."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    Confidence,
    WarningCode,
    WarningRecord,
    collect_nested_field_warnings,
    validate_evidence_links,
)


def normalize_admissions_data(data: AdmissionsData) -> AdmissionsData:
    """Attach deterministic validation, conflict, stale, and manual-check policy.

    Extractors should emit candidate claims plus evidence.  This function owns
    the cross-cutting policy for whether a run remains high/medium confidence
    or is downgraded by missing/conflicting/stale/manual-check conditions.
    """

    _dedupe_warnings_in_place(data)
    for warning in (
        collect_nested_field_warnings(data)
        + validate_evidence_links(data)
        + detect_conflicts(data)
        + detect_stale_sources(data)
        + detect_non_official_sources(data)
        + detect_ambiguous_applicant_groups(data)
    ):
        add_warning(data, warning)
    if any(w.code in {WarningCode.MISSING_EVIDENCE, WarningCode.CONFLICT} for w in data.warnings):
        data.confidence = Confidence.LOW
    elif data.evidence:
        data.confidence = Confidence.MEDIUM
    return data


def add_warning(data: AdmissionsData, warning: WarningRecord) -> None:
    key = (warning.code, warning.field, warning.message, tuple(warning.source_urls))
    existing = {(w.code, w.field, w.message, tuple(w.source_urls)) for w in data.warnings}
    if key not in existing:
        data.warnings.append(warning)


def detect_conflicts(data: AdmissionsData) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    value_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    values_by_label: dict[str, set[str]] = defaultdict(set)
    sources_by_label: dict[str, set[str]] = defaultdict(set)

    groups: Iterable = (
        list(data.admissions.application_periods)
        + list(data.admissions.english_requirements)
        + list(data.admissions.accepted_qualifications)
        + list(data.admissions.required_documents)
        + list(data.fees)
        + list(data.scholarships)
        + list(data.visa)
        + list(data.housing)
        + list(data.contacts)
    )
    evidence_by_path = {item.claim_path: item for item in data.evidence}
    for record in groups:
        if record.value.is_unknownish:
            continue
        label = record.label.lower()
        value = str(record.value.value).strip().lower()
        values_by_label[label].add(value)
        for path in record.value.evidence:
            item = evidence_by_path.get(path)
            if item:
                value_sources[(label, value)].add(item.source_url)
                sources_by_label[label].add(item.source_url)

    for label, values in values_by_label.items():
        if len(values) > 1:
            warnings.append(
                WarningRecord(
                    WarningCode.CONFLICT,
                    f"Conflicting official values found for {label}; preserve all sources for manual review.",
                    field=f"/conflicts/{label.replace(' ', '_')}",
                    source_urls=sorted(sources_by_label[label]),
                )
            )
    return warnings


def detect_stale_sources(data: AdmissionsData, current_year: int | None = None) -> list[WarningRecord]:
    current_year = current_year or datetime.now().year
    warnings: list[WarningRecord] = []
    for source in data.sources:
        if not source.academic_year:
            continue
        years = [int(part) for part in source.academic_year.replace("/", "-").split("-") if part.isdigit() and len(part) == 4]
        if years and max(years) < current_year:
            warnings.append(
                WarningRecord(
                    WarningCode.STALE_PAGE,
                    f"Source academic year {source.academic_year} appears older than {current_year}.",
                    field=source.source_url,
                    source_urls=[source.source_url],
                )
            )
    return warnings


def detect_non_official_sources(data: AdmissionsData) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    source_by_url = {source.source_url: source for source in data.sources}
    for item in data.evidence:
        source = source_by_url.get(item.source_url)
        if source is not None and not source.is_official:
            warnings.append(
                WarningRecord(
                    WarningCode.NON_OFFICIAL_SOURCE,
                    "Claim is supported by a source marked non-official; verify before relying on it.",
                    field=item.claim_path,
                    source_urls=[item.source_url],
                )
            )
    return warnings


def detect_ambiguous_applicant_groups(data: AdmissionsData) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for path, record in _iter_requirement_records(data):
        if record.requires_applicant_group and record.applicant_group.is_unknownish:
            warnings.append(
                WarningRecord(
                    WarningCode.AMBIGUOUS_APPLICANT_GROUP,
                    "Requirement needs applicant-group context but none was confidently extracted.",
                    field=f"{path}/applicant_group",
                )
            )
    return warnings


def _iter_requirement_records(data: AdmissionsData):
    groups = {
        "/admissions/international_requirements": data.admissions.international_requirements,
        "/admissions/accepted_qualifications": data.admissions.accepted_qualifications,
        "/admissions/application_periods": data.admissions.application_periods,
        "/admissions/required_documents": data.admissions.required_documents,
        "/admissions/english_requirements": data.admissions.english_requirements,
        "/admissions/standardized_tests": data.admissions.standardized_tests,
        "/admissions/selection_tests_or_interviews": data.admissions.selection_tests_or_interviews,
        "/fees": data.fees,
        "/scholarships": data.scholarships,
        "/visa": data.visa,
        "/housing": data.housing,
        "/contacts": data.contacts,
    }
    for base, records in groups.items():
        for index, record in enumerate(records):
            yield f"{base}/{index}", record
    for programme_index, programme in enumerate(data.programmes):
        for prereq_index, record in enumerate(programme.prerequisites):
            yield f"/programmes/{programme_index}/prerequisites/{prereq_index}", record


def _dedupe_warnings_in_place(data: AdmissionsData) -> None:
    deduped: list[WarningRecord] = []
    seen: set[tuple] = set()
    for warning in data.warnings:
        key = (warning.code, warning.field, warning.message, tuple(warning.source_urls))
        if key not in seen:
            deduped.append(warning)
            seen.add(key)
    data.warnings = deduped
