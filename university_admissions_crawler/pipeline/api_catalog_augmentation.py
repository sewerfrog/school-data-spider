"""Dynamic catalog augmentation for public API discovery."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from university_admissions_crawler.classifier.page_classifier import classify_page
from university_admissions_crawler.crawler.discovery import DiscoveredPage, DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import Fetcher, FetchResult
from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url
from university_admissions_crawler.extractor.schema import AdmissionsData, PageCategory, SourceType, WarningCode, WarningRecord
from university_admissions_crawler.pipeline.api_catalog_discovery import attach_api_catalog_discovery_diagnostics
from university_admissions_crawler.pipeline.scan_context import looks_like_dynamic_catalog_shell
from university_admissions_crawler.pipeline.source_capture import domain_policy_for_scan


MAX_DYNAMIC_SHELL_BROWSER_CAPTURES = 3
MAX_DYNAMIC_SHELL_STATIC_ASSET_PAGES = 3
MAX_STATIC_ASSET_DISCOVERY_FETCHES = 8
MAX_STATIC_ASSET_DISCOVERY_BYTES = 1_000_000

_SCRIPT_SRC_RE = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*(?P<quote>["'])(?P<url>[^"']+)(?P=quote)""", re.IGNORECASE)
_LINK_TAG_RE = re.compile(r"""<link\b[^>]*>""", re.IGNORECASE)
_HREF_RE = re.compile(r"""\bhref\s*=\s*(?P<quote>["'])(?P<url>[^"']+)(?P=quote)""", re.IGNORECASE)


def augment_api_catalog_discovery(
    data: AdmissionsData,
    pages: list[DiscoveredPage],
    fetcher: Fetcher,
    *,
    seed_url: str,
    discovery_config: DiscoveryConfig,
) -> list[DiscoveredPage]:
    attach_api_catalog_discovery_diagnostics(data, pages, seed_url=seed_url, config=discovery_config)
    pages, browser_capture_diagnostic = _augment_dynamic_catalog_shells_with_browser_capture(pages, fetcher, data)
    if browser_capture_diagnostic is not None:
        data.run.config["programme_catalog_browser_capture"] = browser_capture_diagnostic
        attach_api_catalog_discovery_diagnostics(data, pages, seed_url=seed_url, config=discovery_config)
    static_asset_pages, static_asset_diagnostic = _augment_api_discovery_with_static_assets(
        pages,
        fetcher,
        data,
        seed_url=seed_url,
        discovery_config=discovery_config,
    )
    if static_asset_diagnostic is not None:
        data.run.config["programme_catalog_static_asset_discovery"] = static_asset_diagnostic
        if static_asset_pages:
            attach_api_catalog_discovery_diagnostics(
                data,
                pages + static_asset_pages,
                seed_url=seed_url,
                config=discovery_config,
            )
            _annotate_static_asset_api_candidates(data)
    return pages


