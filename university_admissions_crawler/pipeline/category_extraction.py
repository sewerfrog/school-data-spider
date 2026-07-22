"""Category-routed deterministic extraction for captured admissions sources."""

from __future__ import annotations

from dataclasses import dataclass

from university_admissions_crawler.crawler.admissions_context import (
    has_admissions_contact_context,
    has_english_requirement_context,
    has_undergraduate_admissions_context,
    has_undergraduate_fee_context,
    has_undergraduate_scholarship_context,
)
from university_admissions_crawler.crawler.filters import canonicalize_url
from university_admissions_crawler.crawler.html_text import HTMLContentBlock
from university_admissions_crawler.crawler.programme_sources import (
    classify_programme_source_role,
    is_catalog_backed_programme_detail_source,
    is_explicit_programme_detail_source,
)
from university_admissions_crawler.evidence.provenance import evidence_from_source
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
from university_admissions_crawler.extractor.llm_provider import ProgrammeCatalogAssistProvider
from university_admissions_crawler.extractor.pdf_extractor import PDFPageText
from university_admissions_crawler.extractor.programme_catalog import extract_programme_catalog
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    ClaimStatus,
    Confidence,
    EvidenceItem,
    FieldValue,
    PageCategory,
    ProgrammeCatalogRecord,
    ProgrammeRecord,
    RequirementRecord,
    SourceRecord,
)
from university_admissions_crawler.pipeline.programme_catalog_merge import (
    compatible_programme_detail_indexes,
    compatible_programme_indexes,
    merge_programme_catalog_records,
    remove_resolved_programme_field_warning,
)


@dataclass(slots=True)
class SourceExtractionContext:
    final_url: str
    title: str | None
    source: SourceRecord
    text: str
    pdf_pages: list[PDFPageText]
    category: PageCategory
    content_blocks: tuple[HTMLContentBlock, ...] = ()
    requested_url: str | None = None


def start_extraction_diagnostics(
    data: AdmissionsData,
    context: SourceExtractionContext,
    *,
    source_strategy: str,
) -> "ExtractionDiagnosticsRecorder":
    extraction_attempts: list[dict[str, object]] = []
    extraction_entry: dict[str, object] = {
        "url": context.final_url,
        "source_type": str(context.source.source_type),
        "category": str(context.category),
        "attempts": extraction_attempts,
    }
    if source_strategy == "blocked_or_challenge":
        extraction_entry["source_acquisition_status"] = "blocked_or_challenge"
    data.run.config.setdefault("extraction_diagnostics", []).append(extraction_entry)
    return ExtractionDiagnosticsRecorder(extraction_attempts)


