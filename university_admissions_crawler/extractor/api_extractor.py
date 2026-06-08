"""Deterministic extraction helpers for public JSON/API sources."""

from __future__ import annotations

import json
import re
from typing import Any

from university_admissions_crawler.evidence.provenance import evidence_from_source
from university_admissions_crawler.extractor.schema import ClaimStatus, Confidence, EvidenceItem, FieldValue, ProgrammeRecord, RequirementRecord, SourceRecord
from university_admissions_crawler.extractor.structured import parse_application_dates, parse_money_candidates


def extract_api_claims(
    text: str,
    source: SourceRecord,
    *,
    programme_start: int,
    deadline_start: int,
    fee_start: int,
    document_start: int,
) -> tuple[list[ProgrammeRecord], list[RequirementRecord], list[RequirementRecord], list[RequirementRecord], list[EvidenceItem]]:
    """Extract known admissions-shaped claims from public JSON.

    The extractor is deliberately conservative: it only promotes fields whose
    keys look like common public API names and preserves the JSON object as the
    evidence snippet.
    """

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], [], [], [], []

    programmes: list[ProgrammeRecord] = []
    deadlines: list[RequirementRecord] = []
    fees: list[RequirementRecord] = []
    documents: list[RequirementRecord] = []
    evidence: list[EvidenceItem] = []

    for item in _candidate_objects(payload):
        snippet = _snippet(item)
        programme_name = _first_value(item, ("programme", "program", "programName", "programmeName", "title", "name"))
        if programme_name and _looks_like_programme(programme_name):
            claim_path = f"/programmes/{programme_start + len(programmes)}/name"
            programmes.append(
                ProgrammeRecord(
                    name=FieldValue(value=programme_name, status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[claim_path]),
                    source_url=source.source_url,
                    evidence=[claim_path],
                )
            )
            evidence.append(evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM))

        deadline = _first_value(item, ("deadline", "applicationDeadline", "closingDate", "closing_date", "applyBy", "apply_by"))
        if deadline:
            claim_path = f"/admissions/application_periods/{deadline_start + len(deadlines)}/value"
            parsed, parse_status = parse_application_dates(str(deadline))
            deadlines.append(_requirement("application deadline", str(deadline), claim_path, parsed=parsed, parse_status=parse_status))
            evidence.append(evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM))

        fee = _first_value(item, ("fee", "fees", "tuition", "tuitionFee", "tuition_fee"))
        if fee:
            claim_path = f"/fees/{fee_start + len(fees)}/value"
            parsed, parse_status = parse_money_candidates(str(fee))
            fees.append(_requirement("tuition/fees", str(fee), claim_path, parsed=parsed, parse_status=parse_status))
            evidence.append(evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM))

        document = _first_value(item, ("requiredDocuments", "required_documents", "documents", "document"))
        if document:
            claim_path = f"/admissions/required_documents/{document_start + len(documents)}/value"
            documents.append(_requirement("required documents", _stringify(document), claim_path))
            evidence.append(evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM))

    return programmes, deadlines, fees, documents, evidence


def _candidate_objects(value: Any):
    if isinstance(value, dict):
        if any(_normalize_key(key) in _KNOWN_KEYS for key in value):
            yield value
        for subvalue in value.values():
            yield from _candidate_objects(subvalue)
    elif isinstance(value, list):
        for subvalue in value:
            yield from _candidate_objects(subvalue)


def _first_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    normalized = {_normalize_key(key): value for key, value in item.items()}
    for key in keys:
        value = normalized.get(_normalize_key(key))
        if value not in (None, "", []):
            return value
    return None


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _looks_like_programme(value: Any) -> bool:
    text = str(value)
    return bool(re.search(r"\b(?:Bachelor|BSc|BA|BEng|LLB|MBBS|Programme|Program|Major)\b", text, flags=re.IGNORECASE))


def _requirement(label: str, value: str, claim_path: str, *, parsed=None, parse_status: str = "unparsed") -> RequirementRecord:
    return RequirementRecord(
        label=label,
        value=FieldValue(value=value, raw_text=value, parsed=parsed, parse_status=parse_status, status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[claim_path]),
    )


def _stringify(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _snippet(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)[:500]


_KNOWN_KEYS = {
    "programme",
    "program",
    "programname",
    "programmename",
    "title",
    "name",
    "deadline",
    "applicationdeadline",
    "closingdate",
    "applyby",
    "fee",
    "fees",
    "tuition",
    "tuitionfee",
    "requireddocuments",
    "documents",
    "document",
}
