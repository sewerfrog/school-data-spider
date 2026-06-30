"""Guarded source planning helpers."""

from __future__ import annotations

from university_admissions_crawler.crawler.filters import DomainPolicy, validate_source_plan_candidate_url
from university_admissions_crawler.extractor.llm_provider import SourcePlanProvider, generate_source_plan_diagnostic
from university_admissions_crawler.extractor.schema import AdmissionsData


def attach_source_plan_diagnostics(data: AdmissionsData, provider: SourcePlanProvider) -> AdmissionsData:
    """Attach an optional source plan without changing crawl results or facts."""

    diagnostic = build_source_plan_diagnostic(data, provider)
    diagnostic["applied"] = False
    data.run.config["llm_source_plan"] = diagnostic
    return data


def build_source_plan_diagnostic(data: AdmissionsData, provider: SourcePlanProvider) -> dict[str, object]:
    context = source_planning_context(data)
    if not context["trigger_reasons"]:
        return {
            "enabled": True,
            "triggered": False,
            "provider": getattr(provider, "name", type(provider).__name__),
            "trigger_reasons": [],
            "candidate_urls": [],
            "candidate_path_patterns": [],
            "accepted_candidate_urls": [],
            "rejected_candidate_urls": [],
            "candidate_queries": [],
            "warnings": [],
            "applied": False,
            "note": "Source planning was enabled but no blocked source or all-missing core-field condition was detected.",
        }
    diagnostic = generate_source_plan_diagnostic(context, provider)
    accepted, rejected = validate_source_plan_candidates(diagnostic.get("candidate_urls"), data)
    diagnostic["accepted_candidate_urls"] = accepted
    diagnostic["rejected_candidate_urls"] = rejected
    diagnostic["enabled"] = True
    diagnostic["triggered"] = True
    return diagnostic


def validate_source_plan_candidates(candidates: object, data: AdmissionsData) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not isinstance(candidates, list):
        return [], []
    policy = _domain_policy_for_data(data)
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        url = candidate.get("url")
        if not isinstance(url, str) or not url:
            continue
        if url in seen:
            rejected.append({**candidate, "validation_status": "rejected", "rejection_reason": "duplicate_url"})
            continue
        seen.add(url)
        ok, reason = validate_source_plan_candidate_url(url, policy)
        out = dict(candidate)
        out["validation_status"] = "accepted" if ok else "rejected"
        if ok:
            accepted.append(out)
        else:
            out["rejection_reason"] = reason
            rejected.append(out)
    return accepted, rejected


def source_planning_context(data: AdmissionsData) -> dict[str, object]:
    source_strategy = data.run.config.get("source_strategy")
    blocked_urls: list[str] = []
    if isinstance(source_strategy, list):
        blocked_urls = sorted(
            {
                str(item.get("url"))
                for item in source_strategy
                if isinstance(item, dict) and item.get("strategy") == "blocked_or_challenge" and item.get("url")
            }
        )
    coverage = data.run.config.get("coverage")
    missing_fields: list[str] = []
    found_count = None
    if isinstance(coverage, dict):
        missing = coverage.get("missing")
        if isinstance(missing, list):
            missing_fields = [str(item) for item in missing]
        found = coverage.get("found_count")
        if isinstance(found, int):
            found_count = found
    trigger_reasons: list[str] = []
    if blocked_urls:
        trigger_reasons.append("blocked_or_challenge_source")
    if found_count == 0 and missing_fields:
        trigger_reasons.append("all_core_fields_missing")
    return {
        "input_url": data.run.input_url,
        "blocked_urls": blocked_urls,
        "missing_fields": missing_fields,
        "found_count": found_count,
        "trigger_reasons": trigger_reasons,
        "note": "Source planning context is diagnostic only and must not be used as admissions facts.",
    }


def _domain_policy_for_data(data: AdmissionsData) -> DomainPolicy:
    config = data.run.config
    allowed_hosts = config.get("allowed_hosts")
    allowed_domains = config.get("allowed_domains")
    return DomainPolicy(
        seed_url=data.run.input_url,
        allowed_hosts=set(allowed_hosts) if isinstance(allowed_hosts, list) else set(),
        allowed_domains=set(allowed_domains) if isinstance(allowed_domains, list) else set(),
    )
