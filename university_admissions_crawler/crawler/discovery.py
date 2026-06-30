"""Bounded discovery for fixture/static admissions crawls."""

from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappop, heappush
from urllib.parse import urlparse

from university_admissions_crawler.crawler.fetcher import FetchResult, Fetcher
from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url, is_low_value_source_url
from university_admissions_crawler.crawler.relevance import DEFAULT_RELEVANCE_STRATEGY, KeywordPlan, RelevanceStrategy, relevance_diagnostics
from university_admissions_crawler.crawler.sitemap import common_official_path_probe_urls, parse_sitemap_urls, sitemap_probe_urls
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
    extra_candidates: tuple[str, ...] = ()


@dataclass(slots=True)
class DiscoveredPage:
    result: FetchResult
    depth: int
    score: int = 0


@dataclass(frozen=True, slots=True)
class FrontierCandidate:
    url: str
    depth: int
    score: int
    source_url: str | None = None
    anchor_text: str = ""
    reason_signals: tuple[str, ...] = ()
    order: int = 0


def discover(seed_url: str, fetcher: Fetcher, config: DiscoveryConfig | None = None) -> list[DiscoveredPage]:
    config = config or DiscoveryConfig()
    policy = DomainPolicy(
        seed_url=seed_url,
        allowed_hosts=set(config.allowed_hosts) | {urlparse(seed_url).netloc},
        allowed_domains=config.allowed_domains,
        allow_official_subdomains=config.allow_official_subdomains,
    )
    frontier: list[tuple[int, int, int, FrontierCandidate]] = []
    next_order = 0
    seed = _candidate_for(
        seed_url,
        depth=0,
        source_url=None,
        anchor_text=seed_url,
        strategy=config.relevance_strategy,
        order=next_order,
    )
    next_order += 1
    _push_candidate(frontier, seed)
    seen: set[str] = set()
    queued: set[str] = {normalize_url(seed_url)}
    pages: list[DiscoveredPage] = []
    sitemap_candidates_added = False
    path_probes_added = False

    while frontier and len(pages) < config.max_pages:
        _priority, _depth, _order, candidate = heappop(frontier)
        normalized = normalize_url(candidate.url)
        queued.discard(normalized)
        depth = candidate.depth
        if normalized in seen or depth > config.max_depth:
            continue
        seen.add(normalized)
        if not policy.is_allowed(normalized):
            continue
        result = _fetch_with_retries(fetcher, normalized, config.retries)
        if not result.ok and "path_probe_candidate" in candidate.reason_signals:
            continue
        page_score = config.relevance_strategy.score(result.final_url, result.title, result.markdown or result.text)
        pages.append(DiscoveredPage(result=result, depth=depth, score=page_score))
        if result.ok and depth < config.max_depth:
            for link in result.links:
                link = normalize_url(link)
                if link in seen or link in queued:
                    continue
                if not config.relevance_strategy.should_follow(link, policy):
                    continue
                queued.add(link)
                next_candidate = _candidate_for(
                    link,
                    depth=depth + 1,
                    source_url=result.final_url,
                    anchor_text=link,
                    strategy=config.relevance_strategy,
                    order=next_order,
                )
                next_order += 1
                _push_candidate(frontier, next_candidate)
        if not sitemap_candidates_added:
            sitemap_candidates_added = True
            next_order = _enqueue_sitemap_candidates(seed_url, fetcher, config, policy, frontier, seen, queued, next_order)
            next_order = _enqueue_extra_candidates(seed_url, config, frontier, seen, queued, next_order)
        if not path_probes_added and not frontier:
            path_probes_added = True
            next_order = _enqueue_common_path_probe_candidates(seed_url, config, frontier, seen, queued, next_order)
    return pages


def normalize_url(url: str) -> str:
    return canonicalize_url(url)


def _candidate_for(
    url: str,
    *,
    depth: int,
    source_url: str | None,
    anchor_text: str,
    strategy: RelevanceStrategy,
    order: int,
    extra_signals: tuple[str, ...] = (),
    score_adjustment: int = 0,
) -> FrontierCandidate:
    normalized = normalize_url(url)
    diagnostics = relevance_diagnostics(strategy, normalized, text=anchor_text)
    return FrontierCandidate(
        url=normalized,
        depth=depth,
        score=diagnostics.score + score_adjustment,
        source_url=source_url,
        anchor_text=anchor_text,
        reason_signals=tuple(dict.fromkeys((*diagnostics.signals, *extra_signals))),
        order=order,
    )


