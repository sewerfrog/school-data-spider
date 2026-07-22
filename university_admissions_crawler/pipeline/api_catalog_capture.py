"""Safe capture and extraction for public programme catalog APIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from university_admissions_crawler.crawler.discovery import DiscoveredPage, DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import Fetcher, FetchResult
from university_admissions_crawler.crawler.filters import DomainPolicy, allowed_scope_suggestion, canonicalize_url
from university_admissions_crawler.crawler.types import NetworkResponseRecord
from university_admissions_crawler.evidence.provenance import content_hash
from university_admissions_crawler.extractor.api_extractor import extract_api_claims
from university_admissions_crawler.extractor.llm_provider import ClassificationAssistProvider
from university_admissions_crawler.extractor.pdf_extractor import PDFExtractor
from university_admissions_crawler.extractor.programme_catalog_api import catalog_api_body_profile, extract_programme_catalog_api, programme_catalog_api_diagnostics
from university_admissions_crawler.extractor.schema import AdmissionsData, EvidenceItem, SourceRecord, SourceType, WarningCode, WarningRecord
from university_admissions_crawler.pipeline.api_catalog_discovery import (
    MAX_API_RESPONSE_SIZE_BYTES,
    MAX_SAFE_API_CAPTURE_CANDIDATES,
    api_catalog_candidate_capture_urls,
    mark_api_catalog_candidate_capture,
)
from university_admissions_crawler.pipeline.api_catalog_filters import fetch_api_catalog_filter_pages
from university_admissions_crawler.pipeline.api_catalog_pagination import (
    ApiCatalogPaginationOutcome,
    api_pagination_group_url,
    fetch_additional_api_catalog_pages,
)
from university_admissions_crawler.pipeline.category_extraction import SourceExtractionContext, start_extraction_diagnostics
from university_admissions_crawler.pipeline.programme_catalog_merge import merge_programme_catalog_records
from university_admissions_crawler.pipeline.scan_context import build_captured_source_context
from university_admissions_crawler.pipeline.source_capture import domain_policy_for_scan, record_fetch_result


@dataclass(slots=True)
class ApiCatalogCaptureContext:
    fetcher: Fetcher
    discovery_config: DiscoveryConfig
    pdf_extractor: PDFExtractor
    classification_assist_provider: ClassificationAssistProvider | None
    captured_source_texts: dict[str, str]
    source_output_dir: str | Path | None
    domain_policy: DomainPolicy | None = None

    def with_domain_policy(self, domain_policy: DomainPolicy) -> ApiCatalogCaptureContext:
        return ApiCatalogCaptureContext(
            fetcher=self.fetcher,
            discovery_config=self.discovery_config,
            pdf_extractor=self.pdf_extractor,
            classification_assist_provider=self.classification_assist_provider,
            captured_source_texts=self.captured_source_texts,
            source_output_dir=self.source_output_dir,
            domain_policy=domain_policy,
        )


def capture_safe_api_catalog_candidates(
    data: AdmissionsData,
    *,
    context: ApiCatalogCaptureContext,
    network_responses_by_url: dict[str, NetworkResponseRecord] | None = None,
) -> None:
    existing_urls = {canonicalize_url(source.source_url) for source in data.sources}
    candidate_urls = api_catalog_candidate_capture_urls(data, existing_urls=existing_urls)
    network_responses = network_responses_by_url or {}
    seed_url = data.run.input_url or data.institution.homepage_url
    policy = context.domain_policy or domain_policy_for_scan(seed_url, context.discovery_config)
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
        "network_body_urls": [],
        "accepted_row_count": 0,
        "budget_hit": isinstance(pending_count, int) and pending_count > len(candidate_urls),
        "applied_to_facts": False,
        "note": "Safe capture fetches only bounded public JSON API candidates already discovered on allowed official sources.",
    }

    for url in candidate_urls:
        diagnostics["attempted_urls"].append(url)
        network_response = network_responses.get(canonicalize_url(url))
        if network_response is not None and network_response.body_text:
            diagnostics["network_body_urls"].append(url)
            result = _fetch_result_from_network_response(network_response, retrieved_at=data.run.retrieved_at, engine=context.fetcher.engine)
        else:
            try:
                result = context.fetcher.fetch(url)
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
            suggestion = allowed_scope_suggestion(result.final_url)
            data.warnings.extend(result.warnings)
            diagnostics["rejected_urls"].append(
                {
                    "url": url,
                    "reason": "redirected_off_domain",
                    "captured_url": result.final_url,
                    **suggestion,
                }
            )
            mark_api_catalog_candidate_capture(
                data,
                url,
                status="rejected_off_domain",
                content_type=result.content_type,
                response_size_bytes=response_size,
                captured_url=result.final_url,
                rejection_reason="redirected_off_domain",
                suggested_allowed_hosts=suggestion.get("suggested_allowed_hosts"),
                suggested_allowed_domains=suggestion.get("suggested_allowed_domains"),
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
        body_profile = catalog_api_body_profile(result.text)
        if not body_profile.get("api_body_likely_catalog"):
            data.warnings.extend(result.warnings)
            diagnostics["rejected_urls"].append({"url": url, "reason": "body_not_catalog_like"})
            mark_api_catalog_candidate_capture(
                data,
                url,
                status="rejected_body_not_catalog",
                content_type=result.content_type,
                response_size_bytes=response_size,
                captured_url=result.final_url,
                rejection_reason="body_not_catalog_like",
                body_profile=body_profile,
            )
            continue
        if not record_fetch_result(
            data,
            result,
            captured_source_texts=context.captured_source_texts,
            source_output_dir=context.source_output_dir,
            domain_policy=policy,
        ):
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

        captured_context = build_captured_source_context(
            data,
            DiscoveredPage(result=result, depth=1, score=0.0),
            context.discovery_config,
            context.pdf_extractor,
            context.classification_assist_provider,
        )
        source_context = SourceExtractionContext(
            final_url=captured_context.final_url,
            title=captured_context.title,
            source=captured_context.source,
            text=captured_context.extraction_text,
            pdf_pages=captured_context.pdf_pages,
            category=captured_context.classification.category,
            content_blocks=captured_context.content_blocks,
        )
        extraction_recorder = start_extraction_diagnostics(data, source_context, source_strategy=captured_context.source_strategy)
        if captured_context.source_strategy == "blocked_or_challenge":
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
            body_profile=body_profile,
        )
        rows_added = process_json_api_with_pagination(
            data,
            result,
            context=context.with_domain_policy(policy),
            depth=1,
            score=0.0,
            extraction_recorder=extraction_recorder,
        )
        diagnostics["captured_urls"].append(result.final_url)
        diagnostics["accepted_row_count"] += rows_added

    diagnostics["applied_to_facts"] = diagnostics["accepted_row_count"] > 0
    data.run.config["programme_catalog_api_capture"] = diagnostics


def network_responses_by_url(pages: list[DiscoveredPage]) -> dict[str, NetworkResponseRecord]:
    records: dict[str, NetworkResponseRecord] = {}
    for page in pages:
        for record in page.result.network_responses:
            if record.body_text:
                records.setdefault(canonicalize_url(record.url), record)
    return records


def process_json_api_with_pagination(
    data: AdmissionsData,
    result: FetchResult,
    *,
    context: ApiCatalogCaptureContext,
    depth: int,
    score: float,
    extraction_recorder: Any,
    filter_dimensions: dict[str, str] | None = None,
    enable_filter_enumeration: bool = True,
) -> int:
    rows_before = len(data.programme_catalog)
    pagination_outcome = fetch_additional_api_catalog_pages(context.fetcher, result, domain_policy=context.domain_policy)
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
        if not record_fetch_result(
            data,
            paged_result,
            captured_source_texts=context.captured_source_texts,
            source_output_dir=context.source_output_dir,
            domain_policy=context.domain_policy,
        ):
            continue
        paged_context = build_captured_source_context(
            data,
            DiscoveredPage(result=paged_result, depth=depth + 1, score=score),
            context.discovery_config,
            context.pdf_extractor,
            context.classification_assist_provider,
        )
        paged_source_context = SourceExtractionContext(
            final_url=paged_context.final_url,
            title=paged_context.title,
            source=paged_context.source,
            text=paged_context.extraction_text,
            pdf_pages=paged_context.pdf_pages,
            category=paged_context.classification.category,
            content_blocks=paged_context.content_blocks,
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
            context=context,
            depth=depth,
            score=score,
        )
    return len(data.programme_catalog) - rows_before


def _fetch_result_from_network_response(record: NetworkResponseRecord, *, retrieved_at: str, engine: str) -> FetchResult:
    text = record.body_text or ""
    title = Path(urlparse(record.url).path).name or "Network API response"
    source = SourceRecord(
        source_url=record.url,
        source_type=SourceType.JSON,
        title=title,
        retrieved_at=retrieved_at,
        content_hash=content_hash(text),
        engine=engine,
    )
    return FetchResult(
        url=record.url,
        final_url=record.url,
        status=record.status or 200,
        title=title,
        content_type=record.content_type or "application/json",
        retrieved_at=retrieved_at,
        engine=engine,
        text=text,
        markdown=text,
        source=source,
    )


def _process_json_api_filter_pages(
    data: AdmissionsData,
    result: FetchResult,
    *,
    context: ApiCatalogCaptureContext,
    depth: int,
    score: float,
) -> int:
    rows_before = len(data.programme_catalog)
    filter_outcome = fetch_api_catalog_filter_pages(context.fetcher, result, domain_policy=context.domain_policy)
    data.run.config.setdefault("programme_catalog_api_filter_enumeration", []).append(filter_outcome.to_dict())
    for filter_capture in filter_outcome.fetched_pages:
        filter_result = filter_capture.result
        if not record_fetch_result(
            data,
            filter_result,
            captured_source_texts=context.captured_source_texts,
            source_output_dir=context.source_output_dir,
            domain_policy=context.domain_policy,
        ):
            continue
        filter_context = build_captured_source_context(
            data,
            DiscoveredPage(result=filter_result, depth=depth + 1, score=score),
            context.discovery_config,
            context.pdf_extractor,
            context.classification_assist_provider,
        )
        filter_source_context = SourceExtractionContext(
            final_url=filter_context.final_url,
            title=filter_context.title,
            source=filter_context.source,
            text=filter_context.extraction_text,
            pdf_pages=filter_context.pdf_pages,
            category=filter_context.classification.category,
            content_blocks=filter_context.content_blocks,
        )
        filter_recorder = start_extraction_diagnostics(data, filter_source_context, source_strategy=filter_context.source_strategy)
        if filter_context.source_strategy == "blocked_or_challenge" or filter_result.source.source_type != SourceType.JSON:
            continue
        process_json_api_with_pagination(
            data,
            filter_result,
            context=context,
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
    extraction_recorder: Any,
    *,
    pagination_outcome: ApiCatalogPaginationOutcome,
    page_index: int,
    is_completion_page: bool,
    filter_dimensions: dict[str, str] | None = None,
) -> None:
    candidate_diagnostics: list[dict[str, object]] = []
    catalog_records = extract_programme_catalog_api(
        result.text,
        result.source,
        start_index=len(data.programme_catalog),
        candidate_diagnostics=candidate_diagnostics,
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

    diagnostics = programme_catalog_api_diagnostics(result.text, accepted_row_count=len(catalog_records))
    api_completeness_proven = bool(pagination_outcome.completed or diagnostics.get("api_pagination_complete"))
    api_source_role = "canonical_catalog" if api_completeness_proven else "faculty_catalog"
    for item in candidate_diagnostics:
        item["source_role"] = api_source_role
        item["api_completeness_proven"] = api_completeness_proven
    merge_outcome = merge_programme_catalog_records(
        data,
        catalog_records,
        source_role=api_source_role,
        candidate_diagnostics=candidate_diagnostics,
    )
    extraction_recorder.record_count(
        field="programme_catalog",
        extractor="extract_programme_catalog_api",
        reason="json_api",
        claim_path="/programme_catalog",
        record_count=(
            merge_outcome.appended_count
            + merge_outcome.merged_count
            + merge_outcome.replaced_count
        ),
        evidence_count=merge_outcome.evidence_count,
    )
    if candidate_diagnostics:
        data.run.config.setdefault("programme_catalog_candidate_diagnostics", []).extend(candidate_diagnostics)
    _set_captured_api_source_role(
        data,
        result.final_url,
        source_role=api_source_role,
        completeness_proven=api_completeness_proven,
    )
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
            "api_pagination_complete": bool(api_completeness_proven and is_completion_page),
            "api_pagination_budget_hit": pagination_outcome.budget_hit,
            "api_pagination_stop_reason": pagination_outcome.stop_reason,
            "source_role": api_source_role,
            "api_completeness_proven": api_completeness_proven,
            "api_filter_dimensions": dict(sorted((filter_dimensions or {}).items())),
            "api_filter_enumerated": bool(filter_dimensions),
            "legacy_programmes_skipped": high_cardinality_catalog,
        }
    )


def _set_captured_api_source_role(
    data: AdmissionsData,
    url: str,
    *,
    source_role: str,
    completeness_proven: bool,
) -> None:
    source_strategy = data.run.config.get("source_strategy")
    if not isinstance(source_strategy, list):
        return
    for item in reversed(source_strategy):
        if not isinstance(item, dict) or item.get("url") != url:
            continue
        item["source_role"] = source_role
        item["source_role_signals"] = [
            "captured_json_catalog",
            "api_completeness_proven" if completeness_proven else "api_completeness_unproven",
        ]
        return


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
