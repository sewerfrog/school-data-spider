"""Second-phase programme detail selection from the bounded discovery frontier."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from university_admissions_crawler.crawler.filters import canonicalize_url
from university_admissions_crawler.crawler.programme_sources import (
    BOUNDED_FRONTIER_SOURCE_ROLES,
    is_catalog_backed_programme_detail_source,
)
from university_admissions_crawler.extractor.schema import AdmissionsData
from university_admissions_crawler.pipeline.programme_catalog_merge import (
    normalise_programme_detail_identity,
    programme_detail_identity_from_url,
)


@dataclass(frozen=True, slots=True)
class TargetedProgrammeDetailCandidate:
    url: str
    depth: int
    score: int
    source_family: str
    row_index: int
    row_name: str
    match_method: str
    selection_tier: str
    backing_catalog_roles: tuple[str, ...]
    reason_signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "depth": self.depth,
            "score": self.score,
            "source_family": self.source_family,
            "matched_claim_path": f"/programme_catalog/{self.row_index}/name",
            "programme_name": self.row_name,
            "match_method": self.match_method,
            "selection_tier": self.selection_tier,
            "backing_catalog_roles": list(self.backing_catalog_roles),
            "reason_signals": list(self.reason_signals),
        }


def targeted_programme_detail_family_reserve(reserve_limit: int, family_budget: int) -> int:
    """Reserve family capacity for evidence-aware selection without raising the family cap."""

    bounded_reserve = max(0, reserve_limit)
    bounded_family_budget = max(0, family_budget)
    if bounded_reserve <= 2:
        return min(bounded_reserve, bounded_family_budget)
    return min(bounded_reserve - 1, bounded_family_budget)


def select_targeted_programme_detail_candidates(
    data: AdmissionsData,
    frontier_entries: list[dict[str, object]],
    *,
    limit: int,
    family_budget: int,
) -> list[TargetedProgrammeDetailCandidate]:
    """Select unfetched details that uniquely identify rows still missing faculty evidence."""

    bounded_limit = max(0, limit)
    bounded_family_budget = max(0, family_budget)
    catalog_sources = _catalog_sources(data)
    catalog_urls = tuple(url for url, _role in catalog_sources)
    faculty_catalog_urls = tuple(url for url, role in catalog_sources if role == "faculty_catalog")
    unresolved_by_identity: dict[str, list[int]] = defaultdict(list)
    primary_url_indexes: dict[str, list[int]] = defaultdict(list)
    provenance = data.run.config.get("programme_catalog_row_provenance")
    for index, row in enumerate(data.programme_catalog):
        if row.faculty_or_school:
            continue
        identity = normalise_programme_detail_identity(row.name)
        if identity:
            unresolved_by_identity[identity].append(index)
        item = provenance.get(row.evidence_path) if isinstance(provenance, dict) else None
        primary_urls = item.get("primary_source_urls") if isinstance(item, dict) else None
        if isinstance(primary_urls, list):
            for url in primary_urls:
                if isinstance(url, str) and url:
                    primary_url_indexes[canonicalize_url(url)].append(index)

    fetched_urls = {
        canonicalize_url(str(item.get("url")))
        for item in frontier_entries
        if item.get("decision") == "fetched" and item.get("url")
    }
    fetched_by_family = Counter(
        str(item.get("source_family", ""))
        for item in frontier_entries
        if item.get("decision") == "fetched"
        and item.get("source_role") in BOUNDED_FRONTIER_SOURCE_ROLES
    )
    rejection_counts: Counter[str] = Counter()
    candidates_by_url: dict[str, tuple[tuple[int, int, int, int, int, str], TargetedProgrammeDetailCandidate]] = {}
    for entry in frontier_entries:
        if entry.get("decision") not in {"pending", "skipped"}:
            continue
        if entry.get("source_role") != "programme_detail" and entry.get("queued_source_role") != "programme_detail":
            continue
        raw_url = entry.get("url")
        if not isinstance(raw_url, str) or not raw_url:
            continue
        url = canonicalize_url(raw_url)
        if url in fetched_urls:
            rejection_counts["already_fetched"] += 1
            continue
        source_family = str(entry.get("source_family", ""))
        if fetched_by_family[source_family] >= bounded_family_budget:
            rejection_counts["family_budget_exhausted"] += 1
            continue

        primary_matches = list(dict.fromkeys(primary_url_indexes.get(url, [])))
        identity = programme_detail_identity_from_url(url)
        identity_matches = list(dict.fromkeys(unresolved_by_identity.get(identity, []))) if identity else []
        if len(primary_matches) == 1:
            row_index = primary_matches[0]
            match_method = "primary_source_url"
        elif len(identity_matches) == 1:
            if not is_catalog_backed_programme_detail_source(url, catalog_urls):
                rejection_counts["detail_source_family_without_catalog_context"] += 1
                continue
            row_index = identity_matches[0]
            match_method = "detail_url_identity"
        elif len(primary_matches) > 1 or len(identity_matches) > 1:
            rejection_counts["ambiguous_unresolved_row_match"] += 1
            continue
        else:
            rejection_counts["no_unresolved_row_match"] += 1
            continue

        row = data.programme_catalog[row_index]
        faculty_catalog_backed = is_catalog_backed_programme_detail_source(url, faculty_catalog_urls)
        backing_catalog_roles = _backing_catalog_roles(
            url,
            row_source_url=row.source_url,
            match_method=match_method,
            catalog_sources=catalog_sources,
        )
        reason_signals = tuple(
            str(item)
            for item in entry.get("queued_reason_signals", [])
            if isinstance(item, str)
        )
        candidate = TargetedProgrammeDetailCandidate(
            url=url,
            depth=max(0, int(entry.get("depth", 0))),
            score=int(entry.get("score", 0)),
            source_family=source_family,
            row_index=row_index,
            row_name=row.name,
            match_method=match_method,
            selection_tier=(
                "faculty_catalog_backed"
                if faculty_catalog_backed
                else "catalog_backed_exploration"
            ),
            backing_catalog_roles=backing_catalog_roles,
            reason_signals=reason_signals,
        )
        priority = (
            0 if "/detail/" in url.lower() else 1,
            candidate.row_index,
            0 if match_method == "primary_source_url" else 1,
            candidate.depth,
            int(entry.get("order", 0)),
            url,
        )
        existing = candidates_by_url.get(url)
        if existing is None or priority < existing[0]:
            candidates_by_url[url] = (priority, candidate)

    ranked = sorted(candidates_by_url.values(), key=lambda item: item[0])
    selected: list[TargetedProgrammeDetailCandidate] = []
    selected_rows: set[int] = set()
    selected_by_family: Counter[str] = Counter()
    faculty_backed = [item for item in ranked if item[1].selection_tier == "faculty_catalog_backed"]
    exploration = [item for item in ranked if item[1].selection_tier == "catalog_backed_exploration"]
    exploration_quota = 1 if bounded_limit > 1 and faculty_backed and exploration else 0

    def select_from(
        pool: list[tuple[tuple[int, int, int, int, int, str], TargetedProgrammeDetailCandidate]],
        target_count: int,
    ) -> None:
        while len(selected) < target_count:
            eligible = [
                item
                for item in pool
                if item[1].row_index not in selected_rows
                and fetched_by_family[item[1].source_family] + selected_by_family[item[1].source_family]
                < bounded_family_budget
            ]
            if not eligible:
                return
            _priority, chosen = min(
                eligible,
                key=lambda item: (selected_by_family[item[1].source_family], *item[0]),
            )
            selected.append(chosen)
            selected_rows.add(chosen.row_index)
            selected_by_family[chosen.source_family] += 1

    select_from(faculty_backed, bounded_limit - exploration_quota)
    select_from(exploration, min(bounded_limit, len(selected) + exploration_quota))
    select_from(ranked, bounded_limit)

    candidate_tier_counts = Counter(item[1].selection_tier for item in ranked)
    selected_tier_counts = Counter(item.selection_tier for item in selected)

    data.run.config["programme_catalog_targeted_detail_selection"] = {
        "enabled": bounded_limit > 0,
        "reserve_limit": bounded_limit,
        "family_budget": bounded_family_budget,
        "frontier_candidate_count": len(candidates_by_url),
        "eligible_row_count": len({item[1].row_index for item in candidates_by_url.values()}),
        "selected_count": len(selected),
        "selected": [item.to_dict() for item in selected],
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "ranking_policy": "faculty_catalog_backing_then_catalog_row_order_with_one_exploration",
        "relevance_score_role": "diagnostic_only",
        "exploration_quota": exploration_quota,
        "candidate_tier_counts": dict(sorted(candidate_tier_counts.items())),
        "selected_tier_counts": dict(sorted(selected_tier_counts.items())),
    }
    return selected


def _catalog_sources(data: AdmissionsData) -> tuple[tuple[str, str], ...]:
    source_strategy = data.run.config.get("source_strategy")
    if not isinstance(source_strategy, list):
        return ()
    return tuple(dict.fromkeys(
        (str(item.get("url")), str(item.get("source_role")))
        for item in source_strategy
        if isinstance(item, dict)
        and item.get("source_role") in {"canonical_catalog", "faculty_catalog"}
        and item.get("url")
    ))


def _backing_catalog_roles(
    detail_url: str,
    *,
    row_source_url: str,
    match_method: str,
    catalog_sources: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    roles = {
        role
        for catalog_url, role in catalog_sources
        if is_catalog_backed_programme_detail_source(detail_url, (catalog_url,))
    }
    if match_method == "primary_source_url":
        row_source = canonicalize_url(row_source_url)
        roles.update(
            role
            for catalog_url, role in catalog_sources
            if canonicalize_url(catalog_url) == row_source
        )
    return tuple(sorted(roles))
