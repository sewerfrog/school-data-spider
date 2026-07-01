"""Deterministic validation for LLM structured extraction candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from university_admissions_crawler.crawler.admissions_context import has_undergraduate_admissions_context, has_undergraduate_fee_context, has_undergraduate_scholarship_context, has_english_requirement_context
from university_admissions_crawler.crawler.filters import DomainPolicy, validate_source_plan_candidate_url
from university_admissions_crawler.extractor.llm_provider import LLMStructuredCandidateFact, STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS
from university_admissions_crawler.extractor.schema import SourceRecord


LLM_STRUCTURED_MIN_CONFIDENCE = 0.2


@dataclass(frozen=True, slots=True)
class LLMStructuredCandidateValidation:
    candidate: LLMStructuredCandidateFact | None
    accepted: bool
    reject_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "accepted": self.accepted,
            "candidate": self.candidate.to_dict() if self.candidate is not None else None,
        }
        if self.reject_reason is not None:
            out["reject_reason"] = self.reject_reason
        return out


def validate_llm_candidate_fact(
    candidate: object,
    *,
    captured_sources: Mapping[str, str],
    source_records: Mapping[str, SourceRecord] | list[SourceRecord] | tuple[SourceRecord, ...] = (),
    domain_policy: DomainPolicy | None = None,
    allowed_claim_paths: tuple[str, ...] = STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
    min_confidence: float = LLM_STRUCTURED_MIN_CONFIDENCE,
) -> LLMStructuredCandidateValidation:
    """Validate one LLM structured candidate without refetching or mutating results."""

    if not isinstance(candidate, LLMStructuredCandidateFact):
        return LLMStructuredCandidateValidation(candidate=None, accepted=False, reject_reason="malformed_candidate")
    if candidate.confidence < 0.0 or candidate.confidence > 1.0:
        return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="malformed_candidate")
    if candidate.confidence < min_confidence:
        return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="low_confidence")
    if candidate.claim_path not in allowed_claim_paths:
        return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="claim_path_not_allowed")
    source_text = captured_sources.get(candidate.source_url)
    if source_text is None:
        return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="source_not_captured")
    source_lookup = _source_lookup(source_records)
    source_record = source_lookup.get(candidate.source_url)
    if source_record is not None and not source_record.is_official:
        return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="source_not_official")
    if domain_policy is not None:
        accepted_url, _reason = validate_source_plan_candidate_url(candidate.source_url, domain_policy)
        if not accepted_url:
            return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="source_not_official")
    if candidate.evidence_snippet not in source_text:
        return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="snippet_not_found")
    if candidate.value not in candidate.evidence_snippet:
        return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="value_not_in_snippet")
    title = source_record.title if source_record is not None else candidate.source_title
    if not _claim_path_context_ok(candidate.claim_path, candidate.source_url, title, source_text):
        return LLMStructuredCandidateValidation(candidate=candidate, accepted=False, reject_reason="context_gate_failed")
    return LLMStructuredCandidateValidation(candidate=candidate, accepted=True)


def _source_lookup(source_records: Mapping[str, SourceRecord] | list[SourceRecord] | tuple[SourceRecord, ...]) -> dict[str, SourceRecord]:
    if isinstance(source_records, Mapping):
        return dict(source_records)
    return {source.source_url: source for source in source_records}


def _claim_path_context_ok(claim_path: str, source_url: str, title: str | None, source_text: str) -> bool:
    if claim_path.startswith("programme_catalog[]"):
        return _has_programme_catalog_context(source_url, title, source_text)
    if claim_path == "admissions.requirements.english":
        return has_english_requirement_context(source_url, title, source_text)
    if claim_path == "admissions.fees":
        return has_undergraduate_fee_context(source_url, title, source_text)
    if claim_path == "admissions.scholarships":
        return has_undergraduate_scholarship_context(source_url, title, source_text)
    if claim_path.startswith("admissions."):
        return has_undergraduate_admissions_context(source_url, title, source_text)
    return False


def _has_programme_catalog_context(source_url: str, title: str | None, source_text: str) -> bool:
    haystack = f"{source_url} {title or ''} {source_text[:2500]}".lower()
    if any(token in haystack for token in ("postgraduate", "graduate research", "phd", "master of")):
        return False
    return any(
        token in haystack
        for token in (
            "undergraduate programme",
            "undergraduate program",
            "bachelor",
            "degree programme",
            "degree program",
            "major",
            "minor",
            "catalogue",
            "catalog",
        )
    )
