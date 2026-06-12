"""Optional LLM provider interface with evidence-gated mock support."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

from university_admissions_crawler.crawler.relevance import KEYWORD_PLAN_OUTPUT_SCHEMA, KeywordPlan, keyword_plan_from_payload, keyword_plan_from_query
from university_admissions_crawler.extractor.schema import EvidenceItem, PageCategory, WarningCode, WarningRecord


MAX_CLASSIFICATION_REASON_LENGTH = 300
MAX_CLASSIFICATION_SIGNAL_LENGTH = 80
MAX_CLASSIFICATION_SIGNALS = 20
CLASSIFICATION_ASSIST_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["category", "reason", "confidence", "signals"],
    "properties": {
        "category": {"type": "string", "enum": [str(item) for item in PageCategory]},
        "reason": {"type": "string", "maxLength": MAX_CLASSIFICATION_REASON_LENGTH},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "signals": {"type": "array", "items": {"type": "string", "maxLength": MAX_CLASSIFICATION_SIGNAL_LENGTH}, "maxItems": MAX_CLASSIFICATION_SIGNALS},
    },
    "additionalProperties": False,
}


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


@dataclass(frozen=True, slots=True)
class ClassificationAssistResult:
    category: PageCategory
    reason: str
    confidence: str = "low"
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "category": str(self.category),
            "reason": self.reason,
            "confidence": self.confidence,
            "signals": list(self.signals),
        }


class LLMProvider(Protocol):
    def extract_candidates(self, source_text: str, schema_hint: str) -> list[LLMCandidateClaim]:
        ...


class KeywordPlanProvider(Protocol):
    name: str

    def generate_keyword_plan_payload(self, query: str, schema: dict[str, object]) -> dict[str, object]:
        ...


class ClassificationAssistProvider(Protocol):
    name: str

    def classify_page_payload(self, url: str, title: str | None, text: str, schema: dict[str, object]) -> dict[str, object]:
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


class MockClassificationAssistProvider:
    """Deterministic page-classification assist provider for diagnostics tests."""

    name = "mock"

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = dict(payload) if payload is not None else None
        self._error = error

    def classify_page_payload(self, url: str, title: str | None, text: str, schema: dict[str, object]) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        if self._payload is not None:
            return dict(self._payload)
        lowered = f"{url} {title or ''} {text[:1200]}".lower()
        if "tuition" in lowered or "fee" in lowered:
            category = PageCategory.FEES
            signals = ["tuition_or_fee"]
        elif "deadline" in lowered or "apply by" in lowered:
            category = PageCategory.APPLICATION_DEADLINES
            signals = ["deadline"]
        elif "ielts" in lowered or "toefl" in lowered or "english" in lowered:
            category = PageCategory.INTERNATIONAL_REQUIREMENTS
            signals = ["english_requirement"]
        elif "scholarship" in lowered:
            category = PageCategory.SCHOLARSHIPS
            signals = ["scholarship"]
        elif "undergraduate" in lowered or "admission" in lowered:
            category = PageCategory.UNDERGRADUATE_ADMISSIONS
            signals = ["undergraduate_admissions"]
        else:
            category = PageCategory.IRRELEVANT
            signals = []
        return {
            "category": str(category),
            "reason": "Mock classification assist based on bounded keyword hints.",
            "confidence": "low",
            "signals": signals,
        }


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


def generate_classification_assist_diagnostic(
    *,
    url: str,
    title: str | None,
    text: str,
    rule_category: PageCategory,
    rule_score: int,
    provider: ClassificationAssistProvider,
) -> dict[str, object]:
    """Return model-assisted classification diagnostics without changing the rule result."""

    provider_name = getattr(provider, "name", type(provider).__name__)
    started = perf_counter()
    try:
        payload = provider.classify_page_payload(url, title, text[:4000], CLASSIFICATION_ASSIST_OUTPUT_SCHEMA)
        assist = classification_assist_from_payload(payload)
        return {
            "url": url,
            "provider": provider_name,
            "schema": "CLASSIFICATION_ASSIST_OUTPUT_SCHEMA",
            "fallback": False,
            "elapsed_ms": _elapsed_ms(started),
            "rule_category": str(rule_category),
            "rule_score": rule_score,
            "candidate": assist.to_dict(),
            "applied": False,
        }
    except Exception as exc:
        return {
            "url": url,
            "provider": provider_name,
            "schema": "CLASSIFICATION_ASSIST_OUTPUT_SCHEMA",
            "fallback": True,
            "elapsed_ms": _elapsed_ms(started),
            "rule_category": str(rule_category),
            "rule_score": rule_score,
            "candidate": None,
            "applied": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def classification_assist_from_payload(payload: dict[str, object]) -> ClassificationAssistResult:
    allowed_keys = {"category", "reason", "confidence", "signals"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported classification assist fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Classification assist missing required fields: {', '.join(sorted(missing_keys))}")
    category_value = _required_text(payload.get("category"), field="category")
    try:
        category = PageCategory(category_value)
    except ValueError as exc:
        raise ValueError(f"Unsupported classification category: {category_value}") from exc
    confidence = _required_text(payload.get("confidence"), field="confidence")
    if confidence not in {"low", "medium", "high"}:
        raise ValueError(f"Unsupported classification confidence: {confidence}")
    return ClassificationAssistResult(
        category=category,
        reason=_bounded_text(_required_text(payload.get("reason"), field="reason"), field="reason", max_length=MAX_CLASSIFICATION_REASON_LENGTH),
        confidence=confidence,
        signals=tuple(_bounded_text_list(payload.get("signals", []), field="signals", max_items=MAX_CLASSIFICATION_SIGNALS, max_length=MAX_CLASSIFICATION_SIGNAL_LENGTH)),
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


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Classification assist field {field} must be a string.")
    return value


def _bounded_text(value: str, *, field: str, max_length: int) -> str:
    stripped = value.strip()
    if len(stripped) > max_length:
        raise ValueError(f"Classification assist field {field} exceeds {max_length} characters.")
    return stripped


def _bounded_text_list(value: object, *, field: str, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Classification assist field {field} must be a list of strings.")
    if len(value) > max_items:
        raise ValueError(f"Classification assist field {field} exceeds {max_items} items.")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Classification assist field {field} must contain only strings.")
        bounded = _bounded_text(item, field=field, max_length=max_length)
        if bounded and bounded not in seen:
            seen.add(bounded)
            out.append(bounded)
    return out
