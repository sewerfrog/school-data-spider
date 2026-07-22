"""Bounded discovery for fixture/static admissions crawls."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from heapq import heappop, heappush

from university_admissions_crawler.crawler.fetcher import FetchResult, Fetcher
from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url, domain_policy_for_seed, is_low_value_source_url
from university_admissions_crawler.crawler.programme_sources import (
    BOUNDED_FRONTIER_SOURCE_ROLES,
    classify_programme_source_role,
    institution_profile_programme_urls,
    is_compound_programme_detail_source,
)
from university_admissions_crawler.crawler.relevance import DEFAULT_RELEVANCE_STRATEGY, KeywordPlan, RelevanceStrategy, relevance_diagnostics
from university_admissions_crawler.crawler.sitemap import common_official_path_probe_urls, parse_sitemap_urls, sitemap_probe_urls
from university_admissions_crawler.extractor.schema import WarningCode, WarningRecord


_CANONICAL_DETAIL_SCORE_BOOST = 30
_RELATED_COMPOUND_DETAIL_SCORE_BOOST = 20


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
    programme_source_family_budget: int = 4
    programme_detail_faculty_catalog_family_budget: int | None = None
    programme_detail_unbacked_family_budget: int | None = None
    programme_detail_targeted_reserve: int = 0
    capture_pending_frontier: bool = field(default=False, repr=False)
    frontier_diagnostics: list[dict[str, object]] = field(default_factory=list, repr=False)


@dataclass(slots=True)
class DiscoveredPage:
    result: FetchResult
    depth: int
    score: int = 0
    source_role: str = "unrelated"
    source_family: str = ""
    source_role_signals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FrontierCandidate:
    url: str
    depth: int
    score: int
    source_url: str | None = None
    anchor_text: str = ""
    reason_signals: tuple[str, ...] = ()
    source_role: str = "unrelated"
    source_role_priority: int = 2
    source_family: str = ""
    order: int = 0


def discover(seed_url: str, fetcher: Fetcher, config: DiscoveryConfig | None = None) -> list[DiscoveredPage]:
    config = config or DiscoveryConfig()
    config.frontier_diagnostics.clear()
    policy = domain_policy_for_seed(
        seed_url,
        allowed_hosts=config.allowed_hosts,
        allowed_domains=config.allowed_domains,
        allow_official_subdomains=config.allow_official_subdomains,
    )
    frontier: list[tuple[int, int, int, int, FrontierCandidate]] = []
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
    fetched_by_bounded_family: Counter[str] = Counter()
    catalog_backed_source_families: set[str] = set()
    faculty_catalog_backed_source_families: set[str] = set()
    canonical_catalog_backed_detail_urls: set[str] = set()
    sitemap_candidates_added = False
    profile_candidates_added = False
    path_probes_added = False

    while frontier and len(pages) < config.max_pages:
        _role_priority, _score_priority, _depth, _order, candidate = heappop(frontier)
        normalized = normalize_url(candidate.url)
        queued.discard(normalized)
        depth = candidate.depth
        if normalized in seen or depth > config.max_depth:
            continue
        if not policy.is_allowed(normalized):
            continue
        family_budget, family_budget_policy = _candidate_family_budget(
            candidate,
            config,
            faculty_catalog_backed_source_families,
            canonical_catalog_backed_detail_urls,
        )
        if (
            candidate.source_role in BOUNDED_FRONTIER_SOURCE_ROLES
            and fetched_by_bounded_family[candidate.source_family] >= family_budget
        ):
            seen.add(normalized)
            config.frontier_diagnostics.append(
                {
                    "url": normalized,
                    "decision": "skipped",
                    "reason": "programme_source_family_budget_exhausted",
                    "source_role": candidate.source_role,
                    "queued_source_role": candidate.source_role,
                    "source_family": candidate.source_family,
                    "depth": candidate.depth,
                    "score": candidate.score,
                    "order": candidate.order,
                    "source_url": candidate.source_url,
                    "family_fetched_count": fetched_by_bounded_family[candidate.source_family],
                    "family_budget": family_budget,
                    "family_budget_policy": family_budget_policy,
                    "queued_reason_signals": list(candidate.reason_signals),
                }
            )
            continue
        seen.add(normalized)
        result = _fetch_with_retries(fetcher, normalized, config.retries)
        if result.source is not None:
            result.source.is_official = policy.is_allowed(result.source.source_url)
        if not result.ok and "path_probe_candidate" in candidate.reason_signals:
            continue
        page_score = config.relevance_strategy.score(result.final_url, result.title, result.markdown or result.text)
        source_role = classify_programme_source_role(
            result.final_url,
            result.title,
            result.markdown or result.text,
            result.content_blocks,
        )
        if source_role.role in BOUNDED_FRONTIER_SOURCE_ROLES:
            fetched_by_bounded_family[source_role.source_family] += 1
        if source_role.role in {"canonical_catalog", "faculty_catalog"}:
            catalog_backed_source_families.add(source_role.source_family)
        if source_role.role == "faculty_catalog":
            faculty_catalog_backed_source_families.add(source_role.source_family)
        config.frontier_diagnostics.append(
            {
                "url": result.final_url,
                "decision": "fetched",
                "source_role": source_role.role,
                "queued_source_role": candidate.source_role,
                "source_family": source_role.source_family,
                "source_role_signals": list(source_role.signals),
                "queued_reason_signals": list(candidate.reason_signals),
                "depth": candidate.depth,
                "score": candidate.score,
                "order": candidate.order,
                "source_url": candidate.source_url,
            }
        )
        pages.append(
            DiscoveredPage(
                result=result,
                depth=depth,
                score=page_score,
                source_role=source_role.role,
                source_family=source_role.source_family,
                source_role_signals=source_role.signals,
            )
        )
        if result.ok and depth < config.max_depth:
            for link in result.links:
                link = normalize_url(link)
                linked_source_role = classify_programme_source_role(link, link).role
                if source_role.role == "canonical_catalog" and linked_source_role == "programme_detail":
                    canonical_catalog_backed_detail_urls.add(link)
                if link in seen or link in queued:
                    continue
                if not config.relevance_strategy.should_follow(link, policy):
                    continue
                is_canonical_detail_link = (
                    source_role.role == "canonical_catalog"
                    and linked_source_role == "programme_detail"
                )
                is_related_compound_detail_link = (
                    source_role.role == "programme_detail"
                    and linked_source_role == "programme_detail"
                    and source_role.source_family in catalog_backed_source_families
                    and is_compound_programme_detail_source(link)
                )
                link_signals: list[str] = []
                link_score_adjustment = 0
                if is_canonical_detail_link:
                    link_signals.append("canonical_catalog_detail_link")
                    link_score_adjustment += _CANONICAL_DETAIL_SCORE_BOOST
                if is_related_compound_detail_link:
                    link_signals.append("related_compound_programme_detail_link")
                    link_score_adjustment += _RELATED_COMPOUND_DETAIL_SCORE_BOOST
                queued.add(link)
                next_candidate = _candidate_for(
                    link,
                    depth=depth + 1,
                    source_url=result.final_url,
                    anchor_text=link,
                    strategy=config.relevance_strategy,
                    order=next_order,
                    extra_signals=tuple(link_signals),
                    score_adjustment=link_score_adjustment,
                )
                next_order += 1
                _push_candidate(frontier, next_candidate)
        if not sitemap_candidates_added:
            sitemap_candidates_added = True
            next_order = _enqueue_sitemap_candidates(seed_url, fetcher, config, policy, frontier, seen, queued, next_order)
            next_order = _enqueue_extra_candidates(seed_url, config, frontier, seen, queued, next_order)
        if not profile_candidates_added:
            profile_candidates_added = True
            next_order = _enqueue_institution_profile_candidates(seed_url, config, frontier, seen, queued, next_order)
        if not path_probes_added and not frontier:
            path_probes_added = True
            next_order = _enqueue_common_path_probe_candidates(seed_url, config, frontier, seen, queued, next_order)
    if config.capture_pending_frontier:
        _record_pending_programme_detail_candidates(config, frontier, seen)
    return pages


def fetch_discovered_candidate(
    seed_url: str,
    url: str,
    fetcher: Fetcher,
    config: DiscoveryConfig,
    *,
    depth: int,
    policy: DomainPolicy | None = None,
) -> DiscoveredPage | None:
    """Fetch one already-discovered candidate under the scan's existing policy."""

    normalized = normalize_url(url)
    policy = policy or domain_policy_for_seed(
        seed_url,
        allowed_hosts=config.allowed_hosts,
        allowed_domains=config.allowed_domains,
        allow_official_subdomains=config.allow_official_subdomains,
    )
    if not policy.is_allowed(normalized) or depth > config.max_depth:
        return None
    result = _fetch_with_retries(fetcher, normalized, config.retries)
    if result.source is not None:
        result.source.is_official = policy.is_allowed(result.source.source_url)
    source_role = classify_programme_source_role(
        result.final_url,
        result.title,
        result.markdown or result.text,
        result.content_blocks,
    )
    return DiscoveredPage(
        result=result,
        depth=depth,
        score=config.relevance_strategy.score(result.final_url, result.title, result.markdown or result.text),
        source_role=source_role.role,
        source_family=source_role.source_family,
        source_role_signals=source_role.signals,
    )


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
    source_role = classify_programme_source_role(normalized, anchor_text)
    return FrontierCandidate(
        url=normalized,
        depth=depth,
        score=diagnostics.score + score_adjustment,
        source_url=source_url,
        anchor_text=anchor_text,
        reason_signals=tuple(dict.fromkeys((*diagnostics.signals, *source_role.signals, *extra_signals))),
        source_role=source_role.role,
        source_role_priority=source_role.priority,
        source_family=source_role.source_family,
        order=order,
    )


