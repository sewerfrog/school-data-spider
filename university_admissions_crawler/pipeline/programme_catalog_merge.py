"""Source-aware identity and merge rules for programme catalog rows."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
import unicodedata
from urllib.parse import unquote, urlparse

from university_admissions_crawler.crawler.programme_sources import PROGRAMME_SOURCE_ROLE_PRIORITY
from university_admissions_crawler.crawler.public_suffix import registrable_domain
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    EvidenceItem,
    ProgrammeCatalogRecord,
    WarningCode,
    WarningRecord,
)


_SCALAR_ENRICHMENT_FIELDS = (
    "degree_or_award",
    "faculty_or_school",
    "mode",
    "duration_or_units",
    "admissions_choice_name",
)

_DEGREE_FAMILY_PREFIXES = (
    "bachelor of communication studies",
    "bachelor of applied computing",
    "bachelor of engineering science",
    "bachelor of social sciences",
    "bachelor of accountancy",
    "bachelor of engineering",
    "bachelor of fine arts",
    "bachelor of computing",
    "bachelor of business",
    "bachelor of science",
    "bachelor of arts",
)


@dataclass(frozen=True, slots=True)
class ProgrammeCatalogMergeOutcome:
    appended_count: int = 0
    merged_count: int = 0
    replaced_count: int = 0
    quarantined_count: int = 0
    evidence_count: int = 0


def merge_programme_catalog_records(
    data: AdmissionsData,
    records: list[tuple[ProgrammeCatalogRecord, list[EvidenceItem]]],
    *,
    source_role: str,
    candidate_diagnostics: list[dict[str, object]],
) -> ProgrammeCatalogMergeOutcome:
    """Append unique rows and merge compatible duplicates by source priority."""

    appended_count = 0
    merged_count = 0
    replaced_count = 0
    quarantined_count = 0
    evidence_count = 0
    for candidate, candidate_evidence in records:
        candidate_diagnostic = _candidate_diagnostic(candidate, candidate_diagnostics)
        matches = compatible_programme_indexes(data, candidate)
        match_method: str | None = None
        if not matches:
            matches = compatible_programme_display_variant_indexes(
                data,
                candidate,
                candidate_source_role=source_role,
            )
            if matches:
                match_method = "cross_source_display_variant"
        if not matches:
            evidence_count += _append_unique_candidate(
                data,
                candidate,
                candidate_evidence,
                source_role=source_role,
                candidate_diagnostic=candidate_diagnostic,
            )
            appended_count += 1
            continue
        if len(matches) > 1:
            _quarantine_ambiguous_candidate(
                data,
                candidate,
                source_role=source_role,
                candidate_diagnostic=candidate_diagnostic,
                match_count=len(matches),
                match_method=match_method,
            )
            quarantined_count += 1
            continue

        matched_index = matches[0]
        existing = data.programme_catalog[matched_index]
        existing_role = _row_source_role(data, existing)
        if _source_role_priority(source_role) < _source_role_priority(existing_role):
            added_evidence = _replace_with_preferred_candidate(
                data,
                matched_index,
                candidate,
                candidate_evidence,
                source_role=source_role,
                existing_role=existing_role,
                candidate_diagnostic=candidate_diagnostic,
                match_method=match_method,
            )
            replaced_count += 1
        else:
            added_evidence = _merge_candidate_into_existing(
                data,
                matched_index,
                candidate,
                candidate_evidence,
                source_role=source_role,
                existing_role=existing_role,
                candidate_diagnostic=candidate_diagnostic,
                match_method=match_method,
            )
            merged_count += 1
        evidence_count += added_evidence

    return ProgrammeCatalogMergeOutcome(
        appended_count=appended_count,
        merged_count=merged_count,
        replaced_count=replaced_count,
        quarantined_count=quarantined_count,
        evidence_count=evidence_count,
    )


def compatible_programme_indexes(
    data: AdmissionsData,
    candidate: ProgrammeCatalogRecord,
    *,
    eligible_source_urls: set[str] | None = None,
) -> list[int]:
    institution_key = _institution_key(data)
    return [
        index
        for index, existing in enumerate(data.programme_catalog)
        if (eligible_source_urls is None or existing.source_url in eligible_source_urls)
        and _records_are_compatible(existing, candidate)
        and _row_institution_key(data, existing) == institution_key
    ]


def compatible_programme_display_variant_indexes(
    data: AdmissionsData,
    candidate: ProgrammeCatalogRecord,
    *,
    candidate_source_role: str,
) -> list[int]:
    """Match conservative canonical/faculty display variants missed by strict identity."""

    if candidate_source_role not in {"canonical_catalog", "faculty_catalog"}:
        return []
    if not _source_is_official_html(data, candidate.source_url):
        return []
    candidate_identity = _detail_programme_identity(candidate.name)
    candidate_degree_family = _programme_degree_family(candidate)
    if not candidate_identity or not candidate_degree_family:
        return []
    institution_key = _institution_key(data)
    return [
        index
        for index, existing in enumerate(data.programme_catalog)
        if {candidate_source_role, _row_source_role(data, existing)}
        == {"canonical_catalog", "faculty_catalog"}
        and _source_is_official_html(data, existing.source_url)
        and _row_institution_key(data, existing) == institution_key
        and _normalise_identity(existing.category) == _normalise_identity(candidate.category)
        and _programme_degree_family(existing) == candidate_degree_family
        and _detail_programme_identity(existing.name) == candidate_identity
    ]


def _append_unique_candidate(
    data: AdmissionsData,
    candidate: ProgrammeCatalogRecord,
    candidate_evidence: list[EvidenceItem],
    *,
    source_role: str,
    candidate_diagnostic: dict[str, object] | None,
) -> int:
    row_index = len(data.programme_catalog)
    _rebase_candidate(candidate, candidate_evidence, candidate_diagnostic, row_index)
    data.programme_catalog.append(candidate)
    data.evidence.extend(candidate_evidence)
    _store_candidate_field_evidence(data, candidate_diagnostic)
    _set_row_provenance(data, candidate, source_role, candidate_diagnostic)
    _append_merge_diagnostic(
        data,
        candidate=candidate,
        source_role=source_role,
        decision="appended",
        reason="unique_identity",
        matched_claim_path=candidate.evidence_path,
    )
    return len(candidate_evidence)


def _quarantine_ambiguous_candidate(
    data: AdmissionsData,
    candidate: ProgrammeCatalogRecord,
    *,
    source_role: str,
    candidate_diagnostic: dict[str, object] | None,
    match_count: int,
    match_method: str | None = None,
) -> None:
    if candidate_diagnostic is not None:
        candidate_diagnostic["parser_decision"] = candidate_diagnostic.get("decision")
        candidate_diagnostic["decision"] = "quarantined"
        candidate_diagnostic["reason"] = "ambiguous_programme_identity"
        candidate_diagnostic["parser_stage"] = "source_role_merge"
        candidate_diagnostic["compatible_match_count"] = match_count
        if match_method:
            candidate_diagnostic["match_method"] = match_method
    _append_merge_diagnostic(
        data,
        candidate=candidate,
        source_role=source_role,
        decision="quarantined",
        reason="ambiguous_programme_identity",
        matched_claim_path=candidate.evidence_path,
        ambiguous_match_count=match_count,
        match_method=match_method,
    )


def _replace_with_preferred_candidate(
    data: AdmissionsData,
    matched_index: int,
    candidate: ProgrammeCatalogRecord,
    candidate_evidence: list[EvidenceItem],
    *,
    source_role: str,
    existing_role: str,
    candidate_diagnostic: dict[str, object] | None,
    match_method: str | None,
) -> int:
    existing = data.programme_catalog[matched_index]
    existing_snapshot = _field_evidence_snapshot(data, existing)
    existing_diagnostic = _accepted_diagnostic(data, existing)
    old_source_url = existing.source_url
    old_root = _row_root(existing.evidence_path)
    existing_primary_source_urls = _row_primary_source_urls(data, existing)

    _remove_row_evidence_and_mappings(data, old_root)
    _rebase_candidate(candidate, candidate_evidence, candidate_diagnostic, matched_index)
    data.programme_catalog[matched_index] = candidate
    data.evidence.extend(candidate_evidence)
    _store_candidate_field_evidence(data, candidate_diagnostic)

    enriched_fields, conflicting_fields, enrichment_evidence_count = _enrich_preferred_row(
        data,
        matched_index,
        preferred=candidate,
        supplement=existing,
        supplement_evidence=existing_snapshot,
    )
    _set_row_provenance(data, candidate, source_role, candidate_diagnostic)
    _merge_row_primary_source_urls(data, candidate, existing_primary_source_urls)
    _rewrite_merged_candidate(
        existing_diagnostic,
        reason="replaced_by_higher_priority_source",
        matched_claim_path=candidate.evidence_path,
        preferred_source_role=source_role,
        enriched_fields=(),
        conflicting_fields=conflicting_fields,
        match_method=match_method,
    )
    _append_merge_diagnostic(
        data,
        candidate=candidate,
        source_role=source_role,
        decision="replaced",
        reason="higher_priority_source_replaced_row",
        matched_claim_path=candidate.evidence_path,
        previous_source_url=old_source_url,
        previous_source_role=existing_role,
        enriched_fields=enriched_fields,
        conflicting_fields=conflicting_fields,
        match_method=match_method,
    )
    return len(candidate_evidence) + enrichment_evidence_count


def _merge_candidate_into_existing(
    data: AdmissionsData,
    matched_index: int,
    candidate: ProgrammeCatalogRecord,
    candidate_evidence: list[EvidenceItem],
    *,
    source_role: str,
    existing_role: str,
    candidate_diagnostic: dict[str, object] | None,
    match_method: str | None,
) -> int:
    existing = data.programme_catalog[matched_index]
    candidate_snapshot = _candidate_field_evidence(candidate, candidate_evidence, candidate_diagnostic)
    enriched_fields, conflicting_fields, evidence_count = _enrich_preferred_row(
        data,
        matched_index,
        preferred=existing,
        supplement=candidate,
        supplement_evidence=candidate_snapshot,
    )
    reason = "lower_priority_source_enriched_row" if enriched_fields else "duplicate_identity_ignored"
    _merge_row_primary_source_urls(
        data,
        existing,
        _diagnostic_primary_source_urls(candidate_diagnostic),
    )
    _rewrite_merged_candidate(
        candidate_diagnostic,
        reason=reason,
        matched_claim_path=existing.evidence_path,
        preferred_source_role=existing_role,
        enriched_fields=enriched_fields,
        conflicting_fields=conflicting_fields,
        match_method=match_method,
    )
    _append_merge_diagnostic(
        data,
        candidate=candidate,
        source_role=source_role,
        decision="merged",
        reason=reason,
        matched_claim_path=existing.evidence_path,
        previous_source_url=existing.source_url,
        previous_source_role=existing_role,
        enriched_fields=enriched_fields,
        conflicting_fields=conflicting_fields,
        match_method=match_method,
    )
    return evidence_count


def _enrich_preferred_row(
    data: AdmissionsData,
    row_index: int,
    *,
    preferred: ProgrammeCatalogRecord,
    supplement: ProgrammeCatalogRecord,
    supplement_evidence: dict[str, EvidenceItem],
) -> tuple[list[str], list[str], int]:
    enriched_fields: list[str] = []
    conflicting_fields: list[str] = []
    evidence_count = 0
    preferred_evidence = _field_evidence_snapshot(data, preferred)
    for field_name in _SCALAR_ENRICHMENT_FIELDS:
        preferred_value = getattr(preferred, field_name)
        supplement_value = getattr(supplement, field_name)
        if preferred_value and supplement_value and not _field_values_are_equivalent(
            field_name,
            preferred_value,
            supplement_value,
        ):
            conflicting_fields.append(field_name)
            if field_name == "faculty_or_school":
                _append_field_conflict_warning(
                    preferred,
                    supplement,
                    field_name,
                    preferred_source_url=_field_evidence_source_url(
                        preferred_evidence,
                        field_name,
                        fallback=preferred.source_url,
                    ),
                    supplement_source_url=_field_evidence_source_url(
                        supplement_evidence,
                        field_name,
                        fallback=supplement.source_url,
                    ),
                )
            continue
        if preferred_value or not supplement_value:
            continue
        setattr(preferred, field_name, supplement_value)
        evidence_count += _append_enrichment_evidence(
            data,
            row_index,
            field_name,
            supplement,
            supplement_evidence,
        )
        enriched_fields.append(field_name)
        remove_resolved_programme_field_warning(preferred, field_name)

    supplement_specialisations = [
        value
        for value in supplement.specialisations_or_majors
        if _normalise_identity(value)
        not in {_normalise_identity(existing) for existing in preferred.specialisations_or_majors}
    ]
    if supplement_specialisations:
        preferred.specialisations_or_majors.extend(supplement_specialisations)
        evidence_count += _append_enrichment_evidence(
            data,
            row_index,
            "specialisations_or_majors",
            supplement,
            supplement_evidence,
        )
        enriched_fields.append("specialisations_or_majors")
    return enriched_fields, conflicting_fields, evidence_count


def _append_enrichment_evidence(
    data: AdmissionsData,
    row_index: int,
    field_name: str,
    supplement: ProgrammeCatalogRecord,
    evidence_by_field: dict[str, EvidenceItem],
) -> int:
    source_evidence = evidence_by_field.get(field_name) or evidence_by_field.get("name")
    if source_evidence is None:
        return 0
    claim_path = f"/programme_catalog/{row_index}/{field_name}"
    data.evidence.append(replace(source_evidence, claim_path=claim_path))
    mapping = data.run.config.setdefault("programme_catalog_enrichment_evidence", {})
    if isinstance(mapping, dict):
        row_mapping = mapping.setdefault(f"/programme_catalog/{row_index}/name", {})
        if isinstance(row_mapping, dict):
            row_mapping[field_name] = {
                "claim_path": claim_path,
                "source_url": supplement.source_url,
            }
    return 1


def _candidate_field_evidence(
    candidate: ProgrammeCatalogRecord,
    candidate_evidence: list[EvidenceItem],
    candidate_diagnostic: dict[str, object] | None,
) -> dict[str, EvidenceItem]:
    paths = {"name": candidate.evidence_path}
    if candidate_diagnostic is not None:
        raw_paths = candidate_diagnostic.get("field_evidence_paths")
        if isinstance(raw_paths, dict):
            paths.update(
                {
                    str(field): str(path)
                    for field, path in raw_paths.items()
                    if isinstance(field, str) and isinstance(path, str)
                }
            )
    by_path = {item.claim_path: item for item in candidate_evidence}
    return {field: by_path[path] for field, path in paths.items() if path in by_path}


def _field_evidence_snapshot(data: AdmissionsData, row: ProgrammeCatalogRecord) -> dict[str, EvidenceItem]:
    paths = {"name": row.evidence_path}
    for mapping_name in ("programme_catalog_field_evidence", "programme_catalog_enrichment_evidence"):
        mapping = data.run.config.get(mapping_name)
        row_mapping = mapping.get(row.evidence_path) if isinstance(mapping, dict) else None
        if not isinstance(row_mapping, dict):
            continue
        for field_name, raw_value in row_mapping.items():
            if isinstance(raw_value, str):
                paths[str(field_name)] = raw_value
            elif isinstance(raw_value, dict) and isinstance(raw_value.get("claim_path"), str):
                paths[str(field_name)] = str(raw_value["claim_path"])
    by_path = {item.claim_path: item for item in data.evidence}
    return {field: by_path[path] for field, path in paths.items() if path in by_path}


def _rebase_candidate(
    candidate: ProgrammeCatalogRecord,
    evidence: list[EvidenceItem],
    diagnostic: dict[str, object] | None,
    row_index: int,
) -> tuple[str, str]:
    old_root = _row_root(candidate.evidence_path)
    new_root = f"/programme_catalog/{row_index}"
    candidate.evidence_path = f"{new_root}/name"
    for item in evidence:
        item.claim_path = _rebase_path(item.claim_path, old_root, new_root)
    for warning in candidate.warnings:
        warning.field = _rebase_path(warning.field, old_root, new_root) if warning.field else warning.field
    if diagnostic is not None:
        diagnostic["claim_path"] = candidate.evidence_path
        raw_paths = diagnostic.get("field_evidence_paths")
        if isinstance(raw_paths, dict):
            diagnostic["field_evidence_paths"] = {
                field: _rebase_path(path, old_root, new_root) if isinstance(path, str) else path
                for field, path in raw_paths.items()
            }
    return old_root, new_root


def _store_candidate_field_evidence(data: AdmissionsData, diagnostic: dict[str, object] | None) -> None:
    if diagnostic is None or not isinstance(diagnostic.get("claim_path"), str):
        return
    raw_paths = diagnostic.get("field_evidence_paths")
    if not isinstance(raw_paths, dict):
        return
    field_paths = {
        str(field): str(path)
        for field, path in raw_paths.items()
        if isinstance(field, str) and isinstance(path, str)
    }
    if not field_paths:
        return
    mapping = data.run.config.setdefault("programme_catalog_field_evidence", {})
    if isinstance(mapping, dict):
        mapping[str(diagnostic["claim_path"])] = field_paths


def _remove_row_evidence_and_mappings(data: AdmissionsData, row_root: str) -> None:
    data.evidence = [item for item in data.evidence if not _path_is_within(item.claim_path, row_root)]
    row_path = f"{row_root}/name"
    for mapping_name in (
        "programme_catalog_field_evidence",
        "programme_catalog_enrichment_evidence",
        "programme_catalog_row_provenance",
    ):
        mapping = data.run.config.get(mapping_name)
        if isinstance(mapping, dict):
            mapping.pop(row_path, None)


def _set_row_provenance(
    data: AdmissionsData,
    row: ProgrammeCatalogRecord,
    source_role: str,
    candidate_diagnostic: dict[str, object] | None,
) -> None:
    mapping = data.run.config.setdefault("programme_catalog_row_provenance", {})
    if not isinstance(mapping, dict):
        return
    item: dict[str, object] = {
        "institution_key": _institution_key(data),
        "source_url": row.source_url,
        "source_role": source_role,
        "identity": _identity_dict(data, row),
    }
    raw_primary_urls = candidate_diagnostic.get("primary_source_urls") if candidate_diagnostic else None
    if isinstance(raw_primary_urls, list):
        primary_urls = [url for url in raw_primary_urls if isinstance(url, str) and url]
        if primary_urls:
            item["primary_source_urls"] = list(dict.fromkeys(primary_urls))
    mapping[row.evidence_path] = item


def _diagnostic_primary_source_urls(diagnostic: dict[str, object] | None) -> list[str]:
    raw_urls = diagnostic.get("primary_source_urls") if diagnostic else None
    if not isinstance(raw_urls, list):
        return []
    return [url for url in raw_urls if isinstance(url, str) and url]


def _row_primary_source_urls(data: AdmissionsData, row: ProgrammeCatalogRecord) -> list[str]:
    mapping = data.run.config.get("programme_catalog_row_provenance")
    item = mapping.get(row.evidence_path) if isinstance(mapping, dict) else None
    raw_urls = item.get("primary_source_urls") if isinstance(item, dict) else None
    if not isinstance(raw_urls, list):
        return []
    return [url for url in raw_urls if isinstance(url, str) and url]


def _merge_row_primary_source_urls(
    data: AdmissionsData,
    row: ProgrammeCatalogRecord,
    source_urls: list[str],
) -> None:
    if not source_urls:
        return
    mapping = data.run.config.get("programme_catalog_row_provenance")
    item = mapping.get(row.evidence_path) if isinstance(mapping, dict) else None
    if not isinstance(item, dict):
        return
    existing = item.get("primary_source_urls")
    existing_urls = [url for url in existing if isinstance(url, str) and url] if isinstance(existing, list) else []
    item["primary_source_urls"] = list(dict.fromkeys((*existing_urls, *source_urls)))


def _row_source_role(data: AdmissionsData, row: ProgrammeCatalogRecord) -> str:
    mapping = data.run.config.get("programme_catalog_row_provenance")
    item = mapping.get(row.evidence_path) if isinstance(mapping, dict) else None
    if isinstance(item, dict) and isinstance(item.get("source_role"), str):
        return str(item["source_role"])
    source_strategy = data.run.config.get("source_strategy")
    if isinstance(source_strategy, list):
        for entry in reversed(source_strategy):
            if isinstance(entry, dict) and entry.get("url") == row.source_url and isinstance(entry.get("source_role"), str):
                return str(entry["source_role"])
    return "faculty_catalog"


def _row_institution_key(data: AdmissionsData, row: ProgrammeCatalogRecord) -> str:
    mapping = data.run.config.get("programme_catalog_row_provenance")
    item = mapping.get(row.evidence_path) if isinstance(mapping, dict) else None
    if isinstance(item, dict) and isinstance(item.get("institution_key"), str):
        return str(item["institution_key"])
    return _institution_key(data)


def _institution_key(data: AdmissionsData) -> str:
    for raw_url in (data.institution.homepage_url, data.run.input_url):
        host = (urlparse(raw_url).hostname or "").lower()
        domain = registrable_domain(host)
        if domain:
            return domain
        if host:
            return host
    name = data.institution.name.value
    return _normalise_identity(name if isinstance(name, str) else "unknown") or "unknown"


def _source_is_official_html(data: AdmissionsData, source_url: str) -> bool:
    return any(
        source.source_url == source_url
        and source.is_official
        and str(source.source_type) == "html"
        for source in data.sources
    )


def _records_are_compatible(existing: ProgrammeCatalogRecord, candidate: ProgrammeCatalogRecord) -> bool:
    if _normalise_identity(existing.category) != _normalise_identity(candidate.category):
        return False
    existing_name = _normalise_identity(existing.name)
    candidate_name = _normalise_identity(candidate.name)
    if not existing_name or not candidate_name:
        return False
    existing_award = _normalise_award_identity(existing.degree_or_award)
    candidate_award = _normalise_award_identity(candidate.degree_or_award)
    if existing_name == candidate_name:
        return not (existing_award and candidate_award and existing_award != candidate_award)
    existing_name_as_award = _normalise_award_identity(existing.name)
    candidate_name_as_award = _normalise_award_identity(candidate.name)
    return bool(
        (candidate_name_as_award and candidate_name_as_award == existing_award)
        or (existing_name_as_award and existing_name_as_award == candidate_award)
    ) and not (existing_award and candidate_award and existing_award != candidate_award)


def compatible_programme_detail_indexes(
    data: AdmissionsData,
    candidate: ProgrammeCatalogRecord,
    *,
    eligible_source_urls: set[str] | None = None,
) -> list[int]:
    """Match a title-bound detail candidate to a unique catalog programme name."""

    institution_key = _institution_key(data)
    candidate_identity = _detail_programme_identity(candidate.name)
    if not candidate_identity:
        return []
    return [
        index
        for index, existing in enumerate(data.programme_catalog)
        if (eligible_source_urls is None or existing.source_url in eligible_source_urls)
        and _normalise_identity(existing.category) == _normalise_identity(candidate.category)
        and _row_institution_key(data, existing) == institution_key
        and _detail_programme_identity(existing.name) == candidate_identity
    ]


def normalise_programme_detail_identity(value: object) -> str:
    """Return the conservative identity used to match a detail title to one catalog row."""

    return _detail_programme_identity(value)


def programme_detail_identity_from_url(url: str) -> str:
    path = unquote(urlparse(url).path).rstrip("/")
    leaf = path.rsplit("/", 1)[-1].replace("-", " ") if path else ""
    return _detail_programme_identity(leaf)


def _detail_programme_identity(value: object) -> str:
    raw = unicodedata.normalize("NFKC", str(value or ""))
    raw = re.sub(r"\((?:hons?|honours?|honors?)\)", " ", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\([A-Z][A-Z0-9]{1,7}\)", " ", raw)
    raw = re.sub(
        r"\bat\s+(?:NTU|Nanyang\s+Technological\s+University)\b.*$",
        " ",
        raw,
        flags=re.IGNORECASE,
    )
    normalized = _normalise_identity(raw.replace("&", " and "))
    for prefix in _DEGREE_FAMILY_PREFIXES:
        if normalized == prefix:
            return ""
        if normalized.startswith(f"{prefix} "):
            normalized = normalized[len(prefix) + 1 :]
            break
    normalized = re.sub(r"^(?:in\s+)?(?:double\s+major\s+)?", "", normalized)
    return normalized.strip()


def _programme_degree_family(row: ProgrammeCatalogRecord) -> str:
    for value in (row.degree_or_award, row.name):
        normalized = _normalise_award_identity(value)
        for prefix in _DEGREE_FAMILY_PREFIXES:
            if normalized == prefix or normalized.startswith(f"{prefix} "):
                return prefix
    return ""


def _identity_dict(data: AdmissionsData, row: ProgrammeCatalogRecord) -> dict[str, str]:
    return {
        "institution": _institution_key(data),
        "category": _normalise_identity(row.category),
        "name": _normalise_identity(row.name),
        "degree_or_award": _normalise_identity(row.degree_or_award),
    }


def _candidate_diagnostic(
    candidate: ProgrammeCatalogRecord,
    diagnostics: list[dict[str, object]],
) -> dict[str, object] | None:
    return next(
        (
            item
            for item in diagnostics
            if item.get("decision") == "accepted" and item.get("claim_path") == candidate.evidence_path
        ),
        None,
    )


def _accepted_diagnostic(data: AdmissionsData, row: ProgrammeCatalogRecord) -> dict[str, object] | None:
    raw = data.run.config.get("programme_catalog_candidate_diagnostics")
    if not isinstance(raw, list):
        return None
    return next(
        (
            item
            for item in reversed(raw)
            if isinstance(item, dict)
            and item.get("decision") == "accepted"
            and item.get("claim_path") == row.evidence_path
            and item.get("source_url") == row.source_url
        ),
        None,
    )


def _rewrite_merged_candidate(
    diagnostic: dict[str, object] | None,
    *,
    reason: str,
    matched_claim_path: str,
    preferred_source_role: str,
    enriched_fields: list[str] | tuple[str, ...],
    conflicting_fields: list[str],
    match_method: str | None = None,
) -> None:
    if diagnostic is None:
        return
    diagnostic["parser_decision"] = diagnostic.get("decision")
    diagnostic["parser_claim_path"] = diagnostic.get("claim_path")
    diagnostic["decision"] = "context"
    diagnostic["reason"] = reason
    diagnostic["parser_stage"] = "source_role_merge"
    diagnostic["claim_path"] = matched_claim_path
    diagnostic["matched_claim_path"] = matched_claim_path
    diagnostic["preferred_source_role"] = preferred_source_role
    diagnostic["enriched_fields"] = list(enriched_fields)
    diagnostic["conflicting_fields"] = list(conflicting_fields)
    if match_method:
        diagnostic["match_method"] = match_method


def _append_merge_diagnostic(
    data: AdmissionsData,
    *,
    candidate: ProgrammeCatalogRecord,
    source_role: str,
    decision: str,
    reason: str,
    matched_claim_path: str,
    previous_claim_path: str | None = None,
    previous_source_url: str | None = None,
    previous_source_role: str | None = None,
    enriched_fields: list[str] | None = None,
    conflicting_fields: list[str] | None = None,
    ambiguous_match_count: int = 0,
    match_method: str | None = None,
) -> None:
    diagnostics = data.run.config.setdefault("programme_catalog_merge_diagnostics", [])
    if not isinstance(diagnostics, list):
        return
    item: dict[str, object] = {
        "decision": decision,
        "reason": reason,
        "source_url": candidate.source_url,
        "source_role": source_role,
        "matched_claim_path": matched_claim_path,
        "identity": _identity_dict(data, candidate),
        "enriched_fields": list(enriched_fields or ()),
        "conflicting_fields": list(conflicting_fields or ()),
    }
    if previous_claim_path:
        item["previous_claim_path"] = previous_claim_path
    if previous_source_url:
        item["previous_source_url"] = previous_source_url
    if previous_source_role:
        item["previous_source_role"] = previous_source_role
    if ambiguous_match_count:
        item["ambiguous_match_count"] = ambiguous_match_count
    if match_method:
        item["match_method"] = match_method
    diagnostics.append(item)


def remove_resolved_programme_field_warning(row: ProgrammeCatalogRecord, field_name: str) -> None:
    labels = {
        "degree_or_award": "ambiguous_degree:",
        "faculty_or_school": "missing_faculty:",
    }
    label = labels.get(field_name)
    if label:
        row.warnings = [warning for warning in row.warnings if label not in warning.message]


def _append_field_conflict_warning(
    preferred: ProgrammeCatalogRecord,
    supplement: ProgrammeCatalogRecord,
    field_name: str,
    *,
    preferred_source_url: str,
    supplement_source_url: str,
) -> None:
    label = f"conflicting_{field_name}:"
    source_urls = list(dict.fromkeys((preferred_source_url, supplement_source_url)))
    existing = next((warning for warning in preferred.warnings if warning.message.startswith(label)), None)
    if existing is not None:
        existing.source_urls = list(dict.fromkeys((*existing.source_urls, *source_urls)))
        return
    preferred.warnings.append(
        WarningRecord(
            WarningCode.NEEDS_MANUAL_CHECK,
            (
                f"{label} Retained value is {getattr(preferred, field_name)!r}; "
                f"another official source reports {getattr(supplement, field_name)!r}."
            ),
            field=preferred.evidence_path,
            source_urls=source_urls,
        )
    )


def _field_evidence_source_url(
    evidence_by_field: dict[str, EvidenceItem],
    field_name: str,
    *,
    fallback: str,
) -> str:
    evidence = evidence_by_field.get(field_name)
    return evidence.source_url if evidence is not None else fallback


def _source_role_priority(source_role: str) -> int:
    return PROGRAMME_SOURCE_ROLE_PRIORITY.get(source_role, 99)


def _normalise_identity(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    tokens: list[str] = []
    current: list[str] = []
    for char in normalized:
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return " ".join(tokens)


def _normalise_award_identity(value: object) -> str:
    normalized = _normalise_identity(str(value or "").replace("&", " and "))
    return " ".join(
        token
        for token in normalized.split()
        if token not in {"hons", "honours", "honors"}
    )


def _field_values_are_equivalent(field_name: str, left: object, right: object) -> bool:
    normalizer = _normalise_award_identity if field_name == "degree_or_award" else _normalise_identity
    return normalizer(left) == normalizer(right)


def _row_root(claim_path: str) -> str:
    return claim_path.rsplit("/", 1)[0]


def _rebase_path(path: str, old_root: str, new_root: str) -> str:
    if path == old_root:
        return new_root
    if path.startswith(f"{old_root}/"):
        return f"{new_root}{path[len(old_root):]}"
    return path


def _path_is_within(path: str, root: str) -> bool:
    return path == root or path.startswith(f"{root}/")
