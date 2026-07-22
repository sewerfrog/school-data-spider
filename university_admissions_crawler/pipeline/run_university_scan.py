"""Pipeline orchestration: discover -> fetch -> classify -> extract -> normalize."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from university_admissions_crawler.crawler.discovery import (
    DiscoveredPage,
    DiscoveryConfig,
    discover,
    fetch_discovered_candidate,
)
from university_admissions_crawler.crawler.fetcher import Fetcher, FixtureFetcher
from university_admissions_crawler.crawler.filters import DomainPolicy
from university_admissions_crawler.crawler.relevance import DEFAULT_RELEVANCE_STRATEGY, KeywordPlan, RelevanceStrategy
from university_admissions_crawler.extractor.llm_provider import (
    ClassificationAssistProvider,
    ProgrammeCatalogAssistProvider,
    SourcePlanProvider,
    StructuredExtractionProvider,
)
from university_admissions_crawler.extractor.pdf_extractor import FixturePDFExtractor, MissingPDFExtractor, PDFExtractor
from university_admissions_crawler.pipeline.api_catalog_augmentation import augment_api_catalog_discovery
from university_admissions_crawler.pipeline.api_catalog_capture import (
    ApiCatalogCaptureContext,
    capture_safe_api_catalog_candidates,
    network_responses_by_url,
    process_json_api_with_pagination,
)
from university_admissions_crawler.pipeline.category_extraction import (
    SourceExtractionContext,
    extract_category_route,
    extract_core_supplements_for_context,
    start_extraction_diagnostics,
)
from university_admissions_crawler.pipeline.diagnostics import attach_run_diagnostics
from university_admissions_crawler.pipeline.incremental_diff import apply_incremental_diff
from university_admissions_crawler.pipeline.programme_detail_selection import (
    TargetedProgrammeDetailCandidate,
    select_targeted_programme_detail_candidates,
    targeted_programme_detail_family_reserve,
)
from university_admissions_crawler.pipeline.scan_context import build_captured_source_context
from university_admissions_crawler.pipeline.source_capture import (
    attach_programme_frontier_diagnostics,
    domain_policy_for_scan,
    initialize_scan_data,
    record_fetch_result,
)
from university_admissions_crawler.pipeline.source_planning import SourcePlanScanContext, apply_source_plan_second_pass
from university_admissions_crawler.pipeline.structured_fallback import attach_llm_structured_extraction_diagnostics
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    FieldValue,
    RequirementRecord,
    SourceType,
    attach_validation_warnings,
)


def run_fixture_scan(
    root: str | Path,
    seed_url: str = "https://fixture.test/",
    max_pages: int = 20,
    max_depth: int = 3,
    previous_result: dict[str, Any] | None = None,
    allowed_hosts: set[str] | None = None,
    allowed_domains: set[str] | None = None,
    keyword_plan: KeywordPlan | None = None,
    relevance_strategy: RelevanceStrategy | None = None,
    source_output_dir: str | Path | None = None,
    classification_assist_provider: ClassificationAssistProvider | None = None,
    programme_catalog_assist_provider: ProgrammeCatalogAssistProvider | None = None,
    source_plan_provider: SourcePlanProvider | None = None,
    structured_extraction_provider: StructuredExtractionProvider | None = None,
    programme_detail_targeted_reserve: int = 0,
) -> AdmissionsData:
    return run_scan(
        seed_url,
        FixtureFetcher(root, base_url=seed_url),
        DiscoveryConfig(
            max_pages=max_pages,
            max_depth=max_depth,
            allowed_hosts=allowed_hosts or set(),
            allowed_domains=allowed_domains or set(),
            keyword_plan=keyword_plan,
            relevance_strategy=relevance_strategy or DEFAULT_RELEVANCE_STRATEGY,
            programme_detail_targeted_reserve=programme_detail_targeted_reserve,
        ),
        previous_result=previous_result,
        source_output_dir=source_output_dir,
        classification_assist_provider=classification_assist_provider,
        programme_catalog_assist_provider=programme_catalog_assist_provider,
        source_plan_provider=source_plan_provider,
        structured_extraction_provider=structured_extraction_provider,
    )


def run_scan(
    seed_url: str,
    fetcher: Fetcher,
    config: DiscoveryConfig | None = None,
    *,
    previous_result: dict[str, Any] | None = None,
    pdf_extractor: PDFExtractor | None = None,
    source_output_dir: str | Path | None = None,
    classification_assist_provider: ClassificationAssistProvider | None = None,
    programme_catalog_assist_provider: ProgrammeCatalogAssistProvider | None = None,
    source_plan_provider: SourcePlanProvider | None = None,
    structured_extraction_provider: StructuredExtractionProvider | None = None,
) -> AdmissionsData:
    data = _run_scan_once(
        seed_url,
        fetcher,
        config,
        previous_result=previous_result,
        pdf_extractor=pdf_extractor,
        source_output_dir=source_output_dir,
        classification_assist_provider=classification_assist_provider,
        programme_catalog_assist_provider=programme_catalog_assist_provider,
        structured_extraction_provider=structured_extraction_provider,
    )
    if source_plan_provider is None:
        return data

    return apply_source_plan_second_pass(
        data,
        source_plan_provider,
        SourcePlanScanContext(
            seed_url=seed_url,
            fetcher=fetcher,
            config=config,
            previous_result=previous_result,
            pdf_extractor=pdf_extractor,
            source_output_dir=source_output_dir,
            classification_assist_provider=classification_assist_provider,
            programme_catalog_assist_provider=programme_catalog_assist_provider,
            structured_extraction_provider=structured_extraction_provider,
        ),
        scan_once=_run_scan_once,
    )


def _run_scan_once(
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
) -> AdmissionsData:
    discovery_config = config or DiscoveryConfig()
    source_domain_policy = domain_policy_for_scan(seed_url, discovery_config)
    targeted_reserve = _effective_targeted_detail_reserve(discovery_config)
    targeted_family_reserve = targeted_programme_detail_family_reserve(
        targeted_reserve,
        discovery_config.programme_source_family_budget,
    )
    default_family_reserve = min(
        targeted_reserve,
        max(0, discovery_config.programme_source_family_budget),
        2,
    )
    first_pass_family_budget = max(
        0,
        discovery_config.programme_source_family_budget - default_family_reserve,
    )
    first_pass_faculty_catalog_family_budget = max(
        0,
        discovery_config.programme_source_family_budget - targeted_family_reserve,
    )
    first_pass_config = replace(
        discovery_config,
        max_pages=max(0, discovery_config.max_pages - targeted_reserve),
        programme_source_family_budget=first_pass_family_budget,
        programme_detail_faculty_catalog_family_budget=first_pass_faculty_catalog_family_budget,
        programme_detail_unbacked_family_budget=first_pass_faculty_catalog_family_budget,
        capture_pending_frontier=targeted_reserve > 0,
        frontier_diagnostics=[],
    )
    pages = discover(seed_url, fetcher, first_pass_config)
    discovery_config.frontier_diagnostics[:] = first_pass_config.frontier_diagnostics
    data = initialize_scan_data(
        seed_url,
        discovery_config,
        classification_assist_provider=classification_assist_provider,
        structured_extraction_provider=structured_extraction_provider,
    )
    data.run.config["programme_detail_targeted_effective_reserve"] = targeted_reserve
    data.run.config["programme_detail_first_pass_max_pages"] = first_pass_config.max_pages
    data.run.config["programme_detail_first_pass_family_budget"] = first_pass_config.programme_source_family_budget
    data.run.config["programme_detail_first_pass_faculty_catalog_family_budget"] = (
        first_pass_config.programme_detail_faculty_catalog_family_budget
    )
    data.run.config["programme_detail_first_pass_unbacked_family_budget"] = (
        first_pass_config.programme_detail_unbacked_family_budget
    )
    data.run.config["programme_detail_targeted_family_reserve"] = targeted_family_reserve
    pdf_extractor = pdf_extractor or _default_pdf_extractor(fetcher)
    captured_source_texts: dict[str, str] = {}
    api_capture_context = ApiCatalogCaptureContext(
        fetcher=fetcher,
        discovery_config=discovery_config,
        pdf_extractor=pdf_extractor,
        classification_assist_provider=classification_assist_provider,
        captured_source_texts=captured_source_texts,
        source_output_dir=source_output_dir,
        domain_policy=source_domain_policy,
    )
    pages = augment_api_catalog_discovery(
        data,
        pages,
        fetcher,
        seed_url=seed_url,
        discovery_config=discovery_config,
    )

    _process_discovered_pages(
        data,
        pages,
        discovery_config=discovery_config,
        pdf_extractor=pdf_extractor,
        classification_assist_provider=classification_assist_provider,
        programme_catalog_assist_provider=programme_catalog_assist_provider,
        captured_source_texts=captured_source_texts,
        source_output_dir=source_output_dir,
        source_domain_policy=source_domain_policy,
        api_capture_context=api_capture_context,
    )

    if discovery_config.programme_detail_targeted_reserve > 0:
        available_slots = min(targeted_reserve, max(0, discovery_config.max_pages - len(pages)))
        targeted_candidates = select_targeted_programme_detail_candidates(
            data,
            discovery_config.frontier_diagnostics,
            limit=available_slots,
            family_budget=discovery_config.programme_source_family_budget,
        )
        targeted_pages = _fetch_targeted_programme_details(
            seed_url,
            fetcher,
            discovery_config,
            targeted_candidates,
            source_domain_policy=source_domain_policy,
        )
        pages.extend(targeted_pages)
        _process_discovered_pages(
            data,
            targeted_pages,
            discovery_config=discovery_config,
            pdf_extractor=pdf_extractor,
            classification_assist_provider=classification_assist_provider,
            programme_catalog_assist_provider=programme_catalog_assist_provider,
            captured_source_texts=captured_source_texts,
            source_output_dir=source_output_dir,
            source_domain_policy=source_domain_policy,
            api_capture_context=api_capture_context,
        )
        selection = data.run.config.get("programme_catalog_targeted_detail_selection")
        if isinstance(selection, dict):
            selection["fetched_count"] = len(targeted_pages)
            selection["combined_discovered_page_count"] = len(pages)
            selection["combined_page_budget"] = discovery_config.max_pages
    attach_programme_frontier_diagnostics(data, discovery_config.frontier_diagnostics)

    capture_safe_api_catalog_candidates(
        data,
        context=api_capture_context,
        network_responses_by_url=network_responses_by_url(pages),
    )

    if not data.admissions.required_documents:
        data.admissions.required_documents.append(
            RequirementRecord(
                label="required documents",
                value=FieldValue.manual_check("Required documents were not found in the offline fixture.", "/admissions/required_documents/0/value"),
            )
        )
    apply_incremental_diff(data, previous_result)
    attach_run_diagnostics(data)
    if structured_extraction_provider is not None:
        attach_llm_structured_extraction_diagnostics(data, captured_source_texts, structured_extraction_provider, discovery_config)
    return attach_validation_warnings(data)


def _process_discovered_pages(
    data: AdmissionsData,
    pages: list[DiscoveredPage],
    *,
    discovery_config: DiscoveryConfig,
    pdf_extractor: PDFExtractor,
    classification_assist_provider: ClassificationAssistProvider | None,
    programme_catalog_assist_provider: ProgrammeCatalogAssistProvider | None,
    captured_source_texts: dict[str, str],
    source_output_dir: str | Path | None,
    source_domain_policy: DomainPolicy,
    api_capture_context: ApiCatalogCaptureContext,
) -> None:
    for page in pages:
        result = page.result
        if not record_fetch_result(
            data,
            result,
            captured_source_texts=captured_source_texts,
            source_output_dir=source_output_dir,
            domain_policy=source_domain_policy,
        ):
            continue
        context = build_captured_source_context(
            data,
            page,
            discovery_config,
            pdf_extractor,
            classification_assist_provider,
        )
        source_context = SourceExtractionContext(
            final_url=context.final_url,
            title=context.title,
            source=context.source,
            text=context.extraction_text,
            pdf_pages=context.pdf_pages,
            category=context.classification.category,
            content_blocks=context.content_blocks,
            requested_url=result.url,
        )
        extraction_recorder = start_extraction_diagnostics(data, source_context, source_strategy=context.source_strategy)

        if context.source_strategy == "blocked_or_challenge":
            continue

        if result.source.source_type == SourceType.JSON:
            process_json_api_with_pagination(
                data,
                result,
                context=api_capture_context,
                depth=page.depth,
                score=page.score,
                extraction_recorder=extraction_recorder,
            )
            continue

        extract_category_route(
            data,
            source_context,
            extraction_recorder,
            programme_catalog_assist_provider=programme_catalog_assist_provider,
        )
        extract_core_supplements_for_context(data, source_context, extraction_recorder)


def _effective_targeted_detail_reserve(config: DiscoveryConfig) -> int:
    requested = max(0, config.programme_detail_targeted_reserve)
    return min(requested, max(0, config.max_pages // 4))


def _fetch_targeted_programme_details(
    seed_url: str,
    fetcher: Fetcher,
    config: DiscoveryConfig,
    candidates: list[TargetedProgrammeDetailCandidate],
    *,
    source_domain_policy: DomainPolicy,
) -> list[DiscoveredPage]:
    pages: list[DiscoveredPage] = []
    for candidate in candidates:
        page = fetch_discovered_candidate(
            seed_url,
            candidate.url,
            fetcher,
            config,
            depth=candidate.depth,
            policy=source_domain_policy,
        )
        if page is None:
            config.frontier_diagnostics.append(
                {
                    **candidate.to_dict(),
                    "decision": "rejected",
                    "reason": "targeted_candidate_outside_scan_policy",
                    "source_role": "programme_detail",
                }
            )
            continue
        if not source_domain_policy.is_allowed(page.result.final_url):
            config.frontier_diagnostics.append(
                {
                    **candidate.to_dict(),
                    "decision": "rejected",
                    "reason": "targeted_candidate_redirected_off_domain",
                    "source_role": page.source_role,
                    "final_url": page.result.final_url,
                }
            )
            continue
        config.frontier_diagnostics.append(
            {
                **candidate.to_dict(),
                "url": page.result.final_url,
                "requested_url": candidate.url,
                "decision": "fetched",
                "reason": "targeted_unresolved_programme_detail",
                "source_role": page.source_role,
                "queued_source_role": "programme_detail",
                "source_family": page.source_family,
                "source_role_signals": list(page.source_role_signals),
                "fetch_status": page.result.status,
            }
        )
        pages.append(page)
    return pages


def _default_pdf_extractor(fetcher: Fetcher) -> PDFExtractor:
    if isinstance(fetcher, FixtureFetcher):
        return FixturePDFExtractor()
    return MissingPDFExtractor()
