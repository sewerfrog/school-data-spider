"""Warning-only stubs for optional future fetch engines."""

from __future__ import annotations

from university_admissions_crawler.crawler.types import FetchResult
from university_admissions_crawler.extractor.schema import WarningCode, WarningRecord


class Crawl4AIFetcherStub:
    """Contract stub for future crawl4ai adapter.

    The stub deliberately warns instead of importing browser/crawl4ai dependencies,
    so core tests prove optional browser support is not required.
    """

    engine = "crawl4ai-stub"

    def fetch(self, url: str) -> FetchResult:
        return _optional_dependency_result(
            url,
            self.engine,
            "crawl4ai/browser support is optional and not installed/enabled for this run.",
        )


class ScrapeGraphFetcherStub:
    """Contract stub for a future optional ScrapeGraphAI adapter."""

    engine = "scrapegraph-stub"

    def fetch(self, url: str) -> FetchResult:
        return _optional_dependency_result(
            url,
            self.engine,
            "ScrapeGraphAI support is optional and not installed/enabled for this run.",
        )


def _optional_dependency_result(url: str, engine: str, message: str) -> FetchResult:
    from university_admissions_crawler.crawler.fetcher import _fixed_retrieved_at

    return FetchResult(
        url=url,
        final_url=url,
        status=0,
        title=None,
        content_type="application/octet-stream",
        retrieved_at=_fixed_retrieved_at(),
        engine=engine,
        warnings=[
            WarningRecord(
                WarningCode.OPTIONAL_DEPENDENCY_MISSING,
                message,
                field=url,
            )
        ],
    )