def _augment_dynamic_catalog_shells_with_browser_capture(
    pages: list[DiscoveredPage],
    fetcher: Fetcher,
    data: AdmissionsData,
) -> tuple[list[DiscoveredPage], dict[str, object] | None]:
    """Force a bounded browser pass when HTTP captured only a dynamic catalog shell."""

    if not _api_candidate_zero(data):
        return pages, None
    browser_fetch = getattr(getattr(fetcher, "browser_fetcher", None), "fetch", None)
    if not callable(browser_fetch):
        return pages, None

    candidate_indexes = [
        index
        for index, page in enumerate(pages)
        if _result_is_dynamic_catalog_shell(page.result)
    ][:MAX_DYNAMIC_SHELL_BROWSER_CAPTURES]
    if not candidate_indexes:
        return pages, None

    updated_pages = list(pages)
    diagnostic: dict[str, object] = {
        "triggered": True,
        "max_pages": MAX_DYNAMIC_SHELL_BROWSER_CAPTURES,
        "attempted_urls": [],
        "captured_urls": [],
        "rejected_urls": [],
        "network_response_count": 0,
        "network_body_count": 0,
        "note": "Dynamic programme shell pages with zero API candidates are fetched once through the configured browser fetcher to capture public network JSON diagnostics.",
    }

    for index in candidate_indexes:
        original_page = pages[index]
        url = original_page.result.final_url
        diagnostic["attempted_urls"].append(url)
        try:
            browser_result = browser_fetch(url)
        except Exception as exc:
            diagnostic["rejected_urls"].append({"url": url, "reason": "browser_exception", "error_type": type(exc).__name__, "message": str(exc)[:500]})
            data.warnings.append(
                WarningRecord(
                    WarningCode.FETCH_FAILED,
                    f"Dynamic catalog browser capture raised {type(exc).__name__}: {exc}",
                    field=url,
                    source_urls=[url],
                )
            )
            continue
        if not browser_result.ok or browser_result.source is None:
            reason = "browser_fetch_failed"
            message = ""
            if browser_result.warnings:
                reason = str(browser_result.warnings[0].code)
                message = browser_result.warnings[0].message
                data.warnings.extend(browser_result.warnings)
            diagnostic["rejected_urls"].append({"url": url, "reason": reason, "message": message[:500]})
            continue
        updated_pages[index] = DiscoveredPage(
            result=browser_result,
            depth=original_page.depth,
            score=original_page.score,
            source_role=original_page.source_role,
            source_family=original_page.source_family,
            source_role_signals=original_page.source_role_signals,
        )
        diagnostic["captured_urls"].append(browser_result.final_url)
        diagnostic["network_response_count"] = int(diagnostic["network_response_count"]) + len(browser_result.network_responses)
        diagnostic["network_body_count"] = int(diagnostic["network_body_count"]) + sum(1 for record in browser_result.network_responses if record.body_text)

    return updated_pages, diagnostic


def _augment_api_discovery_with_static_assets(
    pages: list[DiscoveredPage],
    fetcher: Fetcher,
    data: AdmissionsData,
    *,
    seed_url: str,
    discovery_config: DiscoveryConfig,
) -> tuple[list[DiscoveredPage], dict[str, object] | None]:
    """Fetch bounded same-domain JS assets only to discover public catalog API hints."""

    if not _api_candidate_zero(data):
        return [], None

    candidate_source_pages = [
        page
        for page in pages
        if _result_is_dynamic_catalog_shell(page.result)
    ][:MAX_DYNAMIC_SHELL_STATIC_ASSET_PAGES]
    if not candidate_source_pages:
        return [], None

    policy = domain_policy_for_scan(seed_url, discovery_config)
    diagnostic: dict[str, object] = {
        "triggered": True,
        "max_pages": MAX_DYNAMIC_SHELL_STATIC_ASSET_PAGES,
        "max_assets": MAX_STATIC_ASSET_DISCOVERY_FETCHES,
        "max_asset_bytes": MAX_STATIC_ASSET_DISCOVERY_BYTES,
        "candidate_source_pages": [page.result.final_url for page in candidate_source_pages],
        "candidate_asset_urls": [],
        "fetched_asset_urls": [],
        "rejected_asset_urls": [],
        "endpoint_hint_count": 0,
        "candidate_api_urls": [],
        "note": "Dynamic catalogue shell pages with zero API candidates are probed for same-domain static JavaScript assets; assets are used only for API endpoint discovery diagnostics, not as admissions fact sources.",
    }

    asset_urls = _static_catalog_asset_urls(candidate_source_pages, policy)
    if not asset_urls:
        return [], None
    diagnostic["candidate_asset_urls"] = asset_urls
    asset_pages: list[DiscoveredPage] = []
    for asset_url in asset_urls[:MAX_STATIC_ASSET_DISCOVERY_FETCHES]:
        try:
            result = fetcher.fetch(asset_url)
        except Exception as exc:
            _append_static_asset_rejection(diagnostic, asset_url, "asset_fetch_exception", type(exc).__name__)
            continue
        response_size = len(result.text.encode("utf-8"))
        if not policy.is_allowed(result.final_url):
            _append_static_asset_rejection(diagnostic, asset_url, "redirected_off_domain")
            continue
        if not result.ok or result.source is None:
            _append_static_asset_rejection(diagnostic, asset_url, "asset_fetch_failed")
            continue
        if response_size > MAX_STATIC_ASSET_DISCOVERY_BYTES:
            _append_static_asset_rejection(diagnostic, asset_url, "asset_too_large")
            continue
        asset_pages.append(DiscoveredPage(result=result, depth=1, score=0))
        diagnostic["fetched_asset_urls"].append(result.final_url)

    if len(asset_urls) > MAX_STATIC_ASSET_DISCOVERY_FETCHES:
        for skipped_url in asset_urls[MAX_STATIC_ASSET_DISCOVERY_FETCHES:]:
            _append_static_asset_rejection(diagnostic, skipped_url, "asset_budget_skipped")
    return asset_pages, diagnostic


