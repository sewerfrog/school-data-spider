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
