"""Guarded source planning helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import Fetcher
from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url, domain_policy_for_seed, validate_source_plan_candidate_url
from university_admissions_crawler.extractor.llm_provider import (
    ClassificationAssistProvider,
    ProgrammeCatalogAssistProvider,
    SourcePlanProvider,
    StructuredExtractionProvider,
    generate_source_plan_diagnostic,
)
from university_admissions_crawler.extractor.pdf_extractor import PDFExtractor
from university_admissions_crawler.extractor.schema import AdmissionsData
from university_admissions_crawler.pipeline.diagnostics import attach_template_completeness


class SourcePlanScanOnce(Protocol):
    def __call__(
        self,
        seed_url: str,
        fetcher: Fetcher,
        config: DiscoveryConfig | None = None,
        *,
        previous_result: dict[str, Any] | None = None,
        pdf_extractor: PDFExtractor | None = None,
        source_output_dir: str | Path | None = None,
        classification_assist_provider: ClassificationAssistProvider | None = None,
        programme_catalog_assist_provider: ProgrammeCatalogAssistProvider | None = None,
        structured_extraction_provider: StructuredExtractionProvider | None = None,
    ) -> AdmissionsData: ...


@dataclass(slots=True)
class SourcePlanScanContext:
    seed_url: str
    fetcher: Fetcher
    config: DiscoveryConfig | None = None
    previous_result: dict[str, Any] | None = None
    pdf_extractor: PDFExtractor | None = None
    source_output_dir: str | Path | None = None
    classification_assist_provider: ClassificationAssistProvider | None = None
    programme_catalog_assist_provider: ProgrammeCatalogAssistProvider | None = None
    structured_extraction_provider: StructuredExtractionProvider | None = None


def attach_source_plan_diagnostics(data: AdmissionsData, provider: SourcePlanProvider) -> AdmissionsData:
    """Attach an optional source plan without changing crawl results or facts."""

    diagnostic = build_source_plan_diagnostic(data, provider)
    diagnostic["applied"] = False
    data.run.config["llm_source_plan"] = diagnostic
    return data


def apply_source_plan_second_pass(
    data: AdmissionsData,
    provider: SourcePlanProvider,
    context: SourcePlanScanContext,
    *,
    scan_once: SourcePlanScanOnce,
) -> AdmissionsData:
    source_plan = build_source_plan_diagnostic(data, provider)
    if not source_plan.get("triggered"):
        data.run.config["llm_source_plan"] = source_plan
        attach_template_completeness(data)
        return data

    accepted_candidates = _accepted_source_plan_urls(source_plan)
    if not accepted_candidates:
        source_plan["applied"] = False
        source_plan["applied_candidate_urls"] = []
        source_plan["budget_skipped_candidate_urls"] = []
        data.run.config["llm_source_plan"] = source_plan
        attach_template_completeness(data)
        return data

    second_pass_config = _config_with_extra_candidates(context.config or DiscoveryConfig(), accepted_candidates)
    planned_data = scan_once(
        context.seed_url,
        context.fetcher,
        second_pass_config,
        previous_result=context.previous_result,
        pdf_extractor=context.pdf_extractor,
        source_output_dir=context.source_output_dir,
        classification_assist_provider=context.classification_assist_provider,
        programme_catalog_assist_provider=context.programme_catalog_assist_provider,
        structured_extraction_provider=context.structured_extraction_provider,
    )
    crawled_urls = {canonicalize_url(source.source_url) for source in planned_data.sources}
    applied_urls = [url for url in accepted_candidates if canonicalize_url(url) in crawled_urls]
    for item in source_plan.get("accepted_candidate_urls", []):
        if isinstance(item, dict):
            url = item.get("url")
            item["crawl_status"] = "crawled" if isinstance(url, str) and canonicalize_url(url) in crawled_urls else "budget_skipped"
    source_plan["applied"] = bool(applied_urls)
    source_plan["applied_candidate_urls"] = applied_urls
    source_plan["budget_skipped_candidate_urls"] = [url for url in accepted_candidates if url not in crawled_urls]
    planned_data.run.config["llm_source_plan"] = source_plan
    attach_template_completeness(planned_data)
    return planned_data


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


def _accepted_source_plan_urls(source_plan: dict[str, object]) -> tuple[str, ...]:
    accepted = source_plan.get("accepted_candidate_urls")
    if not isinstance(accepted, list):
        return ()
    urls: list[str] = []
    seen: set[str] = set()
    for item in accepted:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return tuple(urls)


def _config_with_extra_candidates(config: DiscoveryConfig, extra_candidates: tuple[str, ...]) -> DiscoveryConfig:
    return DiscoveryConfig(
        max_depth=config.max_depth,
        max_pages=config.max_pages,
        allowed_hosts=set(config.allowed_hosts),
        allowed_domains=set(config.allowed_domains),
        allow_official_subdomains=config.allow_official_subdomains,
        retries=config.retries,
        relevance_strategy=config.relevance_strategy,
        keyword_plan=config.keyword_plan,
        extra_candidates=tuple(dict.fromkeys((*config.extra_candidates, *extra_candidates))),
        programme_source_family_budget=config.programme_source_family_budget,
        programme_detail_faculty_catalog_family_budget=config.programme_detail_faculty_catalog_family_budget,
        programme_detail_unbacked_family_budget=config.programme_detail_unbacked_family_budget,
        programme_detail_targeted_reserve=config.programme_detail_targeted_reserve,
    )


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
    allow_official_subdomains = config.get("allow_official_subdomains")
    return domain_policy_for_seed(
        data.run.input_url,
        allowed_hosts=set(allowed_hosts) if isinstance(allowed_hosts, list) else set(),
        allowed_domains=set(allowed_domains) if isinstance(allowed_domains, list) else set(),
        allow_official_subdomains=allow_official_subdomains if isinstance(allow_official_subdomains, bool) else True,
    )
