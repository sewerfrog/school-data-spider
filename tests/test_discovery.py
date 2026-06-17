from pathlib import Path

from university_admissions_crawler.crawler.discovery import DiscoveryConfig, discover, normalize_url
from university_admissions_crawler.crawler.fetcher import FetchResult, FixtureFetcher
from university_admissions_crawler.crawler.filters import score_url
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import SourceType
from university_admissions_crawler.crawler.relevance import BM25LikeRelevanceStrategy, RuleBasedRelevanceStrategy, keyword_plan_from_query, relevance_diagnostics


ROOT = Path("tests/fixtures/mini_university_site")


def test_discovery_respects_max_pages():
    pages = discover("https://fixture.test/", FixtureFetcher(ROOT), DiscoveryConfig(max_pages=2, max_depth=3))
    assert len(pages) == 2


def test_discovery_respects_max_depth():
    pages = discover("https://fixture.test/", FixtureFetcher(ROOT), DiscoveryConfig(max_pages=20, max_depth=0))
    assert [page.result.final_url for page in pages] == ["https://fixture.test/"]


def test_discovery_normalizes_and_dedupes_tracking_links():
    pages = discover("https://fixture.test/", FixtureFetcher(ROOT), DiscoveryConfig(max_pages=20, max_depth=2))
    urls = [page.result.final_url for page in pages]
    assert "https://fixture.test/admissions/deadlines.html" in urls
    assert len(urls) == len(set(urls))
    assert normalize_url("https://fixture.test/a/?utm_source=x#frag") == "https://fixture.test/a"


def test_discovery_rejects_external_host():
    pages = discover("https://fixture.test/", FixtureFetcher(ROOT), DiscoveryConfig(max_pages=50, max_depth=2, allowed_hosts={"fixture.test"}))
    assert all("example.com" not in page.result.final_url for page in pages)


def test_discovery_allows_official_subdomain_discovered_from_seed_domain():
    pages = discover("https://fixture.test/", FixtureFetcher(ROOT), DiscoveryConfig(max_pages=50, max_depth=1))
    assert any(page.result.final_url == "https://apply.fixture.test/apply.html" for page in pages)


def test_explicit_default_relevance_strategy_preserves_discovery_results():
    default_pages = discover("https://fixture.test/", FixtureFetcher(ROOT), DiscoveryConfig(max_pages=20, max_depth=2))
    explicit_pages = discover(
        "https://fixture.test/",
        FixtureFetcher(ROOT),
        DiscoveryConfig(max_pages=20, max_depth=2, relevance_strategy=RuleBasedRelevanceStrategy()),
    )
    assert [page.result.final_url for page in explicit_pages] == [page.result.final_url for page in default_pages]
    assert [page.score for page in explicit_pages] == [page.score for page in default_pages]
    assert explicit_pages[0].score == score_url(
        explicit_pages[0].result.final_url,
        explicit_pages[0].result.title,
        explicit_pages[0].result.markdown or explicit_pages[0].result.text,
    )


def test_bm25_like_relevance_strategy_is_opt_in_and_uses_keyword_plan():
    keyword_plan = keyword_plan_from_query("fees tuition international")
    strategy = BM25LikeRelevanceStrategy(keyword_plan)
    baseline_score = score_url("https://fixture.test/fees.html", "Tuition Fees", "Tuition fees for international undergraduate students.")
    opt_in_score = strategy.score("https://fixture.test/fees.html", "Tuition Fees", "Tuition fees for international undergraduate students.")
    diagnostics = relevance_diagnostics(strategy, "https://fixture.test/fees.html", "Tuition Fees", "Tuition fees for international undergraduate students.", score=opt_in_score)

    assert opt_in_score > baseline_score
    assert diagnostics.strategy == "bm25_like"
    assert "keyword_plan_positive:fees" in diagnostics.signals
    assert "keyword_plan_url_hint:/fees" in diagnostics.signals


def test_discovery_filters_static_assets_and_privacy_pdfs_before_fetching():
    fetcher = LinkedAssetFetcher()
    keyword_plan = keyword_plan_from_query("admissions css privacy")
    strategy = BM25LikeRelevanceStrategy(keyword_plan)

    pages = discover("https://admissions.example.edu/", fetcher, DiscoveryConfig(max_pages=10, max_depth=1, relevance_strategy=strategy))

    urls = [page.result.final_url for page in pages]
    assert "https://admissions.example.edu/" in urls
    assert "https://admissions.example.edu/apply/overview" in urls
    assert "https://admissions.example.edu/core/assets/base.css?t=x" not in fetcher.fetched
    assert "https://admissions.example.edu/sites/default/files/favicon.ico" not in fetcher.fetched
    assert "https://admissions.example.edu/files/GDPR%20Privacy%20Notice%20Applicants.pdf" not in fetcher.fetched


def test_discovery_keeps_admissions_pdf_counterexamples():
    fetcher = LinkedAssetFetcher()
    keyword_plan = keyword_plan_from_query("admissions prospectus requirements fees")
    strategy = BM25LikeRelevanceStrategy(keyword_plan)

    pages = discover("https://admissions.example.edu/", fetcher, DiscoveryConfig(max_pages=10, max_depth=1, relevance_strategy=strategy))

    urls = [page.result.final_url for page in pages]
    assert "https://admissions.example.edu/files/2026-undergraduate-admissions-prospectus.pdf" in urls
    assert "https://admissions.example.edu/files/international-entry-requirements.pdf" in urls
    assert "https://admissions.example.edu/files/undergraduate-tuition-fees.pdf" in urls


class LinkedAssetFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://admissions.example.edu/":
            text = "Undergraduate admissions"
            links = [
                "https://admissions.example.edu/core/assets/base.css?t=x",
                "https://admissions.example.edu/sites/default/files/favicon.ico",
                "https://admissions.example.edu/files/GDPR%20Privacy%20Notice%20Applicants.pdf",
                "https://admissions.example.edu/apply/overview",
                "https://admissions.example.edu/files/2026-undergraduate-admissions-prospectus.pdf",
                "https://admissions.example.edu/files/international-entry-requirements.pdf",
                "https://admissions.example.edu/files/undergraduate-tuition-fees.pdf",
            ]
        else:
            text = "Application overview"
            links = []
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title="Admissions",
            content_type="text/html",
            retrieved_at="2026-06-15T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=text,
            links=links,
            source=source_from_text(source_url=url, title="Admissions", source_type=SourceType.HTML, text=text),
        )
