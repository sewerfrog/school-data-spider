"""Run diagnostics for coverage and source strategy reporting."""

from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

from university_admissions_crawler.crawler.filters import looks_like_blocked_or_challenge_source
from university_admissions_crawler.extractor.schema import AdmissionsData, PageCategory, SourceType, WarningCode, WarningRecord


CORE_FIELDS: tuple[tuple[str, str], ...] = (
    ("undergraduate_application_entry", "/admissions/undergraduate_application_entry"),
    ("application_periods", "/admissions/application_periods"),
    ("english_requirements", "/admissions/english_requirements"),
    ("accepted_qualifications", "/admissions/accepted_qualifications"),
    ("required_documents", "/admissions/required_documents"),
    ("programmes", "/programmes"),
    ("fees", "/fees"),
    ("scholarships", "/scholarships"),
    ("contacts", "/contacts"),
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

    coverage = _coverage(data)
    source_strategy = data.run.config.get("source_strategy", [])
    summary = Counter(item.get("strategy", "unknown") for item in source_strategy if isinstance(item, dict))
    data.run.config["coverage"] = coverage
    data.run.config["source_strategy_summary"] = dict(sorted(summary.items()))
    extraction_diagnostics = data.run.config.get("extraction_diagnostics")
    data.run.config["programme_catalog_summary"] = _programme_catalog_summary(data, extraction_diagnostics, source_strategy)
    classification_assist = data.run.config.get("classification_assist")
    if isinstance(classification_assist, list):
        data.run.config["classification_assist_summary"] = _classification_assist_summary(classification_assist)
    if isinstance(extraction_diagnostics, list):
        data.run.config["extraction_diagnostics_summary"] = _extraction_diagnostics_summary(extraction_diagnostics)
        data.run.config["missing_reasons"] = _missing_reasons(coverage, extraction_diagnostics, source_strategy)
    attach_template_completeness(data)
    if coverage["missing"]:
        data.warnings.append(
            WarningRecord(
                WarningCode.NEEDS_MANUAL_CHECK,
                "Some core undergraduate admissions fields were not found; review coverage.missing.",
                field="/run/config/coverage",
            )
        )
    if summary.get("blocked_or_challenge") or summary.get("application_portal"):
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
    data.run.config["template_completeness"] = _template_completeness(data, coverage, extraction_diagnostics, source_strategy, missing_reasons)
    return data


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
    probable_incomplete_catalog = _probable_incomplete_catalog(
        candidate_source_count=len(candidate_source_urls),
        accepted_row_count=len(rows),
        raw_needs_review_count=raw_needs_review_count,
    )
    return {
        "candidate_count": len(rows),
        "accepted_count": len(rows),
        "rejected_count": 0,
        "candidate_source_count": len(candidate_source_urls),
        "candidate_source_urls": candidate_source_urls,
        "crawled_catalog_source_count": len(crawled_catalog_source_urls),
        "crawled_catalog_source_urls": crawled_catalog_source_urls,
        "accepted_row_count": len(rows),
        "raw_needs_review_count": raw_needs_review_count,
        "probable_incomplete_catalog": probable_incomplete_catalog,
        "recommended_next_action": _programme_catalog_next_action(len(candidate_source_urls), len(rows), raw_needs_review_count, probable_incomplete_catalog),
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
            "probable_incomplete_catalog": programme_summary.get("probable_incomplete_catalog", False),
            "next_action": programme_summary.get("recommended_next_action", "none"),
        },
        "note": "Template completeness diagnostics describe this run's captured-source and extractor state; they do not prove the official site lacks a field.",
    }


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


def _probable_incomplete_catalog(*, candidate_source_count: int, accepted_row_count: int, raw_needs_review_count: int) -> bool:
    if candidate_source_count > 0 and accepted_row_count == 0:
        return True
    if accepted_row_count > 0 and raw_needs_review_count > 0:
        return True
    return False


def _programme_catalog_next_action(candidate_source_count: int, accepted_row_count: int, raw_needs_review_count: int, probable_incomplete_catalog: bool) -> str:
    if not candidate_source_count:
        return "improve_source_discovery"
    if not accepted_row_count:
        return "improve_programme_catalog_extractor"
    if raw_needs_review_count:
        return "manual_review_or_catalog_parser"
    if probable_incomplete_catalog:
        return "manual_check_required"
    return "none"


def _normalise_programme_name(name: str) -> str:
    return " ".join(name.casefold().split())


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
    if missing_reason == "source_not_crawled":
        return ["source_blocked_or_challenge"]
    if missing_reason == "application_portal_unreachable":
        return ["portal_or_login_required"]
    if missing_reason == "attempted_no_match":
        return ["source_found", "attempted_no_match"]
    if missing_reason in {"context_gate_failed", "undergraduate_context_gate_failed"}:
        return ["source_found", "context_gate_failed"]
    if not attempts or missing_reason == "not_attempted":
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

    challenge_urls = _urls_for_source_strategies(source_strategy, {"blocked_or_challenge"})
    portal_urls = _urls_for_source_strategies(source_strategy, {"application_portal"})
    out: dict[str, object] = {}
    for field in missing:
        field_name = str(field)
        attempts = attempts_by_field.get(field_name, [])
        reason = _missing_reason_for_attempts(attempts, challenge_urls, portal_urls)
        source_urls = sorted({str(item.get("source_url")) for item in attempts if item.get("source_url")})
        if not source_urls and reason == "source_not_crawled":
            source_urls = challenge_urls
        elif not source_urls and reason == "application_portal_unreachable":
            source_urls = portal_urls
        out[field_name] = {
            "reason": reason,
            "attempts": len(attempts),
            "attempted_extractors": sorted({str(item.get("extractor", "unknown")) for item in attempts}),
            "source_urls": source_urls[:10],
            "note": _missing_reason_note(reason),
        }
    return out


def _missing_reason_for_attempts(attempts: list[dict[str, object]], challenge_urls: list[str], portal_urls: list[str]) -> str:
    if not attempts:
        if challenge_urls:
            return "source_not_crawled"
        return "application_portal_unreachable" if portal_urls else "not_attempted"
    if _all_attempts_from_blocked_sources(attempts, challenge_urls):
        return "source_not_crawled"
    usable_attempts = [item for item in attempts if not _is_blocked_source_attempt(item, challenge_urls)]
    if any(item.get("status") == "no_match" for item in usable_attempts):
        return "attempted_no_match"
    if any(item.get("reason") == "context_gate_failed" for item in usable_attempts):
        return "context_gate_failed"
    if any(item.get("reason") == "undergraduate_context_gate_failed" for item in usable_attempts):
        return "undergraduate_context_gate_failed"
    if portal_urls:
        return "application_portal_unreachable"
    if any(item.get("status") == "skipped" for item in attempts):
        return "manual_check_required"
    return "manual_check_required"


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
        "not_attempted": "No extractor attempt was recorded for this missing field in the captured sources.",
        "source_not_crawled": "Captured source was blocked/challenge content, so extractors did not receive usable official page text.",
        "attempted_no_match": "At least one extractor ran on captured sources but did not match a supported pattern.",
        "context_gate_failed": "Captured sources did not pass the field-specific context gate.",
        "undergraduate_context_gate_failed": "Captured sources did not pass the undergraduate admissions context gate.",
        "application_portal_unreachable": "Relevant source diagnostics indicate an application portal that this crawler cannot enter.",
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
