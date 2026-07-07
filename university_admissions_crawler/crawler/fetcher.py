"""Fetch/capture adapters for deterministic fixtures and optional live engines."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen
import re

from university_admissions_crawler.crawler.html_text import _html_to_text, _strip_tags
from university_admissions_crawler.crawler.json_content import (
    dedupe_preserve_order,
    extract_json_links,
    json_to_text,
    looks_like_link,
    walk_json_values,
)
from university_admissions_crawler.crawler.optional_stubs import Crawl4AIFetcherStub, ScrapeGraphFetcherStub
from university_admissions_crawler.crawler.filters import canonicalize_url, score_url
from university_admissions_crawler.crawler.source_types import (
    content_type_for_source_type,
    looks_like_pdf_url,
    source_type_for_fixture_path,
    source_type_for_url_or_content,
)
from university_admissions_crawler.crawler.types import FetchResult, Fetcher, NetworkResponseRecord
from university_admissions_crawler.evidence.provenance import content_hash
from university_admissions_crawler.extractor.schema import SourceRecord, SourceType, WarningCode, WarningRecord

_MAX_NETWORK_RESPONSE_BODY_BYTES = 2_000_000
_SAFE_RESPONSE_HEADER_NAMES = {
    "cache-control",
    "content-length",
    "content-type",
    "etag",
    "last-modified",
    "link",
    "x-total-count",
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

_dedupe_preserve_order = dedupe_preserve_order
_extract_json_links = extract_json_links
_json_to_text = json_to_text
_looks_like_link = looks_like_link
_walk_json_values = walk_json_values
_content_type_for_source_type = content_type_for_source_type
_looks_like_pdf_url = looks_like_pdf_url
_source_type_for_fixture_path = source_type_for_fixture_path
_source_type_for_url_or_content = source_type_for_url_or_content


class FixtureFetcher:
    """Fetch pages from a local fixture tree while preserving URL-like metadata."""

    engine = "fixture"

    def __init__(self, root: str | Path, base_url: str = "https://fixture.test/") -> None:
        root_path = Path(root)
        if root_path.is_file():
            root_path = root_path.parent
        self.root = root_path
        self.base_url = base_url.rstrip("/") + "/"

    def fetch(self, url: str) -> FetchResult:
        target = self._resolve_path(url)
        retrieved_at = _fixed_retrieved_at()
        if not target.exists() or not target.is_file():
            return FetchResult(
                url=url,
                final_url=self._final_url_for_request(url, target),
                status=404,
                title=None,
                content_type="text/plain",
                retrieved_at=retrieved_at,
                engine=self.engine,
                warnings=[WarningRecord(WarningCode.FETCH_FAILED, f"Fixture not found: {target}", field=url)],
            )

        text = target.read_text(encoding="utf-8")
        source_type = _source_type_for_fixture_path(target)
        content_type = _content_type_for_source_type(source_type)
        title = _extract_title(text) or target.stem.replace("-", " ").title()
        final_url = self._final_url_for_request(url, target)
        source = SourceRecord(
            source_url=final_url,
            source_type=source_type,
            title=title,
            retrieved_at=retrieved_at,
            academic_year=_extract_academic_year(text),
            content_hash=content_hash(text),
            engine=self.engine,
        )
        links = _extract_links_for_source(text, final_url, source_type)
        markdown = _text_for_source(text, source_type)
        return FetchResult(
            url=url,
            final_url=final_url,
            status=200,
            title=title,
            content_type=content_type,
            retrieved_at=retrieved_at,
            engine=self.engine,
            text=text,
            markdown=markdown,
            links=links,
            source=source,
        )

    def _resolve_path(self, url: str) -> Path:
        if url.startswith("file://"):
            candidate = Path(url.removeprefix("file://")).resolve()
            root = self.root.resolve()
            if root not in candidate.parents and candidate != root:
                return self.root / "__outside_fixture__"
            return candidate
        parsed_url = urlparse(url)
        parsed_base = urlparse(self.base_url)
        if parsed_url.scheme in {"http", "https"} and parsed_url.netloc != parsed_base.netloc:
            rel = f"{parsed_url.netloc}{parsed_url.path}"
        elif parsed_url.scheme in {"http", "https"} and parsed_url.netloc == parsed_base.netloc:
            rel = parsed_url.path
        elif url.startswith(self.base_url):
            rel = url.removeprefix(self.base_url)
        else:
            rel = url
        rel = urldefrag(rel)[0].split("?", 1)[0].lstrip("/")
        if not rel:
            rel = "index.html"
        candidate = (self.root / rel).resolve()
        root = self.root.resolve()
        if root not in candidate.parents and candidate != root:
            return self.root / "__outside_fixture__"
        if candidate.is_dir():
            candidate = (candidate / "index.html").resolve()
            if root not in candidate.parents and candidate != root:
                return self.root / "__outside_fixture__"
        return candidate

    def _url_for_path(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.root.resolve()).as_posix()
        if rel == "index.html":
            return self.base_url
        return urljoin(self.base_url, rel)

    def _final_url_for_request(self, url: str, path: Path) -> str:
        parsed_url = urlparse(url)
        parsed_base = urlparse(self.base_url)
        if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
            clean = urldefrag(url)[0].split("?", 1)[0]
            return clean
        if parsed_url.scheme == "file":
            return parsed_url._replace(params="", query="", fragment="").geturl()
        return self._url_for_path(path)


class LiveHTTPFetcher:
    """Fetch live pages with Python stdlib urllib.

    This is suitable for ordinary static HTML and downloadable text/PDF
    sources. JavaScript-rendered or WAF-protected pages should use
    ``PlaywrightBrowserFetcher`` instead.
    """

    engine = "live-http"

    def __init__(self, timeout_seconds: float = 15.0, user_agent: str | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent or (
            "UniversityAdmissionsCrawler/0.1 "
            "(evidence-first research crawler; contact: local-run)"
        )

    def fetch(self, url: str) -> FetchResult:
        retrieved_at = _retrieved_at_now()
        request = Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                final_url = response.geturl()
                status = getattr(response, "status", response.getcode())
                content_type = response.headers.get_content_type() or "application/octet-stream"
                raw = response.read()
        except Exception as exc:
            return FetchResult(
                url=url,
                final_url=url,
                status=0,
                title=None,
                content_type="application/octet-stream",
                retrieved_at=retrieved_at,
                engine=self.engine,
                warnings=[
                    WarningRecord(
                        WarningCode.FETCH_FAILED,
                        f"Live HTTP fetch raised {type(exc).__name__}: {exc}",
                        field=url,
                        source_urls=[url],
                    )
                ],
            )

        source_type = _source_type_for_url_or_content(final_url, content_type)
        text = raw.decode("latin-1") if source_type == SourceType.PDF else _decode_bytes(raw)
        title = _extract_title(text) if source_type == SourceType.HTML else Path(urlparse(final_url).path).name or final_url
        source = SourceRecord(
            source_url=final_url,
            source_type=source_type,
            title=title,
            retrieved_at=retrieved_at,
            academic_year=_extract_academic_year(text),
            content_hash=content_hash(raw),
            engine=self.engine,
        )
        links = _extract_links_for_source(text, final_url, source_type)
        markdown = _text_for_source(text, source_type)
        return FetchResult(
            url=url,
            final_url=final_url,
            status=status,
            title=title,
            content_type=content_type,
            retrieved_at=retrieved_at,
            engine=self.engine,
            text=text,
            markdown=markdown,
            links=links,
            source=source,
        )


class PlaywrightBrowserFetcher:
    """Fetch live pages through Playwright, loaded only when explicitly used."""

    engine = "playwright-browser"

    def __init__(
        self,
        timeout_seconds: float = 30.0,
        wait_until: str = "networkidle",
        user_agent: str | None = None,
        headless: bool = True,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.wait_until = wait_until
        self.user_agent = user_agent
        self.headless = headless

    def fetch(self, url: str) -> FetchResult:
        if _looks_like_pdf_url(url):
            return self._fetch_pdf_via_http(url)
        retrieved_at = _retrieved_at_now()
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return FetchResult(
                url=url,
                final_url=url,
                status=0,
                title=None,
                content_type="application/octet-stream",
                retrieved_at=retrieved_at,
                engine=self.engine,
                warnings=[
                    WarningRecord(
                        WarningCode.OPTIONAL_DEPENDENCY_MISSING,
                        f"Playwright browser support is optional and not available: {type(exc).__name__}: {exc}",
                        field=url,
                        source_urls=[url],
                    )
                ],
            )

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                try:
                    context_kwargs = {"user_agent": self.user_agent} if self.user_agent else {}
                    context = browser.new_context(**context_kwargs)
                    try:
                        page = context.new_page()
                        network_responses: list[NetworkResponseRecord] = []
                        page.on("response", lambda response: _capture_api_response_record(response, network_responses))
                        response = page.goto(url, wait_until=self.wait_until, timeout=int(self.timeout_seconds * 1000))
                        page.wait_for_load_state("domcontentloaded", timeout=int(self.timeout_seconds * 1000))
                        html = page.content()
                        final_url = page.url
                        title = page.title() or _extract_title(html)
                        dom_links = page.eval_on_selector_all(
                            "a[href]",
                            "(nodes) => nodes.map((node) => node.href).filter(Boolean)",
                        )
                        status = response.status if response is not None else 200
                        content_type = response.headers.get("content-type", "text/html").split(";", 1)[0] if response is not None else "text/html"
                        if _source_type_for_url_or_content(final_url, content_type) == SourceType.PDF:
                            return self._fetch_pdf_via_http(final_url)
                    finally:
                        context.close()
                finally:
                    browser.close()
        except PlaywrightError as exc:
            if "Download is starting" in str(exc):
                return self._fetch_pdf_via_http(url)
            return FetchResult(
                url=url,
                final_url=url,
                status=0,
                title=None,
                content_type="application/octet-stream",
                retrieved_at=retrieved_at,
                engine=self.engine,
                warnings=[
                    WarningRecord(
                        WarningCode.FETCH_FAILED,
                        f"Playwright fetch raised {type(exc).__name__}: {exc}",
                        field=url,
                        source_urls=[url],
                    )
                ],
            )
        except Exception as exc:
            return FetchResult(
                url=url,
                final_url=url,
                status=0,
                title=None,
                content_type="application/octet-stream",
                retrieved_at=retrieved_at,
                engine=self.engine,
                warnings=[
                    WarningRecord(
                        WarningCode.FETCH_FAILED,
                        f"Browser fetch raised {type(exc).__name__}: {exc}",
                        field=url,
                        source_urls=[url],
                    )
                ],
            )

        source = SourceRecord(
            source_url=final_url,
            source_type=SourceType.HTML,
            title=title,
            retrieved_at=retrieved_at,
            academic_year=_extract_academic_year(html),
            content_hash=content_hash(html),
            engine=self.engine,
        )
        return FetchResult(
            url=url,
            final_url=final_url,
            status=status,
            title=title,
            content_type=content_type,
            retrieved_at=retrieved_at,
            engine=self.engine,
            text=html,
            markdown=_html_to_text(html),
            links=_dedupe_preserve_order(list(dom_links) + [record.url for record in network_responses]),
            network_response_urls=_dedupe_preserve_order([record.url for record in network_responses]),
            network_responses=network_responses,
            source=source,
        )

    def _fetch_pdf_via_http(self, url: str) -> FetchResult:
        result = LiveHTTPFetcher(timeout_seconds=self.timeout_seconds, user_agent=self.user_agent).fetch(url)
        result.engine = self.engine
        if result.source is not None:
            result.source.engine = self.engine
        return result


class BrowserFallbackFetcher:
    """HTTP-first fetcher with guarded browser fallback for JS-rendered pages."""

    engine = "browser-fallback"

    def __init__(self, primary_fetcher: Fetcher, browser_fetcher: Fetcher, seed_url: str | None = None) -> None:
        self.primary_fetcher = primary_fetcher
        self.browser_fetcher = browser_fetcher
        self.seed_url = canonicalize_url(seed_url) if seed_url else None

    def fetch(self, url: str) -> FetchResult:
        primary_result = self.primary_fetcher.fetch(url)
        reason = _browser_fallback_reason(primary_result, self.seed_url)
        if reason is None:
            return primary_result
        browser_result = self.browser_fetcher.fetch(url)
        if browser_result.ok:
            return browser_result
        return _primary_with_browser_fallback_warning(primary_result, browser_result, reason)


def assert_fetch_contract(result: FetchResult) -> None:
    assert result.url is not None
    assert result.final_url is not None
    assert result.retrieved_at
    assert result.engine
    assert isinstance(result.links, list)
    assert isinstance(result.warnings, list)
    if result.ok:
        assert result.source is not None
        assert result.source.source_url == result.final_url
        assert result.source.content_hash
        assert result.source.engine == result.engine


def _extract_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        heading = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        match = heading
    if not match:
        return None
    return _strip_tags(match.group(1)).strip() or None


def _extract_links(html: str, base_url: str) -> list[str]:
    links: list[str] = []
    for href in re.findall(r"href=[\"']([^\"']+)[\"']", html, re.IGNORECASE):
        href = href.strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        links.append(urljoin(base_url, href))
    return links


def _extract_academic_year(text: str) -> str | None:
    plain = _html_to_text(text)
    match = re.search(r"(?:academic year|ay)\s*[: ]\s*([0-9]{4}\s*[/\\-]\s*[0-9]{4})", plain, re.IGNORECASE)
    if match:
        return re.sub(r"\s+", "", match.group(1)).replace("-", "/")
    return None


def _fixed_retrieved_at() -> str:
    return "2026-06-01T00:00:00+00:00"


def _retrieved_at_now() -> str:
    return datetime.now(UTC).isoformat()


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_links_for_source(text: str, base_url: str, source_type: SourceType) -> list[str]:
    if source_type == SourceType.HTML:
        return _extract_links(text, base_url)
    if source_type == SourceType.JSON:
        return _extract_json_links(text, base_url)
    return []


def _text_for_source(text: str, source_type: SourceType) -> str:
    if source_type == SourceType.HTML:
        return _html_to_text(text)
    if source_type == SourceType.JSON:
        return _json_to_text(text)
    return text


def _capture_api_response_record(response, records: list[NetworkResponseRecord]) -> None:
    try:
        headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        content_type = headers.get("content-type", "").split(";", 1)[0].lower()
        url = response.url
        method = str(response.request.method or "GET").upper()
        status = int(response.status)
    except Exception:
        return
    if content_type in {"application/json", "application/ld+json"} or _looks_like_api_url(url):
        response_size = _int_or_none(headers.get("content-length"))
        body_text: str | None = None
        body_sha256: str | None = None
        body_truncated = bool(response_size is not None and response_size > _MAX_NETWORK_RESPONSE_BODY_BYTES)
        if method == "GET" and content_type in {"application/json", "application/ld+json"} and not body_truncated:
            try:
                body = response.body()
            except Exception:
                body = b""
            if body:
                response_size = len(body)
                if len(body) <= _MAX_NETWORK_RESPONSE_BODY_BYTES:
                    body_text = _decode_bytes(body)
                    body_sha256 = content_hash(body)
                else:
                    body_truncated = True
        records.append(
            NetworkResponseRecord(
                url=url,
                method=method,
                status=status,
                content_type=content_type,
                response_size_bytes=response_size,
                request_query_params=_safe_query_params(url),
                response_headers=_safe_response_headers(headers),
                body_text=body_text,
                body_sha256=body_sha256,
                body_truncated=body_truncated,
            )
        )


def _looks_like_api_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return "/api/" in path or path.endswith(".json") or "/graphql" in path or "/odata/" in path


def _safe_query_params(url: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for key, value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        normalised = re.sub(r"[^a-z0-9]", "", key.lower())
        params[key] = "[redacted]" if normalised in _SENSITIVE_QUERY_KEYS else _truncate_metadata_value(value)
    return params


def _safe_response_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: _truncate_metadata_value(value)
        for key, value in sorted(headers.items())
        if key in _SAFE_RESPONSE_HEADER_NAMES
    }


def _truncate_metadata_value(value: str, limit: int = 160) -> str:
    value = str(value)
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _browser_fallback_reason(result: FetchResult, seed_url: str | None) -> str | None:
    if not result.ok or _source_type_for_url_or_content(result.final_url, result.content_type) != SourceType.HTML:
        return None
    if _looks_like_hard_block_or_challenge(result):
        return None
    if not _is_homepage_or_high_value(result, seed_url):
        return None
    if _looks_like_browser_renderable_shell(result):
        return "js_rendered_shell"
    if _has_no_useful_links(result) and _has_thin_text(result):
        return "no_useful_links"
    return None


def _is_homepage_or_high_value(result: FetchResult, seed_url: str | None) -> bool:
    if seed_url and canonicalize_url(result.final_url) == seed_url:
        return True
    text = result.markdown or _html_to_text(result.text)
    return score_url(result.final_url, result.title, text) >= 6


def _looks_like_browser_renderable_shell(result: FetchResult) -> bool:
    raw = result.text.lower()
    plain = (result.markdown or _html_to_text(result.text)).lower()
    if len(result.links) > 1:
        return False
    has_app_root = bool(re.search(r"id=[\"'](?:__next|root|app|nuxt|gatsby-focus-wrapper)[\"']", raw))
    has_framework_state = any(
        signal in raw
        for signal in (
            "__next_data__",
            "window.__nuxt__",
            "ng-version",
            "data-reactroot",
            "webpackjsonp",
            "vite/client",
        )
    )
    asks_for_javascript = "enable javascript" in plain or "javascript is required" in plain or "you need javascript" in plain
    script_heavy_shell = raw.count("<script") >= 4 and _has_thin_text(result)
    return has_app_root or has_framework_state or (asks_for_javascript and "<script" in raw) or script_heavy_shell


def _looks_like_hard_block_or_challenge(result: FetchResult) -> bool:
    haystack = f"{result.final_url} {result.title or ''} {(result.markdown or result.text)[:4000]}".lower()
    hard_terms = (
        "_incapsula_resource",
        "incapsula incident id",
        "captcha",
        "cloudflare",
        "access denied",
        "verify you are human",
        "bot detection",
    )
    if any(term in haystack for term in hard_terms):
        return True
    return "noindex" in haystack and "nofollow" in haystack and ("robots" in haystack or "<meta" in haystack)


def _has_no_useful_links(result: FetchResult) -> bool:
    return len(result.links) == 0


def _has_thin_text(result: FetchResult) -> bool:
    plain = re.sub(r"\s+", " ", result.markdown or _html_to_text(result.text)).strip()
    return len(plain) < 500


def _primary_with_browser_fallback_warning(primary: FetchResult, browser: FetchResult, reason: str) -> FetchResult:
    warnings = list(primary.warnings)
    browser_warnings = browser.warnings or [
        WarningRecord(
            WarningCode.NEEDS_MANUAL_CHECK,
            f"Browser fallback was attempted for {reason} but did not return usable content.",
            field=primary.final_url,
            source_urls=[primary.final_url],
        )
    ]
    for warning in browser_warnings:
        if warning.code == WarningCode.FETCH_FAILED:
            warnings.append(
                WarningRecord(
                    WarningCode.NEEDS_MANUAL_CHECK,
                    f"Browser fallback failed after HTTP source looked like {reason}: {warning.message}",
                    field=warning.field or primary.final_url,
                    source_urls=warning.source_urls or [primary.final_url],
                )
            )
        else:
            warnings.append(warning)
    primary.warnings = warnings
    return primary
