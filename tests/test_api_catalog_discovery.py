import json

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.types import FetchResult
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import SourceType, WarningCode, WarningRecord
from university_admissions_crawler.pipeline.run_university_scan import run_scan
from university_admissions_crawler.reports.render_report import render_markdown_report


def test_api_catalog_discovery_safe_captures_embedded_endpoint_and_writes_catalog():
    seed_url = "https://example.edu/programmes"
    api_url = "https://example.edu/api/programmes.json?level=undergraduate"
    html = """
    <html>
      <body><div id="app">Programmes</div></body>
      <script>window.catalogApi = "/api/programmes.json?level=undergraduate";</script>
    </html>
    """
    fetcher = _ApiDiscoveryFetcher(
        {
            seed_url: _html_response(html),
            api_url: _json_response(
                {
                    "items": [
                        {
                            "programmeName": "Bachelor of Data Science",
                            "degree": "BSc",
                            "faculty": "Faculty of Science",
                            "level": "undergraduate",
                        }
                    ]
                }
            ),
        }
    )
    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert [row.name for row in data.programme_catalog] == ["Bachelor of Data Science"]
    summary = data.run.config["programme_catalog_api_discovery_summary"]
    assert summary["api_catalog_candidate_count"] == 1
    assert summary["api_candidate_status_counts"] == {"captured_json": 1}
    assert summary["captured_json_count"] == 1
    assert summary["safe_capture_pending_count"] == 0
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_url"] == api_url
    assert candidate["api_candidate_source_page"] == seed_url
    assert candidate["api_candidate_reason"] == "embedded_endpoint_hint"
    assert candidate["api_candidate_status"] == "captured_json"
    assert candidate["api_response_content_type"] == "application/json"
    assert fetcher.requests == [seed_url, api_url]
    capture = data.run.config["programme_catalog_api_capture"]
    assert capture["attempted_urls"] == [api_url]
    assert capture["captured_urls"] == [api_url]
    assert capture["accepted_row_count"] == 1
    assert capture["applied_to_facts"] is True

    report = render_markdown_report(data)
    assert "## API Catalog Discovery Diagnostics" in report
    assert "- Safe capture attempted endpoints: 1" in report
    assert "Candidate discovery alone does not create admissions facts" in report


def test_api_catalog_discovery_records_failed_safe_capture_without_changing_facts():
    seed_url = "https://example.edu/programmes"
    api_url = "https://example.edu/api/programmes.json?level=undergraduate"
    html = """
    <html>
      <body><div id="app">Programmes</div></body>
      <script>window.catalogApi = "/api/programmes.json?level=undergraduate";</script>
    </html>
    """
    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher({seed_url: _html_response(html)}),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert not data.programme_catalog
    summary = data.run.config["programme_catalog_api_discovery_summary"]
    assert summary["api_catalog_candidate_count"] == 1
    assert summary["api_candidate_status_counts"] == {"capture_failed": 1}
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_url"] == api_url
    assert candidate["api_candidate_status"] == "capture_failed"
    assert candidate["api_capture_rejection_reason"] == "fetch_failed"
    capture = data.run.config["programme_catalog_api_capture"]
    assert capture["attempted_urls"] == [api_url]
    assert capture["rejected_urls"] == [{"url": api_url, "reason": "fetch_failed"}]
    assert capture["applied_to_facts"] is False


def test_api_catalog_discovery_marks_linked_json_candidate_as_captured_json():
    seed_url = "https://example.edu/"
    api_url = "https://example.edu/api/programmes.json"
    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher(
            {
                seed_url: _html_response('<a href="/api/programmes.json">Programmes API</a>', links=[api_url]),
                api_url: _json_response(
                    {
                        "items": [
                            {
                                "programmeName": "Bachelor of Science",
                                "degree": "BSc",
                                "faculty": "Faculty of Science",
                                "level": "undergraduate",
                            }
                        ]
                    }
                ),
            }
        ),
        DiscoveryConfig(max_pages=2, max_depth=1, allowed_hosts={"example.edu"}),
    )

    assert [row.name for row in data.programme_catalog] == ["Bachelor of Science"]
    summary = data.run.config["programme_catalog_api_discovery_summary"]
    assert summary["api_catalog_candidate_count"] == 1
    assert summary["api_candidate_status_counts"] == {"captured_json": 1}
    assert summary["captured_json_count"] == 1
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_url"] == api_url
    assert candidate["api_candidate_status"] == "captured_json"
    assert candidate["api_response_content_type"] == "application/json"
    assert isinstance(candidate["api_response_size_bytes"], int)
    assert candidate["api_response_size_bytes"] > 0
    assert data.run.config["programme_catalog_api_capture"]["attempted_urls"] == []


