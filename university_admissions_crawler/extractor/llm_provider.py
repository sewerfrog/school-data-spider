"""Optional LLM provider interface with evidence-gated mock support."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from university_admissions_crawler.extractor.schema import EvidenceItem, WarningCode, WarningRecord


@dataclass(slots=True)
class LLMCandidateClaim:
    claim_path: str
    value: str
    evidence_snippet: str
    confidence: str = "low"
    source_url: str | None = None


@dataclass(slots=True)
class LLMValidationResult:
    accepted: list[LLMCandidateClaim] = field(default_factory=list)
    warnings: list[WarningRecord] = field(default_factory=list)


class LLMProvider(Protocol):
    def extract_candidates(self, source_text: str, schema_hint: str) -> list[LLMCandidateClaim]:
        ...


class MockLLMProvider:
    """Deterministic provider for tests; never calls a hosted API."""

    def __init__(self, candidates: list[LLMCandidateClaim]) -> None:
        self._candidates = list(candidates)

    def extract_candidates(self, source_text: str, schema_hint: str) -> list[LLMCandidateClaim]:
        return list(self._candidates)


def validate_llm_candidates(candidates: list[LLMCandidateClaim], evidence: list[EvidenceItem], source_text: str) -> LLMValidationResult:
    """Accept only candidates whose snippet is grounded in captured source text.

    This is intentionally strict: unsupported claims are not promoted into the
    admissions schema by the MVP.  Callers may surface warnings/manual checks.
    """

    result = LLMValidationResult()
    evidence_by_path: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        evidence_by_path.setdefault(item.claim_path, []).append(item)
    for candidate in candidates:
        snippet = candidate.evidence_snippet.strip()
        matching_path_evidence = evidence_by_path.get(candidate.claim_path, [])
        path_snippet_match = any(
            snippet
            and snippet == item.snippet.strip()
            and (candidate.source_url is None or candidate.source_url == item.source_url)
            for item in matching_path_evidence
        )
        value_supported = str(candidate.value).strip().lower() in snippet.lower()
        if snippet and snippet in source_text and path_snippet_match and value_supported:
            result.accepted.append(candidate)
        else:
            result.warnings.append(
                WarningRecord(
                    WarningCode.LLM_UNSUPPORTED_CLAIM,
                    "LLM candidate claim was rejected because its evidence snippet was not found in captured source text.",
                    field=candidate.claim_path,
                )
            )
    return result
