"""Discovery diagnostics and safe capture bookkeeping for public catalog APIs."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import parse_qsl, urljoin, urlparse

from university_admissions_crawler.crawler.discovery import DiscoveredPage, DiscoveryConfig
from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url, domain_policy_for_seed
from university_admissions_crawler.crawler.types import NetworkResponseRecord
from university_admissions_crawler.extractor.programme_catalog_api import catalog_api_body_profile
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

    policy = domain_policy_for_seed(
        seed_url,
        allowed_hosts=set(config.allowed_hosts),
        allowed_domains=set(config.allowed_domains),
        allow_official_subdomains=config.allow_official_subdomains,
    )
    fetched_json_by_url = _fetched_json_by_url(pages)
    candidates_by_url: dict[str, dict[str, object]] = {}

    for page in pages:
        result = page.result
        seen_network_urls: set[str] = set()
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
        for network_response in result.network_responses:
            seen_network_urls.add(canonicalize_url(network_response.url))
            _add_candidate(
                candidates_by_url,
                raw_url=network_response.url,
                base_url=result.final_url,
                source_page=result.final_url,
                reason="browser_network_json_response",
                source_kind="browser_network_json",
                policy=policy,
                fetched_json_by_url=fetched_json_by_url,
                network_response=network_response,
            )
        for response_url in result.network_response_urls:
            if canonicalize_url(response_url) in seen_network_urls:
                continue
            _add_candidate(
                candidates_by_url,
                raw_url=response_url,
                base_url=result.final_url,
                source_page=result.final_url,
                reason="browser_network_json_response",
                source_kind="browser_network_json",
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
    body_profile: dict[str, object] | None = None,
    suggested_allowed_hosts: list[str] | None = None,
    suggested_allowed_domains: list[str] | None = None,
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
        if suggested_allowed_hosts:
            item["api_suggested_allowed_hosts"] = list(suggested_allowed_hosts)
        if suggested_allowed_domains:
            item["api_suggested_allowed_domains"] = list(suggested_allowed_domains)
        if body_profile:
            _attach_body_profile(item, body_profile)
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
        "browser_network_candidate_count": reason_counts.get("browser_network_json_response", 0),
        "network_body_available_count": sum(1 for item in candidates if item.get("api_network_body_available") is True),
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
    network_response: NetworkResponseRecord | None = None,
) -> None:
    url = canonicalize_url(urljoin(base_url, raw_url))
    captured = fetched_json_by_url.get(url)
    body_profile = _body_profile_for(captured) or _body_profile_for_network_response(network_response)
    if not _should_consider_candidate_url(url, source_kind=source_kind, body_profile=body_profile):
        return
    status = _candidate_status(url, policy, source_kind, fetched_json_by_url, network_response=network_response)
    response_content_type = getattr(captured, "content_type", None) if captured is not None else None
    if response_content_type is None and network_response is not None:
        response_content_type = network_response.content_type or None
    response_size = len(getattr(captured, "text", "").encode("utf-8")) if captured is not None else None
    if response_size is None and network_response is not None:
        response_size = network_response.response_size_bytes
    if isinstance(response_size, int) and response_size > MAX_API_RESPONSE_SIZE_BYTES:
        status = "rejected_too_large"
    elif status == "captured_json" and body_profile and not body_profile.get("api_body_likely_catalog"):
        status = "rejected_body_not_catalog"
    elif network_response is not None and network_response.body_text and body_profile and not body_profile.get("api_body_likely_catalog"):
        status = "rejected_body_not_catalog"
    existing = candidates_by_url.get(url)
    if existing is not None:
        if existing.get("api_candidate_status") != "captured_json" and status == "captured_json":
            existing["api_candidate_status"] = status
            existing["api_response_content_type"] = response_content_type
            existing["api_response_size_bytes"] = response_size
            if body_profile:
                _attach_body_profile(existing, body_profile)
        if network_response is not None:
            _attach_network_response_metadata(existing, network_response)
        return
    candidate = {
        "api_candidate_url": url,
        "api_candidate_source_page": source_page,
        "api_candidate_reason": reason,
        "api_candidate_status": status,
        "api_response_content_type": response_content_type,
        "api_response_size_bytes": response_size,
    }
    if status == "rejected_body_not_catalog":
        candidate["api_capture_rejection_reason"] = "body_not_catalog_like"
    if body_profile:
        _attach_body_profile(candidate, body_profile)
    if network_response is not None:
        _attach_network_response_metadata(candidate, network_response)
    candidates_by_url[url] = candidate


def _candidate_status(
    url: str,
    policy: DomainPolicy,
    source_kind: str,
    fetched_json_by_url: dict[str, object],
    *,
    network_response: NetworkResponseRecord | None = None,
) -> str:
    parsed = urlparse(url)
    method = network_response.method.upper() if network_response is not None and network_response.method else "GET"
    if method != "GET":
        return "rejected_non_get"
    if parsed.scheme not in {"http", "https"}:
        return "rejected_non_get"
    if _has_sensitive_query(parsed.query):
        return "rejected_auth_or_token"
    if not policy.is_allowed(url):
        return "rejected_off_domain"
    if url in fetched_json_by_url:
        return "captured_json"
    if source_kind in {"captured_url", "browser_network_json"}:
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
    has_api_shape = any(
        marker in haystack
        for marker in (
            ".json",
            "/api/",
            "/_next/data/",
            "graphql",
            "/odata/",
            "sitecore",
            "/search",
            "search?",
        )
    )
    has_catalog_signal = any(
        marker in haystack
        for marker in (
            "programme",
            "program",
            "course",
            "catalog",
            "degree",
            "major",
        )
    )
    return has_api_shape and has_catalog_signal


def _should_consider_candidate_url(url: str, *, source_kind: str, body_profile: dict[str, object] | None) -> bool:
    if _looks_like_catalog_api_url(url):
        return True
    if source_kind == "browser_network_json":
        return True
    return bool(source_kind == "captured_json" and body_profile and body_profile.get("api_body_likely_catalog"))


def _body_profile_for(result: object | None) -> dict[str, object] | None:
    text = getattr(result, "text", None)
    if not isinstance(text, str) or not text:
        return None
    return catalog_api_body_profile(text)


def _body_profile_for_network_response(record: NetworkResponseRecord | None) -> dict[str, object] | None:
    if record is None or not record.body_text:
        return None
    return catalog_api_body_profile(record.body_text)


def _attach_body_profile(candidate: dict[str, object], body_profile: dict[str, object]) -> None:
    for key in (
        "api_body_likely_catalog",
        "api_body_signals",
        "api_body_candidate_object_count",
        "api_body_parseable_row_count",
        "api_body_filter_keys",
        "api_body_sample_keys",
        "api_body_rejection_reason",
    ):
        if key in body_profile:
            candidate[key] = body_profile[key]


def _attach_network_response_metadata(candidate: dict[str, object], record: NetworkResponseRecord) -> None:
    candidate["api_network_method"] = record.method
    if record.status is not None:
        candidate["api_network_status"] = record.status
    if record.content_type:
        candidate["api_network_content_type"] = record.content_type
    if record.response_size_bytes is not None:
        candidate["api_network_response_size_bytes"] = record.response_size_bytes
    if record.request_query_params:
        candidate["api_network_query_params"] = dict(sorted(record.request_query_params.items()))
        candidate["api_network_query_param_keys"] = sorted(record.request_query_params)
    if record.response_headers:
        candidate["api_network_response_headers"] = dict(sorted(record.response_headers.items()))
    candidate["api_network_body_available"] = bool(record.body_text)
    candidate["api_network_body_truncated"] = record.body_truncated
    if record.body_sha256:
        candidate["api_network_body_sha256"] = record.body_sha256


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
    r"""(?P<quote>["'])(?P<url>(?:https?://|/|\.\.?/)[^"']*(?:\.json|/api/|/_next/data/|graphql|/odata/|sitecore|search|listing)[^"']*)\1""",
    flags=re.IGNORECASE,
)
