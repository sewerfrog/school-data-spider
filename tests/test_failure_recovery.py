from dataclasses import dataclass

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import FetchResult, Fetcher
from university_admissions_crawler.extractor.pdf_extractor import PDFExtractionResult, PDFPageText
from university_admissions_crawler.extractor.schema import SourceType, WarningCode, WarningRecord
from university_admissions_crawler.pipeline.run_university_scan import run_scan


@dataclass
class MixedFailureFetcher(Fetcher):
    engine = "mixed-failure"

    def fetch(self, url: str) -> FetchResult:
        if url.endswith("/"):
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                title="Home",
                content_type="text/html",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
                text='<a href="/timeout.html">Admissions timeout</a><a href="/ok.html">Undergraduate Admissions</a>',
                markdown="Undergraduate Admissions",
                links=["https://fixture.test/timeout.html", "https://fixture.test/ok.html"],
                source=None,
            )
        if url.endswith("timeout.html"):
            return FetchResult(
                url=url,
                final_url=url,
                status=504,
                title=None,
                content_type="text/plain",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
                warnings=[WarningRecord(WarningCode.FETCH_FAILED, "timeout", field=url)],
            )
        from university_admissions_crawler.evidence.provenance import source_from_text

        source = source_from_text(source_url=url, title="Undergraduate Admissions", text="Applicants should apply by 31 January 2027.", retrieved_at="2026-06-01T00:00:00+00:00", engine=self.engine)
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title="Undergraduate Admissions",
            content_type="text/html",
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
            text="Applicants should apply by 31 January 2027.",
            markdown="Applicants should apply by 31 January 2027.",
            source=source,
        )


def test_fetch_failures_warn_and_scan_continues():
    data = run_scan("https://fixture.test/", MixedFailureFetcher(), DiscoveryConfig(max_pages=5, max_depth=1, allowed_hosts={"fixture.test"}))
    assert any(w.code == WarningCode.FETCH_FAILED for w in data.warnings)
    assert data.admissions.application_periods[0].value.value == "31 January 2027"


class BadStatusNoWarningFetcher(MixedFailureFetcher):
    def fetch(self, url: str) -> FetchResult:
        if url.endswith("bad.html"):
            return FetchResult(
                url=url,
                final_url=url,
                status=500,
                title="Bad",
                content_type="text/html",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
            )
        if url.endswith("/"):
            result = super().fetch(url)
            result.links.append("https://fixture.test/bad.html")
            return result
        return super().fetch(url)


def test_bad_status_without_adapter_warning_gets_contract_warning_and_continues():
    data = run_scan("https://fixture.test/", BadStatusNoWarningFetcher(), DiscoveryConfig(max_pages=5, max_depth=1, allowed_hosts={"fixture.test"}))
    assert any(w.code == WarningCode.FETCH_FAILED and w.field == "https://fixture.test/bad.html" for w in data.warnings)
    assert data.admissions.application_periods


class RaisingTimeoutFetcher(MixedFailureFetcher):
    def fetch(self, url: str) -> FetchResult:
        if url.endswith("boom.html"):
            raise TimeoutError("simulated timeout")
        if url.endswith("/"):
            result = super().fetch(url)
            result.links.insert(0, "https://fixture.test/boom.html")
            return result
        return super().fetch(url)


def test_fetcher_exception_warns_and_scan_continues():
    data = run_scan("https://fixture.test/", RaisingTimeoutFetcher(), DiscoveryConfig(max_pages=5, max_depth=1, allowed_hosts={"fixture.test"}, retries=0))
    assert any(w.code == WarningCode.FETCH_FAILED and w.field == "https://fixture.test/boom.html" for w in data.warnings)
    assert data.admissions.application_periods[0].value.value == "31 January 2027"


class ParseFailureFetcher(MixedFailureFetcher):
    def fetch(self, url: str) -> FetchResult:
        if url.endswith("parse.html"):
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                title="Parse Failure",
                content_type="text/html",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
                warnings=[WarningRecord(WarningCode.PARSE_FAILED, "HTML parse warning", field=url)],
            )
        if url.endswith("/"):
            result = super().fetch(url)
            result.links.append("https://fixture.test/parse.html")
            return result
        return super().fetch(url)


def test_parse_failure_warning_is_preserved_and_scan_continues():
    data = run_scan("https://fixture.test/", ParseFailureFetcher(), DiscoveryConfig(max_pages=5, max_depth=1, allowed_hosts={"fixture.test"}))
    assert any(w.code == WarningCode.PARSE_FAILED for w in data.warnings)
    assert data.admissions.application_periods


class PDFPageFetcher(MixedFailureFetcher):
    def fetch(self, url: str) -> FetchResult:
        if url.endswith("prospectus.pdf"):
            from university_admissions_crawler.evidence.provenance import source_from_text

            source = source_from_text(source_url=url, title="Prospectus", source_type=SourceType.PDF, text="broken pdf", retrieved_at="2026-06-01T00:00:00+00:00", engine=self.engine)
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                title="Prospectus",
                content_type="application/pdf",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
                text="broken pdf",
                source=source,
            )
        if url.endswith("/"):
            result = super().fetch(url)
            result.links.append("https://fixture.test/prospectus.pdf")
            return result
        return super().fetch(url)


class FailingPDFExtractor:
    def extract(self, source, raw_text: str, max_pages: int = 10) -> PDFExtractionResult:
        return PDFExtractionResult([], [WarningRecord(WarningCode.PDF_PARSE_FAILED, "PDF parse failed", field=source.source_url, source_urls=[source.source_url])])


def test_pdf_parse_failure_warning_is_preserved_and_scan_continues():
    data = run_scan(
        "https://fixture.test/",
        PDFPageFetcher(),
        DiscoveryConfig(max_pages=5, max_depth=1, allowed_hosts={"fixture.test"}),
        pdf_extractor=FailingPDFExtractor(),
    )
    assert any(w.code == WarningCode.PDF_PARSE_FAILED for w in data.warnings)
    assert data.admissions.application_periods


class RaisingPDFExtractor:
    def extract(self, source, raw_text: str, max_pages: int = 10) -> PDFExtractionResult:
        raise ValueError("simulated parser failure")


def test_pdf_extractor_exception_warns_and_scan_continues():
    data = run_scan(
        "https://fixture.test/",
        PDFPageFetcher(),
        DiscoveryConfig(max_pages=5, max_depth=1, allowed_hosts={"fixture.test"}),
        pdf_extractor=RaisingPDFExtractor(),
    )
    assert any(w.code == WarningCode.PDF_PARSE_FAILED and w.field == "https://fixture.test/prospectus.pdf" for w in data.warnings)
    assert data.admissions.application_periods