def extract_category_route(
    data: AdmissionsData,
    context: SourceExtractionContext,
    recorder: "ExtractionDiagnosticsRecorder",
    *,
    programme_catalog_assist_provider: ProgrammeCatalogAssistProvider | None,
) -> None:
    text = context.text
    source = context.source
    category = context.category
    final_url = context.final_url
    title = context.title
    category_routes_programme_catalog = category in {
        PageCategory.PROGRAMME_LIST,
        PageCategory.PROGRAMME_PREREQUISITES,
    }
    if (
        not category_routes_programme_catalog
        and classify_programme_source_role(final_url, title, text, context.content_blocks).role == "programme_detail"
        and is_explicit_programme_detail_source(final_url, title)
    ):
        _append_programme_catalog(
            data,
            text,
            source,
            recorder,
            reason="explicit_programme_detail",
            assist_provider=programme_catalog_assist_provider,
            content_blocks=context.content_blocks,
            requested_url=context.requested_url,
        )

    if category == PageCategory.UNDERGRADUATE_ADMISSIONS:
        claim_path = f"/admissions/application_periods/{len(data.admissions.application_periods)}/value"
        record, evidence = extract_deadline(text, source, claim_path)
        recorder.record_record(
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
                        source=source,
                        snippet=title or final_url,
                        confidence=Confidence.HIGH,
                    )
                )
                data.admissions.undergraduate_application_entry = FieldValue(
                    value=final_url,
                    status=ClaimStatus.KNOWN,
                    confidence=Confidence.HIGH,
                    evidence=[entry_claim_path],
                )
                recorder.record(
                    field="undergraduate_application_entry",
                    extractor="source_url_from_application_period",
                    status="extracted",
                    reason="category_route",
                    claim_path=entry_claim_path,
                    record_count=1,
                    evidence_count=1,
                )
            else:
                recorder.skip(
                    field="undergraduate_application_entry",
                    extractor="source_url_from_application_period",
                    reason="existing_value",
                    claim_path=entry_claim_path,
                )
        else:
            recorder.skip(
                field="undergraduate_application_entry",
                extractor="source_url_from_application_period",
                reason="requires_application_period",
                claim_path="/admissions/undergraduate_application_entry",
            )
        doc_claim = f"/admissions/required_documents/{len(data.admissions.required_documents)}/value"
        doc_record, doc_evidence = extract_required_document(text, source, doc_claim)
        recorder.record_record(
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
    elif category == PageCategory.INTERNATIONAL_REQUIREMENTS:
        claim_path = f"/admissions/english_requirements/{len(data.admissions.english_requirements)}/value"
        has_context = has_english_requirement_context(final_url, title, text)
        record, evidence = (extract_english_requirement(text, source, claim_path) if has_context else (None, []))
        if has_context:
            recorder.record_record(
                field="english_requirements",
                extractor="extract_english_requirement",
                record=record,
                evidence=evidence,
                reason="category_route",
                claim_path=claim_path,
            )
        else:
            recorder.skip(field="english_requirements", extractor="extract_english_requirement", reason="context_gate_failed", claim_path=claim_path)
        if record:
            data.admissions.english_requirements.append(record)
            data.evidence.extend(evidence)
    elif category == PageCategory.APPLICATION_DEADLINES:
        claim_path = f"/admissions/application_periods/{len(data.admissions.application_periods)}/value"
        record, evidence = extract_deadline(text, source, claim_path)
        recorder.record_record(
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
    elif category == PageCategory.ACCEPTED_QUALIFICATIONS:
        claim_path = f"/admissions/accepted_qualifications/{len(data.admissions.accepted_qualifications)}/value"
        record, evidence = extract_accepted_qualification(text, source, claim_path)
        recorder.record_record(
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
    elif category_routes_programme_catalog:
        _append_programme_catalog(
            data,
            text,
            source,
            recorder,
            reason="category_route",
            assist_provider=programme_catalog_assist_provider,
            content_blocks=context.content_blocks,
            requested_url=context.requested_url,
        )
        programme_start = len(data.programmes)
        programme_claim = f"/programmes/{programme_start}/name"
        programme_records = extract_programmes(text, source, "/programmes", programme_start)
        recorder.record_count(
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
            programme_name, programme_evidence = extract_programme(text, source, programme_claim)
            recorder.record_record(
                field="programmes",
                extractor="extract_programme",
                record=programme_name,
                evidence=programme_evidence,
                reason="fallback_single_programme",
                claim_path=programme_claim,
            )
        prereq_claim = f"/programmes/{programme_start}/prerequisites/0/value"
        prereq, prereq_evidence = _extract_prerequisite_with_pdf_page(text, source, prereq_claim, context.pdf_pages)
        recorder.record_record(
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
                source_url=final_url,
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
    elif category == PageCategory.FEES:
        claim_path = f"/fees/{len(data.fees)}/value"
        if has_undergraduate_fee_context(final_url, title, text):
            record_count, evidence_count = _append_requirement(data.fees, data.evidence, extract_fee, text, source, claim_path)
            recorder.record_count(
                field="fees",
                extractor="extract_fee",
                reason="category_route",
                claim_path=claim_path,
                record_count=record_count,
                evidence_count=evidence_count,
            )
        else:
            recorder.skip(field="fees", extractor="extract_fee", reason="context_gate_failed", claim_path=claim_path)
    elif category == PageCategory.SCHOLARSHIPS:
        claim_path = f"/scholarships/{len(data.scholarships)}/value"
        if has_undergraduate_scholarship_context(final_url, title, text):
            record_count, evidence_count = _append_requirement(data.scholarships, data.evidence, extract_scholarship, text, source, claim_path)
            recorder.record_count(
                field="scholarships",
                extractor="extract_scholarship",
                reason="category_route",
                claim_path=claim_path,
                record_count=record_count,
                evidence_count=evidence_count,
            )
        else:
            recorder.skip(field="scholarships", extractor="extract_scholarship", reason="context_gate_failed", claim_path=claim_path)
    elif category == PageCategory.VISA:
        claim_path = f"/visa/{len(data.visa)}/value"
        record_count, evidence_count = _append_requirement(data.visa, data.evidence, extract_visa, text, source, claim_path)
        recorder.record_count(
            field="visa",
            extractor="extract_visa",
            reason="category_route",
            claim_path=claim_path,
            record_count=record_count,
            evidence_count=evidence_count,
        )
    elif category == PageCategory.HOUSING:
        claim_path = f"/housing/{len(data.housing)}/value"
        record_count, evidence_count = _append_requirement(data.housing, data.evidence, extract_housing, text, source, claim_path)
        recorder.record_count(
            field="housing",
            extractor="extract_housing",
            reason="category_route",
            claim_path=claim_path,
            record_count=record_count,
            evidence_count=evidence_count,
        )
    elif category == PageCategory.CONTACT:
        claim_path = f"/contacts/{len(data.contacts)}/value"
        if has_admissions_contact_context(final_url, title, text):
            record_count, evidence_count = _append_requirement(data.contacts, data.evidence, extract_contact, text, source, claim_path)
            recorder.record_count(
                field="contacts",
                extractor="extract_contact",
                reason="category_route",
                claim_path=claim_path,
                record_count=record_count,
                evidence_count=evidence_count,
            )
        else:
            recorder.skip(field="contacts", extractor="extract_contact", reason="context_gate_failed", claim_path=claim_path)


def extract_core_supplements_for_context(
    data: AdmissionsData,
    context: SourceExtractionContext,
    recorder: "ExtractionDiagnosticsRecorder",
) -> None:
    if context.category == PageCategory.IRRELEVANT:
        return
    if has_undergraduate_admissions_context(context.final_url, context.title, context.text):
        _extract_core_supplements(data, context.text, context.source, recorder)
    else:
        recorder.skip(
            field="core_supplements",
            extractor="extract_core_supplements",
            reason="undergraduate_context_gate_failed",
        )


def _append_requirement(dest: list[RequirementRecord], evidence_dest, extractor, text, source, claim_path: str) -> tuple[int, int]:
    record, evidence = extractor(text, source, claim_path)
    if record:
        dest.append(record)
        evidence_dest.extend(evidence)
        return 1, len(evidence)
    return 0, 0


def _append_programme_catalog(
    data: AdmissionsData,
    text: str,
    source,
    recorder: "ExtractionDiagnosticsRecorder",
    *,
    reason: str,
    assist_provider: ProgrammeCatalogAssistProvider | None = None,
    content_blocks: tuple[HTMLContentBlock, ...] = (),
    requested_url: str | None = None,
) -> None:
    candidate_diagnostics: list[dict[str, object]] = []
    source_role = classify_programme_source_role(source.source_url, source.title, text, content_blocks).role
    catalog_records = extract_programme_catalog(
        text,
        source,
        start_index=len(data.programme_catalog),
        assist_provider=assist_provider,
        candidate_diagnostics=candidate_diagnostics,
        content_blocks=content_blocks,
    )
    accepted_records = 0
    appended_evidence = 0
    if source_role == "programme_detail":
        appended_evidence = _apply_programme_detail_enrichments(
            data,
            source,
            catalog_records,
            candidate_diagnostics,
            requested_url=requested_url,
        )
    else:
        outcome = merge_programme_catalog_records(
            data,
            catalog_records,
            source_role=source_role,
            candidate_diagnostics=candidate_diagnostics,
        )
        accepted_records = outcome.appended_count + outcome.merged_count + outcome.replaced_count
        appended_evidence = outcome.evidence_count
    if candidate_diagnostics:
        data.run.config.setdefault("programme_catalog_candidate_diagnostics", []).extend(candidate_diagnostics)
    recorder.record_count(
        field="programme_catalog",
        extractor="extract_programme_catalog",
        reason=reason,
        claim_path="/programme_catalog",
        record_count=accepted_records,
        evidence_count=appended_evidence,
    )


def _apply_programme_detail_enrichments(
    data: AdmissionsData,
    source: SourceRecord,
    catalog_records: list[tuple[ProgrammeCatalogRecord, list[EvidenceItem]]],
    candidate_diagnostics: list[dict[str, object]],
    *,
    requested_url: str | None,
) -> int:
    evidence_count = 0
    eligible_source_urls = _catalog_enumeration_source_urls(data)
    enrichment_entries = data.run.config.setdefault("programme_catalog_detail_enrichment_diagnostics", [])
    for candidate, candidate_evidence in catalog_records:
        match = _stable_programme_detail_match(
            data,
            candidate,
            eligible_source_urls,
            requested_url=requested_url,
        )
        candidate_diagnostic = next(
            (
                item
                for item in candidate_diagnostics
                if item.get("decision") == "accepted" and item.get("claim_path") == candidate.evidence_path
            ),
            None,
        )
        if match is None:
            rejection_reason = _programme_detail_rejection_reason(
                data,
                candidate,
                eligible_source_urls,
            )
            _rewrite_detail_candidate_diagnostic(candidate_diagnostic, decision="rejected", reason=rejection_reason)
            if isinstance(enrichment_entries, list):
                enrichment_entries.append(
                    {
                        "source_url": source.source_url,
                        "programme_name": candidate.name,
                        "decision": "rejected",
                        "reason": rejection_reason,
                    }
                )
            continue

        matched_index, match_method = match
        existing = data.programme_catalog[matched_index]
        enriched_fields: list[str] = []
        enrichment_mapping = data.run.config.setdefault("programme_catalog_enrichment_evidence", {})
        row_mapping: dict[str, object] | None = None
        if isinstance(enrichment_mapping, dict):
            configured = enrichment_mapping.setdefault(existing.evidence_path, {})
            if isinstance(configured, dict):
                row_mapping = configured
        field_evidence_paths = (
            candidate_diagnostic.get("field_evidence_paths", {})
            if isinstance(candidate_diagnostic, dict)
            else {}
        )
        for field_name in ("faculty_or_school", "mode", "duration_or_units"):
            candidate_value = getattr(candidate, field_name)
            if getattr(existing, field_name) or not candidate_value:
                continue
            setattr(existing, field_name, candidate_value)
            claim_path = f"/programme_catalog/{matched_index}/{field_name}"
            source_evidence_path = (
                field_evidence_paths.get(field_name)
                if isinstance(field_evidence_paths, dict)
                else None
            )
            source_evidence = next(
                (item for item in candidate_evidence if item.claim_path == source_evidence_path),
                None,
            )
            evidence = evidence_from_source(
                claim_path=claim_path,
                source=source,
                snippet=source_evidence.snippet if source_evidence else candidate.evidence_snippet,
                confidence=source_evidence.confidence if source_evidence else candidate.evidence_confidence,
            )
            data.evidence.append(evidence)
            evidence_count += 1
            enriched_fields.append(field_name)
            remove_resolved_programme_field_warning(existing, field_name)
            if row_mapping is not None:
                row_mapping[field_name] = {
                    "claim_path": claim_path,
                    "source_url": source.source_url,
                }

        reason = "detail_enriched_existing_row" if enriched_fields else "detail_matched_no_missing_fields"
        _rewrite_detail_candidate_diagnostic(candidate_diagnostic, decision="context", reason=reason)
        if candidate_diagnostic is not None:
            candidate_diagnostic["matched_claim_path"] = existing.evidence_path
            candidate_diagnostic["enriched_fields"] = enriched_fields
            candidate_diagnostic["match_method"] = match_method
        if isinstance(enrichment_entries, list):
            enrichment_entries.append(
                {
                    "source_url": source.source_url,
                    "programme_name": candidate.name,
                    "decision": "enriched" if enriched_fields else "matched",
                    "matched_claim_path": existing.evidence_path,
                    "enriched_fields": enriched_fields,
                    "match_method": match_method,
                }
            )
    return evidence_count


def _catalog_enumeration_source_urls(data: AdmissionsData) -> set[str]:
    source_strategy = data.run.config.get("source_strategy")
    if not isinstance(source_strategy, list):
        return set()
    return {
        str(item.get("url"))
        for item in source_strategy
        if isinstance(item, dict)
        and item.get("source_role") in {"canonical_catalog", "faculty_catalog"}
        and item.get("url")
    }


def _stable_programme_detail_match(
    data: AdmissionsData,
    candidate: ProgrammeCatalogRecord,
    eligible_source_urls: set[str],
    *,
    requested_url: str | None,
) -> tuple[int, str] | None:
    linked_matches = _linked_programme_detail_indexes(
        data,
        candidate.source_url,
        requested_url=requested_url,
        eligible_source_urls=eligible_source_urls,
    )
    if len(linked_matches) == 1:
        return linked_matches[0], "primary_source_url"
    if len(linked_matches) > 1:
        return None
    if not is_catalog_backed_programme_detail_source(candidate.source_url, eligible_source_urls):
        return None
    matches = compatible_programme_indexes(
        data,
        candidate,
        eligible_source_urls=eligible_source_urls,
    )
    if len(matches) == 1:
        return matches[0], "catalog_identity"
    if len(matches) > 1:
        return None
    detail_matches = compatible_programme_detail_indexes(
        data,
        candidate,
        eligible_source_urls=eligible_source_urls,
    )
    return (detail_matches[0], "detail_title_identity") if len(detail_matches) == 1 else None


def _programme_detail_rejection_reason(
    data: AdmissionsData,
    candidate: ProgrammeCatalogRecord,
    eligible_source_urls: set[str],
) -> str:
    if (
        not is_catalog_backed_programme_detail_source(candidate.source_url, eligible_source_urls)
        and (
            compatible_programme_indexes(data, candidate, eligible_source_urls=eligible_source_urls)
            or compatible_programme_detail_indexes(data, candidate, eligible_source_urls=eligible_source_urls)
        )
    ):
        return "detail_source_family_without_catalog_context"
    return "detail_without_canonical_match"
def _linked_programme_detail_indexes(
    data: AdmissionsData,
    source_url: str,
    *,
    requested_url: str | None,
    eligible_source_urls: set[str],
) -> list[int]:
    detail_urls = {
        canonicalize_url(url)
        for url in (source_url, requested_url)
        if isinstance(url, str) and url
    }
    provenance = data.run.config.get("programme_catalog_row_provenance")
    if not detail_urls or not isinstance(provenance, dict):
        return []
    matches: list[int] = []
    for index, row in enumerate(data.programme_catalog):
        if row.source_url not in eligible_source_urls:
            continue
        item = provenance.get(row.evidence_path)
        primary_urls = item.get("primary_source_urls") if isinstance(item, dict) else None
        if not isinstance(primary_urls, list):
            continue
        if detail_urls.intersection(
            canonicalize_url(url) for url in primary_urls if isinstance(url, str) and url
        ):
            matches.append(index)
    return matches


def _rewrite_detail_candidate_diagnostic(
    diagnostic: dict[str, object] | None,
    *,
    decision: str,
    reason: str,
) -> None:
    if diagnostic is None:
        return
    diagnostic["parser_decision"] = diagnostic.get("decision")
    diagnostic["decision"] = decision
    diagnostic["reason"] = reason
    diagnostic["parser_stage"] = "source_role_gate"


def _extract_core_supplements(data: AdmissionsData, text: str, source, recorder: "ExtractionDiagnosticsRecorder") -> None:
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


class ExtractionDiagnosticsRecorder:
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
        parse_status: str | None = None,
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
            parse_status=parse_status,
            record_count=record_count,
            evidence_count=evidence_count,
        )

    def record_record(self, *, field: str, extractor: str, record, evidence, reason: str, claim_path: str) -> None:
        parse_status = None
        value = getattr(record, "value", None)
        if value is not None:
            parse_status = getattr(value, "parse_status", None)
        self.record(
            field=field,
            extractor=extractor,
            status="extracted" if record else "no_match",
            reason=reason,
            claim_path=claim_path,
            parse_status=parse_status,
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
    parse_status: str | None = None,
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
    if parse_status:
        attempt["parse_status"] = parse_status
    attempts.append(attempt)


def _extract_prerequisite_with_pdf_page(text, source, claim_path: str, pdf_pages):
    if not pdf_pages:
        return extract_prerequisite(text, source, claim_path)
    for page in pdf_pages:
        record, evidence = extract_prerequisite(page.text, source, claim_path, page_number=page.page_number)
        if record:
            return record, evidence
    return extract_prerequisite(text, source, claim_path)