def test_api_catalog_discovery_records_rejected_candidates_with_reasons():
    seed_url = "https://example.edu/"
    off_domain = "https://evil.example/api/programmes.json"
    tokenised = "https://example.edu/api/programmes.json?token=secret"
    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher(
            {
                seed_url: _html_response(
                    """
                    <a href="https://evil.example/api/programmes.json">Off domain API</a>
                    <a href="/api/programmes.json?token=secret">Token API</a>
                    """,
                    links=[off_domain, tokenised],
                )
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    candidates = {
        item["api_candidate_url"]: item["api_candidate_status"]
        for item in data.run.config["programme_catalog_api_candidates"]
    }
    assert candidates[off_domain] == "rejected_off_domain"
    assert candidates[tokenised] == "rejected_auth_or_token"
    summary = data.run.config["programme_catalog_api_discovery_summary"]
    assert summary["rejected_count"] == 2
    assert summary["api_candidate_status_counts"] == {
        "rejected_auth_or_token": 1,
        "rejected_off_domain": 1,
    }
    assert data.run.config["programme_catalog_api_capture"]["attempted_urls"] == []


def test_api_catalog_safe_capture_rejects_off_domain_redirect():
    seed_url = "https://example.edu/"
    api_url = "https://example.edu/api/programmes.json"
    redirected_url = "https://cdn.evil.example/api/programmes.json"
    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher(
            {
                seed_url: _html_response('<script>window.catalogApi="/api/programmes.json";</script>'),
                api_url: _json_response(
                    {
                        "items": [
                            {
                                "programmeName": "Bachelor of Redirects",
                                "degree": "BSc",
                                "faculty": "Faculty of Science",
                                "level": "undergraduate",
                            }
                        ]
                    },
                    final_url=redirected_url,
                ),
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert not data.programme_catalog
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_url"] == api_url
    assert candidate["api_candidate_status"] == "rejected_off_domain"
    assert candidate["api_captured_url"] == redirected_url
    assert candidate["api_capture_rejection_reason"] == "redirected_off_domain"
    capture = data.run.config["programme_catalog_api_capture"]
    assert capture["attempted_urls"] == [api_url]
    assert capture["rejected_urls"] == [{"url": api_url, "reason": "redirected_off_domain"}]


def _html_response(text: str, *, links: list[str] | None = None) -> tuple[SourceType, str, list[str]]:
    return SourceType.HTML, text, links or []


def _json_response(payload: dict, *, final_url: str | None = None) -> tuple[SourceType, str, list[str], str | None]:
    return SourceType.JSON, json.dumps(payload), [], final_url


class _ApiDiscoveryFetcher:
    engine = "api-discovery-fixture"

    def __init__(self, responses: dict[str, tuple[SourceType, str, list[str]] | tuple[SourceType, str, list[str], str | None]]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.requests.append(url)
        response = self.responses.get(url)
        if response is None:
            return FetchResult(
                url=url,
                final_url=url,
                status=404,
                title=None,
                content_type="text/plain",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
                warnings=[WarningRecord(WarningCode.FETCH_FAILED, f"Missing fixture page: {url}", field=url, source_urls=[url])],
            )
        source_type, text, links = response[:3]
        final_url = response[3] if len(response) > 3 and response[3] is not None else url
        content_type = "application/json" if source_type == SourceType.JSON else "text/html"
        source = source_from_text(
            source_url=final_url,
            source_type=source_type,
            title="Programmes",
            text=text,
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
        )
        return FetchResult(
            url=url,
            final_url=final_url,
            status=200,
            title="Programmes",
            content_type=content_type,
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=text,
            links=links,
            source=source,
        )
