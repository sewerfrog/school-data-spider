"""Run diagnostics for coverage and source strategy reporting."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from university_admissions_crawler.crawler.filters import looks_like_blocked_or_challenge_source
from university_admissions_crawler.extractor.schema import AdmissionsData, PageCategory, SourceType, WarningCode, WarningRecord


MISSING_REASON_CODES: tuple[str, ...] = (
    "source_not_found",
    "blocked_or_challenge",
    "attempted_no_match",
    "context_gate_failed",
    "raw_needs_manual_review",
    "portal_or_login_required",
    "manual_check_required",
)
LEGACY_MISSING_REASON_CODES: tuple[str, ...] = (
    "not_attempted",
    "source_not_crawled",
    "application_portal_unreachable",
    "attempted_no_match",
    "context_gate_failed",
    "undergraduate_context_gate_failed",
    "manual_check_required",
)
LEGACY_MISSING_REASON_BY_CANONICAL = {
    "source_not_found": "not_attempted",
    "blocked_or_challenge": "source_not_crawled",
    "portal_or_login_required": "application_portal_unreachable",
}
MISSING_REASON_ACTION_TARGETS = {
    "source_not_found": "discovery_or_classifier",
    "blocked_or_challenge": "source_acquisition",
    "attempted_no_match": "extractor",
    "context_gate_failed": "context_gate",
    "raw_needs_manual_review": "parser_or_manual_review",
    "portal_or_login_required": "portal_or_manual_review",
    "manual_check_required": "manual_review",
}


@dataclass(frozen=True, slots=True)
class FieldCapability:
    """Static capability map used by diagnostics; it does not drive extraction."""

    field: str
    claim_path: str
    discovery_categories: tuple[PageCategory, ...]
    context_gates: tuple[str, ...]
    deterministic_extractors: tuple[str, ...]
    llm_claim_paths: tuple[str, ...] = ()
    diagnostics_reasons: tuple[str, ...] = MISSING_REASON_CODES


FIELD_CAPABILITIES: tuple[FieldCapability, ...] = (
    FieldCapability(
        field="undergraduate_application_entry",
        claim_path="/admissions/undergraduate_application_entry",
        discovery_categories=(PageCategory.UNDERGRADUATE_ADMISSIONS,),
        context_gates=("requires_application_period",),
        deterministic_extractors=("source_url_from_application_period",),
        llm_claim_paths=("admissions.application_entry",),
    ),
    FieldCapability(
        field="application_periods",
        claim_path="/admissions/application_periods",
        discovery_categories=(PageCategory.UNDERGRADUATE_ADMISSIONS, PageCategory.APPLICATION_DEADLINES),
        context_gates=(),
        deterministic_extractors=("extract_deadline",),
        llm_claim_paths=("admissions.application_period", "admissions.application_deadline"),
    ),
    FieldCapability(
        field="english_requirements",
        claim_path="/admissions/english_requirements",
        discovery_categories=(PageCategory.INTERNATIONAL_REQUIREMENTS,),
        context_gates=("has_english_requirement_context", "has_undergraduate_admissions_context"),
        deterministic_extractors=("extract_english_requirement",),
        llm_claim_paths=("admissions.requirements.english",),
    ),
    FieldCapability(
        field="accepted_qualifications",
        claim_path="/admissions/accepted_qualifications",
        discovery_categories=(
            PageCategory.ACCEPTED_QUALIFICATIONS,
            PageCategory.INTERNATIONAL_REQUIREMENTS,
            PageCategory.PROGRAMME_PREREQUISITES,
        ),
        context_gates=(),
        deterministic_extractors=("extract_accepted_qualification", "extract_prerequisite"),
        llm_claim_paths=("admissions.requirements.academic",),
    ),
    FieldCapability(
        field="required_documents",
        claim_path="/admissions/required_documents",
        discovery_categories=(PageCategory.UNDERGRADUATE_ADMISSIONS,),
        context_gates=(),
        deterministic_extractors=("extract_required_document",),
        llm_claim_paths=("admissions.required_documents",),
    ),
    FieldCapability(
        field="programmes",
        claim_path="/programmes",
        discovery_categories=(PageCategory.PROGRAMME_LIST, PageCategory.PROGRAMME_PREREQUISITES),
        context_gates=("has_undergraduate_admissions_context",),
        deterministic_extractors=("extract_programmes", "extract_programme"),
    ),
    FieldCapability(
        field="fees",
        claim_path="/fees",
        discovery_categories=(PageCategory.FEES,),
        context_gates=("has_undergraduate_fee_context", "has_undergraduate_admissions_context"),
        deterministic_extractors=("extract_fee",),
        llm_claim_paths=("admissions.fees",),
    ),
    FieldCapability(
        field="scholarships",
        claim_path="/scholarships",
        discovery_categories=(PageCategory.SCHOLARSHIPS,),
        context_gates=("has_undergraduate_scholarship_context", "has_undergraduate_admissions_context"),
        deterministic_extractors=("extract_scholarship",),
        llm_claim_paths=("admissions.scholarships",),
    ),
    FieldCapability(
        field="contacts",
        claim_path="/contacts",
        discovery_categories=(PageCategory.CONTACT,),
        context_gates=("has_admissions_contact_context", "has_undergraduate_admissions_context"),
        deterministic_extractors=("extract_contact",),
        llm_claim_paths=("admissions.contact",),
    ),
)
FIELD_CAPABILITY_BY_FIELD: dict[str, FieldCapability] = {
    capability.field: capability for capability in FIELD_CAPABILITIES
}
CORE_FIELDS: tuple[tuple[str, str], ...] = tuple(
    (capability.field, capability.claim_path) for capability in FIELD_CAPABILITIES
)

PORTAL_TERMS = (
    "applyto",
    "application portal",
    "applicant portal",
    "login",
    "sign in",
    "signin",
    "sso",
)

def source_strategy_for(source_type: SourceType, url: str, title: str | None, text: str, category: PageCategory | None = None) -> str:
    """Return a coarse strategy label for report diagnostics."""

    url_title = f"{url} {title or ''}".lower()
    text_lower = text.lower()
    if looks_like_blocked_or_challenge_source(url, title, text):
        return "blocked_or_challenge"
    if any(term in url_title for term in PORTAL_TERMS) or "please log in" in text_lower[:1200] or "sign in to" in text_lower[:1200]:
        return "application_portal"
    if source_type == SourceType.PDF:
        return "pdf_document"
    if source_type == SourceType.JSON:
        return "json_api"
    if category == PageCategory.IRRELEVANT:
        return "irrelevant"
    if source_type == SourceType.HTML:
        return "html_page"
    return "other"


def attach_run_diagnostics(data: AdmissionsData) -> AdmissionsData:
    """Attach coverage/source-strategy diagnostics under run.config."""

    refresh_run_diagnostics(data)
    coverage = data.run.config.get("coverage", {})
    source_strategy = data.run.config.get("source_strategy", [])
    source_strategy_summary = data.run.config.get("source_strategy_summary", {})
    if coverage["missing"]:
        data.warnings.append(
            WarningRecord(
                WarningCode.NEEDS_MANUAL_CHECK,
                "Some core undergraduate admissions fields were not found; review coverage.missing.",
                field="/run/config/coverage",
            )
        )
    if source_strategy_summary.get("blocked_or_challenge") or source_strategy_summary.get("application_portal"):
        blocked = [item.get("url") for item in source_strategy if item.get("strategy") in {"blocked_or_challenge", "application_portal"}]
        data.warnings.append(
            WarningRecord(
                WarningCode.NEEDS_MANUAL_CHECK,
                "Some sources look like application portals or bot/challenge pages; crawler will not bypass restricted systems.",
                field="/run/config/source_strategy",
                source_urls=[url for url in blocked if url],
            )
        )
    return data


def refresh_run_diagnostics(data: AdmissionsData) -> AdmissionsData:
    """Refresh run.config diagnostics without adding warnings or changing facts."""

    coverage = _coverage(data)
    source_strategy = data.run.config.get("source_strategy", [])
    summary = Counter(item.get("strategy", "unknown") for item in source_strategy if isinstance(item, dict))
    extraction_diagnostics = data.run.config.get("extraction_diagnostics")
    data.run.config["coverage"] = coverage
    data.run.config["field_capability_matrix"] = _field_capability_matrix()
    data.run.config["source_strategy_summary"] = dict(sorted(summary.items()))
    data.run.config["programme_catalog_summary"] = _programme_catalog_summary(data, extraction_diagnostics, source_strategy)
    classification_assist = data.run.config.get("classification_assist")
    if isinstance(classification_assist, list):
        data.run.config["classification_assist_summary"] = _classification_assist_summary(classification_assist)
    if isinstance(extraction_diagnostics, list):
        data.run.config["extraction_diagnostics_summary"] = _extraction_diagnostics_summary(extraction_diagnostics)
        data.run.config["missing_reasons_contract"] = _missing_reasons_contract()
        data.run.config["missing_reasons"] = _missing_reasons(coverage, extraction_diagnostics, source_strategy)
    attach_template_completeness(data)
    return data


def attach_template_completeness(data: AdmissionsData) -> AdmissionsData:
    """Attach template-completeness diagnostics without changing facts."""

    coverage = data.run.config.get("coverage")
    source_strategy = data.run.config.get("source_strategy", [])
    extraction_diagnostics = data.run.config.get("extraction_diagnostics", [])
    missing_reasons = data.run.config.get("missing_reasons", {})
    if not isinstance(coverage, dict):
        coverage = _coverage(data)
        data.run.config["coverage"] = coverage
    if not isinstance(missing_reasons, dict):
        missing_reasons = {}
    if not isinstance(extraction_diagnostics, list):
        extraction_diagnostics = []
    data.run.config["field_capability_matrix"] = _field_capability_matrix()
    data.run.config["template_completeness"] = _template_completeness(data, coverage, extraction_diagnostics, source_strategy, missing_reasons)
    return data


def llm_structured_validation_summary(results: list[object]) -> dict[str, object]:
    """Summarize accepted/rejected LLM structured candidate validation results."""

    accepted_count = 0
    rejected_count = 0
    reject_reasons: Counter[str] = Counter()
    accepted_claim_paths: Counter[str] = Counter()
    for result in results:
        if not isinstance(result, dict):
            continue
        candidate = result.get("candidate")
        if result.get("accepted") is True:
            accepted_count += 1
            if isinstance(candidate, dict):
                accepted_claim_paths[str(candidate.get("claim_path", "unknown"))] += 1
        else:
            rejected_count += 1
            reject_reasons[str(result.get("reject_reason", "unknown"))] += 1
    return {
        "candidate_count": accepted_count + rejected_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "reject_reasons": dict(sorted(reject_reasons.items())),
        "accepted_claim_paths": dict(sorted(accepted_claim_paths.items())),
        "note": "LLM structured extraction candidates are summarized after deterministic validation; rejected candidates are diagnostics only.",
    }


def _field_capability_matrix() -> dict[str, object]:
    return {capability.field: _field_capability_to_dict(capability) for capability in FIELD_CAPABILITIES}


def _missing_reasons_contract() -> dict[str, object]:
    return {
        "reason": "legacy-compatible diagnostic label retained for existing consumers",
        "canonical_reason": "actionable diagnostic label for debt-2 capability routing",
        "action_target": "repair layer suggested by canonical_reason",
        "canonical_reasons": list(MISSING_REASON_CODES),
        "legacy_reasons": list(LEGACY_MISSING_REASON_CODES),
        "note": "Consumers should migrate from reason to canonical_reason; reason remains stable for compatibility.",
    }


def _field_capability_details(field: str) -> dict[str, object]:
    capability = FIELD_CAPABILITY_BY_FIELD.get(field)
    if capability is None:
        return {
            "field": field,
            "claim_path": "",
            "discovery_categories": [],
            "context_gates": [],
            "deterministic_extractors": [],
            "structured_llm_fallback": False,
            "llm_claim_paths": [],
            "diagnostics_reasons": list(MISSING_REASON_CODES),
            "compatibility_reasons": list(LEGACY_MISSING_REASON_CODES),
        }
    return _field_capability_to_dict(capability)


def _field_capability_to_dict(capability: FieldCapability) -> dict[str, object]:
    return {
        "field": capability.field,
        "claim_path": capability.claim_path,
        "discovery_categories": [str(category) for category in capability.discovery_categories],
        "context_gates": list(capability.context_gates),
        "deterministic_extractors": list(capability.deterministic_extractors),
        "structured_llm_fallback": bool(capability.llm_claim_paths),
        "llm_claim_paths": list(capability.llm_claim_paths),
        "diagnostics_reasons": list(capability.diagnostics_reasons),
        "compatibility_reasons": list(LEGACY_MISSING_REASON_CODES),
    }


def _classification_assist_summary(entries: list[object]) -> dict[str, object]:
    valid_entries = [item for item in entries if isinstance(item, dict)]
    candidate_categories: Counter[str] = Counter()
    candidate_confidences: Counter[str] = Counter()
    rule_categories: Counter[str] = Counter()
    rule_scores: Counter[str] = Counter()
    disagreement_count = 0
    fallback_count = 0
    applied_count = 0
    for entry in valid_entries:
        rule_category = str(entry.get("rule_category", "unknown"))
        rule_categories[rule_category] += 1
        rule_scores[str(entry.get("rule_score", "unknown"))] += 1
        if entry.get("fallback") is True:
            fallback_count += 1
        if entry.get("applied") is True:
            applied_count += 1
        candidate = entry.get("candidate")
        candidate_category = "none"
        if isinstance(candidate, dict):
            candidate_category = str(candidate.get("category", "unknown"))
            candidate_categories[candidate_category] += 1
            candidate_confidences[str(candidate.get("confidence", "unknown"))] += 1
        else:
            candidate_categories[candidate_category] += 1
        if candidate_category != rule_category:
            disagreement_count += 1
    return {
        "entries_count": len(valid_entries),
        "fallback_count": fallback_count,
        "applied_count": applied_count,
        "disagreement_count": disagreement_count,
        "rule_categories": dict(sorted(rule_categories.items())),
        "rule_scores": dict(sorted(rule_scores.items())),
        "candidate_categories": dict(sorted(candidate_categories.items())),
        "candidate_confidences": dict(sorted(candidate_confidences.items())),
        "note": "Classification assist is diagnostics-only; candidates are not applied to facts.",
    }


def _extraction_diagnostics_summary(entries: list[object]) -> dict[str, object]:
    valid_sources = [item for item in entries if isinstance(item, dict)]
    attempts: list[dict[str, object]] = []
    sources_with_extractions = 0
    for source in valid_sources:
        raw_attempts = source.get("attempts")
        if not isinstance(raw_attempts, list):
            continue
        source_attempts = [item for item in raw_attempts if isinstance(item, dict)]
        attempts.extend(source_attempts)
        if any(item.get("status") == "extracted" for item in source_attempts):
            sources_with_extractions += 1

    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    extractor_counts: Counter[str] = Counter()
    field_status_counts: dict[str, Counter[str]] = {}
    for attempt in attempts:
        field = str(attempt.get("field", "unknown"))
        status = str(attempt.get("status", "unknown"))
        status_counts[status] += 1
        reason_counts[str(attempt.get("reason", "unknown"))] += 1
        extractor_counts[str(attempt.get("extractor", "unknown"))] += 1
        field_status_counts.setdefault(field, Counter())[status] += 1

    return {
        "sources_count": len(valid_sources),
        "sources_with_extractions": sources_with_extractions,
        "attempts_count": len(attempts),
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "extractor_counts": dict(sorted(extractor_counts.items())),
        "field_status_counts": {field: dict(sorted(counts.items())) for field, counts in sorted(field_status_counts.items())},
        "note": "Extraction diagnostics report attempted extractors and outcomes only; they do not change facts.",
    }


def _programme_catalog_summary(data: AdmissionsData, extraction_entries: object = None, source_strategy: object = None) -> dict[str, object]:
    rows = data.programme_catalog
    api_summary = _programme_catalog_api_summary(data)
    programme_types: Counter[str] = Counter()
    faculties: Counter[str] = Counter()
    parse_statuses: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    names: dict[str, tuple[str, int]] = {}
    manual_review_count = 0
    warning_count = 0
    raw_needs_review_count = 0

    for row in rows:
        programme_types[row.category or "unknown"] += 1
        faculties[row.faculty_or_school or "unknown"] += 1
        parse_statuses[row.parse_status or "unknown"] += 1
        sources[row.source_url] += 1
        normalised_name = _normalise_programme_name(row.name)
        if normalised_name:
            display_name, count = names.get(normalised_name, (row.name, 0))
            names[normalised_name] = (display_name, count + 1)
        if row.parse_status != "parsed" or row.warnings:
            manual_review_count += 1
        if row.parse_status != "parsed":
            raw_needs_review_count += 1
        warning_count += len(row.warnings)

    duplicate_names = [
        {"name": display_name, "count": count}
        for display_name, count in sorted((value for value in names.values() if value[1] > 1), key=lambda item: item[0].casefold())
    ]
    duplicate_count = sum(item["count"] - 1 for item in duplicate_names)
    source_urls = sorted(sources)
    candidate_source_urls = _programme_catalog_candidate_source_urls(data, extraction_entries, source_strategy)
    crawled_catalog_source_urls = sorted(set(candidate_source_urls) & {source.source_url for source in data.sources})
    source_status_counts = _programme_catalog_source_status_counts(candidate_source_urls, extraction_entries, source_strategy)
    catalog_source_family_counts = _source_family_counts(candidate_source_urls)
    accepted_source_family_counts = _source_family_counts(source_urls)
    source_family_bias = _source_family_bias(
        catalog_source_family_counts=catalog_source_family_counts,
        accepted_source_family_counts=accepted_source_family_counts,
        accepted_row_count=len(rows),
    )
    false_positive_rejected_count = _false_positive_rejected_count(extraction_entries)
    accepted_to_candidate_source_ratio = _programme_catalog_source_ratio(
        candidate_source_count=len(candidate_source_urls),
        accepted_row_count=len(rows),
    )
    low_row_yield = _programme_catalog_low_row_yield(
        candidate_source_count=len(candidate_source_urls),
        accepted_row_count=len(rows),
    )
    probable_incomplete_catalog = _probable_incomplete_catalog(
        candidate_source_count=len(candidate_source_urls),
        accepted_row_count=len(rows),
        raw_needs_review_count=raw_needs_review_count,
        source_status_counts=source_status_counts,
        low_row_yield=low_row_yield,
    ) or bool(api_summary.get("api_pagination_incomplete", False))
    api_candidate_zero_reason = _api_candidate_zero_reason(
        data,
        candidate_source_count=len(candidate_source_urls),
        source_status_counts=source_status_counts,
    )
    return {
        "candidate_count": len(rows),
        "accepted_count": len(rows),
        "rejected_count": false_positive_rejected_count,
        "candidate_source_count": len(candidate_source_urls),
        "candidate_source_urls": candidate_source_urls,
        "crawled_catalog_source_count": len(crawled_catalog_source_urls),
        "crawled_catalog_source_urls": crawled_catalog_source_urls,
        "accepted_row_count": len(rows),
        "raw_needs_review_count": raw_needs_review_count,
        "accepted_to_candidate_source_ratio": accepted_to_candidate_source_ratio,
        "low_row_yield": low_row_yield,
        "source_status_counts": dict(sorted(source_status_counts.items())),
        "catalog_source_family_counts": dict(sorted(catalog_source_family_counts.items())),
        "accepted_source_family_counts": dict(sorted(accepted_source_family_counts.items())),
        "source_family_bias": source_family_bias["source_family_bias"],
        "source_family_bias_reason": source_family_bias["source_family_bias_reason"],
        "dominant_source_family": source_family_bias["dominant_source_family"],
        "false_positive_rejected_count": false_positive_rejected_count,
        "api_candidate_zero_reason": api_candidate_zero_reason,
        "probable_incomplete_catalog": probable_incomplete_catalog,
        **api_summary,
        "recommended_next_action": _programme_catalog_next_action(
            candidate_source_count=len(candidate_source_urls),
            accepted_row_count=len(rows),
            raw_needs_review_count=raw_needs_review_count,
            warning_count=warning_count,
            source_status_counts=source_status_counts,
            low_row_yield=low_row_yield,
            probable_incomplete_catalog=probable_incomplete_catalog,
            api_summary=api_summary,
            api_candidate_zero_reason=api_candidate_zero_reason,
            source_family_bias=bool(source_family_bias["source_family_bias"]),
            false_positive_rejected_count=false_positive_rejected_count,
        ),
        "duplicate_count": duplicate_count,
        "duplicate_names": duplicate_names,
        "by_programme_type": dict(sorted(programme_types.items())),
        "by_faculty_or_school": dict(sorted(faculties.items())),
        "parse_status_counts": dict(sorted(parse_statuses.items())),
        "sources_count": len(source_urls),
        "source_urls": source_urls,
        "manual_review_count": manual_review_count,
        "warning_count": warning_count,
        "note": "Programme catalog diagnostics summarize extracted catalog rows only; rejected candidate rows are not persisted as admissions facts.",
    }


def _template_completeness(
    data: AdmissionsData,
    coverage: dict[str, object],
    extraction_entries: list[object],
    source_strategy: object,
    missing_reasons: dict[str, object],
) -> dict[str, object]:
    found_fields = {str(item) for item in coverage.get("found", []) if item}
    missing_fields = {str(item) for item in coverage.get("missing", []) if item}
    attempts_by_field = _attempts_by_field(extraction_entries)
    source_plan_budget_skipped = _source_plan_budget_skipped_by_field(data.run.config.get("llm_source_plan"))

    fields: dict[str, object] = {}
    status_counts: Counter[str] = Counter()
    next_action_counts: Counter[str] = Counter()
    for field, _path in CORE_FIELDS:
        is_found = field in found_fields
        details = missing_reasons.get(field)
        if not isinstance(details, dict):
            details = {}
        attempts = attempts_by_field.get(field, [])
        status_flags = _template_status_flags(
            field=field,
            found=is_found,
            missing_reason=str(details.get("reason", "")),
            attempts=attempts,
            source_plan_budget_skipped=source_plan_budget_skipped,
        )
        next_action = _template_next_action(is_found, status_flags)
        for flag in status_flags:
            status_counts[flag] += 1
        next_action_counts[next_action] += 1
        fields[field] = {
            "found": is_found,
            "status": "found" if is_found else "missing",
            "status_flags": status_flags,
            "reason": "found" if is_found else details.get("reason", "manual_check_required"),
            "canonical_reason": "found" if is_found else details.get("canonical_reason", details.get("reason", "manual_check_required")),
            "action_target": "none" if is_found else details.get("action_target", "manual_review"),
            "capability": _field_capability_details(field),
            "attempts": len(attempts),
            "attempted_extractors": sorted({str(item.get("extractor", "unknown")) for item in attempts}),
            "source_urls": _template_source_urls(field, details, attempts, source_plan_budget_skipped),
            "next_action": next_action,
            "note": _template_field_note(is_found, status_flags),
        }

    programme_summary = data.run.config.get("programme_catalog_summary")
    if not isinstance(programme_summary, dict):
        programme_summary = _programme_catalog_summary(data, extraction_entries, source_strategy)
        data.run.config["programme_catalog_summary"] = programme_summary

    return {
        "fields_total": coverage.get("core_fields_total", len(CORE_FIELDS)),
        "found_count": coverage.get("found_count", len(found_fields)),
        "missing_count": coverage.get("missing_count", len(missing_fields)),
        "status_counts": dict(sorted(status_counts.items())),
        "next_action_counts": dict(sorted(next_action_counts.items())),
        "fields": fields,
        "programme_catalog": {
            "candidate_source_count": programme_summary.get("candidate_source_count", 0),
            "crawled_catalog_source_count": programme_summary.get("crawled_catalog_source_count", 0),
            "accepted_row_count": programme_summary.get("accepted_row_count", programme_summary.get("accepted_count", 0)),
            "raw_needs_review_count": programme_summary.get("raw_needs_review_count", 0),
            "accepted_to_candidate_source_ratio": programme_summary.get("accepted_to_candidate_source_ratio"),
            "api_catalog_candidate_count": programme_summary.get("api_catalog_candidate_count", 0),
            "api_response_count": programme_summary.get("api_response_count", 0),
            "api_page_count": programme_summary.get("api_page_count", 0),
            "api_accepted_row_count": programme_summary.get("api_accepted_row_count", 0),
            "api_rejected_row_count": programme_summary.get("api_rejected_row_count", 0),
            "api_total_count": programme_summary.get("api_total_count"),
            "api_pagination_complete": programme_summary.get("api_pagination_complete", False),
            "api_pagination_incomplete": programme_summary.get("api_pagination_incomplete", False),
            "api_filter_dimensions": programme_summary.get("api_filter_dimensions", {}),
            "api_filter_candidate_dimensions": programme_summary.get("api_filter_candidate_dimensions", {}),
            "api_filter_attempted_url_count": programme_summary.get("api_filter_attempted_url_count", 0),
            "api_filter_fetched_url_count": programme_summary.get("api_filter_fetched_url_count", 0),
            "api_filter_rejected_url_count": programme_summary.get("api_filter_rejected_url_count", 0),
            "api_filter_enumeration_budget_hit": programme_summary.get("api_filter_enumeration_budget_hit", False),
            "api_endpoint_candidate_count": programme_summary.get("api_endpoint_candidate_count", 0),
            "browser_network_candidate_count": programme_summary.get("browser_network_candidate_count", 0),
            "network_body_available_count": programme_summary.get("network_body_available_count", 0),
            "api_candidate_zero_reason": programme_summary.get("api_candidate_zero_reason"),
            "catalog_source_family_counts": programme_summary.get("catalog_source_family_counts", {}),
            "accepted_source_family_counts": programme_summary.get("accepted_source_family_counts", {}),
            "source_family_bias": programme_summary.get("source_family_bias", False),
            "false_positive_rejected_count": programme_summary.get("false_positive_rejected_count", 0),
            "html_fallback_used": programme_summary.get("html_fallback_used", False),
            "api_to_csv_ratio": programme_summary.get("api_to_csv_ratio"),
            "low_row_yield": programme_summary.get("low_row_yield", False),
            "source_status_counts": programme_summary.get("source_status_counts", {}),
            "probable_incomplete_catalog": programme_summary.get("probable_incomplete_catalog", False),
            "next_action": programme_summary.get("recommended_next_action", "none"),
        },
        "note": "Template completeness diagnostics describe this run's captured-source and extractor state; they do not prove the official site lacks a field.",
    }


def _programme_catalog_api_summary(data: AdmissionsData) -> dict[str, object]:
    raw_entries = data.run.config.get("programme_catalog_api_diagnostics")
    entries = [item for item in raw_entries if isinstance(item, dict)] if isinstance(raw_entries, list) else []
    discovery_summary = data.run.config.get("programme_catalog_api_discovery_summary")
    if not isinstance(discovery_summary, dict):
        discovery_summary = {}
    filter_summary = _programme_catalog_filter_summary(data)
    api_urls = {str(item.get("url")) for item in entries if isinstance(item.get("url"), str)}
    groups: dict[str, dict[str, object]] = {}
    for item in entries:
        key = _api_diagnostic_group_key(item)
        group = groups.setdefault(
            key,
            {
                "candidate_object_count": 0,
                "accepted_row_count": 0,
                "rejected_row_count": 0,
                "api_total_count": None,
                "api_page_count": 0,
                "complete_flag": False,
                "budget_hit": False,
                "entry_incomplete": False,
            },
        )
        group["candidate_object_count"] = _int_or_zero(group.get("candidate_object_count")) + _int_or_zero(item.get("candidate_object_count"))
        group["accepted_row_count"] = _int_or_zero(group.get("accepted_row_count")) + _int_or_zero(item.get("accepted_row_count"))
        group["rejected_row_count"] = _int_or_zero(group.get("rejected_row_count")) + _int_or_zero(item.get("rejected_row_count"))
        total_count = _int_or_none(item.get("api_total_count"))
        current_total = _int_or_none(group.get("api_total_count"))
        if total_count is not None:
            group["api_total_count"] = max(total_count, current_total or 0)
        group["api_page_count"] = max(_int_or_zero(group.get("api_page_count")), _int_or_zero(item.get("api_page_count")) or 1)
        group["complete_flag"] = bool(group.get("complete_flag")) or bool(item.get("api_pagination_complete"))
        group["budget_hit"] = bool(group.get("budget_hit")) or bool(item.get("api_pagination_budget_hit"))
        group["entry_incomplete"] = bool(group.get("entry_incomplete")) or bool(item.get("api_pagination_incomplete"))

    candidate_object_count = sum(_int_or_zero(group.get("candidate_object_count")) for group in groups.values())
    accepted_row_count = sum(_int_or_zero(group.get("accepted_row_count")) for group in groups.values())
    rejected_row_count = sum(_int_or_zero(group.get("rejected_row_count")) for group in groups.values())
    known_total_values = [_int_or_none(group.get("api_total_count")) for group in groups.values()]
    known_total_values = [value for value in known_total_values if value is not None]
    api_total_count = sum(known_total_values) if known_total_values else None
    page_count = sum(_int_or_zero(group.get("api_page_count")) for group in groups.values())
    incomplete = any(_api_group_incomplete(group) for group in groups.values())
    complete = bool(groups) and not incomplete and all(_api_group_complete(group) for group in groups.values())
    html_fallback_used = bool(data.programme_catalog) and any(row.source_url not in api_urls for row in data.programme_catalog)
    api_to_csv_ratio = round(accepted_row_count / len(data.programme_catalog), 3) if data.programme_catalog else None
    return {
        "api_catalog_candidate_count": candidate_object_count,
        "api_response_count": len(entries),
        "api_page_count": page_count,
        "api_accepted_row_count": accepted_row_count,
        "api_rejected_row_count": rejected_row_count,
        "api_total_count": api_total_count,
        "api_pagination_complete": complete,
        "api_pagination_incomplete": incomplete,
        "api_filter_dimensions": _api_filter_dimensions(entries),
        "api_endpoint_candidate_count": _int_or_zero(discovery_summary.get("api_catalog_candidate_count")),
        "browser_network_candidate_count": _int_or_zero(discovery_summary.get("browser_network_candidate_count")),
        "network_body_available_count": _int_or_zero(discovery_summary.get("network_body_available_count")),
        "captured_json_endpoint_count": _int_or_zero(discovery_summary.get("captured_json_count")),
        "api_endpoint_rejected_count": _int_or_zero(discovery_summary.get("rejected_count")),
        **filter_summary,
        "html_fallback_used": html_fallback_used,
        "api_to_csv_ratio": api_to_csv_ratio,
    }


def _programme_catalog_filter_summary(data: AdmissionsData) -> dict[str, object]:
    raw_outcomes = data.run.config.get("programme_catalog_api_filter_enumeration")
    outcomes = [item for item in raw_outcomes if isinstance(item, dict)] if isinstance(raw_outcomes, list) else []
    candidate_dimensions: dict[str, set[str]] = {}
    attempted_count = 0
    fetched_count = 0
    rejected_count = 0
    budget_hit = False
    for outcome in outcomes:
        raw_dimensions = outcome.get("filter_dimensions")
        if isinstance(raw_dimensions, dict):
            for key, values in raw_dimensions.items():
                if not isinstance(values, list):
                    continue
                bucket = candidate_dimensions.setdefault(str(key), set())
                bucket.update(str(value) for value in values if value)
        attempted = outcome.get("attempted_urls")
        fetched = outcome.get("fetched_urls")
        rejected = outcome.get("rejected_urls")
        attempted_count += len(attempted) if isinstance(attempted, list) else 0
        fetched_count += len(fetched) if isinstance(fetched, list) else 0
        rejected_count += len(rejected) if isinstance(rejected, list) else 0
        budget_hit = budget_hit or bool(outcome.get("budget_hit"))
    return {
        "api_filter_candidate_dimensions": {key: sorted(values) for key, values in sorted(candidate_dimensions.items())},
        "api_filter_attempted_url_count": attempted_count,
        "api_filter_fetched_url_count": fetched_count,
        "api_filter_rejected_url_count": rejected_count,
        "api_filter_enumeration_budget_hit": budget_hit,
    }


def _api_filter_dimensions(entries: list[dict[str, object]]) -> dict[str, list[str]]:
    dimensions: dict[str, set[str]] = {}
    for entry in entries:
        raw_dimensions = entry.get("api_filter_dimensions")
        if not isinstance(raw_dimensions, dict):
            continue
        for key, value in raw_dimensions.items():
            if value in (None, ""):
                continue
            dimensions.setdefault(str(key), set()).add(str(value))
    return {key: sorted(values) for key, values in sorted(dimensions.items())}


def _api_group_incomplete(group: dict[str, object]) -> bool:
    if group.get("budget_hit"):
        return True
    total_count = _int_or_none(group.get("api_total_count"))
    accepted_row_count = _int_or_zero(group.get("accepted_row_count"))
    if total_count is not None:
        return accepted_row_count < total_count
    return bool(group.get("entry_incomplete")) and not bool(group.get("complete_flag"))


def _api_group_complete(group: dict[str, object]) -> bool:
    total_count = _int_or_none(group.get("api_total_count"))
    accepted_row_count = _int_or_zero(group.get("accepted_row_count"))
    if total_count is not None:
        return accepted_row_count >= total_count
    return bool(group.get("complete_flag"))


def _api_diagnostic_group_key(entry: dict[str, object]) -> str:
    group = entry.get("pagination_group_url")
    if isinstance(group, str) and group:
        return group
    url = entry.get("url")
    if not isinstance(url, str):
        return "unknown"
    parsed = urlparse(url)
    filtered = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if _normalise_query_key(key) not in {"page", "pagenumber", "offset", "skip", "cursor", "after"}
    ]
    return urlunparse(parsed._replace(query=urlencode(filtered, doseq=True)))


def _programme_catalog_candidate_source_urls(data: AdmissionsData, extraction_entries: object, source_strategy: object) -> list[str]:
    urls: set[str] = set()
    for record in data.discovered_categories:
        if record.category in {PageCategory.PROGRAMME_LIST, PageCategory.PROGRAMME_PREREQUISITES}:
            urls.add(record.source_url)
    if isinstance(source_strategy, list):
        for item in source_strategy:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category", ""))
            url = item.get("url")
            if isinstance(url, str) and category in {str(PageCategory.PROGRAMME_LIST), str(PageCategory.PROGRAMME_PREREQUISITES)}:
                urls.add(url)
    if isinstance(extraction_entries, list):
        for entry in extraction_entries:
            if not isinstance(entry, dict):
                continue
            raw_attempts = entry.get("attempts")
            if not isinstance(raw_attempts, list):
                continue
            if any(isinstance(attempt, dict) and attempt.get("field") == "programme_catalog" for attempt in raw_attempts):
                url = entry.get("url")
                if isinstance(url, str):
                    urls.add(url)
    urls.update(row.source_url for row in data.programme_catalog if row.source_url)
    return sorted(urls)


def _programme_catalog_source_status_counts(candidate_source_urls: list[str], extraction_entries: object, source_strategy: object) -> Counter[str]:
    candidate_urls = set(candidate_source_urls)
    statuses_by_url: dict[str, set[str]] = {url: set() for url in candidate_urls}
    if isinstance(source_strategy, list):
        for item in source_strategy:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            category = item.get("category")
            if not isinstance(url, str) or (url not in candidate_urls and not _is_programme_catalog_category(category)):
                continue
            statuses = statuses_by_url.setdefault(url, set())
            for key in ("catalog_source_status", "programme_catalog_status", "programme_catalog_source_status"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    statuses.add(value)
            strategy = item.get("strategy")
            if strategy in {"blocked_or_challenge", "application_portal"}:
                statuses.add("source_acquisition_issue")
            elif strategy == "json_api":
                statuses.add("api_capture")
            elif strategy == "html_page":
                statuses.add("html_candidate")
            crawl_status = item.get("crawl_status")
            if isinstance(crawl_status, str) and crawl_status in {"budget_skipped", "not_crawled"}:
                statuses.add(crawl_status)

    if isinstance(extraction_entries, list):
        for entry in extraction_entries:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str):
                continue
            attempts = _programme_catalog_attempts(entry)
            if not attempts:
                continue
            statuses = statuses_by_url.setdefault(url, set())
            if any(_attempt_record_count(attempt) > 0 for attempt in attempts):
                statuses.add("parsed_rows")
            else:
                statuses.add("parsed_zero_rows")
            source_acquisition_status = entry.get("source_acquisition_status")
            if source_acquisition_status in {"blocked_or_challenge", "application_portal"}:
                statuses.add("source_acquisition_issue")

    counts: Counter[str] = Counter()
    for statuses in statuses_by_url.values():
        if not statuses:
            counts["candidate_source"] += 1
            continue
        for status in statuses:
            counts[status] += 1
    return counts


def _source_family_counts(urls: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for url in urls:
        family = _source_family(url)
        if family:
            counts[family] += 1
    return counts


def _source_family(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or "unknown"
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return host
    if len(segments) == 1:
        return f"{host}/{segments[0]}"
    return f"{host}/{segments[0]}/{segments[1]}"


def _source_family_bias(
    *,
    catalog_source_family_counts: Counter[str],
    accepted_source_family_counts: Counter[str],
    accepted_row_count: int,
) -> dict[str, object]:
    if accepted_row_count < 5 or len(catalog_source_family_counts) < 2 or not accepted_source_family_counts:
        return {
            "source_family_bias": False,
            "source_family_bias_reason": None,
            "dominant_source_family": None,
        }
    dominant_family, dominant_count = accepted_source_family_counts.most_common(1)[0]
    share = dominant_count / accepted_row_count
    is_biased = share >= 0.75
    return {
        "source_family_bias": is_biased,
        "source_family_bias_reason": (
            f"{dominant_count}/{accepted_row_count} accepted rows came from {dominant_family}"
            if is_biased
            else None
        ),
        "dominant_source_family": dominant_family if is_biased else None,
    }


def _false_positive_rejected_count(extraction_entries: object) -> int:
    if not isinstance(extraction_entries, list):
        return 0
    count = 0
    for entry in extraction_entries:
        if not isinstance(entry, dict):
            continue
        for attempt in _programme_catalog_attempts(entry):
            haystack = " ".join(
                str(attempt.get(key, ""))
                for key in ("status", "reason", "extractor", "message", "rejection_reason")
            ).lower()
            if "false_positive" in haystack or "course_table" in haystack:
                count += max(1, _attempt_record_count(attempt))
    return count


def _api_candidate_zero_reason(
    data: AdmissionsData,
    *,
    candidate_source_count: int,
    source_status_counts: Counter[str],
) -> str | None:
    discovery_summary = data.run.config.get("programme_catalog_api_discovery_summary")
    if isinstance(discovery_summary, dict) and _int_or_zero(discovery_summary.get("api_catalog_candidate_count")) > 0:
        return None
    static_asset_discovery = data.run.config.get("programme_catalog_static_asset_discovery")
    if isinstance(static_asset_discovery, dict) and static_asset_discovery.get("triggered"):
        candidate_assets = static_asset_discovery.get("candidate_asset_urls")
        fetched_assets = static_asset_discovery.get("fetched_asset_urls")
        rejected_assets = static_asset_discovery.get("rejected_asset_urls")
        endpoint_hint_count = _int_or_zero(static_asset_discovery.get("endpoint_hint_count"))
        if isinstance(fetched_assets, list) and fetched_assets and endpoint_hint_count == 0:
            return "static_asset_no_endpoint_hints"
        if isinstance(candidate_assets, list) and candidate_assets and isinstance(rejected_assets, list) and rejected_assets and not fetched_assets:
            return "static_asset_fetch_failed"
        if isinstance(candidate_assets, list) and not candidate_assets:
            return "static_asset_no_script_assets"
    browser_capture = data.run.config.get("programme_catalog_browser_capture")
    if isinstance(browser_capture, dict) and browser_capture.get("triggered"):
        captured = browser_capture.get("captured_urls")
        rejected = browser_capture.get("rejected_urls")
        network_response_count = _int_or_zero(browser_capture.get("network_response_count"))
        if isinstance(captured, list) and captured and network_response_count == 0:
            return "browser_capture_no_network_json"
        if isinstance(rejected, list) and rejected and not captured:
            return "browser_capture_failed"
        if network_response_count > 0:
            return "browser_capture_no_catalog_api_candidate"
    if source_status_counts.get("dynamic_shell_no_rows"):
        return "browser_network_capture_not_triggered"
    if candidate_source_count == 0:
        return "no_catalog_source"
    return "no_api_endpoint_hints"


def _programme_catalog_attempts(entry: dict[str, object]) -> list[dict[str, object]]:
    attempts = entry.get("attempts")
    if not isinstance(attempts, list):
        return []
    return [attempt for attempt in attempts if isinstance(attempt, dict) and attempt.get("field") == "programme_catalog"]


def _attempt_record_count(attempt: dict[str, object]) -> int:
    value = attempt.get("record_count", 0)
    return value if isinstance(value, int) else 0


def _is_programme_catalog_category(value: object) -> bool:
    return str(value) in {str(PageCategory.PROGRAMME_LIST), str(PageCategory.PROGRAMME_PREREQUISITES)}


def _programme_catalog_source_ratio(*, candidate_source_count: int, accepted_row_count: int) -> float | None:
    if candidate_source_count == 0:
        return None
    return round(accepted_row_count / candidate_source_count, 3)


def _programme_catalog_low_row_yield(*, candidate_source_count: int, accepted_row_count: int) -> bool:
    if candidate_source_count >= 8 and accepted_row_count <= max(3, candidate_source_count // 3):
        return True
    if candidate_source_count >= 4 and accepted_row_count <= 2:
        return True
    return False


def _probable_incomplete_catalog(
    *,
    candidate_source_count: int,
    accepted_row_count: int,
    raw_needs_review_count: int,
    source_status_counts: Counter[str],
    low_row_yield: bool,
) -> bool:
    if candidate_source_count > 0 and accepted_row_count == 0:
        return True
    if low_row_yield:
        return True
    if source_status_counts.get("dynamic_shell_no_rows") or _many_zero_row_catalog_sources(candidate_source_count, source_status_counts):
        return True
    if source_status_counts.get("budget_skipped") or source_status_counts.get("not_crawled") or source_status_counts.get("source_acquisition_issue"):
        return True
    if accepted_row_count > 0 and raw_needs_review_count > 0:
        return True
    return False


def _programme_catalog_next_action(
    *,
    candidate_source_count: int,
    accepted_row_count: int,
    raw_needs_review_count: int,
    warning_count: int,
    source_status_counts: Counter[str],
    low_row_yield: bool,
    probable_incomplete_catalog: bool,
    api_summary: dict[str, object] | None = None,
    api_candidate_zero_reason: str | None = None,
    source_family_bias: bool = False,
    false_positive_rejected_count: int = 0,
) -> str:
    if api_summary and api_summary.get("api_pagination_incomplete"):
        return "expand_api_pagination"
    if api_summary and api_summary.get("api_filter_enumeration_budget_hit"):
        return "enumerate_api_filters"
    if (
        api_summary
        and api_summary.get("api_filter_candidate_dimensions")
        and api_summary.get("api_filter_attempted_url_count")
        and not api_summary.get("api_filter_fetched_url_count")
    ):
        return "enumerate_api_filters"
    if api_summary and api_summary.get("api_response_count") and not api_summary.get("api_accepted_row_count") and not accepted_row_count:
        return "implement_api_field_mapping"
    if api_summary and api_summary.get("api_endpoint_candidate_count") and not api_summary.get("api_response_count") and not accepted_row_count:
        return "discover_public_catalog_api"
    if api_candidate_zero_reason == "browser_capture_no_network_json":
        return "discover_public_catalog_api"
    if api_candidate_zero_reason == "browser_capture_failed":
        return "capture_browser_network_api"
    if api_candidate_zero_reason == "browser_capture_no_catalog_api_candidate":
        return "inspect_api_response_body"
    if api_candidate_zero_reason in {
        "static_asset_no_endpoint_hints",
        "static_asset_fetch_failed",
        "static_asset_no_script_assets",
    }:
        return "discover_public_catalog_api"
    if source_status_counts.get("dynamic_shell_no_rows") and not accepted_row_count:
        return "capture_browser_network_api"
    if source_status_counts.get("budget_skipped") or source_status_counts.get("not_crawled"):
        return "increase_catalog_crawl_budget"
    if not candidate_source_count:
        return "improve_source_acquisition"
    if source_status_counts.get("source_acquisition_issue"):
        return "improve_source_acquisition"
    if not accepted_row_count:
        return "improve_table_segmentation"
    if false_positive_rejected_count:
        return "tighten_catalog_false_positive_filters"
    if source_family_bias:
        return "review_source_family_bias"
    if low_row_yield or _many_zero_row_catalog_sources(candidate_source_count, source_status_counts):
        return "improve_table_segmentation"
    if raw_needs_review_count:
        if warning_count >= accepted_row_count:
            return "tighten_catalog_false_positive_filters"
        return "manual_review_raw_rows"
    if probable_incomplete_catalog:
        return "manual_review_raw_rows"
    return "none"


def _many_zero_row_catalog_sources(candidate_source_count: int, source_status_counts: Counter[str]) -> bool:
    zero_row_sources = source_status_counts.get("parsed_zero_rows", 0)
    if candidate_source_count < 2 or zero_row_sources < 2:
        return False
    return zero_row_sources >= max(2, candidate_source_count // 2)


def _normalise_programme_name(name: str) -> str:
    return " ".join(name.casefold().split())


def _normalise_query_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) else 0


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _attempts_by_field(extraction_entries: list[object]) -> dict[str, list[dict[str, object]]]:
    attempts_by_field: dict[str, list[dict[str, object]]] = {}
    for source in extraction_entries:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        source_acquisition_status = source.get("source_acquisition_status")
        raw_attempts = source.get("attempts")
        if not isinstance(raw_attempts, list):
            continue
        for attempt in raw_attempts:
            if not isinstance(attempt, dict):
                continue
            field = str(attempt.get("field", "unknown"))
            enriched = dict(attempt)
            if isinstance(url, str) and url:
                enriched["source_url"] = url
            if isinstance(source_acquisition_status, str) and source_acquisition_status:
                enriched["source_acquisition_status"] = source_acquisition_status
            attempts_by_field.setdefault(field, []).append(enriched)
    return attempts_by_field


def _template_status_flags(
    *,
    field: str,
    found: bool,
    missing_reason: str,
    attempts: list[dict[str, object]],
    source_plan_budget_skipped: dict[str, list[str]],
) -> list[str]:
    if found:
        return ["source_found"]
    if source_plan_budget_skipped.get(field):
        return ["source_budget_skipped"]
    if missing_reason in {"blocked_or_challenge", "source_not_crawled"}:
        return ["source_blocked_or_challenge"]
    if missing_reason in {"portal_or_login_required", "application_portal_unreachable"}:
        return ["portal_or_login_required"]
    if missing_reason == "attempted_no_match":
        return ["source_found", "attempted_no_match"]
    if missing_reason in {"context_gate_failed", "undergraduate_context_gate_failed"}:
        return ["source_found", "context_gate_failed"]
    if missing_reason == "raw_needs_manual_review":
        return ["source_found", "raw_needs_manual_review"]
    if not attempts or missing_reason in {"source_not_found", "not_attempted"}:
        return ["source_not_found", "extractor_not_attempted"]
    return ["manual_check_required"]


def _template_next_action(found: bool, status_flags: list[str]) -> str:
    if found:
        return "none"
    flags = set(status_flags)
    if "source_blocked_or_challenge" in flags or "source_budget_skipped" in flags or "source_not_found" in flags:
        return "improve_source_discovery_or_llm_source_navigation"
    if "attempted_no_match" in flags or "context_gate_failed" in flags or "extractor_not_attempted" in flags:
        return "improve_extractor_or_context_gate"
    if "raw_needs_manual_review" in flags:
        return "manual_review_or_parser"
    if "portal_or_login_required" in flags:
        return "manual_check_required"
    return "manual_check_required"


def _template_source_urls(
    field: str,
    details: dict[str, object],
    attempts: list[dict[str, object]],
    source_plan_budget_skipped: dict[str, list[str]],
) -> list[str]:
    if source_plan_budget_skipped.get(field):
        return source_plan_budget_skipped[field][:10]
    urls = details.get("source_urls")
    if isinstance(urls, list) and urls:
        return [str(url) for url in urls[:10]]
    return sorted({str(item.get("source_url")) for item in attempts if item.get("source_url")})[:10]


def _template_field_note(found: bool, status_flags: list[str]) -> str:
    if found:
        return "A value for this template field was extracted with evidence in this run."
    if "source_blocked_or_challenge" in status_flags:
        return "A captured source looked blocked/challenge-like, so this run did not get usable official text for the field."
    if "source_budget_skipped" in status_flags:
        return "A validated candidate source was not crawled within this run's page budget."
    if "source_not_found" in status_flags:
        return "No captured source produced a field-specific extractor attempt in this run."
    if "attempted_no_match" in status_flags:
        return "A field extractor ran on captured official text but did not match a supported pattern."
    if "context_gate_failed" in status_flags:
        return "Captured text did not pass the deterministic context gate for this field."
    if "raw_needs_manual_review" in status_flags:
        return "Captured text produced a raw candidate that needs parser improvement or manual review before structured use."
    if "portal_or_login_required" in status_flags:
        return "Relevant diagnostics point to a portal/login flow that this crawler cannot enter."
    return "The field remains unresolved and needs manual review."


def _source_plan_budget_skipped_by_field(source_plan: object) -> dict[str, list[str]]:
    if not isinstance(source_plan, dict):
        return {}
    budget_skipped = source_plan.get("budget_skipped_candidate_urls")
    if not isinstance(budget_skipped, list):
        return {}
    skipped = {str(url) for url in budget_skipped if isinstance(url, str) and url}
    if not skipped:
        return {}
    out: dict[str, list[str]] = {}
    accepted = source_plan.get("accepted_candidate_urls")
    if not isinstance(accepted, list):
        return {"programmes": sorted(skipped)}
    for item in accepted:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or url not in skipped:
            continue
        fields = _fields_for_candidate_category(str(item.get("expected_category", "")))
        for field in fields:
            out.setdefault(field, []).append(url)
    return {field: sorted(set(urls)) for field, urls in out.items()}


def _fields_for_candidate_category(category: str) -> tuple[str, ...]:
    mapping = {
        str(PageCategory.PROGRAMME_LIST): ("programmes",),
        str(PageCategory.PROGRAMME_PREREQUISITES): ("programmes", "accepted_qualifications"),
        str(PageCategory.UNDERGRADUATE_ADMISSIONS): ("undergraduate_application_entry", "application_periods", "required_documents"),
        str(PageCategory.APPLICATION_DEADLINES): ("application_periods",),
        str(PageCategory.INTERNATIONAL_REQUIREMENTS): ("english_requirements", "accepted_qualifications"),
        str(PageCategory.ACCEPTED_QUALIFICATIONS): ("accepted_qualifications",),
        str(PageCategory.FEES): ("fees",),
        str(PageCategory.SCHOLARSHIPS): ("scholarships",),
        str(PageCategory.CONTACT): ("contacts",),
    }
    return mapping.get(category, ("programmes",))


def _missing_reasons(coverage: dict[str, object], extraction_entries: list[object], source_strategy: object) -> dict[str, object]:
    missing = coverage.get("missing")
    if not isinstance(missing, list):
        return {}

    source_strategy_by_url = _source_strategy_by_url(source_strategy)
    attempts_by_field: dict[str, list[dict[str, object]]] = {}
    for source in extraction_entries:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        source_acquisition_status = source.get("source_acquisition_status")
        if not isinstance(source_acquisition_status, str) and isinstance(url, str):
            source_acquisition_status = source_strategy_by_url.get(url)
        raw_attempts = source.get("attempts")
        if not isinstance(raw_attempts, list):
            continue
        for attempt in raw_attempts:
            if not isinstance(attempt, dict):
                continue
            field = str(attempt.get("field", "unknown"))
            enriched = dict(attempt)
            if isinstance(url, str) and url:
                enriched["source_url"] = url
            if isinstance(source_acquisition_status, str) and source_acquisition_status:
                enriched["source_acquisition_status"] = source_acquisition_status
            attempts_by_field.setdefault(field, []).append(enriched)

    out: dict[str, object] = {}
    for field in missing:
        field_name = str(field)
        attempts = attempts_by_field.get(field_name, [])
        field_source_entries = _source_strategy_entries_for_field(source_strategy, field_name)
        field_source_urls = _urls_for_source_entries(field_source_entries)
        challenge_urls = _urls_for_source_entries(field_source_entries, {"blocked_or_challenge"})
        portal_urls = _urls_for_source_strategies(source_strategy, {"application_portal"})
        canonical_reason, detail_reason = _missing_reason_for_attempts(attempts, challenge_urls, portal_urls, field_source_urls)
        legacy_reason = _legacy_missing_reason_for(canonical_reason, detail_reason)
        source_urls = sorted({str(item.get("source_url")) for item in attempts if item.get("source_url")})
        if not source_urls and canonical_reason == "blocked_or_challenge":
            source_urls = challenge_urls
        elif not source_urls and canonical_reason == "portal_or_login_required":
            source_urls = portal_urls
        elif not source_urls and canonical_reason != "source_not_found":
            source_urls = field_source_urls
        out[field_name] = {
            "reason": legacy_reason,
            "canonical_reason": canonical_reason,
            "legacy_reason": legacy_reason,
            "detail_reason": detail_reason,
            "action_target": MISSING_REASON_ACTION_TARGETS.get(canonical_reason, "manual_review"),
            "attempts": len(attempts),
            "attempted_extractors": sorted({str(item.get("extractor", "unknown")) for item in attempts}),
            "source_urls": source_urls[:10],
            "capability": _field_capability_details(field_name),
            "note": _missing_reason_note(canonical_reason),
        }
    return out


def _legacy_missing_reason_for(canonical_reason: str, detail_reason: str) -> str:
    if canonical_reason == "context_gate_failed" and detail_reason == "undergraduate_context_gate_failed":
        return "undergraduate_context_gate_failed"
    return LEGACY_MISSING_REASON_BY_CANONICAL.get(canonical_reason, canonical_reason)


def _missing_reason_for_attempts(
    attempts: list[dict[str, object]],
    challenge_urls: list[str],
    portal_urls: list[str],
    field_source_urls: list[str],
) -> tuple[str, str]:
    if not attempts:
        if challenge_urls:
            return "blocked_or_challenge", "source_not_crawled"
        if portal_urls:
            return "portal_or_login_required", "application_portal_unreachable"
        if not field_source_urls:
            return "source_not_found", "not_attempted"
        return "manual_check_required", "extractor_not_attempted"
    if _all_attempts_from_blocked_sources(attempts, challenge_urls):
        return "blocked_or_challenge", "source_not_crawled"
    usable_attempts = [item for item in attempts if not _is_blocked_source_attempt(item, challenge_urls)]
    if any(item.get("parse_status") == "raw_needs_manual_review" or item.get("reason") == "raw_needs_manual_review" for item in usable_attempts):
        return "raw_needs_manual_review", "raw_needs_manual_review"
    if any(item.get("status") == "no_match" for item in usable_attempts):
        return "attempted_no_match", "attempted_no_match"
    if any(item.get("reason") == "context_gate_failed" for item in usable_attempts):
        return "context_gate_failed", "context_gate_failed"
    if any(item.get("reason") == "undergraduate_context_gate_failed" for item in usable_attempts):
        return "context_gate_failed", "undergraduate_context_gate_failed"
    if portal_urls:
        return "portal_or_login_required", "application_portal_unreachable"
    if any(item.get("status") == "skipped" for item in attempts):
        return "manual_check_required", "skipped_or_inconclusive"
    return "manual_check_required", "inconclusive"


def _source_strategy_by_url(source_strategy: object) -> dict[str, str]:
    if not isinstance(source_strategy, list):
        return {}
    out: dict[str, str] = {}
    for item in source_strategy:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        strategy = item.get("strategy")
        if isinstance(url, str) and url and isinstance(strategy, str) and strategy:
            out[url] = strategy
    return out


def _source_strategy_entries_for_field(source_strategy: object, field: str) -> list[dict[str, object]]:
    if not isinstance(source_strategy, list):
        return []
    capability = FIELD_CAPABILITY_BY_FIELD.get(field)
    if capability is None:
        return []
    categories = {str(category) for category in capability.discovery_categories}
    entries: list[dict[str, object]] = []
    for item in source_strategy:
        if not isinstance(item, dict):
            continue
        category = item.get("category")
        if isinstance(category, str) and category in categories:
            entries.append(item)
    return entries


def _urls_for_source_entries(entries: list[dict[str, object]], strategies: set[str] | None = None) -> list[str]:
    urls: list[str] = []
    for item in entries:
        if strategies is not None and item.get("strategy") not in strategies:
            continue
        url = item.get("url")
        if isinstance(url, str) and url:
            urls.append(url)
    return sorted(set(urls))


def _all_attempts_from_blocked_sources(attempts: list[dict[str, object]], challenge_urls: list[str]) -> bool:
    return bool(attempts) and all(_is_blocked_source_attempt(item, challenge_urls) for item in attempts)


def _is_blocked_source_attempt(attempt: dict[str, object], challenge_urls: list[str]) -> bool:
    if attempt.get("source_acquisition_status") == "blocked_or_challenge":
        return True
    source_url = attempt.get("source_url")
    return isinstance(source_url, str) and source_url in challenge_urls


def _urls_for_source_strategies(source_strategy: object, strategies: set[str]) -> list[str]:
    if not isinstance(source_strategy, list):
        return []
    urls: list[str] = []
    for item in source_strategy:
        if not isinstance(item, dict) or item.get("strategy") not in strategies:
            continue
        url = item.get("url")
        if isinstance(url, str) and url:
            urls.append(url)
    return sorted(set(urls))


def _missing_reason_note(reason: str) -> str:
    notes = {
        "source_not_found": "No captured source matched this field's capability categories in this run.",
        "blocked_or_challenge": "A field-relevant captured source was blocked/challenge content, so extractors did not receive usable official page text.",
        "attempted_no_match": "At least one extractor ran on captured sources but did not match a supported pattern.",
        "context_gate_failed": "Captured sources did not pass the field-specific context gate.",
        "raw_needs_manual_review": "A captured source produced a raw candidate that needs manual review or parser improvement before structured use.",
        "portal_or_login_required": "Relevant source diagnostics indicate an application portal that this crawler cannot enter.",
        "manual_check_required": "The field remains missing after skipped or inconclusive extraction attempts.",
    }
    return notes.get(reason, "The field remains missing and needs manual review.")


def inferred_allowed_domain(seed_url: str) -> str | None:
    host = urlparse(seed_url).netloc.lower()
    if not host:
        return None
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return host
    if len(parts[-1]) == 2 and parts[-2] in {"ac", "edu", "com", "org", "net", "gov"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _coverage(data: AdmissionsData) -> dict[str, object]:
    found: list[str] = []
    missing: list[str] = []
    values = {
        "undergraduate_application_entry": not data.admissions.undergraduate_application_entry.is_unknownish,
        "application_periods": bool(data.admissions.application_periods),
        "english_requirements": bool(data.admissions.english_requirements),
        "accepted_qualifications": bool(data.admissions.accepted_qualifications),
        "required_documents": bool(data.admissions.required_documents) and not all(record.value.is_unknownish for record in data.admissions.required_documents),
        "programmes": bool(data.programmes),
        "fees": bool(data.fees),
        "scholarships": bool(data.scholarships),
        "contacts": bool(data.contacts),
    }
    for key, _path in CORE_FIELDS:
        if values[key]:
            found.append(key)
        else:
            missing.append(key)
    total = len(CORE_FIELDS)
    return {
        "core_fields_total": total,
        "found_count": len(found),
        "missing_count": len(missing),
        "found": found,
        "missing": missing,
        "coverage_ratio": round(len(found) / total, 3),
        "note": "Coverage reports whether core fields were found; overall confidence reports evidence/conflict quality for extracted claims.",
    }