def _push_candidate(frontier: list[tuple[int, int, int, int, FrontierCandidate]], candidate: FrontierCandidate) -> None:
    heappush(frontier, (candidate.source_role_priority, -candidate.score, candidate.depth, candidate.order, candidate))


def _candidate_family_budget(
    candidate: FrontierCandidate,
    config: DiscoveryConfig,
    faculty_catalog_backed_source_families: set[str],
    canonical_catalog_backed_detail_urls: set[str],
) -> tuple[int, str]:
    default_budget = max(0, config.programme_source_family_budget)
    faculty_catalog_budget = config.programme_detail_faculty_catalog_family_budget
    if (
        candidate.source_role == "programme_detail"
        and candidate.source_family in faculty_catalog_backed_source_families
        and faculty_catalog_budget is not None
    ):
        return min(default_budget, max(0, faculty_catalog_budget)), "faculty_catalog_backed_detail"
    unbacked_budget = config.programme_detail_unbacked_family_budget
    if (
        candidate.source_role == "programme_detail"
        and normalize_url(candidate.url) not in canonical_catalog_backed_detail_urls
        and unbacked_budget is not None
    ):
        return min(default_budget, max(0, unbacked_budget)), "catalog_unbacked_detail"
    return default_budget, "default"


def _record_pending_programme_detail_candidates(
    config: DiscoveryConfig,
    frontier: list[tuple[int, int, int, int, FrontierCandidate]],
    seen: set[str],
) -> None:
    recorded_urls = {
        normalize_url(str(item["url"]))
        for item in config.frontier_diagnostics
        if isinstance(item.get("url"), str)
    }
    for _role_priority, _score_priority, _depth, _order, candidate in sorted(frontier):
        normalized = normalize_url(candidate.url)
        if candidate.source_role != "programme_detail" or normalized in seen or normalized in recorded_urls:
            continue
        config.frontier_diagnostics.append(
            {
                "url": normalized,
                "decision": "pending",
                "reason": "page_budget_reserved",
                "source_role": candidate.source_role,
                "queued_source_role": candidate.source_role,
                "source_family": candidate.source_family,
                "depth": candidate.depth,
                "score": candidate.score,
                "order": candidate.order,
                "source_url": candidate.source_url,
                "queued_reason_signals": list(candidate.reason_signals),
            }
        )
        recorded_urls.add(normalized)


def _enqueue_sitemap_candidates(
    seed_url: str,
    fetcher: Fetcher,
    config: DiscoveryConfig,
    policy: DomainPolicy,
    frontier: list[tuple[int, int, int, int, FrontierCandidate]],
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
    frontier: list[tuple[int, int, int, int, FrontierCandidate]],
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
    frontier: list[tuple[int, int, int, int, FrontierCandidate]],
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


def _enqueue_institution_profile_candidates(
    seed_url: str,
    config: DiscoveryConfig,
    frontier: list[tuple[int, int, int, int, FrontierCandidate]],
    seen: set[str],
    queued: set[str],
    next_order: int,
) -> int:
    if config.max_depth < 1:
        return next_order
    for url in institution_profile_programme_urls(seed_url):
        next_order = _queue_url_candidate(
            url,
            depth=1,
            source_url=seed_url,
            anchor_text=url,
            extra_signals=("institution_profile_candidate",),
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
    frontier: list[tuple[int, int, int, int, FrontierCandidate]],
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
