"""Optional LLM provider interface with evidence-gated mock support."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

from university_admissions_crawler.crawler.relevance import KEYWORD_PLAN_OUTPUT_SCHEMA, KeywordPlan, keyword_plan_from_payload, keyword_plan_from_query
from university_admissions_crawler.extractor.schema import EvidenceItem, PageCategory, WarningCode, WarningRecord


MAX_SOURCE_PLAN_URLS = 20
MAX_SOURCE_PLAN_QUERIES = 20
MAX_SOURCE_PLAN_REASON_LENGTH = 240
MAX_SOURCE_PLAN_QUERY_LENGTH = 160
MAX_SOURCE_PLAN_URL_LENGTH = 300
MAX_SOURCE_PLAN_CATEGORY_LENGTH = 80
MAX_CLASSIFICATION_REASON_LENGTH = 300
MAX_CLASSIFICATION_SIGNAL_LENGTH = 80
MAX_CLASSIFICATION_SIGNALS = 20
MAX_PROGRAMME_HINT_REASON_LENGTH = 300
MAX_PROGRAMME_HINT_SIGNAL_LENGTH = 80
MAX_PROGRAMME_HINT_SIGNALS = 20
PROGRAMME_CATALOG_CATEGORY_VALUES = ("degree_programme", "major", "minor", "special_programme", "dual_degree", "unknown")
PROGRAMME_CATALOG_MODE_VALUES = ("full-time", "part-time", "unknown")
SOURCE_PLAN_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["candidate_urls", "candidate_queries", "warnings"],
    "properties": {
        "candidate_urls": {
            "type": "array",
            "maxItems": MAX_SOURCE_PLAN_URLS,
            "items": {
                "type": "object",
                "required": ["url", "reason", "expected_category"],
                "properties": {
                    "url": {"type": "string", "maxLength": MAX_SOURCE_PLAN_URL_LENGTH},
                    "reason": {"type": "string", "maxLength": MAX_SOURCE_PLAN_REASON_LENGTH},
                    "expected_category": {"type": "string", "maxLength": MAX_SOURCE_PLAN_CATEGORY_LENGTH},
                },
                "additionalProperties": False,
            },
        },
        "candidate_queries": {"type": "array", "items": {"type": "string", "maxLength": MAX_SOURCE_PLAN_QUERY_LENGTH}, "maxItems": MAX_SOURCE_PLAN_QUERIES},
        "warnings": {"type": "array", "items": {"type": "string", "maxLength": MAX_SOURCE_PLAN_REASON_LENGTH}, "maxItems": MAX_SOURCE_PLAN_QUERIES},
    },
    "additionalProperties": False,
}
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
PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["category", "mode", "reason", "confidence", "signals"],
    "properties": {
        "category": {"type": "string", "enum": list(PROGRAMME_CATALOG_CATEGORY_VALUES)},
        "mode": {"type": "string", "enum": list(PROGRAMME_CATALOG_MODE_VALUES)},
        "reason": {"type": "string", "maxLength": MAX_PROGRAMME_HINT_REASON_LENGTH},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "signals": {"type": "array", "items": {"type": "string", "maxLength": MAX_PROGRAMME_HINT_SIGNAL_LENGTH}, "maxItems": MAX_PROGRAMME_HINT_SIGNALS},
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
class SourcePlanCandidateURL:
    url: str
    reason: str
    expected_category: str

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "reason": self.reason,
            "expected_category": self.expected_category,
        }


@dataclass(frozen=True, slots=True)
class SourcePlanResult:
    candidate_urls: tuple[SourcePlanCandidateURL, ...] = ()
    candidate_queries: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_urls": [item.to_dict() for item in self.candidate_urls],
            "candidate_queries": list(self.candidate_queries),
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class SourcePlanGenerationResult:
    source_plan: SourcePlanResult
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


@dataclass(frozen=True, slots=True)
class ProgrammeCatalogClassificationHint:
    category: str
    mode: str = "unknown"
    reason: str = ""
    confidence: str = "low"
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "mode": self.mode,
            "reason": self.reason,
            "confidence": self.confidence,
            "signals": list(self.signals),
        }


@dataclass(slots=True)
class ProgrammeCatalogClassificationHintResult:
    hint: ProgrammeCatalogClassificationHint | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)


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


class SourcePlanProvider(Protocol):
    name: str

    def generate_source_plan_payload(self, context: dict[str, object], schema: dict[str, object]) -> dict[str, object]:
        ...


class ProgrammeCatalogAssistProvider(Protocol):
    name: str

    def classify_programme_candidate_payload(self, candidate_text: str, source_url: str, title: str | None, schema: dict[str, object]) -> dict[str, object]:
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


class MockSourcePlanProvider:
    """Deterministic source-plan provider for diagnostics-only tests."""

    name = "mock"

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = dict(payload) if payload is not None else None
        self._error = error

    def generate_source_plan_payload(self, context: dict[str, object], schema: dict[str, object]) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        if self._payload is not None:
            return dict(self._payload)
        seed_url = str(context.get("input_url") or "").rstrip("/")
        host_hint = seed_url.split("/")[2] if "://" in seed_url else "example.edu"
        return {
            "candidate_urls": [
                {
                    "url": f"https://{host_hint}/admissions",
                    "reason": "Mock official admissions landing page candidate.",
                    "expected_category": "undergraduate_admissions",
                },
                {
                    "url": f"https://{host_hint}/programmes",
                    "reason": "Mock official programmes index candidate.",
                    "expected_category": "programme_list",
                },
            ],
            "candidate_queries": [
                f"site:{host_hint} undergraduate admissions",
                f"site:{host_hint} undergraduate programmes",
            ],
            "warnings": [],
        }


class MockProgrammeCatalogAssistProvider:
    """Deterministic programme-candidate category hint provider for tests."""

    name = "mock"

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = dict(payload) if payload is not None else None
        self._error = error

    def classify_programme_candidate_payload(self, candidate_text: str, source_url: str, title: str | None, schema: dict[str, object]) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        if self._payload is not None:
            return dict(self._payload)
        lowered = candidate_text.lower()
        if "major:" in lowered or "primary major" in lowered:
            category = "major"
        elif "special programme" in lowered or "nus college" in lowered or "scholars programme" in lowered:
            category = "special_programme"
        elif "double degree" in lowered or "dual degree" in lowered:
            category = "dual_degree"
        elif "bachelor" in lowered or "bsc" in lowered or "beng" in lowered or "bba" in lowered:
            category = "degree_programme"
        else:
            category = "unknown"
        return {
            "category": category,
            "mode": _mode_hint_from_text(candidate_text),
            "reason": "Mock programme catalog hint based only on the captured candidate row.",
            "confidence": "low",
            "signals": [category] if category != "unknown" else [],
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


def generate_source_plan_diagnostic(context: dict[str, object], provider: SourcePlanProvider) -> dict[str, object]:
    """Return source-planning diagnostics without adding URLs to the crawl."""

    provider_name = getattr(provider, "name", type(provider).__name__)
    started = perf_counter()
    try:
        payload = provider.generate_source_plan_payload(context, SOURCE_PLAN_OUTPUT_SCHEMA)
        source_plan = source_plan_from_payload(payload)
        return {
            "provider": provider_name,
            "schema": "SOURCE_PLAN_OUTPUT_SCHEMA",
            "fallback": False,
            "elapsed_ms": _elapsed_ms(started),
            "trigger_reasons": _bounded_text_list(context.get("trigger_reasons", []), field="trigger_reasons", max_items=MAX_SOURCE_PLAN_QUERIES, max_length=MAX_SOURCE_PLAN_REASON_LENGTH),
            "candidate_urls": [item.to_dict() for item in source_plan.candidate_urls],
            "candidate_queries": list(source_plan.candidate_queries),
            "warnings": list(source_plan.warnings),
            "applied": False,
            "note": "Source planning is diagnostics-only; candidate URLs are not crawled and do not create admissions facts.",
        }
    except Exception as exc:
        return {
            "provider": provider_name,
            "schema": "SOURCE_PLAN_OUTPUT_SCHEMA",
            "fallback": True,
            "elapsed_ms": _elapsed_ms(started),
            "trigger_reasons": _bounded_text_list(context.get("trigger_reasons", []), field="trigger_reasons", max_items=MAX_SOURCE_PLAN_QUERIES, max_length=MAX_SOURCE_PLAN_REASON_LENGTH),
            "candidate_urls": [],
            "candidate_queries": [],
            "warnings": ["llm_source_plan_fallback"],
            "applied": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "note": "Source planning is diagnostics-only; candidate URLs are not crawled and do not create admissions facts.",
        }


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


def generate_programme_catalog_classification_hint(
    *,
    candidate_text: str,
    source_url: str,
    title: str | None,
    provider: ProgrammeCatalogAssistProvider,
) -> ProgrammeCatalogClassificationHintResult:
    """Return a bounded category hint for one captured programme candidate row."""

    provider_name = getattr(provider, "name", type(provider).__name__)
    started = perf_counter()
    try:
        payload = provider.classify_programme_candidate_payload(candidate_text, source_url, title, PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA)
        hint = programme_catalog_classification_hint_from_payload(payload)
        return ProgrammeCatalogClassificationHintResult(
            hint=hint,
            diagnostics={
                "provider": provider_name,
                "schema": "PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA",
                "fallback": False,
                "elapsed_ms": _elapsed_ms(started),
                "applied": hint.category != "unknown" or hint.mode != "unknown",
            },
        )
    except Exception as exc:
        return ProgrammeCatalogClassificationHintResult(
            hint=None,
            diagnostics={
                "provider": provider_name,
                "schema": "PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA",
                "fallback": True,
                "elapsed_ms": _elapsed_ms(started),
                "applied": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )


def programme_catalog_classification_hint_from_payload(payload: dict[str, object]) -> ProgrammeCatalogClassificationHint:
    allowed_keys = {"category", "mode", "reason", "confidence", "signals"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported programme catalog hint fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Programme catalog hint missing required fields: {', '.join(sorted(missing_keys))}")
    category = _required_text(payload.get("category"), field="category")
    if category not in PROGRAMME_CATALOG_CATEGORY_VALUES:
        raise ValueError(f"Unsupported programme catalog category: {category}")
    mode = _required_text(payload.get("mode"), field="mode")
    if mode not in PROGRAMME_CATALOG_MODE_VALUES:
        raise ValueError(f"Unsupported programme catalog mode: {mode}")
    confidence = _required_text(payload.get("confidence"), field="confidence")
    if confidence not in {"low", "medium", "high"}:
        raise ValueError(f"Unsupported programme catalog confidence: {confidence}")
    return ProgrammeCatalogClassificationHint(
        category=category,
        mode=mode,
        reason=_bounded_text(_required_text(payload.get("reason"), field="reason"), field="reason", max_length=MAX_PROGRAMME_HINT_REASON_LENGTH),
        confidence=confidence,
        signals=tuple(_bounded_text_list(payload.get("signals", []), field="signals", max_items=MAX_PROGRAMME_HINT_SIGNALS, max_length=MAX_PROGRAMME_HINT_SIGNAL_LENGTH)),
    )


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


def source_plan_from_payload(payload: dict[str, object]) -> SourcePlanResult:
    allowed_keys = {"candidate_urls", "candidate_queries", "warnings"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported source plan fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Source plan missing required fields: {', '.join(sorted(missing_keys))}")
    candidate_urls = tuple(_source_plan_candidate_from_payload(item) for item in _required_dict_list(payload.get("candidate_urls"), field="candidate_urls", max_items=MAX_SOURCE_PLAN_URLS))
    candidate_queries = tuple(_bounded_text_list(payload.get("candidate_queries", []), field="candidate_queries", max_items=MAX_SOURCE_PLAN_QUERIES, max_length=MAX_SOURCE_PLAN_QUERY_LENGTH))
    warnings = tuple(_bounded_text_list(payload.get("warnings", []), field="warnings", max_items=MAX_SOURCE_PLAN_QUERIES, max_length=MAX_SOURCE_PLAN_REASON_LENGTH))
    return SourcePlanResult(candidate_urls=candidate_urls, candidate_queries=candidate_queries, warnings=warnings)


def _source_plan_candidate_from_payload(payload: dict[str, object]) -> SourcePlanCandidateURL:
    allowed_keys = {"url", "reason", "expected_category"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported source plan candidate fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Source plan candidate missing required fields: {', '.join(sorted(missing_keys))}")
    return SourcePlanCandidateURL(
        url=_bounded_text(_required_text(payload.get("url"), field="url"), field="url", max_length=MAX_SOURCE_PLAN_URL_LENGTH),
        reason=_bounded_text(_required_text(payload.get("reason"), field="reason"), field="reason", max_length=MAX_SOURCE_PLAN_REASON_LENGTH),
        expected_category=_bounded_text(_required_text(payload.get("expected_category"), field="expected_category"), field="expected_category", max_length=MAX_SOURCE_PLAN_CATEGORY_LENGTH),
    )


def _required_dict_list(value: object, *, field: str, max_items: int) -> list[dict[str, object]]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Source plan field {field} must be a list.")
    if len(value) > max_items:
        raise ValueError(f"Source plan field {field} exceeds {max_items} items.")
    out: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Source plan field {field} must contain only objects.")
        out.append(item)
    return out


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


def _mode_hint_from_text(text: str) -> str:
    lowered = text.lower()
    if "full-time" in lowered or "full time" in lowered:
        return "full-time"
    if "part-time" in lowered or "part time" in lowered:
        return "part-time"
    return "unknown"
