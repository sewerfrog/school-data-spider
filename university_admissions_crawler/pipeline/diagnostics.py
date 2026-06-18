"""Run diagnostics for coverage and source strategy reporting."""

from __future__ import annotations

from collections import Counter
from urllib.parse import urlparse

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

CHALLENGE_TERMS = (
    "captcha",
    "cloudflare",
    "access denied",
    "verify you are human",
    "enable javascript",
    "blocked",
)


def source_strategy_for(source_type: SourceType, url: str, title: str | None, text: str, category: PageCategory | None = None) -> str:
    """Return a coarse strategy label for report diagnostics."""

    url_title = f"{url} {title or ''}".lower()
    text_lower = text.lower()
    if any(term in url_title for term in CHALLENGE_TERMS) or any(term in text_lower[:1200] for term in CHALLENGE_TERMS):
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
    classification_assist = data.run.config.get("classification_assist")
    if isinstance(classification_assist, list):
        data.run.config["classification_assist_summary"] = _classification_assist_summary(classification_assist)
    extraction_diagnostics = data.run.config.get("extraction_diagnostics")
    if isinstance(extraction_diagnostics, list):
        data.run.config["extraction_diagnostics_summary"] = _extraction_diagnostics_summary(extraction_diagnostics)
        data.run.config["missing_reasons"] = _missing_reasons(coverage, extraction_diagnostics, source_strategy)
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


def _missing_reasons(coverage: dict[str, object], extraction_entries: list[object], source_strategy: object) -> dict[str, object]:
    missing = coverage.get("missing")
    if not isinstance(missing, list):
        return {}

    attempts_by_field: dict[str, list[dict[str, object]]] = {}
    for source in extraction_entries:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
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
            attempts_by_field.setdefault(field, []).append(enriched)

    portal_urls = _urls_for_source_strategies(source_strategy, {"application_portal", "blocked_or_challenge"})
    out: dict[str, object] = {}
    for field in missing:
        field_name = str(field)
        attempts = attempts_by_field.get(field_name, [])
        reason = _missing_reason_for_attempts(attempts, portal_urls)
        source_urls = sorted({str(item.get("source_url")) for item in attempts if item.get("source_url")})
        if not source_urls and reason == "application_portal_unreachable":
            source_urls = portal_urls
        out[field_name] = {
            "reason": reason,
            "attempts": len(attempts),
            "attempted_extractors": sorted({str(item.get("extractor", "unknown")) for item in attempts}),
            "source_urls": source_urls[:10],
            "note": _missing_reason_note(reason),
        }
    return out


def _missing_reason_for_attempts(attempts: list[dict[str, object]], portal_urls: list[str]) -> str:
    if not attempts:
        return "application_portal_unreachable" if portal_urls else "not_attempted"
    if any(item.get("status") == "no_match" for item in attempts):
        return "attempted_no_match"
    if any(item.get("reason") == "context_gate_failed" for item in attempts):
        return "context_gate_failed"
    if any(item.get("reason") == "undergraduate_context_gate_failed" for item in attempts):
        return "undergraduate_context_gate_failed"
    if any(item.get("status") == "skipped" for item in attempts):
        return "manual_check_required"
    return "manual_check_required"


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
        "attempted_no_match": "At least one extractor ran on captured sources but did not match a supported pattern.",
        "context_gate_failed": "Captured sources did not pass the field-specific context gate.",
        "undergraduate_context_gate_failed": "Captured sources did not pass the undergraduate admissions context gate.",
        "application_portal_unreachable": "Relevant source diagnostics indicate an application portal or blocked/challenge page.",
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
