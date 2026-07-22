"""Conservative completeness proof for programme catalog diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from university_admissions_crawler.extractor.schema import AdmissionsData


_CATALOG_SOURCE_ROLES = {"canonical_catalog", "faculty_catalog"}
_TERMINAL_CANDIDATE_DECISIONS = {"accepted", "rejected", "context", "quarantined"}
_SOURCE_GAP_STATUSES = {
    "budget_skipped",
    "dynamic_shell_no_rows",
    "not_crawled",
    "source_acquisition_issue",
}
_FAILURE_STAGE_ORDER = (
    "discovery",
    "segmentation",
    "entity_gate",
    "completeness_proof",
)
_FAILURE_STAGE_BY_CHECK = {
    "accepted_rows_present": "segmentation",
    "canonical_catalog_captured": "discovery",
    "canonical_catalog_accepted": "segmentation",
    "candidate_conservation_proven": "completeness_proof",
    "catalog_section_conservation_proven": "completeness_proof",
    "no_quarantined_candidates": "entity_gate",
    "no_manual_review_rows": "entity_gate",
    "accepted_structural_anchors_present": "entity_gate",
    "no_source_acquisition_gaps": "discovery",
    "row_yield_not_suspicious": "segmentation",
    "api_pagination_proven": "completeness_proof",
    "api_filter_enumeration_proven": "completeness_proof",
}


def evaluate_programme_catalog_completeness(
    data: AdmissionsData,
    *,
    candidate_source_urls: list[str],
    source_status_counts: Mapping[str, int],
    candidate_diagnostic_summary: Mapping[str, object],
    api_summary: Mapping[str, object],
    accepted_row_count: int,
    manual_review_count: int,
    low_row_yield: bool,
) -> dict[str, object]:
    """Return an explainable fail-closed completeness decision."""

    entries = _candidate_diagnostics(data)
    captured_urls = {source.source_url for source in data.sources}
    roles_by_url = _source_roles_by_url(data, entries)
    source_role_counts = Counter(roles_by_url.get(url, "unknown") for url in candidate_source_urls)
    accepted_by_source_role = _accepted_rows_by_source_role(data, roles_by_url)

    canonical_captured_urls = {
        url
        for url, role in roles_by_url.items()
        if role == "canonical_catalog" and url in captured_urls
    }
    canonical_catalog_captured = bool(canonical_captured_urls)
    canonical_catalog_accepted = accepted_by_source_role.get("canonical_catalog", 0) > 0

    decision_counts = Counter(str(item.get("decision", "unknown")) for item in entries)
    terminal_count = sum(decision_counts.get(decision, 0) for decision in _TERMINAL_CANDIDATE_DECISIONS)
    unknown_count = len(entries) - terminal_count
    candidate_conservation_proven = bool(entries) and terminal_count == len(entries)
    quarantined_count = decision_counts.get("quarantined", 0)

    identified_sections, processed_sections, ledger_source_urls = _catalog_sections(
        entries,
        candidate_source_urls=set(candidate_source_urls),
    )
    catalog_section_conservation_proven = canonical_catalog_captured and bool(identified_sections) and (
        processed_sections == identified_sections
        and canonical_captured_urls.issubset(ledger_source_urls)
    )

    source_acquisition_gaps = sorted(
        status
        for status in _SOURCE_GAP_STATUSES
        if source_status_counts.get(status, 0) > 0
    )
    api_response_count = _int_or_zero(api_summary.get("api_response_count"))
    api_pagination_proven = not api_response_count or bool(api_summary.get("api_pagination_complete"))
    filter_dimensions = api_summary.get("api_filter_candidate_dimensions")
    filters_detected = isinstance(filter_dimensions, dict) and bool(filter_dimensions)
    filter_attempted_count = _int_or_zero(api_summary.get("api_filter_attempted_url_count"))
    filter_fetched_count = _int_or_zero(api_summary.get("api_filter_fetched_url_count"))
    filter_rejected_count = _int_or_zero(api_summary.get("api_filter_rejected_url_count"))
    api_filter_enumeration_proven = not filters_detected or bool(
        filter_attempted_count > 0
        and filter_fetched_count == filter_attempted_count
        and filter_rejected_count == 0
        and not api_summary.get("api_filter_enumeration_budget_hit")
    )

    checks = {
        "accepted_rows_present": accepted_row_count > 0,
        "canonical_catalog_captured": canonical_catalog_captured,
        "canonical_catalog_accepted": canonical_catalog_accepted,
        "candidate_conservation_proven": candidate_conservation_proven,
        "catalog_section_conservation_proven": catalog_section_conservation_proven,
        "no_quarantined_candidates": quarantined_count == 0,
        "no_manual_review_rows": manual_review_count == 0,
        "accepted_structural_anchors_present": _int_or_zero(
            candidate_diagnostic_summary.get("accepted_without_structural_anchor_count")
        )
        == 0,
        "no_source_acquisition_gaps": not source_acquisition_gaps,
        "row_yield_not_suspicious": not low_row_yield,
        "api_pagination_proven": api_pagination_proven,
        "api_filter_enumeration_proven": api_filter_enumeration_proven,
    }
    failure_reasons = [name for name, passed in checks.items() if not passed]
    failure_stage_counts = Counter(
        _FAILURE_STAGE_BY_CHECK.get(reason, "completeness_proof")
        for reason in failure_reasons
    )
    failure_stages = [stage for stage in _FAILURE_STAGE_ORDER if failure_stage_counts[stage]]
    catalog_complete = not failure_reasons

    return {
        "source_role_counts": dict(sorted(source_role_counts.items())),
        "accepted_by_source_role": dict(sorted(accepted_by_source_role.items())),
        "canonical_catalog_captured": canonical_catalog_captured,
        "canonical_catalog_accepted": canonical_catalog_accepted,
        "candidate_conservation_expected_count": len(entries),
        "candidate_conservation_observed_count": terminal_count,
        "candidate_unknown_decision_count": unknown_count,
        "candidate_conservation_proven": candidate_conservation_proven,
        "quarantined_candidate_count": quarantined_count,
        "identified_catalog_section_count": len(identified_sections),
        "processed_catalog_section_count": len(processed_sections),
        "catalog_section_conservation_proven": catalog_section_conservation_proven,
        "source_acquisition_gap_reasons": source_acquisition_gaps,
        "catalog_complete": catalog_complete,
        "catalog_completeness_status": "complete" if catalog_complete else "probable_incomplete",
        "catalog_completeness_basis": [name for name, passed in checks.items() if passed],
        "catalog_completeness_failure_reasons": failure_reasons,
        "catalog_completeness_failure_stages": failure_stages,
        "catalog_completeness_failure_stage_counts": {
            stage: failure_stage_counts[stage]
            for stage in failure_stages
        },
        "catalog_completeness_checks": checks,
    }


def _candidate_diagnostics(data: AdmissionsData) -> list[dict[str, object]]:
    raw = data.run.config.get("programme_catalog_candidate_diagnostics")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _source_roles_by_url(
    data: AdmissionsData,
    entries: list[dict[str, object]],
) -> dict[str, str]:
    roles: dict[str, str] = {}
    source_strategy = data.run.config.get("source_strategy")
    if isinstance(source_strategy, list):
        for item in source_strategy:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            role = item.get("source_role")
            if isinstance(url, str) and isinstance(role, str):
                roles[url] = role
    for item in entries:
        url = item.get("source_url")
        role = item.get("source_role")
        if isinstance(url, str) and isinstance(role, str) and role in _CATALOG_SOURCE_ROLES:
            roles[url] = role
    provenance = data.run.config.get("programme_catalog_row_provenance")
    if isinstance(provenance, dict):
        for item in provenance.values():
            if not isinstance(item, dict):
                continue
            url = item.get("source_url")
            role = item.get("source_role")
            if isinstance(url, str) and isinstance(role, str):
                roles[url] = role
    return roles


def _accepted_rows_by_source_role(
    data: AdmissionsData,
    roles_by_url: Mapping[str, str],
) -> Counter[str]:
    provenance = data.run.config.get("programme_catalog_row_provenance")
    counts: Counter[str] = Counter()
    for row in data.programme_catalog:
        role = None
        item = provenance.get(row.evidence_path) if isinstance(provenance, dict) else None
        if isinstance(item, dict) and isinstance(item.get("source_role"), str):
            role = str(item["source_role"])
        counts[role or roles_by_url.get(row.source_url, "unknown")] += 1
    return counts


def _catalog_sections(
    entries: list[dict[str, object]],
    *,
    candidate_source_urls: set[str],
) -> tuple[set[tuple[str, tuple[str, ...]]], set[tuple[str, tuple[str, ...]]], set[str]]:
    identified: set[tuple[str, tuple[str, ...]]] = set()
    section_terminal: dict[tuple[str, tuple[str, ...]], bool] = {}
    ledger_source_urls: set[str] = set()
    for item in entries:
        source_url = item.get("source_url")
        if not isinstance(source_url, str) or source_url not in candidate_source_urls:
            continue
        raw_path = item.get("section_path")
        section_path = tuple(str(part) for part in raw_path) if isinstance(raw_path, list) and raw_path else ("__root__",)
        key = (source_url, section_path)
        identified.add(key)
        ledger_source_urls.add(source_url)
        terminal = item.get("decision") in _TERMINAL_CANDIDATE_DECISIONS
        section_terminal[key] = section_terminal.get(key, True) and terminal
    processed = {key for key, terminal in section_terminal.items() if terminal}
    return identified, processed, ledger_source_urls


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) else 0
