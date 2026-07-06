"""Discovery diagnostics and safe capture bookkeeping for public catalog APIs."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import parse_qsl, urljoin, urlparse

from university_admissions_crawler.crawler.discovery import DiscoveredPage, DiscoveryConfig
from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url
from university_admissions_crawler.extractor.schema import AdmissionsData, SourceType


MAX_API_CATALOG_CANDIDATES = 50
MAX_API_RESPONSE_SIZE_BYTES = 2_000_000
MAX_SAFE_API_CAPTURE_CANDIDATES = 5
SAFE_API_CAPTURE_STATUSES = {"not_fetched", "captured_url_only"}


def attach_api_catalog_discovery_diagnostics(
    data: AdmissionsData,
    pages: list[DiscoveredPage],
    *,
    seed_url: str,
    config: DiscoveryConfig,
) -> None:
    """Attach API endpoint candidate diagnostics without changing facts."""

    policy = DomainPolicy(
        seed_url=seed_url,
        allowed_hosts=set(config.allowed_hosts) | {urlparse(seed_url).netloc},
        allowed_domains=set(config.allowed_domains),
        allow_official_subdomains=config.allow_official_subdomains,
    )
    fetched_json_by_url = _fetched_json_by_url(pages)
    candidates_by_url: dict[str, dict[str, object]] = {}

    for page in pages:
        result = page.result
        if result.source is not None and result.source.source_type == SourceType.JSON:
            _add_candidate(
                candidates_by_url,
                raw_url=result.final_url,
                base_url=result.final_url,
                source_page=result.final_url,
                reason="captured_json_source",
                source_kind="captured_json",
                policy=policy,
                fetched_json_by_url=fetched_json_by_url,
            )
        for link in result.links:
            _add_candidate(
                candidates_by_url,
                raw_url=link,
                base_url=result.final_url,
                source_page=result.final_url,
                reason="linked_or_network_api_url",
                source_kind="captured_url",
                policy=policy,
                fetched_json_by_url=fetched_json_by_url,
            )
        for endpoint in _embedded_endpoint_hints(result.text, result.final_url):
            _add_candidate(
                candidates_by_url,
                raw_url=endpoint,
                base_url=result.final_url,
                source_page=result.final_url,
                reason="embedded_endpoint_hint",
                source_kind="embedded_hint",
                policy=policy,
                fetched_json_by_url=fetched_json_by_url,
            )

    candidates = list(candidates_by_url.values())[:MAX_API_CATALOG_CANDIDATES]
    data.run.config["programme_catalog_api_candidates"] = candidates
    refresh_api_catalog_discovery_summary(data)


def api_catalog_candidate_capture_urls(
    data: AdmissionsData,
    *,
    existing_urls: set[str] | None = None,
    max_candidates: int = MAX_SAFE_API_CAPTURE_CANDIDATES,
) -> list[str]:
    """Return bounded unfetched API candidate URLs eligible for safe GET capture."""

    if max_candidates <= 0:
        return []
    existing = {canonicalize_url(url) for url in existing_urls or set()}
    urls: list[str] = []
    seen: set[str] = set()
    for item in _candidate_items(data):
        url_value = item.get("api_candidate_url")
        status = str(item.get("api_candidate_status", "unknown"))
        if not isinstance(url_value, str) or not url_value:
            continue
        url = canonicalize_url(url_value)
        if status not in SAFE_API_CAPTURE_STATUSES:
            continue
        if url in existing or url in seen:
            continue
        urls.append(url)
        seen.add(url)
        if len(urls) >= max_candidates:
            break
    return urls


def mark_api_catalog_candidate_capture(
    data: AdmissionsData,
    url: str,
    *,
    status: str,
    content_type: str | None = None,
    response_size_bytes: int | None = None,
    captured_url: str | None = None,
    rejection_reason: str | None = None,
) -> None:
    """Update a candidate status after bounded capture and refresh its summary."""

    target_url = canonicalize_url(url)
    for item in _candidate_items(data):
        item_url = item.get("api_candidate_url")
        if not isinstance(item_url, str) or canonicalize_url(item_url) != target_url:
            continue
        item["api_candidate_status"] = status
        if content_type is not None:
            item["api_response_content_type"] = content_type
        if response_size_bytes is not None:
            item["api_response_size_bytes"] = response_size_bytes
        if captured_url is not None and canonicalize_url(captured_url) != target_url:
            item["api_captured_url"] = canonicalize_url(captured_url)
        if rejection_reason:
            item["api_capture_rejection_reason"] = rejection_reason
        break
    refresh_api_catalog_discovery_summary(data)


def refresh_api_catalog_discovery_summary(data: AdmissionsData) -> None:
    """Refresh aggregate discovery diagnostics after candidate status changes."""

    candidates = _candidate_items(data)
    status_counts = Counter(str(item.get("api_candidate_status", "unknown")) for item in candidates)
    reason_counts = Counter(str(item.get("api_candidate_reason", "unknown")) for item in candidates)
    data.run.config["programme_catalog_api_discovery_summary"] = {
        "api_catalog_candidate_count": len(candidates),
        "api_candidate_urls": [str(item.get("api_candidate_url")) for item in candidates if item.get("api_candidate_url")],
        "api_candidate_status_counts": dict(sorted(status_counts.items())),
        "api_candidate_reason_counts": dict(sorted(reason_counts.items())),
        "captured_json_count": status_counts.get("captured_json", 0),
        "rejected_count": sum(count for status, count in status_counts.items() if status.startswith("rejected_")),
        "safe_capture_pending_count": sum(status_counts.get(status, 0) for status in SAFE_API_CAPTURE_STATUSES),
        "note": "API catalog candidates become admissions facts only after an official captured JSON response is parsed with row-level evidence.",
    }


def _candidate_items(data: AdmissionsData) -> list[dict[str, object]]:
    candidates = data.run.config.get("programme_catalog_api_candidates")
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, dict)]


def _add_candidate(
    candidates_by_url: dict[str, dict[str, object]],
    *,
    raw_url: str,
    base_url: str,
    source_page: str,
    reason: str,
    source_kind: str,
    policy: DomainPolicy,
    fetched_json_by_url: dict[str, object],
) -> None:
    url = canonicalize_url(urljoin(base_url, raw_url))
    if not _looks_like_catalog_api_url(url):
        return
    status = _candidate_status(url, policy, source_kind, fetched_json_by_url)
    captured = fetched_json_by_url.get(url)
    response_content_type = getattr(captured, "content_type", None) if captured is not None else None
    response_size = len(getattr(captured, "text", "").encode("utf-8")) if captured is not None else None
    if isinstance(response_size, int) and response_size > MAX_API_RESPONSE_SIZE_BYTES:
        status = "rejected_too_large"
    existing = candidates_by_url.get(url)
    if existing is not None:
        if existing.get("api_candidate_status") != "captured_json" and status == "captured_json":
            existing["api_candidate_status"] = status
            existing["api_response_content_type"] = response_content_type
            existing["api_response_size_bytes"] = response_size
        return
    candidates_by_url[url] = {
        "api_candidate_url": url,
        "api_candidate_source_page": source_page,
        "api_candidate_reason": reason,
        "api_candidate_status": status,
        "api_response_content_type": response_content_type,
        "api_response_size_bytes": response_size,
    }


def _candidate_status(url: str, policy: DomainPolicy, source_kind: str, fetched_json_by_url: dict[str, object]) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "rejected_non_get"
    if _has_sensitive_query(parsed.query):
        return "rejected_auth_or_token"
    if not policy.is_allowed(url):
        return "rejected_off_domain"
    if url in fetched_json_by_url:
        return "captured_json"
    if source_kind == "captured_url":
        return "captured_url_only"
    return "not_fetched"


def _fetched_json_by_url(pages: list[DiscoveredPage]) -> dict[str, object]:
    out: dict[str, object] = {}
    for page in pages:
        result = page.result
        if not result.ok or result.source is None or result.source.source_type != SourceType.JSON:
            continue
        out[canonicalize_url(result.final_url)] = result
    return out


def _embedded_endpoint_hints(text: str, base_url: str) -> list[str]:
    hints: list[str] = []
    for match in _QUOTED_URL_RE.finditer(text):
        raw = match.group("url").strip()
        if raw.startswith(("mailto:", "tel:", "javascript:")):
            continue
        hints.append(urljoin(base_url, raw))
    return hints


def _looks_like_catalog_api_url(url: str) -> bool:
    parsed = urlparse(url)
    haystack = f"{parsed.path} {parsed.query}".lower()
    has_api_shape = any(marker in haystack for marker in (".json", "/api/", "/_next/data/", "graphql", "/odata/"))
    has_catalog_signal = any(
        marker in haystack
        for marker in (
            "programme",
            "program",
            "course",
            "catalog",
            "degree",
            "major",
            "search",
        )
    )
    return has_api_shape and has_catalog_signal


def _has_sensitive_query(query: str) -> bool:
    sensitive = {
        "accesskey",
        "accesstoken",
        "apikey",
        "auth",
        "authorization",
        "csrf",
        "csrftoken",
        "jwt",
        "key",
        "nonce",
        "password",
        "secret",
        "session",
        "sig",
        "signature",
        "token",
    }
    for key, _value in parse_qsl(query, keep_blank_values=True):
        normalised = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalised in sensitive:
            return True
    return False


_QUOTED_URL_RE = re.compile(
    r"""(?P<quote>["'])(?P<url>(?:https?://|/|\.\.?/)[^"']*(?:\.json|/api/|/_next/data/|graphql|/odata/)[^"']*)\1""",
    flags=re.IGNORECASE,
)