def _push_candidate(frontier: list[tuple[int, int, int, FrontierCandidate]], candidate: FrontierCandidate) -> None:
    heappush(frontier, (-candidate.score, candidate.depth, candidate.order, candidate))


def _enqueue_sitemap_candidates(
    seed_url: str,
    fetcher: Fetcher,
    config: DiscoveryConfig,
    policy: DomainPolicy,
    frontier: list[tuple[int, int, int, FrontierCandidate]],
    seen: set[str],
    queued: set[str],
    next_order: int,
) -> int:
    if config.max_depth < 1:
        return next_order
    for url in _sitemap_candidate_urls(seed_url, fetcher, config, policy):
        next_order = _queue_url_candidate(
            url,
            depth=1,
            source_url=seed_url,
            anchor_text=url,
            extra_signals=("sitemap_candidate",),
            score_adjustment=0,
            strategy=config.relevance_strategy,
            frontier=frontier,
            seen=seen,
            queued=queued,
            next_order=next_order,
        )
    return next_order


def _enqueue_common_path_probe_candidates(
    seed_url: str,
    config: DiscoveryConfig,
    frontier: list[tuple[int, int, int, FrontierCandidate]],
    seen: set[str],
    queued: set[str],
    next_order: int,
) -> int:
    if config.max_depth < 1:
        return next_order
    for url in common_official_path_probe_urls(seed_url):
        next_order = _queue_url_candidate(
            url,
            depth=1,
            source_url=seed_url,
            anchor_text=url,
            extra_signals=("path_probe_candidate",),
            score_adjustment=-30,
            strategy=config.relevance_strategy,
            frontier=frontier,
            seen=seen,
            queued=queued,
            next_order=next_order,
        )
    return next_order


def _enqueue_extra_candidates(
    seed_url: str,
    config: DiscoveryConfig,
    frontier: list[tuple[int, int, int, FrontierCandidate]],
    seen: set[str],
    queued: set[str],
    next_order: int,
) -> int:
    if config.max_depth < 1:
        return next_order
    for url in config.extra_candidates:
        next_order = _queue_url_candidate(
            url,
            depth=1,
            source_url=seed_url,
            anchor_text=url,
            extra_signals=("extra_candidate",),
            score_adjustment=0,
            strategy=config.relevance_strategy,
            frontier=frontier,
            seen=seen,
            queued=queued,
            next_order=next_order,
        )
    return next_order


def _sitemap_candidate_urls(seed_url: str, fetcher: Fetcher, config: DiscoveryConfig, policy: DomainPolicy) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for sitemap_url in sitemap_probe_urls(seed_url):
        sitemap_url = normalize_url(sitemap_url)
        if not policy.is_allowed(sitemap_url) or is_low_value_source_url(sitemap_url):
            continue
        result = _fetch_with_retries(fetcher, sitemap_url, config.retries)
        if not result.ok:
            continue
        for url in parse_sitemap_urls(result.text, result.final_url):
            normalized = normalize_url(url)
            if normalized in seen:
                continue
            if not config.relevance_strategy.should_follow(normalized, policy):
                continue
            urls.append(normalized)
            seen.add(normalized)
    return urls


def _queue_url_candidate(
    url: str,
    *,
    depth: int,
    source_url: str | None,
    anchor_text: str,
    extra_signals: tuple[str, ...],
    score_adjustment: int,
    strategy: RelevanceStrategy,
    frontier: list[tuple[int, int, int, FrontierCandidate]],
    seen: set[str],
    queued: set[str],
    next_order: int,
) -> int:
    normalized = normalize_url(url)
    if normalized in seen or normalized in queued:
        return next_order
    candidate = _candidate_for(
        normalized,
        depth=depth,
        source_url=source_url,
        anchor_text=anchor_text,
        strategy=strategy,
        order=next_order,
        extra_signals=extra_signals,
        score_adjustment=score_adjustment,
    )
    queued.add(normalized)
    _push_candidate(frontier, candidate)
    return next_order + 1


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
