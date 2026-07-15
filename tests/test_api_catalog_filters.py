import json

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.filters import canonicalize_url
from university_admissions_crawler.crawler.types import FetchResult
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import SourceType, WarningCode, WarningRecord
from university_admissions_crawler.pipeline.run_university_scan import run_scan
from university_admissions_crawler.reports.render_report import render_markdown_report


def test_pipeline_enumerates_low_risk_catalog_api_filters():
    seed_url = "https://example.edu/api/programmes"
    filtered_url = canonicalize_url(
        "https://example.edu/api/programmes?level=undergraduate&programmeType=degree&studyMode=full-time"
    )
    data = run_scan(
        seed_url,
        _JsonApiFilterFetcher(
            {
                seed_url: {
                    "filters": {
                        "level": [
                            {"label": "Undergraduate", "value": "undergraduate"},
                            {"label": "Postgraduate", "value": "postgraduate"},
                        ],
                        "programmeType": [
                            {"label": "Degree", "value": "degree"},
                            {"label": "Minor", "value": "minor"},
                        ],
                        "studyMode": [
                            {"label": "Full-time", "value": "full-time"},
                            {"label": "Part-time", "value": "part-time"},
                        ],
                    },
                    "items": [],
                },
                filtered_url: {
                    "total": 2,
                    "items": [
                        _programme("Bachelor of Arts", "BA", "Faculty of Arts"),
                        _programme("Bachelor of Science", "BSc", "Faculty of Science"),
                    ],
                },
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert [row.name for row in data.programme_catalog] == [
        "Bachelor of Arts",
        "Bachelor of Science",
    ]
    filter_outcome = data.run.config["programme_catalog_api_filter_enumeration"][0]
    assert filter_outcome["attempted_urls"] == [filtered_url]
    assert filter_outcome["fetched_urls"] == [filtered_url]
    assert filter_outcome["budget_hit"] is False

    summary = data.run.config["programme_catalog_summary"]
    assert summary["api_response_count"] == 2
    assert summary["api_accepted_row_count"] == 2
    assert summary["api_total_count"] == 2
    assert summary["api_filter_candidate_dimensions"] == {
        "level": ["undergraduate"],
        "programmeType": ["degree"],
        "studyMode": ["full-time"],
    }
    assert summary["api_filter_dimensions"] == {
        "level": ["undergraduate"],
        "programmeType": ["degree"],
        "studyMode": ["full-time"],
    }
    assert summary["api_filter_attempted_url_count"] == 1
    assert summary["api_filter_fetched_url_count"] == 1
    assert summary["api_filter_enumeration_budget_hit"] is False

    report = render_markdown_report(data)
    assert "API filter candidate dimensions" in report
    assert "API filter dimensions used" in report
    assert "Bachelor of Science" in report


def test_pipeline_rejects_api_filter_off_domain_redirect():
    seed_url = "https://example.edu/api/programmes"
    filtered_url = canonicalize_url(
        "https://example.edu/api/programmes?level=undergraduate&programmeType=degree&studyMode=full-time"
    )
    redirected_url = canonicalize_url(
        "https://evil.example/api/programmes?level=undergraduate&programmeType=degree&studyMode=full-time"
    )
    data = run_scan(
        seed_url,
        _JsonApiFilterFetcher(
            {
                seed_url: {
                    "filters": {
                        "level": [{"label": "Undergraduate", "value": "undergraduate"}],
                        "programmeType": [{"label": "Degree", "value": "degree"}],
                        "studyMode": [{"label": "Full-time", "value": "full-time"}],
                    },
                    "items": [],
                },
                filtered_url: (
                    {"total": 1, "items": [_programme("Bachelor of Science", "BSc", "Faculty of Science")]},
                    redirected_url,
                ),
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert data.programme_catalog == []
    filter_outcome = data.run.config["programme_catalog_api_filter_enumeration"][0]
    assert filter_outcome["attempted_urls"] == [filtered_url]
    assert filter_outcome["fetched_urls"] == []
    assert filter_outcome["rejected_urls"] == [
        {
            "url": filtered_url,
            "reason": "rejected_off_domain",
            "captured_url": redirected_url,
            "suggested_allowed_hosts": ["evil.example"],
            "suggested_allowed_domains": ["evil.example"],
        }
    ]
    report = render_markdown_report(data)
    assert "API filter rejected URL details" in report
    assert "`--allowed-host evil.example`" in report


def test_pipeline_allows_api_filter_redirect_to_configured_host():
    seed_url = "https://example.edu/api/programmes"
    filtered_url = canonicalize_url(
        "https://example.edu/api/programmes?level=undergraduate&programmeType=degree&studyMode=full-time"
    )
    redirected_url = canonicalize_url(
        "https://cdn.example-cdn.com/api/programmes?level=undergraduate&programmeType=degree&studyMode=full-time"
    )
    data = run_scan(
        seed_url,
        _JsonApiFilterFetcher(
            {
                seed_url: {
                    "filters": {
                        "level": [{"label": "Undergraduate", "value": "undergraduate"}],
                        "programmeType": [{"label": "Degree", "value": "degree"}],
                        "studyMode": [{"label": "Full-time", "value": "full-time"}],
                    },
                    "items": [],
                },
                filtered_url: (
                    {"total": 1, "items": [_programme("Bachelor of Science", "BSc", "Faculty of Science")]},
                    redirected_url,
                ),
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu", "cdn.example-cdn.com"}),
    )

    assert [row.name for row in data.programme_catalog] == ["Bachelor of Science"]
    filter_outcome = data.run.config["programme_catalog_api_filter_enumeration"][0]
    assert filter_outcome["attempted_urls"] == [filtered_url]
    assert filter_outcome["fetched_urls"] == [redirected_url]
    assert filter_outcome["rejected_urls"] == []
    cdn_source = next(source for source in data.sources if source.source_url == redirected_url)
    assert cdn_source.is_official is True


def _programme(name: str, degree: str, faculty: str) -> dict[str, str]:
    return {
        "programmeName": name,
        "degree": degree,
        "faculty": faculty,
        "level": "undergraduate",
        "studyMode": "Full-time",
    }


class _JsonApiFilterFetcher:
    engine = "api-filter-fixture"

    def __init__(self, responses: dict[str, dict | tuple[dict, str]]) -> None:
        self.responses = {canonicalize_url(url): payload for url, payload in responses.items()}

    def fetch(self, url: str) -> FetchResult:
        final_url = canonicalize_url(url)
        response = self.responses.get(final_url)
        if response is None:
            return FetchResult(
                url=url,
                final_url=final_url,
                status=404,
                title=None,
                content_type="application/json",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
                warnings=[WarningRecord(WarningCode.FETCH_FAILED, f"Missing fixture API page: {final_url}", field=final_url, source_urls=[final_url])],
            )
        payload = response
        captured_final_url = final_url
        if isinstance(response, tuple):
            payload, captured_final_url = response
        text = json.dumps(payload)
        source = source_from_text(
            source_url=captured_final_url,
            source_type=SourceType.JSON,
            title="Programmes API",
            text=text,
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
        )
        return FetchResult(
            url=url,
            final_url=captured_final_url,
            status=200,
            title="Programmes API",
            content_type="application/json",
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=json.dumps(payload, sort_keys=True, indent=2),
            source=source,
        )
