from pathlib import Path
from unittest.mock import patch

from university_admissions_crawler.crawler.fetcher import (
    Crawl4AIFetcherStub,
    FixtureFetcher,
    LiveHTTPFetcher,
    PlaywrightBrowserFetcher,
    ScrapeGraphFetcherStub,
    assert_fetch_contract,
)
from university_admissions_crawler.extractor.schema import SourceType, WarningCode

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
