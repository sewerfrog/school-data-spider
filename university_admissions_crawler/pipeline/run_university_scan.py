"""Pipeline orchestration: discover -> fetch -> classify -> extract -> normalize."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from university_admissions_crawler.classifier.page_classifier import classify_page, is_low_confidence_classification
from university_admissions_crawler.crawler.admissions_context import (
    has_admissions_contact_context,
    has_english_requirement_context,
    has_undergraduate_admissions_context,
    has_undergraduate_fee_context,
    has_undergraduate_scholarship_context,
)
from university_admissions_crawler.crawler.discovery import DiscoveryConfig, discover
from university_admissions_crawler.crawler.fetcher import Fetcher, FixtureFetcher
from university_admissions_crawler.crawler.filters import canonicalize_url
from university_admissions_crawler.crawler.relevance import DEFAULT_RELEVANCE_STRATEGY, KeywordPlan, RelevanceStrategy, relevance_diagnostics
from university_admissions_crawler.evidence.store import write_source_record
from university_admissions_crawler.evidence.provenance import evidence_from_source
from university_admissions_crawler.extractor.api_extractor import extract_api_claims
from university_admissions_crawler.extractor.html_extractor import (
    extract_accepted_qualification,
    extract_contact,
    extract_deadline,
    extract_english_requirement,
    extract_fee,
    extract_housing,
    extract_prerequisite,
    extract_programme,
    extract_programmes,
    extract_required_document,
    extract_scholarship,
    extract_visa,
)
from university_admissions_crawler.extractor.llm_provider import ClassificationAssistProvider, ProgrammeCatalogAssistProvider, SourcePlanProvider, generate_classification_assist_diagnostic
from university_admissions_crawler.extractor.normalizer import add_warning
from university_admissions_crawler.extractor.pdf_extractor import FixturePDFExtractor, MissingPDFExtractor, PDFExtractor
from university_admissions_crawler.extractor.programme_catalog import extract_programme_catalog
from university_admissions_crawler.pipeline.diagnostics import attach_run_diagnostics, attach_template_completeness, source_strategy_for
from university_admissions_crawler.pipeline.source_planning import build_source_plan_diagnostic
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    ClaimStatus,
    Confidence,
    FieldValue,
    Institution,
    PageCategory,
    PageClassificationRecord,
    ProgrammeRecord,
    RequirementRecord,
    RunMetadata,
    SourceType,
    WarningCode,
    WarningRecord,
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
) -> AdmissionsData:
    discovery_config = config or DiscoveryConfig()
    pages = discover(seed_url, fetcher, discovery_config)
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
    pdf_extractor = pdf_extractor or _default_pdf_extractor(fetcher)

    for page in pages:
        result = page.result
        data.warnings.extend(result.warnings)
        if result.source:
            data.sources.append(result.source)
            if source_output_dir is not None:
                write_source_record(source_output_dir, result.source, result.markdown or result.text)
        if not result.ok or not result.source:
            continue
        if result.source.source_type == SourceType.JSON:
            programmes, deadlines, fees, documents, api_evidence = extract_api_claims(
                result.text,
                result.source,
                programme_start=len(data.programmes),
                deadline_start=len(data.admissions.application_periods),
                fee_start=len(data.fees),
                document_start=len(data.admissions.required_documents),
            )
            data.programmes.extend(programmes)
            data.admissions.application_periods.extend(deadlines)
            data.fees.extend(fees)
            data.admissions.required_documents.extend(documents)
            data.evidence.extend(api_evidence)
        discovery_text = result.markdown or result.text
        text = discovery_text
        pdf_pages = []
        if result.source.source_type == SourceType.PDF:
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
                pdf_pages = []
                text = ""
            else:
                data.warnings.extend(pdf_result.warnings)
                pdf_pages = pdf_result.pages
                text = pdf_result.text if pdf_result.pages else ""

        classification = classify_page(result.final_url, result.title, text)
        if classification_assist_provider is not None and is_low_confidence_classification(classification):
            data.run.config.setdefault("classification_assist", []).append(
                generate_classification_assist_diagnostic(
                    url=result.final_url,
                    title=result.title,
                    text=text,
                    rule_category=classification.category,
                    rule_score=classification.score,
                    provider=classification_assist_provider,
                )
            )
        discovery_diagnostics = relevance_diagnostics(
            discovery_config.relevance_strategy,
            result.final_url,
            result.title,
            discovery_text,
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
        strategy = source_strategy_for(result.source.source_type, result.final_url, result.title, text, classification.category)
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
        extraction_attempts: list[dict[str, object]] = []
        extraction_recorder = _ExtractionDiagnosticsRecorder(extraction_attempts)
        extraction_entry = {
            "url": result.final_url,
            "source_type": str(result.source.source_type),
            "category": str(classification.category),
            "attempts": extraction_attempts,
        }
        if strategy == "blocked_or_challenge":
            extraction_entry["source_acquisition_status"] = "blocked_or_challenge"
        data.run.config.setdefault("extraction_diagnostics", []).append(extraction_entry)

        if strategy == "blocked_or_challenge":
            continue

        if classification.category == PageCategory.UNDERGRADUATE_ADMISSIONS:
            claim_path = f"/admissions/application_periods/{len(data.admissions.application_periods)}/value"
            record, evidence = extract_deadline(text, result.source, claim_path)
            extraction_recorder.record_record(
                field="application_periods",
                extractor="extract_deadline",
                record=record,
                evidence=evidence,
                reason="category_route",
                claim_path=claim_path,
            )
            if record:
                data.admissions.application_periods.append(record)
                data.evidence.extend(evidence)
                entry_claim_path = "/admissions/undergraduate_application_entry"
                if data.admissions.undergraduate_application_entry.is_unknownish:
                    data.evidence.append(
                        evidence_from_source(
                            claim_path=entry_claim_path,
                            source=result.source,
                            snippet=result.title or result.final_url,
                            confidence=Confidence.HIGH,
                        )
                    )
                    data.admissions.undergraduate_application_entry = FieldValue(
                        value=result.final_url,
                        status=ClaimStatus.KNOWN,
                        confidence=Confidence.HIGH,
                        evidence=[entry_claim_path],
                    )
                    extraction_recorder.record(
                        field="undergraduate_application_entry",
                        extractor="source_url_from_application_period",
                        status="extracted",
                        reason="category_route",
                        claim_path=entry_claim_path,
                        record_count=1,
                        evidence_count=1,
                    )
                else:
                    extraction_recorder.skip(
                        field="undergraduate_application_entry",
                        extractor="source_url_from_application_period",
                        reason="existing_value",
                        claim_path=entry_claim_path,
                    )
            else:
                extraction_recorder.skip(
                    field="undergraduate_application_entry",
                    extractor="source_url_from_application_period",
                    reason="requires_application_period",
                    claim_path="/admissions/undergraduate_application_entry",
                )
            doc_claim = f"/admissions/required_documents/{len(data.admissions.required_documents)}/value"
            doc_record, doc_evidence = extract_required_document(text, result.source, doc_claim)
            extraction_recorder.record_record(
                field="required_documents",
                extractor="extract_required_document",
                record=doc_record,
                evidence=doc_evidence,
                reason="category_route",
                claim_path=doc_claim,
            )
            if doc_record:
                data.admissions.required_documents.append(doc_record)
                data.evidence.extend(doc_evidence)
        elif classification.category == PageCategory.INTERNATIONAL_REQUIREMENTS:
            claim_path = f"/admissions/english_requirements/{len(data.admissions.english_requirements)}/value"
            has_context = has_english_requirement_context(result.final_url, result.title, text)
            record, evidence = (extract_english_requirement(text, result.source, claim_path) if has_context else (None, []))
            if has_context:
                extraction_recorder.record_record(
                    field="english_requirements",
                    extractor="extract_english_requirement",
                    record=record,
                    evidence=evidence,
                    reason="category_route",
                    claim_path=claim_path,
                )
            else:
                extraction_recorder.skip(field="english_requirements", extractor="extract_english_requirement", reason="context_gate_failed", claim_path=claim_path)
            if record:
                data.admissions.english_requirements.append(record)
                data.evidence.extend(evidence)
        elif classification.category == PageCategory.APPLICATION_DEADLINES:
            claim_path = f"/admissions/application_periods/{len(data.admissions.application_periods)}/value"
            record, evidence = extract_deadline(text, result.source, claim_path)
            extraction_recorder.record_record(
                field="application_periods",
                extractor="extract_deadline",
                record=record,
                evidence=evidence,
                reason="category_route",
                claim_path=claim_path,
            )
            if record:
                data.admissions.application_periods.append(record)
                data.evidence.extend(evidence)
        elif classification.category == PageCategory.ACCEPTED_QUALIFICATIONS:
            claim_path = f"/admissions/accepted_qualifications/{len(data.admissions.accepted_qualifications)}/value"
            record, evidence = extract_accepted_qualification(text, result.source, claim_path)
            extraction_recorder.record_record(
                field="accepted_qualifications",
                extractor="extract_accepted_qualification",
                record=record,
                evidence=evidence,
                reason="category_route",
                claim_path=claim_path,
            )
            if record:
                data.admissions.accepted_qualifications.append(record)
                data.evidence.extend(evidence)
        elif classification.category in {PageCategory.PROGRAMME_LIST, PageCategory.PROGRAMME_PREREQUISITES}:
            _append_programme_catalog(data, text, result.source, extraction_recorder, reason="category_route", assist_provider=programme_catalog_assist_provider)
            programme_start = len(data.programmes)
            programme_claim = f"/programmes/{programme_start}/name"
            programme_records = extract_programmes(text, result.source, "/programmes", programme_start)
            extraction_recorder.record_count(
                field="programmes",
                extractor="extract_programmes",
                reason="category_route",
                claim_path="/programmes",
                record_count=len(programme_records),
                evidence_count=sum(len(evidence) for _programme, evidence in programme_records),
            )
            programme_name = None
            programme_evidence = []
            if not programme_records:
                programme_name, programme_evidence = extract_programme(text, result.source, programme_claim)
                extraction_recorder.record_record(
                    field="programmes",
                    extractor="extract_programme",
                    record=programme_name,
                    evidence=programme_evidence,
                    reason="fallback_single_programme",
                    claim_path=programme_claim,
                )
            prereq_claim = f"/programmes/{programme_start}/prerequisites/0/value"
            prereq, prereq_evidence = _extract_prerequisite_with_pdf_page(text, result.source, prereq_claim, pdf_pages)
            extraction_recorder.record_record(
                field="programme_prerequisites",
                extractor="extract_prerequisite",
                record=prereq,
                evidence=prereq_evidence,
                reason="category_route",
                claim_path=prereq_claim,
            )
            if programme_records:
                for index, (programme, evidence) in enumerate(programme_records):
                    if index == 0 and prereq:
                        programme.prerequisites.append(prereq)
                        data.evidence.extend(prereq_evidence)
                    data.programmes.append(programme)
                    data.evidence.extend(evidence)
            elif programme_name:
                programme = ProgrammeRecord(
                    name=FieldValue(value=programme_name, status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[programme_claim]),
                    source_url=result.final_url,
                    prerequisites=[prereq] if prereq else [],
                    evidence=[programme_claim],
                )
                data.programmes.append(programme)
                data.evidence.extend(programme_evidence)
                data.evidence.extend(prereq_evidence)
            elif prereq:
                if data.programmes:
                    programme_index = 0
                    dest_index = len(data.programmes[programme_index].prerequisites)
                    dest_claim = f"/programmes/{programme_index}/prerequisites/{dest_index}/value"
                    prereq.value.evidence = [dest_claim]
                    for item in prereq_evidence:
                        item.claim_path = dest_claim
                    data.programmes[programme_index].prerequisites.append(prereq)
                else:
                    dest_index = len(data.admissions.accepted_qualifications)
                    dest_claim = f"/admissions/accepted_qualifications/{dest_index}/value"
                    prereq.value.evidence = [dest_claim]
                    for item in prereq_evidence:
                        item.claim_path = dest_claim
                    data.admissions.accepted_qualifications.append(prereq)
                data.evidence.extend(prereq_evidence)
        elif classification.category == PageCategory.FEES:
            claim_path = f"/fees/{len(data.fees)}/value"
            if has_undergraduate_fee_context(result.final_url, result.title, text):
                record_count, evidence_count = _append_requirement(data.fees, data.evidence, extract_fee, text, result.source, claim_path)
                extraction_recorder.record_count(
                    field="fees",
                    extractor="extract_fee",
                    reason="category_route",
                    claim_path=claim_path,
                    record_count=record_count,
                    evidence_count=evidence_count,
                )
            else:
                extraction_recorder.skip(field="fees", extractor="extract_fee", reason="context_gate_failed", claim_path=claim_path)
        elif classification.category == PageCategory.SCHOLARSHIPS:
            claim_path = f"/scholarships/{len(data.scholarships)}/value"
            if has_undergraduate_scholarship_context(result.final_url, result.title, text):
                record_count, evidence_count = _append_requirement(data.scholarships, data.evidence, extract_scholarship, text, result.source, claim_path)
                extraction_recorder.record_count(
                    field="scholarships",
                    extractor="extract_scholarship",
                    reason="category_route",
                    claim_path=claim_path,
                    record_count=record_count,
                    evidence_count=evidence_count,
                )
            else:
                extraction_recorder.skip(field="scholarships", extractor="extract_scholarship", reason="context_gate_failed", claim_path=claim_path)
        elif classification.category == PageCategory.VISA:
            claim_path = f"/visa/{len(data.visa)}/value"
            record_count, evidence_count = _append_requirement(data.visa, data.evidence, extract_visa, text, result.source, claim_path)
            extraction_recorder.record_count(
                field="visa",
                extractor="extract_visa",
                reason="category_route",
                claim_path=claim_path,
                record_count=record_count,
                evidence_count=evidence_count,
            )
        elif classification.category == PageCategory.HOUSING:
            claim_path = f"/housing/{len(data.housing)}/value"
            record_count, evidence_count = _append_requirement(data.housing, data.evidence, extract_housing, text, result.source, claim_path)
            extraction_recorder.record_count(
                field="housing",
                extractor="extract_housing",
                reason="category_route",
                claim_path=claim_path,
                record_count=record_count,
                evidence_count=evidence_count,
            )
        elif classification.category == PageCategory.CONTACT:
            claim_path = f"/contacts/{len(data.contacts)}/value"
            if has_admissions_contact_context(result.final_url, result.title, text):
                record_count, evidence_count = _append_requirement(data.contacts, data.evidence, extract_contact, text, result.source, claim_path)
                extraction_recorder.record_count(
                    field="contacts",
                    extractor="extract_contact",
                    reason="category_route",
                    claim_path=claim_path,
                    record_count=record_count,
                    evidence_count=evidence_count,
                )
            else:
                extraction_recorder.skip(field="contacts", extractor="extract_contact", reason="context_gate_failed", claim_path=claim_path)

        if classification.category != PageCategory.IRRELEVANT:
            if has_undergraduate_admissions_context(result.final_url, result.title, text):
                _extract_core_supplements(data, text, result.source, extraction_recorder)
            else:
                extraction_recorder.skip(
                    field="core_supplements",
                    extractor="extract_core_supplements",
                    reason="undergraduate_context_gate_failed",
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
    return attach_validation_warnings(data)


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


def _append_requirement(dest: list[RequirementRecord], evidence_dest, extractor, text, source, claim_path: str) -> tuple[int, int]:
    record, evidence = extractor(text, source, claim_path)
    if record:
        dest.append(record)
        evidence_dest.extend(evidence)
        return 1, len(evidence)
    return 0, 0


def _default_pdf_extractor(fetcher: Fetcher) -> PDFExtractor:
    if isinstance(fetcher, FixtureFetcher):
        return FixturePDFExtractor()
    return MissingPDFExtractor()


def _append_programme_catalog(
    data: AdmissionsData,
    text: str,
    source,
    recorder: "_ExtractionDiagnosticsRecorder",
    *,
    reason: str,
    assist_provider: ProgrammeCatalogAssistProvider | None = None,
) -> None:
    catalog_records = extract_programme_catalog(text, source, start_index=len(data.programme_catalog), assist_provider=assist_provider)
    for record, evidence in catalog_records:
        data.programme_catalog.append(record)
        data.evidence.extend(evidence)
    recorder.record_count(
        field="programme_catalog",
        extractor="extract_programme_catalog",
        reason=reason,
        claim_path="/programme_catalog",
        record_count=len(catalog_records),
        evidence_count=sum(len(evidence) for _record, evidence in catalog_records),
    )


def _extract_core_supplements(data: AdmissionsData, text: str, source, recorder: "_ExtractionDiagnosticsRecorder") -> None:
    if not data.admissions.application_periods:
        claim_path = f"/admissions/application_periods/{len(data.admissions.application_periods)}/value"
        status, record_count, evidence_count = _append_unique_requirement(data.admissions.application_periods, data.evidence, extract_deadline, text, source, claim_path)
        recorder.record(field="application_periods", extractor="extract_deadline", status=status, reason="core_supplement", claim_path=claim_path, record_count=record_count, evidence_count=evidence_count)
    else:
        recorder.skip(field="application_periods", extractor="extract_deadline", reason="existing_value")
    if not data.admissions.english_requirements:
        claim_path = f"/admissions/english_requirements/{len(data.admissions.english_requirements)}/value"
        if has_english_requirement_context(source.source_url, source.title, text):
            status, record_count, evidence_count = _append_unique_requirement(data.admissions.english_requirements, data.evidence, extract_english_requirement, text, source, claim_path)
            recorder.record(field="english_requirements", extractor="extract_english_requirement", status=status, reason="core_supplement", claim_path=claim_path, record_count=record_count, evidence_count=evidence_count)
        else:
            recorder.skip(field="english_requirements", extractor="extract_english_requirement", reason="context_gate_failed", claim_path=claim_path)
    else:
        recorder.skip(field="english_requirements", extractor="extract_english_requirement", reason="existing_value")
    if not data.fees:
        claim_path = f"/fees/{len(data.fees)}/value"
        if has_undergraduate_fee_context(source.source_url, source.title, text):
            status, record_count, evidence_count = _append_unique_requirement(data.fees, data.evidence, extract_fee, text, source, claim_path)
            recorder.record(field="fees", extractor="extract_fee", status=status, reason="core_supplement", claim_path=claim_path, record_count=record_count, evidence_count=evidence_count)
        else:
            recorder.skip(field="fees", extractor="extract_fee", reason="context_gate_failed", claim_path=claim_path)
    else:
        recorder.skip(field="fees", extractor="extract_fee", reason="existing_value")
    if not data.scholarships:
        claim_path = f"/scholarships/{len(data.scholarships)}/value"
        if has_undergraduate_scholarship_context(source.source_url, source.title, text):
            status, record_count, evidence_count = _append_unique_requirement(data.scholarships, data.evidence, extract_scholarship, text, source, claim_path)
            recorder.record(field="scholarships", extractor="extract_scholarship", status=status, reason="core_supplement", claim_path=claim_path, record_count=record_count, evidence_count=evidence_count)
        else:
            recorder.skip(field="scholarships", extractor="extract_scholarship", reason="context_gate_failed", claim_path=claim_path)
    else:
        recorder.skip(field="scholarships", extractor="extract_scholarship", reason="existing_value")
    if not data.contacts:
        claim_path = f"/contacts/{len(data.contacts)}/value"
        if has_admissions_contact_context(source.source_url, source.title, text):
            status, record_count, evidence_count = _append_unique_requirement(data.contacts, data.evidence, extract_contact, text, source, claim_path)
            recorder.record(field="contacts", extractor="extract_contact", status=status, reason="core_supplement", claim_path=claim_path, record_count=record_count, evidence_count=evidence_count)
        else:
            recorder.skip(field="contacts", extractor="extract_contact", reason="context_gate_failed", claim_path=claim_path)
    else:
        recorder.skip(field="contacts", extractor="extract_contact", reason="existing_value")
    if not data.programmes:
        programme_count = 0
        evidence_count = 0
        for programme, evidence in extract_programmes(text, source, "/programmes", len(data.programmes)):
            data.programmes.append(programme)
            data.evidence.extend(evidence)
            programme_count += 1
            evidence_count += len(evidence)
        recorder.record_count(
            field="programmes",
            extractor="extract_programmes",
            reason="core_supplement",
            claim_path="/programmes",
            record_count=programme_count,
            evidence_count=evidence_count,
        )
    else:
        recorder.skip(field="programmes", extractor="extract_programmes", reason="existing_value")


def _append_unique_requirement(dest: list[RequirementRecord], evidence_dest, extractor, text, source, claim_path: str) -> tuple[str, int, int]:
    record, evidence = extractor(text, source, claim_path)
    if not record:
        return "no_match", 0, 0
    value = str(record.value.value).strip().lower()
    if any(str(existing.value.value).strip().lower() == value for existing in dest):
        return "skipped", 0, 0
    dest.append(record)
    evidence_dest.extend(evidence)
    return "extracted", 1, len(evidence)


class _ExtractionDiagnosticsRecorder:
    def __init__(self, attempts: list[dict[str, object]]) -> None:
        self.attempts = attempts

    def record(
        self,
        *,
        field: str,
        extractor: str,
        status: str,
        reason: str,
        claim_path: str | None = None,
        record_count: int = 0,
        evidence_count: int = 0,
    ) -> None:
        _record_extraction_attempt(
            self.attempts,
            field=field,
            extractor=extractor,
            status=status,
            reason=reason,
            claim_path=claim_path,
            record_count=record_count,
            evidence_count=evidence_count,
        )

    def record_record(self, *, field: str, extractor: str, record, evidence, reason: str, claim_path: str) -> None:
        self.record(
            field=field,
            extractor=extractor,
            status="extracted" if record else "no_match",
            reason=reason,
            claim_path=claim_path,
            record_count=1 if record else 0,
            evidence_count=len(evidence),
        )

    def record_count(self, *, field: str, extractor: str, reason: str, claim_path: str, record_count: int, evidence_count: int) -> None:
        self.record(
            field=field,
            extractor=extractor,
            status="extracted" if record_count else "no_match",
            reason=reason,
            claim_path=claim_path,
            record_count=record_count,
            evidence_count=evidence_count,
        )

    def skip(self, *, field: str, extractor: str, reason: str, claim_path: str | None = None) -> None:
        self.record(field=field, extractor=extractor, status="skipped", reason=reason, claim_path=claim_path)


def _record_extraction_attempt(
    attempts: list[dict[str, object]],
    *,
    field: str,
    extractor: str,
    status: str,
    reason: str,
    claim_path: str | None = None,
    record_count: int = 0,
    evidence_count: int = 0,
) -> None:
    attempt: dict[str, object] = {
        "field": field,
        "extractor": extractor,
        "status": status,
        "reason": reason,
        "record_count": record_count,
        "evidence_count": evidence_count,
    }
    if claim_path:
        attempt["claim_path"] = claim_path
    attempts.append(attempt)


def _extract_prerequisite_with_pdf_page(text, source, claim_path: str, pdf_pages):
    if not pdf_pages:
        return extract_prerequisite(text, source, claim_path)
    for page in pdf_pages:
        record, evidence = extract_prerequisite(page.text, source, claim_path, page_number=page.page_number)
        if record:
            return record, evidence
    return extract_prerequisite(text, source, claim_path)
