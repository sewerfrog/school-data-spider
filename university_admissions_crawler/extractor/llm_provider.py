"""Optional LLM provider interface with evidence-gated mock support."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

from university_admissions_crawler.crawler.relevance import KEYWORD_PLAN_OUTPUT_SCHEMA, KeywordPlan, keyword_plan_from_payload, keyword_plan_from_query
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


@dataclass(slots=True)
class KeywordPlanGenerationResult:
    keyword_plan: KeywordPlan
    diagnostics: dict[str, object] = field(default_factory=dict)


class LLMProvider(Protocol):
    def extract_candidates(self, source_text: str, schema_hint: str) -> list[LLMCandidateClaim]:
        ...


class KeywordPlanProvider(Protocol):
    name: str

    def generate_keyword_plan_payload(self, query: str, schema: dict[str, object]) -> dict[str, object]:
        ...


class MockLLMProvider:
    """Deterministic provider for tests; never calls a hosted API."""

    def __init__(self, candidates: list[LLMCandidateClaim]) -> None:
        self._candidates = list(candidates)

    def extract_candidates(self, source_text: str, schema_hint: str) -> list[LLMCandidateClaim]:
        return list(self._candidates)


class MockKeywordPlanProvider:
    """Deterministic keyword-plan provider for guarded LLM plumbing tests."""

    name = "mock"

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = dict(payload) if payload is not None else None
        self._error = error

    def generate_keyword_plan_payload(self, query: str, schema: dict[str, object]) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        if self._payload is not None:
            return dict(self._payload)
        return keyword_plan_from_query(query, source="llm").to_dict()


def generate_keyword_plan_with_fallback(query: str, provider: KeywordPlanProvider) -> KeywordPlanGenerationResult:
    """Generate a keyword plan via an optional provider and fall back to rule parsing."""

    provider_name = getattr(provider, "name", type(provider).__name__)
    started = perf_counter()
    try:
        payload = provider.generate_keyword_plan_payload(query, KEYWORD_PLAN_OUTPUT_SCHEMA)
        keyword_plan = keyword_plan_from_payload(payload)
        diagnostics = {
            "provider": provider_name,
            "schema": "KEYWORD_PLAN_OUTPUT_SCHEMA",
            "fallback": False,
            "elapsed_ms": _elapsed_ms(started),
            "warnings": list(keyword_plan.warnings),
        }
        return KeywordPlanGenerationResult(keyword_plan=keyword_plan, diagnostics=diagnostics)
    except Exception as exc:
        fallback_plan = keyword_plan_from_query(query, source="user")
        fallback_plan = KeywordPlan(
            query=fallback_plan.query,
            positive_keywords=fallback_plan.positive_keywords,
            negative_keywords=fallback_plan.negative_keywords,
            url_hints=fallback_plan.url_hints,
            source=fallback_plan.source,
            warnings=tuple(list(fallback_plan.warnings) + ["llm_keyword_plan_fallback"]),
        )
        return KeywordPlanGenerationResult(
            keyword_plan=fallback_plan,
            diagnostics={
                "provider": provider_name,
                "schema": "KEYWORD_PLAN_OUTPUT_SCHEMA",
                "fallback": True,
                "elapsed_ms": _elapsed_ms(started),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "warnings": list(fallback_plan.warnings),
            },
        )


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


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
