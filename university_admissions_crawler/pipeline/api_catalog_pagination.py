"""Safe pagination expansion for captured public programme catalog APIs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from university_admissions_crawler.crawler.filters import DomainPolicy, allowed_scope_suggestion
from university_admissions_crawler.crawler.types import FetchResult, Fetcher
from university_admissions_crawler.extractor.schema import SourceType


@dataclass(slots=True)
class ApiCatalogPageCapture:
    result: FetchResult
    page_index: int
    mode: str


@dataclass(slots=True)
class ApiCatalogPaginationOutcome:
    initial_url: str
    mode: str | None = None
    page_count: int = 1
    attempted_urls: list[str] = field(default_factory=list)
    fetched_urls: list[str] = field(default_factory=list)
    rejected_urls: list[dict[str, object]] = field(default_factory=list)
    fetched_pages: list[ApiCatalogPageCapture] = field(default_factory=list)
    completed: bool = False
    budget_hit: bool = False
    stop_reason: str = "pagination_not_detected"

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_url": self.initial_url,
            "mode": self.mode,
            "page_count": self.page_count,
            "attempted_urls": list(self.attempted_urls),
            "fetched_urls": list(self.fetched_urls),
            "rejected_urls": list(self.rejected_urls),
            "completed": self.completed,
            "budget_hit": self.budget_hit,
            "stop_reason": self.stop_reason,
        }


@dataclass(frozen=True, slots=True)
class _NextPagePlan:
    url: str | None
    mode: str | None
    complete: bool
    reason: str


def fetch_additional_api_catalog_pages(
    fetcher: Fetcher,
    initial_result: FetchResult,
    *,
    max_pages: int = 5,
    domain_policy: DomainPolicy | None = None,
) -> ApiCatalogPaginationOutcome:
    """Fetch safe next pages for the same captured JSON API endpoint."""

    outcome = ApiCatalogPaginationOutcome(initial_url=initial_result.final_url)
    if max_pages <= 1:
        outcome.budget_hit = True
        outcome.stop_reason = "pagination_budget_hit"
        return outcome

    seen_urls = {initial_result.final_url}
    seen_hashes = {source.content_hash for source in [initial_result.source] if source and source.content_hash}
    current = initial_result
    while outcome.page_count < max_pages:
        plan = next_api_catalog_page_url(current.text, current.final_url)
        if plan.mode and not outcome.mode:
            outcome.mode = plan.mode
        if plan.complete:
            outcome.completed = True
            outcome.stop_reason = plan.reason
            return outcome
        if not plan.url:
            outcome.stop_reason = plan.reason
            return outcome

        reject_reason = _unsafe_next_url_reason(initial_result.final_url, plan.url, domain_policy=domain_policy)
        if reject_reason:
            rejected_url = {"url": plan.url, "reason": reject_reason}
            if reject_reason == "rejected_off_domain":
                rejected_url.update(allowed_scope_suggestion(plan.url))
            outcome.rejected_urls.append(rejected_url)
            outcome.stop_reason = reject_reason
            return outcome
        if plan.url in seen_urls:
            outcome.rejected_urls.append({"url": plan.url, "reason": "duplicate_page_url"})
            outcome.stop_reason = "duplicate_page_url"
            return outcome

        outcome.attempted_urls.append(plan.url)
        fetched = fetcher.fetch(plan.url)
        final_url_reject_reason = _unsafe_next_url_reason(initial_result.final_url, fetched.final_url, domain_policy=domain_policy)
        if final_url_reject_reason:
            outcome.rejected_urls.append(
                {
                    "url": plan.url,
                    "reason": final_url_reject_reason,
                    "captured_url": fetched.final_url,
                    **allowed_scope_suggestion(fetched.final_url),
                }
            )
            outcome.stop_reason = final_url_reject_reason
            return outcome
        if not fetched.ok or fetched.source is None:
            outcome.rejected_urls.append({"url": plan.url, "reason": "fetch_failed"})
            outcome.stop_reason = "fetch_failed"
            return outcome
        if fetched.source.source_type != SourceType.JSON:
            outcome.rejected_urls.append({"url": plan.url, "reason": "non_json_response"})
            outcome.stop_reason = "non_json_response"
            return outcome
        content_hash = fetched.source.content_hash
        if content_hash and content_hash in seen_hashes:
            outcome.rejected_urls.append({"url": plan.url, "reason": "duplicate_page_body"})
            outcome.stop_reason = "duplicate_page_body"
            return outcome

        seen_urls.add(fetched.final_url)
        if content_hash:
            seen_hashes.add(content_hash)
        outcome.page_count += 1
        outcome.fetched_urls.append(fetched.final_url)
        outcome.fetched_pages.append(ApiCatalogPageCapture(result=fetched, page_index=outcome.page_count, mode=plan.mode or "unknown"))
        current = fetched

    outcome.budget_hit = True
    outcome.stop_reason = "pagination_budget_hit"
    return outcome


def next_api_catalog_page_url(text: str, url: str) -> _NextPagePlan:
    payload = _json_payload(text)
    if payload is None:
        return _NextPagePlan(None, None, False, "invalid_json")

    cursor = _cursor_plan(payload, url)
    if cursor.mode:
        return cursor

    offset = _offset_plan(payload, url)
    if offset.mode:
        return offset

    page = _page_plan(payload, url)
    if page.mode:
        return page

    return _NextPagePlan(None, None, False, "pagination_not_detected")


def api_pagination_group_url(url: str) -> str:
    """Return endpoint URL with common pagination cursors removed."""

    parsed = urlparse(url)
    filtered = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if _normalise_key(key) not in {"page", "pagenumber", "offset", "skip", "cursor", "after"}
    ]
    return urlunparse(parsed._replace(query=urlencode(filtered, doseq=True)))


def _cursor_plan(payload: Any, url: str) -> _NextPagePlan:
    page_info = _find_page_info(payload)
    if not page_info:
        return _NextPagePlan(None, None, False, "pagination_not_detected")
    has_next = page_info.get("hasNextPage")
    if has_next is False:
        return _NextPagePlan(None, "cursor", True, "pagination_complete")
    end_cursor = page_info.get("endCursor") or page_info.get("end_cursor")
    if has_next is True and isinstance(end_cursor, str) and end_cursor:
        cursor_key = _query_key(url, ("after", "cursor")) or "after"
        return _NextPagePlan(_url_with_query_value(url, cursor_key, end_cursor), "cursor", False, "next_cursor")
    return _NextPagePlan(None, "cursor", False, "cursor_without_end_cursor")


def _offset_plan(payload: Any, url: str) -> _NextPagePlan:
    offset_key = _query_key(url, ("offset", "skip"))
    limit_key = _query_key(url, ("limit", "take"))
    current_offset = _int_query_value(url, offset_key) if offset_key else _payload_int(payload, ("offset", "skip"))
    limit = _int_query_value(url, limit_key) if limit_key else _payload_int(payload, ("limit", "take", "pageSize", "page_size"))
    if current_offset is None or limit is None or limit <= 0:
        return _NextPagePlan(None, None, False, "pagination_not_detected")
    total = _find_total_count(payload)
    next_offset = current_offset + limit
    if total is not None and next_offset >= total:
        return _NextPagePlan(None, "offset", True, "pagination_complete")
    return _NextPagePlan(_url_with_query_value(url, offset_key or "offset", str(next_offset)), "offset", False, "next_offset")


def _page_plan(payload: Any, url: str) -> _NextPagePlan:
    page_key = _query_key(url, ("page", "pageNumber", "pagenumber"))
    current_page = _int_query_value(url, page_key) if page_key else _payload_int(payload, ("page", "currentPage", "pageNumber", "pagenumber"))
    if current_page is None:
        return _NextPagePlan(None, None, False, "pagination_not_detected")
    page_size = _int_query_value(url, _query_key(url, ("pageSize", "pagesize", "limit", "perPage", "perpage", "size"))) or _payload_int(
        payload,
        ("pageSize", "pagesize", "limit", "perPage", "perpage", "size"),
    )
    total_pages = _payload_int(payload, ("totalPages", "totalpages", "pageCount", "pagecount"))
    if total_pages is not None and current_page >= total_pages:
        return _NextPagePlan(None, "page", True, "pagination_complete")
    total = _find_total_count(payload)
    if total is not None and page_size is not None and page_size > 0 and current_page * page_size >= total:
        return _NextPagePlan(None, "page", True, "pagination_complete")
    return _NextPagePlan(_url_with_query_value(url, page_key or "page", str(current_page + 1)), "page", False, "next_page")


def _json_payload(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _find_page_info(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if isinstance(value.get("pageInfo"), dict):
            return value["pageInfo"]
        if isinstance(value.get("page_info"), dict):
            return value["page_info"]
        for subvalue in value.values():
            found = _find_page_info(subvalue)
            if found is not None:
                return found
    elif isinstance(value, list):
        for subvalue in value:
            found = _find_page_info(subvalue)
            if found is not None:
                return found
    return None


def _find_total_count(value: Any) -> int | None:
    if isinstance(value, dict):
        for key, subvalue in value.items():
            if _normalise_key(key) in {"total", "count", "totalcount", "recordstotal"} and isinstance(subvalue, int):
                return subvalue
        for subvalue in value.values():
            found = _find_total_count(subvalue)
            if found is not None:
                return found
    elif isinstance(value, list):
        for subvalue in value:
            found = _find_total_count(subvalue)
            if found is not None:
                return found
    return None


def _payload_int(payload: Any, keys: tuple[str, ...]) -> int | None:
    wanted = {_normalise_key(key) for key in keys}
    if not isinstance(payload, dict):
        return None
    for key, value in payload.items():
        if _normalise_key(key) in wanted and isinstance(value, int):
            return value
    return None


def _query_key(url: str, candidates: tuple[str, ...]) -> str | None:
    wanted = {_normalise_key(candidate) for candidate in candidates}
    for key, _value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        if _normalise_key(key) in wanted:
            return key
    return None


def _int_query_value(url: str, key: str | None) -> int | None:
    if key is None:
        return None
    for query_key, value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        if query_key != key:
            continue
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _url_with_query_value(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    updated: list[tuple[str, str]] = []
    for query_key, query_value in query:
        if query_key == key:
            updated.append((query_key, value))
            replaced = True
        else:
            updated.append((query_key, query_value))
    if not replaced:
        updated.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(updated, doseq=True)))


def _unsafe_next_url_reason(initial_url: str, next_url: str, *, domain_policy: DomainPolicy | None = None) -> str | None:
    initial = urlparse(initial_url)
    parsed = urlparse(next_url)
    if parsed.scheme not in {"http", "https"}:
        return "rejected_non_http"
    if parsed.netloc != initial.netloc and not (domain_policy is not None and domain_policy.is_allowed(next_url)):
        return "rejected_off_domain"
    for url in (initial_url, next_url):
        for key, _value in parse_qsl(urlparse(url).query, keep_blank_values=True):
            if _normalise_key(key) in _SENSITIVE_QUERY_KEYS:
                return "rejected_auth_or_token"
    return None


def _normalise_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


_SENSITIVE_QUERY_KEYS = {
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
