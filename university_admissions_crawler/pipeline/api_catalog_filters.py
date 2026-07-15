"""Bounded filter enumeration for captured public programme catalog APIs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from university_admissions_crawler.crawler.filters import DomainPolicy, allowed_scope_suggestion, canonicalize_url
from university_admissions_crawler.crawler.types import FetchResult, Fetcher
from university_admissions_crawler.extractor.schema import SourceType


MAX_API_FILTER_REQUESTS = 5
MAX_API_FILTER_RESPONSE_SIZE_BYTES = 2_000_000


@dataclass(slots=True)
class ApiCatalogFilterCapture:
    result: FetchResult
    filter_index: int
    filters: dict[str, str]


@dataclass(slots=True)
class ApiCatalogFilterOutcome:
    initial_url: str
    filter_dimensions: dict[str, list[str]] = field(default_factory=dict)
    attempted_urls: list[str] = field(default_factory=list)
    attempted_filters: list[dict[str, str]] = field(default_factory=list)
    fetched_urls: list[str] = field(default_factory=list)
    rejected_urls: list[dict[str, object]] = field(default_factory=list)
    fetched_pages: list[ApiCatalogFilterCapture] = field(default_factory=list)
    budget_hit: bool = False
    stop_reason: str = "filters_not_detected"

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_url": self.initial_url,
            "filter_dimensions": {key: list(values) for key, values in sorted(self.filter_dimensions.items())},
            "attempted_urls": list(self.attempted_urls),
            "attempted_filters": [dict(item) for item in self.attempted_filters],
            "fetched_urls": list(self.fetched_urls),
            "rejected_urls": list(self.rejected_urls),
            "budget_hit": self.budget_hit,
            "stop_reason": self.stop_reason,
        }


@dataclass(frozen=True, slots=True)
class _FilterPlan:
    url: str
    filters: dict[str, str]


def fetch_api_catalog_filter_pages(
    fetcher: Fetcher,
    initial_result: FetchResult,
    *,
    max_requests: int = MAX_API_FILTER_REQUESTS,
    domain_policy: DomainPolicy | None = None,
) -> ApiCatalogFilterOutcome:
    """Fetch safe low-risk filter variants for the same captured JSON endpoint."""

    outcome = ApiCatalogFilterOutcome(initial_url=initial_result.final_url)
    if max_requests <= 0:
        outcome.budget_hit = True
        outcome.stop_reason = "filter_budget_hit"
        return outcome

    payload = _json_payload(initial_result.text)
    if payload is None:
        outcome.stop_reason = "invalid_json"
        return outcome

    dimensions = _safe_filter_dimensions(payload, initial_result.final_url)
    outcome.filter_dimensions = {key: list(values) for key, values in sorted(dimensions.items())}
    plans = _filter_plans(initial_result.final_url, dimensions)
    if not plans:
        outcome.stop_reason = "safe_filters_not_detected" if dimensions else "filters_not_detected"
        return outcome
    if len(plans) > max_requests:
        outcome.budget_hit = True
        plans = plans[:max_requests]

    seen_urls = {canonicalize_url(initial_result.final_url)}
    seen_hashes = {source.content_hash for source in [initial_result.source] if source and source.content_hash}
    for plan in plans:
        url = canonicalize_url(plan.url)
        if url in seen_urls:
            outcome.rejected_urls.append({"url": url, "reason": "duplicate_filter_url"})
            continue
        reject_reason = _unsafe_filter_url_reason(initial_result.final_url, url, domain_policy=domain_policy)
        if reject_reason:
            rejected_url = {"url": url, "reason": reject_reason}
            if reject_reason == "rejected_off_domain":
                rejected_url.update(allowed_scope_suggestion(url))
            outcome.rejected_urls.append(rejected_url)
            continue

        outcome.attempted_urls.append(url)
        outcome.attempted_filters.append(dict(plan.filters))
        fetched = fetcher.fetch(url)
        final_url = canonicalize_url(fetched.final_url)
        reject_reason = _unsafe_filter_url_reason(initial_result.final_url, final_url, domain_policy=domain_policy)
        if reject_reason:
            outcome.rejected_urls.append(
                {
                    "url": url,
                    "reason": reject_reason,
                    "captured_url": final_url,
                    **allowed_scope_suggestion(final_url),
                }
            )
            continue
        if len(fetched.text.encode("utf-8")) > MAX_API_FILTER_RESPONSE_SIZE_BYTES:
            outcome.rejected_urls.append({"url": url, "reason": "rejected_too_large"})
            continue
        if not fetched.ok or fetched.source is None:
            outcome.rejected_urls.append({"url": url, "reason": "fetch_failed"})
            continue
        if fetched.source.source_type != SourceType.JSON:
            outcome.rejected_urls.append({"url": url, "reason": "non_json_response"})
            continue
        content_hash = fetched.source.content_hash
        if content_hash and content_hash in seen_hashes:
            outcome.rejected_urls.append({"url": url, "reason": "duplicate_filter_body"})
            continue

        seen_urls.add(final_url)
        if content_hash:
            seen_hashes.add(content_hash)
        outcome.fetched_urls.append(final_url)
        outcome.fetched_pages.append(
            ApiCatalogFilterCapture(
                result=fetched,
                filter_index=len(outcome.fetched_pages) + 1,
                filters=dict(plan.filters),
            )
        )

    if outcome.fetched_pages:
        outcome.stop_reason = "filter_fetch_complete"
    elif outcome.rejected_urls:
        outcome.stop_reason = "filter_fetch_rejected"
    else:
        outcome.stop_reason = "filters_not_fetched"
    return outcome


def _json_payload(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _safe_filter_dimensions(payload: Any, url: str) -> dict[str, list[str]]:
    options = _collect_filter_options(payload)
    dimensions: dict[str, list[str]] = {}
    for dimension, target_aliases in _CORE_TARGET_ALIASES.items():
        option_values = options.get(dimension, [])
        selected = _select_target_option(option_values, target_aliases)
        if selected:
            dimensions[_query_key_for_dimension(url, dimension, (selected.query_key,))] = [selected.value]

    for option in options.get("faculty_or_school", []):
        if len(dimensions.get(option.query_key, [])) >= 5:
            continue
        if option.value and option.value not in dimensions.setdefault(option.query_key, []):
            dimensions[option.query_key].append(option.value)
    return {key: values for key, values in dimensions.items() if values}


@dataclass(frozen=True, slots=True)
class _FilterOption:
    value: str
    texts: tuple[str, ...]
    query_key: str


def _collect_filter_options(payload: Any) -> dict[str, list[_FilterOption]]:
    out: dict[str, list[_FilterOption]] = {}

    def visit(value: Any, *, in_filter_context: bool = False) -> None:
        if isinstance(value, dict):
            descriptor_dimension = _descriptor_dimension(value)
            descriptor_query_key = _descriptor_query_key(value)
            options = _descriptor_options(value)
            if in_filter_context and descriptor_dimension and descriptor_query_key and options:
                _add_options(out, descriptor_dimension, descriptor_query_key, options)

            for key, subvalue in value.items():
                dimension = _dimension_for_key(key)
                key_is_filter_container = _normalise_key(key) in _FILTER_CONTAINER_KEYS
                if in_filter_context and dimension is not None:
                    _add_options(out, dimension, key, subvalue)
                visit(subvalue, in_filter_context=in_filter_context or key_is_filter_container)
        elif isinstance(value, list):
            for item in value:
                visit(item, in_filter_context=in_filter_context)

    visit(payload)
    return out


def _add_options(out: dict[str, list[_FilterOption]], dimension: str, query_key: str, raw_options: Any) -> None:
    options = raw_options if isinstance(raw_options, list) else [raw_options]
    for raw in options:
        option = _filter_option(raw, query_key)
        if option is None:
            continue
        bucket = out.setdefault(dimension, [])
        if option.value not in {item.value for item in bucket}:
            bucket.append(option)


def _filter_option(raw: Any, query_key: str) -> _FilterOption | None:
    if isinstance(raw, (str, int, float)):
        value = str(raw).strip()
        return _FilterOption(value=value, texts=(value,), query_key=query_key) if value else None
    if not isinstance(raw, dict):
        return None
    value = _first_scalar(raw, ("value", "id", "code", "slug", "key", "name", "label", "title"))
    if not value:
        return None
    texts = [value]
    for key in ("label", "name", "title", "displayName", "text"):
        text = _first_scalar(raw, (key,))
        if text and text not in texts:
            texts.append(text)
    return _FilterOption(value=value, texts=tuple(texts), query_key=query_key)


def _descriptor_dimension(item: dict[str, Any]) -> str | None:
    for key in ("param", "parameter", "field", "key", "name", "id"):
        value = _first_scalar(item, (key,))
        if value:
            dimension = _dimension_for_key(value)
            if dimension is not None:
                return dimension
    return None


def _descriptor_query_key(item: dict[str, Any]) -> str | None:
    for key in ("param", "parameter", "field", "key", "id"):
        value = _first_scalar(item, (key,))
        if value and _dimension_for_key(value) is not None:
            return value
    dimension_name = _first_scalar(item, ("name",))
    dimension = _dimension_for_key(dimension_name or "")
    return _DEFAULT_QUERY_KEYS.get(dimension or "")


def _descriptor_options(item: dict[str, Any]) -> Any | None:
    for key in ("options", "values", "items", "choices", "facets"):
        value = item.get(key)
        if isinstance(value, list) and value:
            return value
    return None


def _first_scalar(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    normalized = {_normalise_key(key): value for key, value in item.items()}
    for key in keys:
        value = normalized.get(_normalise_key(key))
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return None


def _select_target_option(options: list[_FilterOption], aliases: set[str]) -> _FilterOption | None:
    for option in options:
        if any(_normalise_value(text) in aliases for text in option.texts):
            return option
    return None


def _filter_plans(url: str, dimensions: dict[str, list[str]]) -> list[_FilterPlan]:
    core_filters = {
        key: values[0]
        for key, values in dimensions.items()
        if _dimension_for_key(key) in {"level", "programme_type", "study_mode"} and values
    }
    faculty_entries = [
        (key, value)
        for key, values in dimensions.items()
        if _dimension_for_key(key) == "faculty_or_school"
        for value in values[:5]
    ]

    plans: list[_FilterPlan] = []
    if core_filters:
        plans.append(_FilterPlan(url=_url_with_query_values(url, core_filters), filters=dict(core_filters)))
    for key, value in faculty_entries:
        filters = {**core_filters, key: value}
        plans.append(_FilterPlan(url=_url_with_query_values(url, filters), filters=filters))

    out: list[_FilterPlan] = []
    seen: set[str] = set()
    for plan in plans:
        canonical = canonicalize_url(plan.url)
        if canonical == canonicalize_url(url) or canonical in seen:
            continue
        seen.add(canonical)
        out.append(_FilterPlan(url=canonical, filters=plan.filters))
    return out


def _url_with_query_values(url: str, values: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    updated: list[tuple[str, str]] = []
    remaining = dict(values)
    for key, value in query:
        if key in remaining:
            updated.append((key, remaining.pop(key)))
        else:
            updated.append((key, value))
    updated.extend(remaining.items())
    return urlunparse(parsed._replace(query=urlencode(updated, doseq=True)))


def _query_key_for_dimension(url: str, dimension: str, observed_keys: tuple[str, ...]) -> str:
    wanted = {_normalise_key(key) for key in observed_keys}
    for key, _value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        if _normalise_key(key) in wanted:
            return key
    for key in observed_keys:
        if _dimension_for_key(key) == dimension:
            return key
    return _DEFAULT_QUERY_KEYS[dimension]


def _unsafe_filter_url_reason(initial_url: str, next_url: str, *, domain_policy: DomainPolicy | None = None) -> str | None:
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


def _dimension_for_key(key: str) -> str | None:
    return _DIMENSION_BY_KEY.get(_normalise_key(key))


def _normalise_key(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _normalise_value(value: str) -> str:
    return _normalise_key(value)


_DIMENSION_KEYS = {
    "level": ("level", "studylevel", "programmelevel", "programlevel"),
    "programme_type": ("programmetype", "programtype", "programmetypes", "programtypes", "type", "awardtype"),
    "study_mode": ("studymode", "mode", "attendance", "attendancepattern"),
    "faculty_or_school": ("faculty", "facultyid", "facultycode", "school", "schoolid", "schoolcode", "college", "department"),
}
_DIMENSION_BY_KEY = {
    key: dimension
    for dimension, keys in _DIMENSION_KEYS.items()
    for key in keys
}
_DEFAULT_QUERY_KEYS = {
    "level": "level",
    "programme_type": "programmeType",
    "study_mode": "studyMode",
    "faculty_or_school": "faculty",
}
_FILTER_CONTAINER_KEYS = {
    "facet",
    "facets",
    "filter",
    "filters",
    "filteroption",
    "filteroptions",
    "searchfacet",
    "searchfacets",
    "searchfilter",
    "searchfilters",
}
_CORE_TARGET_ALIASES = {
    "level": {"undergraduate", "undergrad", "ug"},
    "programme_type": {"degree", "degreeprogramme", "degreeprogram", "bachelor", "undergraduatedegree"},
    "study_mode": {"fulltime", "full-time", "full time"},
}
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
