"""Shared helpers for scan source capture and run metadata initialization."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import FetchResult
from university_admissions_crawler.crawler.filters import DomainPolicy, domain_policy_for_seed
from university_admissions_crawler.evidence.store import write_source_record
from university_admissions_crawler.extractor.llm_provider import ClassificationAssistProvider, StructuredExtractionProvider
from university_admissions_crawler.extractor.schema import AdmissionsData, Institution, RunMetadata


def domain_policy_for_scan(seed_url: str, discovery_config: DiscoveryConfig) -> DomainPolicy:
    return domain_policy_for_seed(
        seed_url,
        allowed_hosts=set(discovery_config.allowed_hosts),
        allowed_domains=set(discovery_config.allowed_domains),
        allow_official_subdomains=discovery_config.allow_official_subdomains,
    )


def initialize_scan_data(
    seed_url: str,
    discovery_config: DiscoveryConfig,
    *,
    classification_assist_provider: ClassificationAssistProvider | None,
    structured_extraction_provider: StructuredExtractionProvider | None,
) -> AdmissionsData:
    data = AdmissionsData(
        institution=Institution(homepage_url=seed_url),
        run=RunMetadata(
            input_url=seed_url,
            config={
                "max_pages": discovery_config.max_pages,
                "max_depth": discovery_config.max_depth,
                "allowed_hosts": sorted(discovery_config.allowed_hosts),
                "allowed_domains": sorted(discovery_config.allowed_domains),
                "allow_official_subdomains": discovery_config.allow_official_subdomains,
                "relevance_strategy": getattr(discovery_config.relevance_strategy, "name", type(discovery_config.relevance_strategy).__name__),
                "programme_source_family_budget": discovery_config.programme_source_family_budget,
                "programme_detail_targeted_reserve": discovery_config.programme_detail_targeted_reserve,
                "programme_frontier_diagnostics": list(discovery_config.frontier_diagnostics),
                "programme_frontier_summary": _frontier_summary(discovery_config.frontier_diagnostics),
            },
        ),
    )
    if discovery_config.keyword_plan is not None:
        data.run.config["keyword_plan"] = discovery_config.keyword_plan.to_dict()
    if classification_assist_provider is not None:
        data.run.config["classification_assist"] = []
    if structured_extraction_provider is not None:
        data.run.config["llm_structured_extraction"] = {
            "enabled": True,
            "triggered": False,
            "provider": getattr(structured_extraction_provider, "name", type(structured_extraction_provider).__name__),
            "candidate_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "results": [],
            "source_urls_used": [],
            "trigger_reasons": [],
            "applied_to_facts": False,
            "note": "LLM structured extraction fallback writes only validated candidates into missing fields; rejected or skipped candidates remain diagnostics.",
        }
    return data


def attach_programme_frontier_diagnostics(
    data: AdmissionsData,
    entries: list[dict[str, object]],
) -> None:
    data.run.config["programme_frontier_diagnostics"] = list(entries)
    data.run.config["programme_frontier_summary"] = _frontier_summary(entries)


def record_fetch_result(
    data: AdmissionsData,
    result: FetchResult,
    *,
    captured_source_texts: dict[str, str],
    source_output_dir: str | Path | None,
    domain_policy: DomainPolicy | None = None,
) -> bool:
    data.warnings.extend(result.warnings)
    if result.source:
        if domain_policy is not None:
            result.source.is_official = domain_policy.is_allowed(result.source.source_url)
        captured_text = result.markdown or result.text
        data.sources.append(result.source)
        captured_source_texts[result.source.source_url] = captured_text
        if source_output_dir is not None:
            write_source_record(source_output_dir, result.source, captured_text)
    return bool(result.ok and result.source)


def _frontier_summary(entries: list[dict[str, object]]) -> dict[str, object]:
    decisions = Counter(str(item.get("decision", "unknown")) for item in entries)
    roles = Counter(str(item.get("source_role", "unrelated")) for item in entries if item.get("decision") == "fetched")
    skipped_reasons = Counter(
        str(item.get("reason", "unknown"))
        for item in entries
        if item.get("decision") == "skipped"
    )
    skipped_families = Counter(
        str(item.get("source_family", "unknown"))
        for item in entries
        if item.get("decision") == "skipped"
    )
    return {
        "decision_counts": dict(sorted(decisions.items())),
        "fetched_source_role_counts": dict(sorted(roles.items())),
        "skipped_reason_counts": dict(sorted(skipped_reasons.items())),
        "budget_skipped_source_family_counts": dict(sorted(skipped_families.items())),
    }
