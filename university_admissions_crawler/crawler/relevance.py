"""Relevance scoring strategies for bounded admissions discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Protocol
from urllib.parse import urlparse

from university_admissions_crawler.config import NEGATIVE_KEYWORDS, POSITIVE_KEYWORDS
from university_admissions_crawler.crawler.admissions_context import NON_ADMISSIONS_PATH_HINTS, UNDERGRAD_ADMISSIONS_PATH_HINTS
from university_admissions_crawler.crawler.filters import DomainPolicy, is_low_value_source_url, is_pdf_url, score_url, should_follow_url
from university_admissions_crawler.crawler.filters import PROGRAMME_SOURCE_PATH_HINTS


MAX_KEYWORD_QUERY_LENGTH = 500
MAX_KEYWORD_ITEMS = 50
MAX_KEYWORD_LENGTH = 80
KEYWORD_PLAN_SOURCES = {"default", "user", "llm"}
RELEVANCE_STRATEGY_ALIASES = {
    "rule-based": "rule-based",
    "rule_based": "rule-based",
    "bm25-like": "bm25-like",
    "bm25_like": "bm25-like",
}

KEYWORD_PLAN_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["query", "positive_keywords", "negative_keywords", "url_hints", "source", "warnings"],
    "properties": {
        "query": {"type": "string", "maxLength": MAX_KEYWORD_QUERY_LENGTH},
        "positive_keywords": {"type": "array", "items": {"type": "string", "maxLength": MAX_KEYWORD_LENGTH}, "maxItems": MAX_KEYWORD_ITEMS},
        "negative_keywords": {"type": "array", "items": {"type": "string", "maxLength": MAX_KEYWORD_LENGTH}, "maxItems": MAX_KEYWORD_ITEMS},
        "url_hints": {"type": "array", "items": {"type": "string", "maxLength": MAX_KEYWORD_LENGTH}, "maxItems": MAX_KEYWORD_ITEMS},
        "source": {"type": "string", "enum": sorted(KEYWORD_PLAN_SOURCES)},
        "warnings": {"type": "array", "items": {"type": "string", "maxLength": MAX_KEYWORD_LENGTH}, "maxItems": MAX_KEYWORD_ITEMS},
    },
    "additionalProperties": False,
}

PATH_RELEVANCE_HINTS: tuple[str, ...] = (
    "/admission",
    "/undergraduate",
    "/apply",
    "/programme",
    "/program",
    "/degree-program",
    "/major",
    "/minor",
    "/bulletin",
    "/catalogue",
    "/catalog",
    "/study/undergraduate",
    "/fee",
    "/scholarship",
    "/international",
    "/requirement",
    "/contact",
)

PATH_NOISE_HINTS: tuple[str, ...] = (
    "/news",
    "/alumni",
    "/giving",
    "/donate",
    "/staff",
    "/jobs",
    "/career",
    "/privacy",
    "/cookie",
)


KEYWORD_QUERY_SPLIT_RE = re.compile(r"[\s,;|/]+")
TEXT_TOKEN_RE = re.compile(r"[a-z0-9]+")

KEYWORD_URL_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("admission", ("/admissions",)),
    ("admissions", ("/admissions",)),
    ("apply", ("/apply", "/admissions")),
    ("application", ("/apply", "/admissions")),
    ("undergraduate", ("/undergraduate", "/ug")),
    ("ug", ("/undergraduate", "/ug")),
    ("bachelor", ("/undergraduate", "/programmes", "/undergraduate-education", "/degree-programmes")),
    ("degree", ("/degree-programmes", "/programmes", "/undergraduate-education")),
    ("major", ("/majors", "/programmes", "/catalogue")),
    ("majors", ("/majors", "/programmes", "/catalogue")),
    ("minor", ("/minors", "/programmes", "/catalogue")),
    ("minors", ("/minors", "/programmes", "/catalogue")),
    ("bulletin", ("/bulletin",)),
    ("catalogue", ("/catalogue", "/catalog")),
    ("catalog", ("/catalog", "/catalogue")),
    ("programme", ("/programme", "/programmes", "/undergraduate-programmes", "/undergraduate-education")),
    ("program", ("/program", "/programs", "/undergraduate-programs", "/undergraduate-education")),
    ("requirement", ("/requirements",)),
    ("requirements", ("/requirements",)),
    ("international", ("/international",)),
    ("english", ("/english", "/requirements")),
    ("ielts", ("/english", "/requirements")),
    ("toefl", ("/english", "/requirements")),
    ("fee", ("/fees",)),
    ("fees", ("/fees",)),
    ("tuition", ("/fees", "/tuition")),
    ("scholarship", ("/scholarships",)),
    ("scholarships", ("/scholarships",)),
    ("contact", ("/contact",)),
)


@dataclass(frozen=True, slots=True)
class KeywordPlan:
    """User-reviewable keyword plan for future relevance strategies."""

    query: str
    positive_keywords: tuple[str, ...] = ()
    negative_keywords: tuple[str, ...] = ()
    url_hints: tuple[str, ...] = ()
    source: str = "user"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "positive_keywords": list(self.positive_keywords),
            "negative_keywords": list(self.negative_keywords),
            "url_hints": list(self.url_hints),
            "source": self.source,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class RelevanceDiagnostics:
    """Diagnostic details for a relevance decision."""

    strategy: str
    score: int
    signals: tuple[str, ...] = ()


def keyword_plan_from_query(query: str, *, source: str = "user") -> KeywordPlan:
    """Convert a user keyword query into a deterministic, reviewable plan."""

    if not isinstance(query, str):
        raise ValueError("Keyword query must be a string.")
    if source not in KEYWORD_PLAN_SOURCES:
        raise ValueError(f"Unsupported keyword plan source: {source}")
    normalized_query = _bounded_text(query.strip(), field="query", max_length=MAX_KEYWORD_QUERY_LENGTH)
    positive_keywords = tuple(_dedupe([token.lower() for token in KEYWORD_QUERY_SPLIT_RE.split(normalized_query) if token.strip()]))
    warnings = () if positive_keywords else ("empty_keyword_query",)
    return KeywordPlan(
        query=normalized_query,
        positive_keywords=positive_keywords,
        url_hints=tuple(_url_hints_for_keywords(positive_keywords)),
        source=source,
        warnings=warnings,
    )


def keyword_plan_from_payload(payload: dict[str, object], *, source: str | None = None) -> KeywordPlan:
    """Validate a structured keyword plan payload before it reaches a scorer."""

    allowed_keys = {"query", "positive_keywords", "negative_keywords", "url_hints", "source", "warnings"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported keyword plan fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Keyword plan missing required fields: {', '.join(sorted(missing_keys))}")
    plan_source = source or _required_text(payload.get("source"), field="source")
    if plan_source not in KEYWORD_PLAN_SOURCES:
        raise ValueError(f"Unsupported keyword plan source: {plan_source}")
    return KeywordPlan(
        query=_bounded_text(_required_text(payload.get("query"), field="query"), field="query", max_length=MAX_KEYWORD_QUERY_LENGTH),
        positive_keywords=tuple(_bounded_text_list(payload.get("positive_keywords", []), field="positive_keywords")),
        negative_keywords=tuple(_bounded_text_list(payload.get("negative_keywords", []), field="negative_keywords")),
        url_hints=tuple(_bounded_text_list(payload.get("url_hints", []), field="url_hints")),
        source=plan_source,
        warnings=tuple(_bounded_text_list(payload.get("warnings", []), field="warnings")),
    )


def build_relevance_strategy(
    *,
    relevance_strategy: str = "rule-based",
    keyword_query: str | None = None,
    keyword_plan: KeywordPlan | None = None,
    source: str = "user",
) -> tuple[KeywordPlan | None, RelevanceStrategy]:
    """Build a validated relevance strategy while preserving rule-based defaults."""

    normalized_strategy = _normalize_strategy_name(relevance_strategy)
    plan = keyword_plan or (keyword_plan_from_query(keyword_query, source=source) if keyword_query else None)
    if normalized_strategy == "rule-based":
        return plan, DEFAULT_RELEVANCE_STRATEGY
    if normalized_strategy == "bm25-like":
        if plan is None:
            raise ValueError("bm25-like relevance strategy requires a keyword query or keyword plan.")
        return plan, BM25LikeRelevanceStrategy(plan)
    raise ValueError(f"Unsupported relevance strategy: {relevance_strategy}")


class RelevanceStrategy(Protocol):
    """Scores candidate pages and decides whether discovered links are worth following."""

    name: str

    def score(self, url: str, title: str | None = None, text: str | None = None) -> int:
        ...

    def should_follow(self, url: str, policy: DomainPolicy) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class RuleBasedRelevanceStrategy:
    """Default strategy that preserves the existing rule-based scoring behavior."""

    name: str = "rule_based"

    def score(self, url: str, title: str | None = None, text: str | None = None) -> int:
        return score_url(url, title, text)

    def should_follow(self, url: str, policy: DomainPolicy) -> bool:
        return should_follow_url(url, policy)

    def diagnose(self, url: str, title: str | None = None, text: str | None = None) -> RelevanceDiagnostics:
        return RelevanceDiagnostics(strategy=self.name, score=self.score(url, title, text), signals=_rule_based_signals(url, title, text))


@dataclass(frozen=True, slots=True)
class BM25LikeRelevanceStrategy:
    """Opt-in deterministic keyword-plan scorer layered over the existing rules."""

    keyword_plan: KeywordPlan
    baseline_strategy: RelevanceStrategy = field(default_factory=RuleBasedRelevanceStrategy)
    name: str = "bm25_like"

    def score(self, url: str, title: str | None = None, text: str | None = None) -> int:
        baseline = self.baseline_strategy.score(url, title, text)
        positive_score, negative_score, hint_score = self._keyword_scores(url, title, text)
        return baseline + positive_score + hint_score - negative_score

    def should_follow(self, url: str, policy: DomainPolicy) -> bool:
        if not policy.is_allowed(url):
            return False
        if is_low_value_source_url(url):
            return False
        return self.score(url) >= -2

    def diagnose(self, url: str, title: str | None = None, text: str | None = None) -> RelevanceDiagnostics:
        baseline = relevance_diagnostics(self.baseline_strategy, url, title, text)
        signals = list(baseline.signals)
        positive_terms, negative_terms, url_hints = self._matched_terms(url, title, text)
        signals.extend(f"keyword_plan_positive:{term}" for term in positive_terms)
        signals.extend(f"keyword_plan_negative:{term}" for term in negative_terms)
        signals.extend(f"keyword_plan_url_hint:{hint}" for hint in url_hints)
        return RelevanceDiagnostics(strategy=self.name, score=self.score(url, title, text), signals=tuple(_dedupe(signals)))

    def _keyword_scores(self, url: str, title: str | None, text: str | None) -> tuple[int, int, int]:
        positive_terms, negative_terms, url_hints = self._matched_terms(url, title, text)
        return len(positive_terms) * 4, len(negative_terms) * 5, len(url_hints) * 3

    def _matched_terms(self, url: str, title: str | None, text: str | None) -> tuple[list[str], list[str], list[str]]:
        tokens = set(TEXT_TOKEN_RE.findall(" ".join(v for v in [url, title or "", text or ""] if v).lower()))
        path = urlparse(url).path.lower()
        positive_terms = [term for term in self.keyword_plan.positive_keywords if _keyword_matches(term, tokens)]
        negative_terms = [term for term in self.keyword_plan.negative_keywords if _keyword_matches(term, tokens)]
        url_hints = [hint for hint in self.keyword_plan.url_hints if hint.lower() in path]
        return positive_terms, negative_terms, url_hints


def relevance_diagnostics(
    strategy: RelevanceStrategy,
    url: str,
    title: str | None = None,
    text: str | None = None,
    *,
    score: int | None = None,
) -> RelevanceDiagnostics:
    """Return optional strategy diagnostics without making them part of discovery control flow."""

    strategy_name = getattr(strategy, "name", type(strategy).__name__)
    diagnose = getattr(strategy, "diagnose", None)
    if callable(diagnose):
        diagnostics = diagnose(url, title, text)
        return RelevanceDiagnostics(
            strategy=diagnostics.strategy or strategy_name,
            score=score if score is not None else diagnostics.score,
            signals=tuple(diagnostics.signals),
        )
    return RelevanceDiagnostics(
        strategy=str(strategy_name),
        score=score if score is not None else strategy.score(url, title, text),
        signals=(),
    )


def _rule_based_signals(url: str, title: str | None = None, text: str | None = None) -> tuple[str, ...]:
    haystack = " ".join(v for v in [url, title or "", text or ""] if v).lower()
    path = urlparse(url).path.lower()
    signals: list[str] = []
    signals.extend(f"positive_keyword:{kw}" for kw in POSITIVE_KEYWORDS if kw in haystack)
    signals.extend(f"negative_keyword:{kw}" for kw in NEGATIVE_KEYWORDS if kw in haystack)

    non_admissions_hits = [token for token in NON_ADMISSIONS_PATH_HINTS if token in path]
    undergrad_hits = [token for token in UNDERGRAD_ADMISSIONS_PATH_HINTS if token in path]
    if non_admissions_hits and not undergrad_hits:
        signals.extend(f"non_admissions_path:{token}" for token in non_admissions_hits)

    signals.extend(f"path_relevance_hint:{token}" for token in PATH_RELEVANCE_HINTS if token in path)
    signals.extend(f"programme_source_path_hint:{token}" for token in PROGRAMME_SOURCE_PATH_HINTS if token in path)
    signals.extend(f"path_noise_hint:{token}" for token in PATH_NOISE_HINTS if token in path)
    if is_pdf_url(url) and any(kw in haystack for kw in ("admission", "programme", "requirement", "prospectus")):
        signals.append("pdf_admissions_hint")
    if path.endswith(".json") or "/api/" in path:
        signals.append("api_endpoint_hint")
    return tuple(_dedupe(signals))


def _url_hints_for_keywords(keywords: tuple[str, ...]) -> list[str]:
    hints: list[str] = []
    for keyword in keywords:
        for term, term_hints in KEYWORD_URL_HINTS:
            if term in keyword:
                hints.extend(term_hints)
    return _dedupe(hints)


def _keyword_matches(keyword: str, tokens: set[str]) -> bool:
    keyword_tokens = TEXT_TOKEN_RE.findall(keyword.lower())
    return bool(keyword_tokens) and all(token in tokens for token in keyword_tokens)


def _normalize_strategy_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Relevance strategy must be a string.")
    normalized = RELEVANCE_STRATEGY_ALIASES.get(value)
    if normalized is None:
        raise ValueError(f"Unsupported relevance strategy: {value}")
    return normalized


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Keyword plan field {field} must be a string.")
    return value


def _bounded_text(value: str, *, field: str, max_length: int) -> str:
    stripped = value.strip()
    if len(stripped) > max_length:
        raise ValueError(f"Keyword plan field {field} exceeds {max_length} characters.")
    return stripped


def _bounded_text_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Keyword plan field {field} must be a list of strings.")
    if len(value) > MAX_KEYWORD_ITEMS:
        raise ValueError(f"Keyword plan field {field} exceeds {MAX_KEYWORD_ITEMS} items.")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Keyword plan field {field} must contain only strings.")
        bounded = _bounded_text(item, field=field, max_length=MAX_KEYWORD_LENGTH)
        if bounded:
            out.append(bounded.lower() if field.endswith("keywords") else bounded)
    return _dedupe(out)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


DEFAULT_RELEVANCE_STRATEGY = RuleBasedRelevanceStrategy()
