"""Pipeline orchestration: discover -> fetch -> classify -> extract -> normalize."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from university_admissions_crawler.classifier.page_classifier import Classification, classify_page, is_low_confidence_classification
from university_admissions_crawler.crawler.discovery import DiscoveredPage, DiscoveryConfig, discover
from university_admissions_crawler.crawler.fetcher import Fetcher, FetchResult, FixtureFetcher
from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url
from university_admissions_crawler.crawler.relevance import DEFAULT_RELEVANCE_STRATEGY, KeywordPlan, RelevanceStrategy, relevance_diagnostics
from university_admissions_crawler.evidence.store import write_source_record
from university_admissions_crawler.extractor.api_extractor import extract_api_claims
from university_admissions_crawler.extractor.llm_provider import (
    ClassificationAssistProvider,
    ProgrammeCatalogAssistProvider,
    SourcePlanProvider,
    StructuredExtractionProvider,
    generate_classification_assist_diagnostic,
)
from university_admissions_crawler.extractor.normalizer import add_warning
from university_admissions_crawler.extractor.pdf_extractor import FixturePDFExtractor, MissingPDFExtractor, PDFExtractor, PDFPageText
from university_admissions_crawler.extractor.programme_catalog_api import extract_programme_catalog_api, programme_catalog_api_diagnostics
from university_admissions_crawler.pipeline.category_extraction import (
    SourceExtractionContext,
    extract_category_route,
    extract_core_supplements_for_context,
    start_extraction_diagnostics,
)
from university_admissions_crawler.pipeline.diagnostics import attach_run_diagnostics, attach_template_completeness, source_strategy_for
from university_admissions_crawler.pipeline.source_planning import build_source_plan_diagnostic
from university_admissions_crawler.pipeline.structured_fallback import attach_llm_structured_extraction_diagnostics
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    EvidenceItem,
    FieldValue,
    Institution,
    PageClassificationRecord,
    RequirementRecord,
    RunMetadata,
    SourceRecord,
    SourceType,
    WarningCode,
    WarningRecord,
    attach_validation_warnings,
)
from university_admissions_crawler.pipeline.api_catalog_discovery import (
    MAX_API_RESPONSE_SIZE_BYTES,
    MAX_SAFE_API_CAPTURE_CANDIDATES,
    api_catalog_candidate_capture_urls,
    attach_api_catalog_discovery_diagnostics,
    mark_api_catalog_candidate_capture,
)
from university_admissions_crawler.pipeline.api_catalog_filters import fetch_api_catalog_filter_pages
from university_admissions_crawler.pipeline.api_catalog_pagination import (
    ApiCatalogPaginationOutcome,
    api_pagination_group_url,
    fetch_additional_api_catalog_pages,
)


@dataclass(slots=True)
class _SourceTextContext:
    discovery_text: str
    extraction_text: str
    pdf_pages: list[PDFPageText]


@dataclass(slots=True)
class _CapturedSourceContext:
    final_url: str
    title: str | None
    source: SourceRecord
    discovery_text: str
    extraction_text: str
    pdf_pages: list[PDFPageText]
    classification: Classification
    source_strategy: str


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

    source_plan = build_source_plan_diagnostic(data, source_plan_provider)
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

    second_pass_config = _config_with_extra_candidates(config or DiscoveryConfig(), accepted_candidates)
    planned_data = _run_scan_once(
        seed_url,
        fetcher,
        second_pass_config,
        previous_result=previous_result,
        pdf_extractor=pdf_extractor,
        source_output_dir=source_output_dir,
        classification_assist_provider=classification_assist_provider,
        programme_catalog_assist_provider=programme_catalog_assist_provider,
        structured_extraction_provider=structured_extraction_provider,
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
    )


def _initialize_scan_data(
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
                "relevance_strategy": getattr(discovery_config.relevance_strategy, "name", type(discovery_config.relevance_strategy).__name__),
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


def _record_fetch_result(
    data: AdmissionsData,
    result: FetchResult,
    *,
    captured_source_texts: dict[str, str],
    source_output_dir: str | Path | None,
) -> bool:
    data.warnings.extend(result.warnings)
    if result.source:
        captured_text = result.markdown or result.text
        data.sources.append(result.source)
        captured_source_texts[result.source.source_url] = captured_text
        if source_output_dir is not None:
            write_source_record(source_output_dir, result.source, captured_text)
    return bool(result.ok and result.source)


def _source_text_context(data: AdmissionsData, result: FetchResult, pdf_extractor: PDFExtractor) -> _SourceTextContext:
    discovery_text = result.markdown or result.text
    if result.source is None or result.source.source_type != SourceType.PDF:
        return _SourceTextContext(discovery_text=discovery_text, extraction_text=discovery_text, pdf_pages=[])

    try:
        pdf_result = pdf_extractor.extract(result.source, result.text)
    except Exception as exc:
        data.warnings.append(
            WarningRecord(
                WarningCode.PDF_PARSE_FAILED,
                f"PDF extractor raised {type(exc).__name__}: {exc}",
                field=result.source.source_url,
                source_urls=[result.source.source_url],
            )
        )
        return _SourceTextContext(discovery_text=discovery_text, extraction_text="", pdf_pages=[])

    data.warnings.extend(pdf_result.warnings)
    return _SourceTextContext(
        discovery_text=discovery_text,
        extraction_text=pdf_result.text if pdf_result.pages else "",
        pdf_pages=pdf_result.pages,
    )


def _build_captured_source_context(
    data: AdmissionsData,
    page: DiscoveredPage,
    discovery_config: DiscoveryConfig,
    pdf_extractor: PDFExtractor,
    classification_assist_provider: ClassificationAssistProvider | None,
) -> _CapturedSourceContext:
    result = page.result
    if result.source is None:
        raise ValueError("Cannot build a captured source context without a source record.")
    text_context = _source_text_context(data, result, pdf_extractor)
    classification = classify_page(result.final_url, result.title, text_context.extraction_text)
    if classification_assist_provider is not None and is_low_confidence_classification(classification):
        data.run.config.setdefault("classification_assist", []).append(
            generate_classification_assist_diagnostic(
                url=result.final_url,
                title=result.title,
                text=text_context.extraction_text,
                rule_category=classification.category,
                rule_score=classification.score,
                provider=classification_assist_provider,
            )
        )

    discovery_diagnostics = relevance_diagnostics(
        discovery_config.relevance_strategy,
        result.final_url,
        result.title,
        text_context.discovery_text,
        score=page.score,
    )
    data.discovered_categories.append(
        PageClassificationRecord(
            source_url=result.final_url,
            category=classification.category,
            score=classification.score,
            signals=classification.signals,
            title=result.title,
        )
    )
    strategy = source_strategy_for(result.source.source_type, result.final_url, result.title, text_context.extraction_text, classification.category)
    data.run.config.setdefault("source_strategy", []).append(
        {
            "url": result.final_url,
            "source_type": str(result.source.source_type),
            "category": str(classification.category),
            "strategy": strategy,
            "discovery_score": discovery_diagnostics.score,
            "discovery_signals": list(discovery_diagnostics.signals),
            "relevance_strategy": discovery_diagnostics.strategy,
        }
    )
    return _CapturedSourceContext(
        final_url=result.final_url,
        title=result.title,
        source=result.source,
        discovery_text=text_context.discovery_text,
        extraction_text=text_context.extraction_text,
        pdf_pages=text_context.pdf_pages,
        classification=classification,
        source_strategy=strategy,
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
    pages = discover(seed_url, fetcher, discovery_config)
    data = _initialize_scan_data(
        seed_url,
        discovery_config,
        classification_assist_provider=classification_assist_provider,
        structured_extraction_provider=structured_extraction_provider,
    )
    pdf_extractor = pdf_extractor or _default_pdf_extractor(fetcher)
    captured_source_texts: dict[str, str] = {}
    attach_api_catalog_discovery_diagnostics(data, pages, seed_url=seed_url, config=discovery_config)

    for page in pages:
        result = page.result
        if not _record_fetch_result(data, result, captured_source_texts=captured_source_texts, source_output_dir=source_output_dir):
            continue
        context = _build_captured_source_context(
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
        )
        extraction_recorder = start_extraction_diagnostics(data, source_context, source_strategy=context.source_strategy)

        if context.source_strategy == "blocked_or_challenge":
            continue

        if result.source.source_type == SourceType.JSON:
            _process_json_api_with_pagination(
                data,
                result,
                fetcher=fetcher,
                discovery_config=discovery_config,
                pdf_extractor=pdf_extractor,
                classification_assist_provider=classification_assist_provider,
                captured_source_texts=captured_source_texts,
                source_output_dir=source_output_dir,
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

    _capture_safe_api_catalog_candidates(
        data,
        fetcher,
        discovery_config,
        pdf_extractor,
        classification_assist_provider,
        captured_source_texts=captured_source_texts,
        source_output_dir=source_output_dir,
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


def _capture_safe_api_catalog_candidates(
    data: AdmissionsData,
    fetcher: Fetcher,
    discovery_config: DiscoveryConfig,
    pdf_extractor: PDFExtractor,
    classification_assist_provider: ClassificationAssistProvider | None,
    *,
    captured_source_texts: dict[str, str],
    source_output_dir: str | Path | None,
) -> None:
    existing_urls = {canonicalize_url(source.source_url) for source in data.sources}
    candidate_urls = api_catalog_candidate_capture_urls(data, existing_urls=existing_urls)
    seed_url = data.run.input_url or data.institution.homepage_url
    policy = DomainPolicy(
        seed_url=seed_url,
        allowed_hosts=set(discovery_config.allowed_hosts) | {urlparse(seed_url).netloc},
        allowed_domains=set(discovery_config.allowed_domains),
        allow_official_subdomains=discovery_config.allow_official_subdomains,
    )
    discovery_summary = data.run.config.get("programme_catalog_api_discovery_summary")
    pending_count = (
        discovery_summary.get("safe_capture_pending_count", 0)
        if isinstance(discovery_summary, dict)
        else len(candidate_urls)
    )
    diagnostics: dict[str, Any] = {
        "max_candidates": MAX_SAFE_API_CAPTURE_CANDIDATES,
        "attempted_urls": [],
        "captured_urls": [],
        "rejected_urls": [],
        "accepted_row_count": 0,
        "budget_hit": isinstance(pending_count, int) and pending_count > len(candidate_urls),
        "applied_to_facts": False,
        "note": "Safe capture fetches only bounded public JSON API candidates already discovered on allowed official sources.",
    }

    for url in candidate_urls:
        diagnostics["attempted_urls"].append(url)
        try:
            result = fetcher.fetch(url)
        except Exception as exc:
            data.warnings.append(
                WarningRecord(
                    WarningCode.FETCH_FAILED,
                    f"API catalog safe capture raised {type(exc).__name__}: {exc}",
                    field=url,
                    source_urls=[url],
                )
            )
            diagnostics["rejected_urls"].append({"url": url, "reason": "capture_exception"})
            mark_api_catalog_candidate_capture(data, url, status="capture_failed", rejection_reason="capture_exception")
            continue

        response_size = len(result.text.encode("utf-8"))
        if not policy.is_allowed(result.final_url):
            data.warnings.extend(result.warnings)
            diagnostics["rejected_urls"].append({"url": url, "reason": "redirected_off_domain"})
            mark_api_catalog_candidate_capture(
                data,
                url,
                status="rejected_off_domain",
                content_type=result.content_type,
                response_size_bytes=response_size,
                captured_url=result.final_url,
                rejection_reason="redirected_off_domain",
            )
            continue
        if not result.ok or result.source is None:
            data.warnings.extend(result.warnings)
            diagnostics["rejected_urls"].append({"url": url, "reason": "fetch_failed"})
            mark_api_catalog_candidate_capture(
                data,
                url,
                status="capture_failed",
                content_type=result.content_type,
                response_size_bytes=response_size,
                captured_url=result.final_url,
                rejection_reason="fetch_failed",
            )
            continue
        if result.source.source_type != SourceType.JSON:
            data.warnings.extend(result.warnings)
            diagnostics["rejected_urls"].append({"url": url, "reason": "non_json_response"})
            mark_api_catalog_candidate_capture(
                data,
                url,
                status="non_json_response",
                content_type=result.content_type,
                response_size_bytes=response_size,
                captured_url=result.final_url,
                rejection_reason="non_json_response",
            )
            continue
        if response_size > MAX_API_RESPONSE_SIZE_BYTES:
            data.warnings.extend(result.warnings)
            diagnostics["rejected_urls"].append({"url": url, "reason": "rejected_too_large"})
            mark_api_catalog_candidate_capture(
                data,
                url,
                status="rejected_too_large",
                content_type=result.content_type,
                response_size_bytes=response_size,
                captured_url=result.final_url,
                rejection_reason="rejected_too_large",
            )
            continue
        if not _record_fetch_result(data, result, captured_source_texts=captured_source_texts, source_output_dir=source_output_dir):
            diagnostics["rejected_urls"].append({"url": url, "reason": "capture_failed"})
            mark_api_catalog_candidate_capture(
                data,
                url,
                status="capture_failed",
                content_type=result.content_type,
                response_size_bytes=response_size,
                captured_url=result.final_url,
                rejection_reason="capture_failed",
            )
            continue

        context = _build_captured_source_context(
            data,
            DiscoveredPage(result=result, depth=1, score=0.0),
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
        )
        extraction_recorder = start_extraction_diagnostics(data, source_context, source_strategy=context.source_strategy)
        if context.source_strategy == "blocked_or_challenge":
            diagnostics["rejected_urls"].append({"url": url, "reason": "blocked_or_challenge"})
            mark_api_catalog_candidate_capture(
                data,
                url,
                status="blocked_or_challenge",
                content_type=result.content_type,
                response_size_bytes=response_size,
                captured_url=result.final_url,
                rejection_reason="blocked_or_challenge",
            )
            continue

        mark_api_catalog_candidate_capture(
            data,
            url,
            status="captured_json",
            content_type=result.content_type,
            response_size_bytes=response_size,
            captured_url=result.final_url,
        )
        rows_added = _process_json_api_with_pagination(
            data,
            result,
            fetcher=fetcher,
            discovery_config=discovery_config,
            pdf_extractor=pdf_extractor,
            classification_assist_provider=classification_assist_provider,
            captured_source_texts=captured_source_texts,
            source_output_dir=source_output_dir,
            depth=1,
            score=0.0,
            extraction_recorder=extraction_recorder,
        )
        diagnostics["captured_urls"].append(result.final_url)
        diagnostics["accepted_row_count"] += rows_added

    diagnostics["applied_to_facts"] = diagnostics["accepted_row_count"] > 0
    data.run.config["programme_catalog_api_capture"] = diagnostics


def _process_json_api_with_pagination(
    data: AdmissionsData,
    result: FetchResult,
    *,
    fetcher: Fetcher,
    discovery_config: DiscoveryConfig,
    pdf_extractor: PDFExtractor,
    classification_assist_provider: ClassificationAssistProvider | None,
    captured_source_texts: dict[str, str],
    source_output_dir: str | Path | None,
    depth: int,
    score: float,
    extraction_recorder,
    filter_dimensions: dict[str, str] | None = None,
    enable_filter_enumeration: bool = True,
) -> int:
    rows_before = len(data.programme_catalog)
    pagination_outcome = fetch_additional_api_catalog_pages(fetcher, result)
    data.run.config.setdefault("programme_catalog_api_pagination", []).append(pagination_outcome.to_dict())
    _extract_json_api_claims_and_catalog(
        data,
        result,
        extraction_recorder,
        pagination_outcome=pagination_outcome,
        page_index=1,
        is_completion_page=not pagination_outcome.fetched_pages,
        filter_dimensions=filter_dimensions,
    )
    for paged_capture in pagination_outcome.fetched_pages:
        paged_result = paged_capture.result
        if not _record_fetch_result(data, paged_result, captured_source_texts=captured_source_texts, source_output_dir=source_output_dir):
            continue
        paged_context = _build_captured_source_context(
            data,
            DiscoveredPage(result=paged_result, depth=depth + 1, score=score),
            discovery_config,
            pdf_extractor,
            classification_assist_provider,
        )
        paged_source_context = SourceExtractionContext(
            final_url=paged_context.final_url,
            title=paged_context.title,
            source=paged_context.source,
            text=paged_context.extraction_text,
            pdf_pages=paged_context.pdf_pages,
            category=paged_context.classification.category,
        )
        paged_recorder = start_extraction_diagnostics(data, paged_source_context, source_strategy=paged_context.source_strategy)
        if paged_context.source_strategy == "blocked_or_challenge" or paged_result.source.source_type != SourceType.JSON:
            continue
        _extract_json_api_claims_and_catalog(
            data,
            paged_result,
            paged_recorder,
            pagination_outcome=pagination_outcome,
            page_index=paged_capture.page_index,
            is_completion_page=paged_capture.page_index == pagination_outcome.page_count,
            filter_dimensions=filter_dimensions,
        )
    if enable_filter_enumeration:
        _process_json_api_filter_pages(
            data,
            result,
            fetcher=fetcher,
            discovery_config=discovery_config,
            pdf_extractor=pdf_extractor,
            classification_assist_provider=classification_assist_provider,
            captured_source_texts=captured_source_texts,
            source_output_dir=source_output_dir,
            depth=depth,
            score=score,
        )
    return len(data.programme_catalog) - rows_before


def _process_json_api_filter_pages(
    data: AdmissionsData,
    result: FetchResult,
    *,
    fetcher: Fetcher,
    discovery_config: DiscoveryConfig,
    pdf_extractor: PDFExtractor,
    classification_assist_provider: ClassificationAssistProvider | None,
    captured_source_texts: dict[str, str],
    source_output_dir: str | Path | None,
    depth: int,
    score: float,
) -> int:
    rows_before = len(data.programme_catalog)
    filter_outcome = fetch_api_catalog_filter_pages(fetcher, result)
    data.run.config.setdefault("programme_catalog_api_filter_enumeration", []).append(filter_outcome.to_dict())
    for filter_capture in filter_outcome.fetched_pages:
        filter_result = filter_capture.result
        if not _record_fetch_result(data, filter_result, captured_source_texts=captured_source_texts, source_output_dir=source_output_dir):
            continue
        filter_context = _build_captured_source_context(
            data,
            DiscoveredPage(result=filter_result, depth=depth + 1, score=score),
            discovery_config,
            pdf_extractor,
            classification_assist_provider,
        )
        filter_source_context = SourceExtractionContext(
            final_url=filter_context.final_url,
            title=filter_context.title,
            source=filter_context.source,
            text=filter_context.extraction_text,
            pdf_pages=filter_context.pdf_pages,
            category=filter_context.classification.category,
        )
        filter_recorder = start_extraction_diagnostics(data, filter_source_context, source_strategy=filter_context.source_strategy)
        if filter_context.source_strategy == "blocked_or_challenge" or filter_result.source.source_type != SourceType.JSON:
            continue
        _process_json_api_with_pagination(
            data,
            filter_result,
            fetcher=fetcher,
            discovery_config=discovery_config,
            pdf_extractor=pdf_extractor,
            classification_assist_provider=classification_assist_provider,
            captured_source_texts=captured_source_texts,
            source_output_dir=source_output_dir,
            depth=depth + 1,
            score=score,
            extraction_recorder=filter_recorder,
            filter_dimensions=filter_capture.filters,
            enable_filter_enumeration=False,
        )
    return len(data.programme_catalog) - rows_before


def _extract_json_api_claims_and_catalog(
    data: AdmissionsData,
    result: FetchResult,
    extraction_recorder,
    *,
    pagination_outcome: ApiCatalogPaginationOutcome,
    page_index: int,
    is_completion_page: bool,
    filter_dimensions: dict[str, str] | None = None,
) -> None:
    catalog_records = extract_programme_catalog_api(
        result.text,
        result.source,
        start_index=len(data.programme_catalog),
    )
    high_cardinality_catalog = _looks_like_high_cardinality_catalog_api(
        result.text,
        catalog_row_count=len(catalog_records),
        pagination_outcome=pagination_outcome,
    )
    programmes, deadlines, fees, documents, api_evidence = extract_api_claims(
        result.text,
        result.source,
        programme_start=len(data.programmes),
        deadline_start=len(data.admissions.application_periods),
        fee_start=len(data.fees),
        document_start=len(data.admissions.required_documents),
    )
    if not high_cardinality_catalog:
        data.programmes.extend(programmes)
        data.evidence.extend(api_evidence)
    else:
        data.evidence.extend(_non_programme_api_evidence(api_evidence))
    data.admissions.application_periods.extend(deadlines)
    data.fees.extend(fees)
    data.admissions.required_documents.extend(documents)

    for record, evidence in catalog_records:
        data.programme_catalog.append(record)
        data.evidence.extend(evidence)
    extraction_recorder.record_count(
        field="programme_catalog",
        extractor="extract_programme_catalog_api",
        reason="json_api",
        claim_path="/programme_catalog",
        record_count=len(catalog_records),
        evidence_count=sum(len(evidence) for _record, evidence in catalog_records),
    )
    diagnostics = programme_catalog_api_diagnostics(result.text, accepted_row_count=len(catalog_records))
    data.run.config.setdefault("programme_catalog_api_diagnostics", []).append(
        {
            "url": result.final_url,
            "pagination_group_url": api_pagination_group_url(result.final_url),
            "source_type": str(result.source.source_type),
            "status": "captured_json",
            **diagnostics,
            "api_page_index": page_index,
            "api_page_count": pagination_outcome.page_count,
            "api_pagination_mode": pagination_outcome.mode,
            "api_pagination_complete": bool(pagination_outcome.completed and is_completion_page),
            "api_pagination_budget_hit": pagination_outcome.budget_hit,
            "api_pagination_stop_reason": pagination_outcome.stop_reason,
            "api_filter_dimensions": dict(sorted((filter_dimensions or {}).items())),
            "api_filter_enumerated": bool(filter_dimensions),
            "legacy_programmes_skipped": high_cardinality_catalog,
        }
    )


def _looks_like_high_cardinality_catalog_api(text: str, *, catalog_row_count: int, pagination_outcome: ApiCatalogPaginationOutcome) -> bool:
    if catalog_row_count > 1:
        return True
    if pagination_outcome.page_count > 1 or pagination_outcome.mode is not None:
        return True
    diagnostics = programme_catalog_api_diagnostics(text, accepted_row_count=catalog_row_count)
    total_count = diagnostics.get("api_total_count")
    return isinstance(total_count, int) and total_count > 1


def _non_programme_api_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    return [item for item in items if not item.claim_path.startswith("/programmes/")]


def apply_incremental_diff(data: AdmissionsData, previous_result: dict[str, Any] | None) -> None:
    if previous_result is None:
        data.warnings.append(WarningRecord(WarningCode.NEEDS_MANUAL_CHECK, "No prior result supplied; incremental diff baseline is unavailable.", field="/run/diff"))
        data.run.config["diff"] = {"baseline": "none", "changed_sources": [], "changed_fields": []}
        return

    previous_hashes = {source.get("source_url"): source.get("content_hash") for source in previous_result.get("sources", [])}
    changed_sources: list[str] = []
    for source in data.sources:
        old_hash = previous_hashes.get(source.source_url)
        if old_hash is not None and old_hash != source.content_hash:
            changed_sources.append(source.source_url)
    current_fields = _field_snapshot(data.to_dict())
    previous_fields = _field_snapshot(previous_result)
    changed_fields = sorted(path for path, value in current_fields.items() if path in previous_fields and previous_fields[path] != value)
    data.run.config["diff"] = {"baseline": "provided", "changed_sources": changed_sources, "changed_fields": changed_fields}
    for url in changed_sources:
        add_warning(data, WarningRecord(WarningCode.INCREMENTAL_CHANGE, "Source content hash changed since previous result.", field=url, source_urls=[url]))
    for path in changed_fields[:20]:
        add_warning(data, WarningRecord(WarningCode.INCREMENTAL_CHANGE, "Extracted field value changed since previous result.", field=path))


def _field_snapshot(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        if set(value.keys()) >= {"value", "status", "confidence"}:
            out[prefix] = value.get("value")
            return out
        for key, subvalue in value.items():
            if key in {"sources", "evidence", "warnings", "run"}:
                continue
            out.update(_field_snapshot(subvalue, f"{prefix}/{key}"))
    elif isinstance(value, list):
        for index, subvalue in enumerate(value):
            out.update(_field_snapshot(subvalue, f"{prefix}/{index}"))
    return out


def _default_pdf_extractor(fetcher: Fetcher) -> PDFExtractor:
    if isinstance(fetcher, FixtureFetcher):
        return FixturePDFExtractor()
    return MissingPDFExtractor()
