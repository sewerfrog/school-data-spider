from pathlib import Path
from unittest.mock import patch

from university_admissions_crawler.crawler.fetcher import (
    BrowserFallbackFetcher,
    Crawl4AIFetcherStub,
    FixtureFetcher,
    FetchResult,
    LiveHTTPFetcher,
    PlaywrightBrowserFetcher,
    ScrapeGraphFetcherStub,
    assert_fetch_contract,
)
from university_admissions_crawler.extractor.schema import SourceType, WarningCode, WarningRecord
from university_admissions_crawler.evidence.provenance import source_from_text

ROOT = Path("tests/fixtures/mini_university_site")


def test_fixture_fetcher_returns_source_links_and_hash():
    result = FixtureFetcher(ROOT).fetch("https://fixture.test/")
    assert_fetch_contract(result)
    assert result.ok
    assert result.title == "Mini University"
    assert result.source is not None
    assert result.source.content_hash
    assert "https://fixture.test/admissions/index.html" in result.links


def test_fixture_fetcher_reports_missing_file_as_fetch_warning():
    result = FixtureFetcher(ROOT).fetch("https://fixture.test/missing.html")
    assert_fetch_contract(result)
    assert not result.ok
    assert result.warnings[0].code == WarningCode.FETCH_FAILED


def test_fixture_fetcher_pdf_source_type_and_no_links():
    result = FixtureFetcher(ROOT).fetch("https://fixture.test/admissions/prospectus.pdf")
    assert_fetch_contract(result)
    assert result.ok
    assert result.source.source_type == SourceType.PDF
    assert result.links == []


def test_crawl4ai_stub_satisfies_contract_without_optional_dependency():
    result = Crawl4AIFetcherStub().fetch("https://example.edu")
    assert_fetch_contract(result)
    assert result.engine == "crawl4ai-stub"
    assert result.warnings[0].code == WarningCode.OPTIONAL_DEPENDENCY_MISSING


def test_scrapegraph_stub_satisfies_contract_without_optional_dependency():
    result = ScrapeGraphFetcherStub().fetch("https://example.edu")
    assert_fetch_contract(result)
    assert result.engine == "scrapegraph-stub"
    assert result.warnings[0].code == WarningCode.OPTIONAL_DEPENDENCY_MISSING


def test_fixture_fetcher_rejects_file_url_outside_root():
    result = FixtureFetcher(ROOT).fetch("file:///etc/passwd")
    assert not result.ok
    assert result.warnings[0].code == WarningCode.FETCH_FAILED


def test_fixture_fetcher_extracts_academic_year():
    result = FixtureFetcher(ROOT).fetch("https://fixture.test/old-deadlines.html")
    assert result.source.academic_year == "2024/2025"


def test_fixture_fetcher_json_source_type_and_links():
    result = FixtureFetcher(ROOT).fetch("https://fixture.test/api/programmes.json")
    assert_fetch_contract(result)
    assert result.ok
    assert result.source.source_type == SourceType.JSON
    assert "Bachelor of Science" in result.markdown


def test_fixture_fetcher_html_text_prefers_main_content_and_removes_navigation_noise():
    result = FixtureFetcher(ROOT).fetch("https://fixture.test/realistic-admissions.html")
    assert result.ok
    assert "Application Period" in result.markdown
    assert "Alumni News Giving Staff Jobs" not in result.markdown
    assert "Cookie banner" not in result.markdown


def test_live_http_fetcher_fetches_local_html():
    html = b"<title>Live Mini</title><a href='/admissions.html'>Admissions</a>"
    with patch("university_admissions_crawler.crawler.fetcher.urlopen", return_value=_FakeHTTPResponse(html, "https://example.edu/")):
        result = LiveHTTPFetcher(timeout_seconds=5).fetch("https://example.edu/")
    assert_fetch_contract(result)
    assert result.ok
    assert result.engine == "live-http"
    assert result.title == "Live Mini"
    assert result.links == ["https://example.edu/admissions.html"]


def test_live_http_fetcher_fetches_json_source():
    body = b'{"programmes":[{"programmeName":"Bachelor of Science","url":"/programmes/science.html"}]}'
    with patch("university_admissions_crawler.crawler.fetcher.urlopen", return_value=_FakeHTTPResponse(body, "https://example.edu/api/programmes.json", "application/json")):
        result = LiveHTTPFetcher(timeout_seconds=5).fetch("https://example.edu/api/programmes.json")
    assert_fetch_contract(result)
    assert result.source.source_type == SourceType.JSON
    assert result.links == ["https://example.edu/programmes/science.html"]


def test_live_http_fetcher_keeps_sitemap_xml_text_parseable():
    body = b"<urlset><url><loc>https://example.edu/programmes</loc></url></urlset>"
    with patch("university_admissions_crawler.crawler.fetcher.urlopen", return_value=_FakeHTTPResponse(body, "https://example.edu/sitemap.xml", "application/xml")):
        result = LiveHTTPFetcher(timeout_seconds=5).fetch("https://example.edu/sitemap.xml")
    assert_fetch_contract(result)
    assert result.source.source_type == SourceType.OTHER
    assert "<loc>https://example.edu/programmes</loc>" in result.text


def test_playwright_browser_fetcher_warns_when_optional_dependency_missing():
    result = PlaywrightBrowserFetcher(timeout_seconds=1).fetch("https://example.edu")
    if result.ok:
        assert_fetch_contract(result)
    else:
        assert result.warnings[0].code in {WarningCode.OPTIONAL_DEPENDENCY_MISSING, WarningCode.FETCH_FAILED}