def _static_catalog_asset_urls(pages: list[DiscoveredPage], policy: DomainPolicy) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for page in pages:
        result = page.result
        for raw_url in _script_asset_hints(result.text):
            if raw_url.startswith(("#", "data:", "mailto:", "tel:", "javascript:", "blob:")):
                continue
            url = canonicalize_url(raw_url, result.final_url)
            if url in seen or not _looks_like_static_script_asset(url):
                continue
            seen.add(url)
            if policy.is_allowed(url):
                urls.append(url)
    return urls


def _script_asset_hints(text: str) -> list[str]:
    hints: list[str] = []
    for match in _SCRIPT_SRC_RE.finditer(text):
        hints.append(match.group("url").strip())
    for tag_match in _LINK_TAG_RE.finditer(text):
        tag = tag_match.group(0)
        lower = tag.lower()
        if not any(marker in lower for marker in ("modulepreload", "preload", "script")):
            continue
        href_match = _HREF_RE.search(tag)
        if href_match is not None:
            hints.append(href_match.group("url").strip())
    return hints


def _looks_like_static_script_asset(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return path.endswith((".js", ".mjs")) or ("/_next/static/" in path and ".js" in path)


def _append_static_asset_rejection(diagnostic: dict[str, object], url: str, reason: str, message: str = "") -> None:
    rejected = diagnostic.get("rejected_asset_urls")
    if not isinstance(rejected, list):
        rejected = []
        diagnostic["rejected_asset_urls"] = rejected
    item: dict[str, object] = {"url": url, "reason": reason}
    if message:
        item["message"] = message[:500]
    rejected.append(item)


def _annotate_static_asset_api_candidates(data: AdmissionsData) -> None:
    diagnostic = data.run.config.get("programme_catalog_static_asset_discovery")
    if not isinstance(diagnostic, dict):
        return
    fetched = diagnostic.get("fetched_asset_urls")
    if not isinstance(fetched, list):
        return
    fetched_urls = {canonicalize_url(str(url)) for url in fetched if url}
    candidates = data.run.config.get("programme_catalog_api_candidates")
    if not isinstance(candidates, list):
        return
    api_urls: list[str] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        source_page = item.get("api_candidate_source_page")
        api_url = item.get("api_candidate_url")
        if isinstance(source_page, str) and canonicalize_url(source_page) in fetched_urls and isinstance(api_url, str):
            api_urls.append(api_url)
    diagnostic["endpoint_hint_count"] = len(api_urls)
    diagnostic["candidate_api_urls"] = api_urls


def _api_candidate_zero(data: AdmissionsData) -> bool:
    summary = data.run.config.get("programme_catalog_api_discovery_summary")
    if not isinstance(summary, dict):
        return True
    return summary.get("api_catalog_candidate_count", 0) == 0


def _result_is_dynamic_catalog_shell(result: FetchResult) -> bool:
    if not result.ok or result.source is None or result.source.source_type != SourceType.HTML:
        return False
    if result.network_response_urls or result.network_responses:
        return False
    text = result.markdown or result.text
    classification = classify_page(result.final_url, result.title, text)
    return classification.category in {PageCategory.PROGRAMME_LIST, PageCategory.PROGRAMME_PREREQUISITES} and looks_like_dynamic_catalog_shell(text)
