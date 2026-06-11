"""Relevance scoring strategies for bounded admissions discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Protocol
from urllib.parse import urlparse

from university_admissions_crawler.config import NEGATIVE_KEYWORDS, POSITIVE_KEYWORDS
from university_admissions_crawler.crawler.admissions_context import NON_ADMISSIONS_PATH_HINTS, UNDERGRAD_ADMISSIONS_PATH_HINTS
from university_admissions_crawler.crawler.filters import DomainPolicy, is_pdf_url, score_url, should_follow_url


PATH_RELEVANCE_HINTS: tuple[str, ...] = (
    "/admission",
    "/undergraduate",
    "/apply",
    "/programme",
    "/program",
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
    ("bachelor", ("/undergraduate", "/programmes")),
    ("programme", ("/programme", "/programmes")),
    ("program", ("/program", "/programs")),
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

    normalized_query = query.strip()
    positive_keywords = tuple(_dedupe([token.lower() for token in KEYWORD_QUERY_SPLIT_RE.split(normalized_query) if token.strip()]))
    warnings = () if positive_keywords else ("empty_keyword_query",)
    return KeywordPlan(
        query=normalized_query,
        positive_keywords=positive_keywords,
        url_hints=tuple(_url_hints_for_keywords(positive_keywords)),
        source=source,
        warnings=warnings,
    )


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


DEFAULT_RELEVANCE_STRATEGY = RuleBasedRelevanceStrategy()
