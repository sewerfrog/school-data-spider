import json

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.types import FetchResult, NetworkResponseRecord
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
    assert data.run.config["programme_catalog_summary"]["recommended_next_action"] == "discover_public_catalog_api"


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


def test_api_catalog_discovery_captures_browser_network_json_by_body_shape():
    seed_url = "https://example.edu/admissions/undergraduate-programmes"
    api_url = "https://example.edu/listing-data?audience=ug"
    shell_html = """
    <html>
      <body>
        <h1>Undergraduate Programmes</h1>
        <label>Programme Level</label><button>All</button>
        <label>Programme Type</label><button>All</button>
      </body>
    </html>
    """
    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher(
            {
                seed_url: _html_response(shell_html, network_response_urls=[api_url]),
                api_url: _json_response(
                    {
                        "total": 1,
                        "items": [
                            {
                                "programmeName": "Bachelor of Environmental Studies",
                                "degree": "BSc",
                                "school": "School of Science",
                                "level": "undergraduate",
                            }
                        ],
                    }
                ),
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert [row.name for row in data.programme_catalog] == ["Bachelor of Environmental Studies"]
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_url"] == api_url
    assert candidate["api_candidate_reason"] == "browser_network_json_response"
    assert candidate["api_candidate_status"] == "captured_json"
    assert candidate["api_body_likely_catalog"] is True
    assert "parseable_programme_rows" in candidate["api_body_signals"]
    summary = data.run.config["programme_catalog_summary"]
    assert summary["api_response_count"] == 1
    assert summary["api_accepted_row_count"] == 1


def test_api_catalog_discovery_uses_browser_network_body_without_refetch():
    seed_url = "https://example.edu/admissions/undergraduate-programmes"
    api_url = "https://example.edu/listing-data?audience=ug"
    payload = {
        "total": 1,
        "items": [
            {
                "programmeName": "Bachelor of Public Policy",
                "degree": "BSocSci",
                "school": "School of Social Sciences",
                "level": "undergraduate",
            }
        ],
    }
    shell_html = """
    <html>
      <body>
        <h1>Undergraduate Programmes</h1>
        <label>Programme Level</label><button>All</button>
        <label>Programme Type</label><button>All</button>
      </body>
    </html>
    """
    fetcher = _ApiDiscoveryFetcher(
        {
            seed_url: _html_response(
                shell_html,
                network_responses=[
                    _network_response(
                        api_url,
                        body=json.dumps(payload),
                        query_params={"audience": "ug"},
                    )
                ],
            ),
        }
    )
    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert fetcher.requests == [seed_url]
    assert [row.name for row in data.programme_catalog] == ["Bachelor of Public Policy"]
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_url"] == api_url
    assert candidate["api_candidate_reason"] == "browser_network_json_response"
    assert candidate["api_candidate_status"] == "captured_json"
    assert candidate["api_network_method"] == "GET"
    assert candidate["api_network_content_type"] == "application/json"
    assert candidate["api_network_body_available"] is True
    assert candidate["api_network_query_params"] == {"audience": "ug"}
    capture = data.run.config["programme_catalog_api_capture"]
    assert capture["attempted_urls"] == [api_url]
    assert capture["network_body_urls"] == [api_url]
    assert capture["captured_urls"] == [api_url]
    assert capture["accepted_row_count"] == 1
    report = render_markdown_report(data)
    assert "- Safe capture used browser network bodies: 1" in report
    assert "network: method `GET`, content `application/json`, body captured True" in report


def test_api_catalog_discovery_rejects_unsafe_browser_network_responses_without_refetch():
    seed_url = "https://example.edu/admissions/undergraduate-programmes"
    post_url = "https://example.edu/api/programmes.json"
    token_url = "https://example.edu/api/programmes.json?token=secret"
    off_domain_url = "https://evil.example/api/programmes.json"
    payload = json.dumps(
        {
            "items": [
                {
                    "programmeName": "Bachelor of Unsafe Capture",
                    "degree": "BSc",
                    "level": "undergraduate",
                }
            ]
        }
    )
    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher(
            {
                seed_url: _html_response(
                    "<h1>Undergraduate Programmes</h1><label>Programme Level</label><label>Programme Type</label>",
                    network_responses=[
                        _network_response(post_url, method="POST", body=payload),
                        _network_response(token_url, body=payload, query_params={"token": "[redacted]"}),
                        _network_response(off_domain_url, body=payload),
                    ],
                ),
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert data.programme_catalog == []
    candidates = {
        item["api_candidate_url"]: item["api_candidate_status"]
        for item in data.run.config["programme_catalog_api_candidates"]
    }
    assert candidates[post_url] == "rejected_non_get"
    assert candidates[token_url] == "rejected_auth_or_token"
    assert candidates[off_domain_url] == "rejected_off_domain"
    token_candidate = next(
        item
        for item in data.run.config["programme_catalog_api_candidates"]
        if item["api_candidate_url"] == token_url
    )
    assert token_candidate["api_network_query_params"] == {"token": "[redacted]"}
    capture = data.run.config["programme_catalog_api_capture"]
    assert capture["attempted_urls"] == []
    assert capture["network_body_urls"] == []


def test_api_catalog_safe_capture_rejects_network_json_body_that_is_not_catalog():
    seed_url = "https://example.edu/admissions/undergraduate-programmes"
    api_url = "https://example.edu/listing-data?audience=ug"
    shell_html = """
    <html>
      <body>
        <h1>Undergraduate Programmes</h1>
        <label>Programme Level</label><button>All</button>
        <label>Programme Type</label><button>All</button>
      </body>
    </html>
    """
    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher(
            {
                seed_url: _html_response(shell_html, network_response_urls=[api_url]),
                api_url: _json_response(
                    {
                        "items": [
                            {"name": "Home", "url": "/"},
                            {"name": "Contact", "url": "/contact"},
                        ],
                        "navigation": True,
                    }
                ),
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert data.programme_catalog == []
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_status"] == "rejected_body_not_catalog"
    assert candidate["api_capture_rejection_reason"] == "body_not_catalog_like"
    assert candidate["api_body_likely_catalog"] is False
    capture = data.run.config["programme_catalog_api_capture"]
    assert capture["rejected_urls"] == [{"url": api_url, "reason": "body_not_catalog_like"}]


def test_dynamic_shell_without_api_candidate_recommends_browser_network_capture():
    seed_url = "https://example.edu/admissions/undergraduate-programmes"
    shell_html = """
    <html>
      <body>
        <h1>Undergraduate Programmes</h1>
        <label>Programme Level</label><button>All</button>
        <label>Programme Type</label><button>All</button>
        <button>Full-time</button><button>Part-time</button>
      </body>
    </html>
    """
    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher({seed_url: _html_response(shell_html)}),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    source_strategy = data.run.config["source_strategy"][0]
    assert source_strategy["catalog_source_status"] == "dynamic_shell_no_rows"
    summary = data.run.config["programme_catalog_summary"]
    assert summary["source_status_counts"]["dynamic_shell_no_rows"] == 1
    assert summary["recommended_next_action"] == "capture_browser_network_api"
    report = render_markdown_report(data)
    assert "- Recommended next action: `capture_browser_network_api`" in report


def test_dynamic_shell_api_zero_triggers_browser_second_pass_network_body_capture():
    seed_url = "https://example.edu/admissions/undergraduate-programmes"
    api_url = "https://example.edu/listing-data?audience=ug"
    shell_html = """
    <html>
      <body>
        <h1>Undergraduate Programmes</h1>
        <label>Programme Level</label><button>All</button>
        <label>Programme Type</label><button>All</button>
        <button>Full-time</button><button>Part-time</button>
      </body>
    </html>
    """
    payload = {
        "total": 1,
        "items": [
            {
                "programmeName": "Bachelor of Browser Capture",
                "degree": "BSc",
                "school": "School of Computing",
                "level": "undergraduate",
            }
        ],
    }
    primary = _ApiDiscoveryFetcher({seed_url: _html_response(shell_html)})
    browser = _ApiDiscoveryFetcher(
        {
            seed_url: _html_response(
                shell_html,
                network_responses=[
                    _network_response(
                        api_url,
                        body=json.dumps(payload),
                        query_params={"audience": "ug"},
                    )
                ],
            )
        }
    )
    fetcher = _SecondPassBrowserFetcher(primary, browser)

    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert primary.requests == [seed_url]
    assert browser.requests == [seed_url]
    assert fetcher.requests == [seed_url]
    assert [row.name for row in data.programme_catalog] == ["Bachelor of Browser Capture"]
    browser_capture = data.run.config["programme_catalog_browser_capture"]
    assert browser_capture["triggered"] is True
    assert browser_capture["attempted_urls"] == [seed_url]
    assert browser_capture["captured_urls"] == [seed_url]
    assert browser_capture["network_response_count"] == 1
    assert browser_capture["network_body_count"] == 1
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_url"] == api_url
    assert candidate["api_candidate_reason"] == "browser_network_json_response"
    assert candidate["api_candidate_status"] == "captured_json"
    assert candidate["api_network_body_available"] is True
    capture = data.run.config["programme_catalog_api_capture"]
    assert capture["attempted_urls"] == [api_url]
    assert capture["network_body_urls"] == [api_url]
    assert capture["accepted_row_count"] == 1
    report = render_markdown_report(data)
    assert "## Programme Catalog Browser Capture Diagnostics" in report
    assert "- Network bodies: 1" in report


def test_dynamic_shell_static_asset_discovery_finds_public_search_api_and_writes_catalog():
    seed_url = "https://example.edu/admissions/undergraduate-programmes"
    asset_url = "https://example.edu/assets/programmes.js"
    api_url = "https://example.edu/search/programmes?audience=ug"
    shell_html = """
    <html>
      <head><script src="/assets/programmes.js"></script></head>
      <body>
        <h1>Undergraduate Programmes</h1>
        <label>Programme Level</label><button>All</button>
        <label>Programme Type</label><button>All</button>
        <button>Full-time</button><button>Part-time</button>
      </body>
    </html>
    """
    fetcher = _ApiDiscoveryFetcher(
        {
            seed_url: _html_response(shell_html),
            asset_url: _asset_response('window.catalogEndpoint = "/search/programmes?audience=ug";'),
            api_url: _json_response(
                {
                    "total": 1,
                    "items": [
                        {
                            "programmeName": "Bachelor of Static Asset Discovery",
                            "degree": "BSc",
                            "school": "School of Computing",
                            "level": "undergraduate",
                        }
                    ],
                }
            ),
        }
    )

    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert fetcher.requests == [seed_url, asset_url, api_url]
    assert [row.name for row in data.programme_catalog] == ["Bachelor of Static Asset Discovery"]
    assert asset_url not in {source.source_url for source in data.sources}
    static_discovery = data.run.config["programme_catalog_static_asset_discovery"]
    assert static_discovery["triggered"] is True
    assert static_discovery["candidate_source_pages"] == [seed_url]
    assert static_discovery["candidate_asset_urls"] == [asset_url]
    assert static_discovery["fetched_asset_urls"] == [asset_url]
    assert static_discovery["endpoint_hint_count"] == 1
    assert static_discovery["candidate_api_urls"] == [api_url]
    candidate = data.run.config["programme_catalog_api_candidates"][0]
    assert candidate["api_candidate_url"] == api_url
    assert candidate["api_candidate_source_page"] == asset_url
    assert candidate["api_candidate_reason"] == "embedded_endpoint_hint"
    assert candidate["api_candidate_status"] == "captured_json"
    capture = data.run.config["programme_catalog_api_capture"]
    assert capture["attempted_urls"] == [api_url]
    assert capture["accepted_row_count"] == 1
    report = render_markdown_report(data)
    assert "## Programme Catalog Static Asset Discovery Diagnostics" in report
    assert "- API endpoint hints from assets: 1" in report


def test_dynamic_shell_static_asset_discovery_reports_no_endpoint_hints():
    seed_url = "https://example.edu/admissions/undergraduate-programmes"
    asset_url = "https://example.edu/assets/programmes.js"
    shell_html = """
    <html>
      <head><script src="/assets/programmes.js"></script></head>
      <body>
        <h1>Undergraduate Programmes</h1>
        <label>Programme Level</label><button>All</button>
        <label>Programme Type</label><button>All</button>
        <button>Full-time</button><button>Part-time</button>
      </body>
    </html>
    """

    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher(
            {
                seed_url: _html_response(shell_html),
                asset_url: _asset_response("console.log('no public catalogue endpoint here');"),
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert not data.programme_catalog
    static_discovery = data.run.config["programme_catalog_static_asset_discovery"]
    assert static_discovery["triggered"] is True
    assert static_discovery["fetched_asset_urls"] == [asset_url]
    assert static_discovery["endpoint_hint_count"] == 0
    assert static_discovery["candidate_api_urls"] == []
    summary = data.run.config["programme_catalog_summary"]
    assert summary["api_candidate_zero_reason"] == "static_asset_no_endpoint_hints"
    assert summary["recommended_next_action"] == "discover_public_catalog_api"
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


def test_api_catalog_discovery_ignores_generic_search_templates_without_catalog_signal():
    seed_url = "https://example.edu/programmes"
    search_url = "https://example.edu/search-results?q={{=item.value}}"
    html = """
    <html>
      <body>
        <h1>Undergraduate Programmes</h1>
        <a href="/search-results?q={{=item.value}}">Search</a>
        <script>window.searchUrl = "/search-results?q={{=item.value}}";</script>
      </body>
    </html>
    """

    data = run_scan(
        seed_url,
        _ApiDiscoveryFetcher({seed_url: _html_response(html, links=[search_url])}),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    summary = data.run.config["programme_catalog_api_discovery_summary"]
    assert summary["api_catalog_candidate_count"] == 0
    assert data.run.config["programme_catalog_api_candidates"] == []
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


def _html_response(
    text: str,
    *,
    links: list[str] | None = None,
    network_response_urls: list[str] | None = None,
    network_responses: list[NetworkResponseRecord] | None = None,
) -> tuple[SourceType, str, list[str], None, list[str], list[NetworkResponseRecord]]:
    return SourceType.HTML, text, links or [], None, network_response_urls or [], network_responses or []


def _json_response(payload: dict, *, final_url: str | None = None) -> tuple[SourceType, str, list[str], str | None]:
    return SourceType.JSON, json.dumps(payload), [], final_url


def _asset_response(text: str) -> tuple[SourceType, str, list[str], None]:
    return SourceType.OTHER, text, [], None


class _ApiDiscoveryFetcher:
    engine = "api-discovery-fixture"

    def __init__(
        self,
        responses: dict[
            str,
            tuple[SourceType, str, list[str]]
            | tuple[SourceType, str, list[str], str | None]
            | tuple[SourceType, str, list[str], str | None, list[str]]
            | tuple[SourceType, str, list[str], str | None, list[str], list[NetworkResponseRecord]],
        ],
    ) -> None:
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
        network_response_urls = response[4] if len(response) > 4 and isinstance(response[4], list) else []
        network_responses = response[5] if len(response) > 5 and isinstance(response[5], list) else []
        if source_type == SourceType.JSON:
            content_type = "application/json"
        elif source_type == SourceType.OTHER:
            content_type = "application/javascript"
        else:
            content_type = "text/html"
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
            network_response_urls=network_response_urls,
            network_responses=network_responses,
            source=source,
        )


class _SecondPassBrowserFetcher:
    engine = "second-pass-http"

    def __init__(self, primary: _ApiDiscoveryFetcher, browser: _ApiDiscoveryFetcher) -> None:
        self.primary = primary
        self.browser_fetcher = browser
        self.requests: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.requests.append(url)
        return self.primary.fetch(url)


def _network_response(
    url: str,
    *,
    method: str = "GET",
    body: str | None = None,
    content_type: str = "application/json",
    query_params: dict[str, str] | None = None,
) -> NetworkResponseRecord:
    return NetworkResponseRecord(
        url=url,
        method=method,
        status=200,
        content_type=content_type,
        response_size_bytes=len(body.encode("utf-8")) if body is not None else None,
        request_query_params=query_params or {},
        response_headers={"content-type": content_type},
        body_text=body if method == "GET" else None,
        body_sha256="fixture-sha256" if body is not None and method == "GET" else None,
    )
