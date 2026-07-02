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
    FieldValue,
    PageCategory,
    ProgrammeRecord,
    RequirementRecord,
    SourceRecord,
)


@dataclass(slots=True)
class SourceExtractionContext:
    final_url: str
    title: str | None
    source: SourceRecord
    text: str
    pdf_pages: list[PDFPageText]
    category: PageCategory


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
    elif category in {PageCategory.PROGRAMME_LIST, PageCategory.PROGRAMME_PREREQUISITES}:
        _append_programme_catalog(data, text, source, recorder, reason="category_route", assist_provider=programme_catalog_assist_provider)
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
