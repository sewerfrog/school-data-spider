import json

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.filters import canonicalize_url
from university_admissions_crawler.crawler.types import FetchResult
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import SourceType, WarningCode, WarningRecord
from university_admissions_crawler.pipeline.run_university_scan import run_scan


def test_pipeline_expands_page_number_catalog_api_to_completion():
    seed_url = "https://example.edu/api/programmes?page=1&pageSize=2"
    data = run_scan(
        seed_url,
        _JsonApiPaginationFetcher(
            {
                seed_url: {
                    "page": 1,
                    "pageSize": 2,
                    "total": 3,
                    "items": [
                        _programme("Bachelor of Arts", "BA", "Faculty of Arts"),
                        _programme("Bachelor of Science", "BSc", "Faculty of Science"),
                    ],
                },
                "https://example.edu/api/programmes?page=2&pageSize=2": {
                    "page": 2,
                    "pageSize": 2,
                    "total": 3,
                    "items": [_programme("Bachelor of Engineering", "BEng", "Faculty of Engineering")],
                },
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert [row.name for row in data.programme_catalog] == [
        "Bachelor of Arts",
        "Bachelor of Science",
        "Bachelor of Engineering",
    ]
    assert not data.programmes
    summary = data.run.config["programme_catalog_summary"]
    assert summary["api_response_count"] == 2
    assert summary["api_page_count"] == 2
    assert summary["api_total_count"] == 3
    assert summary["api_accepted_row_count"] == 3
    assert summary["api_pagination_complete"] is True
    assert summary["api_pagination_incomplete"] is False
    assert summary["recommended_next_action"] == "none"


def test_pipeline_expands_offset_catalog_api_to_completion():
    seed_url = "https://example.edu/api/programmes?offset=0&limit=1"
    data = run_scan(
        seed_url,
        _JsonApiPaginationFetcher(
            {
                seed_url: {
                    "offset": 0,
                    "limit": 1,
                    "totalCount": 2,
                    "results": [_programme("Bachelor of Business Administration", "BBA", "Business School")],
                },
                "https://example.edu/api/programmes?offset=1&limit=1": {
                    "offset": 1,
                    "limit": 1,
                    "totalCount": 2,
                    "results": [_programme("Bachelor of Laws", "LLB", "Faculty of Law")],
                },
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert [row.name for row in data.programme_catalog] == [
        "Bachelor of Business Administration",
        "Bachelor of Laws",
    ]
    summary = data.run.config["programme_catalog_summary"]
    assert summary["api_page_count"] == 2
    assert summary["api_total_count"] == 2
    assert summary["api_pagination_complete"] is True
    assert summary["api_pagination_incomplete"] is False


def test_pipeline_expands_cursor_catalog_api_to_completion():
    seed_url = "https://example.edu/api/programmes?after=start"
    data = run_scan(
        seed_url,
        _JsonApiPaginationFetcher(
            {
                seed_url: {
                    "data": {
                        "programmes": {
                            "edges": [{"node": _programme("Bachelor of Computing", "BComp", "School of Computing")}],
                            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-2"},
                        }
                    }
                },
                "https://example.edu/api/programmes?after=cursor-2": {
                    "data": {
                        "programmes": {
                            "edges": [{"node": _programme("Bachelor of Social Sciences", "BSocSci", "Faculty of Social Sciences")}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                },
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert [row.name for row in data.programme_catalog] == [
        "Bachelor of Computing",
        "Bachelor of Social Sciences",
    ]
    summary = data.run.config["programme_catalog_summary"]
    assert summary["api_page_count"] == 2
    assert summary["api_total_count"] is None
    assert summary["api_pagination_complete"] is True
    assert summary["api_pagination_incomplete"] is False


def test_pipeline_marks_api_pagination_incomplete_when_budget_hits_before_total():
    seed_url = "https://example.edu/api/programmes?page=1&pageSize=1"
    data = run_scan(
        seed_url,
        _JsonApiPaginationFetcher(
            {
                seed_url: {
                    "page": 1,
                    "pageSize": 1,
                    "total": 3,
                    "items": [_programme("Bachelor of Arts", "BA", "Faculty of Arts")],
                },
                "https://example.edu/api/programmes?page=2&pageSize=1": {
                    "page": 2,
                    "pageSize": 1,
                    "total": 3,
                    "items": [_programme("Bachelor of Science", "BSc", "Faculty of Science")],
                },
            }
        ),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    summary = data.run.config["programme_catalog_summary"]
    assert summary["api_accepted_row_count"] == 2
    assert summary["api_total_count"] == 3
    assert summary["api_pagination_complete"] is False
    assert summary["api_pagination_incomplete"] is True
    assert summary["recommended_next_action"] == "expand_api_pagination"


def _programme(name: str, degree: str, faculty: str) -> dict[str, str]:
    return {
        "programmeName": name,
        "degree": degree,
        "faculty": faculty,
        "level": "undergraduate",
        "studyMode": "Full-time",
    }


class _JsonApiPaginationFetcher:
    engine = "api-pagination-fixture"

    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = {canonicalize_url(url): payload for url, payload in responses.items()}

    def fetch(self, url: str) -> FetchResult:
        final_url = canonicalize_url(url)
        payload = self.responses.get(final_url)
        if payload is None:
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
        text = json.dumps(payload)
        source = source_from_text(
            source_url=final_url,
            source_type=SourceType.JSON,
            title="Programmes API",
            text=text,
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
        )
        return FetchResult(
            url=url,
            final_url=final_url,
            status=200,
            title="Programmes API",
            content_type="application/json",
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=json.dumps(payload, sort_keys=True, indent=2),
            source=source,
        )