def test_playwright_browser_fetcher_delegates_obvious_pdf_to_live_http():
    body = b"%PDF-1.4 fake"
    with patch("university_admissions_crawler.crawler.fetcher.urlopen", return_value=_FakeHTTPResponse(body, "https://example.edu/prospectus.pdf", "application/pdf")):
        result = PlaywrightBrowserFetcher(timeout_seconds=5).fetch("https://example.edu/prospectus.pdf")
    assert_fetch_contract(result)
    assert result.source.source_type == SourceType.PDF
    assert result.engine == "playwright-browser"
    assert result.source.engine == "playwright-browser"


def test_browser_fallback_fetcher_keeps_regular_http_result():
    primary = _StaticFetcher(
        _html_result(
            "https://example.edu/",
            "Undergraduate Admissions",
            "Undergraduate Admissions Applications are open. Tuition fees and programme requirements are listed.",
            links=["https://example.edu/admissions"],
            engine="http-test",
        )
    )
    browser = _StaticFetcher(_html_result("https://example.edu/", "Browser", "Browser rendered", engine="browser-test"))

    result = BrowserFallbackFetcher(primary, browser, seed_url="https://example.edu/").fetch("https://example.edu/")

    assert result.engine == "http-test"
    assert primary.calls == ["https://example.edu/"]
    assert browser.calls == []


def test_browser_fallback_fetcher_uses_browser_for_js_rendered_homepage():
    primary = _StaticFetcher(
        _html_result(
            "https://example.edu/",
            "Example University",
            "<div id='__next'></div><script src='/app.js'></script><script src='/vendor.js'></script>",
            links=[],
            engine="http-test",
        )
    )
    browser = _StaticFetcher(
        _html_result(
            "https://example.edu/",
            "Example University",
            "Undergraduate Admissions <a href='/programmes'>Programmes</a>",
            links=["https://example.edu/programmes"],
            engine="browser-test",
        )
    )

    result = BrowserFallbackFetcher(primary, browser, seed_url="https://example.edu/").fetch("https://example.edu/")

    assert result.engine == "browser-test"
    assert result.links == ["https://example.edu/programmes"]
    assert primary.calls == ["https://example.edu/"]
    assert browser.calls == ["https://example.edu/"]


def test_browser_fallback_fetcher_does_not_mask_challenge_pages():
    challenge = (
        "<title>Access Denied</title>"
        "Access Denied. Please enable JavaScript and complete the captcha."
    )
    primary = _StaticFetcher(_html_result("https://example.edu/", "Access Denied", challenge, links=[], engine="http-test"))
    browser = _StaticFetcher(_html_result("https://example.edu/", "Browser", "Rendered", engine="browser-test"))

    result = BrowserFallbackFetcher(primary, browser, seed_url="https://example.edu/").fetch("https://example.edu/")

    assert result.engine == "http-test"
    assert browser.calls == []


def test_browser_fallback_fetcher_warns_and_keeps_http_when_browser_unavailable():
    primary = _StaticFetcher(
        _html_result(
            "https://example.edu/",
            "Example University",
            "<div id='root'></div><script src='/app.js'></script><script src='/vendor.js'></script>",
            links=[],
            engine="http-test",
        )
    )
    browser = _StaticFetcher(
        FetchResult(
            url="https://example.edu/",
            final_url="https://example.edu/",
            status=0,
            title=None,
            content_type="application/octet-stream",
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine="browser-test",
            warnings=[
                WarningRecord(
                    WarningCode.OPTIONAL_DEPENDENCY_MISSING,
                    "Playwright browser support is optional and not available.",
                    field="https://example.edu/",
                    source_urls=["https://example.edu/"],
                )
            ],
        )
    )

    result = BrowserFallbackFetcher(primary, browser, seed_url="https://example.edu/").fetch("https://example.edu/")

    assert result.engine == "http-test"
    assert result.source is not None
    assert any(w.code == WarningCode.OPTIONAL_DEPENDENCY_MISSING for w in result.warnings)


class _FakeHeaders:
    def __init__(self, content_type: str = "text/html") -> None:
        self._content_type = content_type

    def get_content_type(self):
        return self._content_type


class _FakeHTTPResponse:
    status = 200

    def __init__(self, body: bytes, url: str, content_type: str = "text/html") -> None:
        self._body = body
        self._url = url
        self.headers = _FakeHeaders(content_type)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self._url

    def getcode(self):
        return self.status

    def read(self):
        return self._body


class _StaticFetcher:
    def __init__(self, result: FetchResult) -> None:
        self.result = result
        self.calls: list[str] = []
        self.engine = result.engine

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        return self.result


def _html_result(url: str, title: str, body: str, *, links: list[str] | None = None, engine: str) -> FetchResult:
    source = source_from_text(
        source_url=url,
        source_type=SourceType.HTML,
        title=title,
        text=body,
        retrieved_at="2026-06-01T00:00:00+00:00",
        engine=engine,
    )
    return FetchResult(
        url=url,
        final_url=url,
        status=200,
        title=title,
        content_type="text/html",
        retrieved_at="2026-06-01T00:00:00+00:00",
        engine=engine,
        text=body,
        markdown=body,
        links=links or [],
        source=source,
    )
