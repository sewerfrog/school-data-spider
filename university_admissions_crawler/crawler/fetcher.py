"""Fetch/capture adapters for deterministic fixtures and optional live engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Protocol
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen
import re

from university_admissions_crawler.crawler.html_text import _html_to_text, _strip_tags
from university_admissions_crawler.evidence.provenance import content_hash
from university_admissions_crawler.extractor.schema import SourceRecord, SourceType, WarningCode, WarningRecord


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    title: str | None
    content_type: str
    retrieved_at: str
    engine: str
    text: str = ""
    markdown: str | None = None
    links: list[str] = field(default_factory=list)
    source: SourceRecord | None = None
    warnings: list[WarningRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400 and not any(w.code == WarningCode.FETCH_FAILED for w in self.warnings)


class Fetcher(Protocol):
    engine: str

    def fetch(self, url: str) -> FetchResult:
        ...


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
                        api_links: list[str] = []
                        page.on("response", lambda response: _capture_api_response_url(response, api_links))
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
            links=_dedupe_preserve_order(list(dom_links) + api_links),
            source=source,
        )

    def _fetch_pdf_via_http(self, url: str) -> FetchResult:
        result = LiveHTTPFetcher(timeout_seconds=self.timeout_seconds, user_agent=self.user_agent).fetch(url)
        result.engine = self.engine
        if result.source is not None:
            result.source.engine = self.engine
        return result


class Crawl4AIFetcherStub:
    """Contract stub for future crawl4ai adapter.

    The stub deliberately warns instead of importing browser/crawl4ai dependencies,
    so core tests prove optional browser support is not required.
    """

    engine = "crawl4ai-stub"

    def fetch(self, url: str) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status=0,
            title=None,
            content_type="application/octet-stream",
            retrieved_at=_fixed_retrieved_at(),
            engine=self.engine,
            warnings=[
                WarningRecord(
                    WarningCode.OPTIONAL_DEPENDENCY_MISSING,
                    "crawl4ai/browser support is optional and not installed/enabled for this run.",
                    field=url,
                )
            ],
        )


class ScrapeGraphFetcherStub:
    """Contract stub for a future optional ScrapeGraphAI adapter."""

    engine = "scrapegraph-stub"

    def fetch(self, url: str) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=url,
            status=0,
            title=None,
            content_type="application/octet-stream",
            retrieved_at=_fixed_retrieved_at(),
            engine=self.engine,
            warnings=[
                WarningRecord(
                    WarningCode.OPTIONAL_DEPENDENCY_MISSING,
                    "ScrapeGraphAI support is optional and not installed/enabled for this run.",
                    field=url,
                )
            ],
        )


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


def _source_type_for_url_or_content(url: str, content_type: str) -> SourceType:
    lower_content = content_type.lower()
    if lower_content == "application/pdf" or urlparse(url).path.lower().endswith(".pdf"):
        return SourceType.PDF
    if lower_content in {"text/html", "application/xhtml+xml"}:
        return SourceType.HTML
    if lower_content in {"application/json", "application/ld+json"} or urlparse(url).path.lower().endswith(".json"):
        return SourceType.JSON
    return SourceType.OTHER


def _looks_like_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _source_type_for_fixture_path(path: Path) -> SourceType:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return SourceType.PDF
    if suffix == ".json":
        return SourceType.JSON
    if suffix in {".html", ".htm"}:
        return SourceType.HTML
    return SourceType.OTHER


def _content_type_for_source_type(source_type: SourceType) -> str:
    if source_type == SourceType.PDF:
        return "application/pdf"
    if source_type == SourceType.JSON:
        return "application/json"
    if source_type == SourceType.HTML:
        return "text/html"
    return "application/octet-stream"


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


def _json_to_text(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def _extract_json_links(text: str, base_url: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    links: list[str] = []
    for value in _walk_json_values(payload):
        if isinstance(value, str) and _looks_like_link(value):
            links.append(urljoin(base_url, value))
    return _dedupe_preserve_order(links)


def _walk_json_values(value):
    if isinstance(value, dict):
        for subvalue in value.values():
            yield from _walk_json_values(subvalue)
        return
    if isinstance(value, list):
        for subvalue in value:
            yield from _walk_json_values(subvalue)
        return
    yield value


def _looks_like_link(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith(("http://", "https://", "/")):
        return True
    return bool(re.search(r"\.(?:html?|pdf|json)(?:[?#].*)?$", stripped, flags=re.IGNORECASE))


def _capture_api_response_url(response, links: list[str]) -> None:
    try:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        url = response.url
    except Exception:
        return
    if content_type in {"application/json", "application/ld+json"} or _looks_like_api_url(url):
        links.append(url)


def _looks_like_api_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    return "/api/" in path or path.endswith(".json") or "/graphql" in path or "/odata/" in path


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out
