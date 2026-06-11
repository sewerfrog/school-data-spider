"""Bounded discovery for fixture/static admissions crawls."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlparse

from university_admissions_crawler.crawler.fetcher import FetchResult, Fetcher
from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url
from university_admissions_crawler.crawler.relevance import DEFAULT_RELEVANCE_STRATEGY, KeywordPlan, RelevanceStrategy
from university_admissions_crawler.extractor.schema import WarningCode, WarningRecord


@dataclass(slots=True)
class DiscoveryConfig:
    max_depth: int = 3
    max_pages: int = 20
    allowed_hosts: set[str] = field(default_factory=set)
    allowed_domains: set[str] = field(default_factory=set)
    allow_official_subdomains: bool = True
    retries: int = 1
    relevance_strategy: RelevanceStrategy = DEFAULT_RELEVANCE_STRATEGY
    keyword_plan: KeywordPlan | None = None


@dataclass(slots=True)
class DiscoveredPage:
    result: FetchResult
    depth: int
    score: int = 0


def discover(seed_url: str, fetcher: Fetcher, config: DiscoveryConfig | None = None) -> list[DiscoveredPage]:
    config = config or DiscoveryConfig()
    policy = DomainPolicy(
        seed_url=seed_url,
        allowed_hosts=set(config.allowed_hosts) | {urlparse(seed_url).netloc},
        allowed_domains=config.allowed_domains,
        allow_official_subdomains=config.allow_official_subdomains,
    )
    queue: deque[tuple[str, int]] = deque([(seed_url, 0)])
    seen: set[str] = set()
    pages: list[DiscoveredPage] = []

    while queue and len(pages) < config.max_pages:
        url, depth = queue.popleft()
        normalized = normalize_url(url)
        if normalized in seen or depth > config.max_depth:
            continue
        seen.add(normalized)
        if not policy.is_allowed(normalized):
            continue
        result = _fetch_with_retries(fetcher, normalized, config.retries)
        page_score = config.relevance_strategy.score(result.final_url, result.title, result.markdown or result.text)
        pages.append(DiscoveredPage(result=result, depth=depth, score=page_score))
        if result.ok and depth < config.max_depth:
            scored_links = sorted(
                ((config.relevance_strategy.score(normalize_url(link), text=link), normalize_url(link)) for link in result.links),
                key=lambda item: item[0],
                reverse=True,
            )
            for _, link in scored_links:
                link = normalize_url(link)
                if link not in seen and config.relevance_strategy.should_follow(link, policy):
                    queue.append((link, depth + 1))
    return pages


def normalize_url(url: str) -> str:
    return canonicalize_url(url)


def _fetch_with_retries(fetcher: Fetcher, url: str, retries: int) -> FetchResult:
    result = _safe_fetch(fetcher, url)
    attempts = 0
    while attempts < retries and _should_retry(result):
        attempts += 1
        result = _safe_fetch(fetcher, url)
    return result


def _safe_fetch(fetcher: Fetcher, url: str) -> FetchResult:
    try:
        return _with_contract_warnings(fetcher.fetch(url))
    except Exception as exc:
        return FetchResult(
            url=url,
            final_url=url,
            status=0,
            title=None,
            content_type="application/octet-stream",
            retrieved_at="",
            engine=getattr(fetcher, "engine", "unknown"),
            warnings=[
                WarningRecord(
                    WarningCode.FETCH_FAILED,
                    f"Fetcher raised {type(exc).__name__}: {exc}",
                    field=url,
                    source_urls=[url],
                )
            ],
        )


def _with_contract_warnings(result: FetchResult) -> FetchResult:
    if result.status >= 400 and not any(w.code == WarningCode.FETCH_FAILED for w in result.warnings):
        result.warnings.append(
            WarningRecord(
                WarningCode.FETCH_FAILED,
                f"Fetch returned HTTP status {result.status}.",
                field=result.final_url or result.url,
                source_urls=[result.final_url or result.url],
            )
        )
    return result


def _should_retry(result: FetchResult) -> bool:
    return result.status >= 400 or any(w.code == WarningCode.FETCH_FAILED for w in result.warnings)
