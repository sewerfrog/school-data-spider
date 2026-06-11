"""Relevance scoring strategies for bounded admissions discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from university_admissions_crawler.crawler.filters import DomainPolicy, score_url, should_follow_url


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


DEFAULT_RELEVANCE_STRATEGY = RuleBasedRelevanceStrategy()
