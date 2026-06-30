from pathlib import Path

from university_admissions_crawler.crawler.discovery import DiscoveryConfig, discover, normalize_url
from university_admissions_crawler.crawler.fetcher import FetchResult, FixtureFetcher
from university_admissions_crawler.crawler.filters import score_url
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import SourceType
from university_admissions_crawler.crawler.relevance import AdmissionsProgrammeRelevanceStrategy, BM25LikeRelevanceStrategy, RuleBasedRelevanceStrategy, keyword_plan_from_query, relevance_diagnostics


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


def test_default_relevance_strategy_uses_admissions_programme_profile():
    default_pages = discover("https://fixture.test/", FixtureFetcher(ROOT), DiscoveryConfig(max_pages=20, max_depth=2))
    assert isinstance(DiscoveryConfig().relevance_strategy, AdmissionsProgrammeRelevanceStrategy)
    assert all(page.score == DiscoveryConfig().relevance_strategy.score(page.result.final_url, page.result.title, page.result.markdown or page.result.text) for page in default_pages)


def test_explicit_rule_based_relevance_strategy_remains_available():
    explicit_pages = discover(
        "https://fixture.test/",
        FixtureFetcher(ROOT),
        DiscoveryConfig(max_pages=20, max_depth=2, relevance_strategy=RuleBasedRelevanceStrategy()),
    )
    assert explicit_pages
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

    pages = discover("https://admissions.example.edu/", fetcher, DiscoveryConfig(max_pages=10, max_depth=1))

    urls = [page.result.final_url for page in pages]
    assert "https://admissions.example.edu/" in urls
    assert "https://admissions.example.edu/apply/overview" in urls
    assert "https://admissions.example.edu/core/assets/base.css?t=x" not in fetcher.fetched
    assert "https://admissions.example.edu/sites/default/files/favicon.ico" not in fetcher.fetched
    assert "https://admissions.example.edu/files/GDPR%20Privacy%20Notice%20Applicants.pdf" not in fetcher.fetched


def test_discovery_keeps_admissions_pdf_counterexamples():
    fetcher = LinkedAssetFetcher()

    pages = discover("https://admissions.example.edu/", fetcher, DiscoveryConfig(max_pages=10, max_depth=1))

    urls = [page.result.final_url for page in pages]
    assert "https://admissions.example.edu/files/2026-undergraduate-admissions-prospectus.pdf" in urls
    assert "https://admissions.example.edu/files/international-entry-requirements.pdf" in urls
    assert "https://admissions.example.edu/files/undergraduate-tuition-fees.pdf" in urls


def test_discovery_prioritizes_programme_catalog_source_paths_under_page_limit():
    fetcher = ProgrammeCatalogPriorityFetcher()

    pages = discover(
        "https://example.edu/",
        fetcher,
        DiscoveryConfig(max_pages=4, max_depth=1, allowed_hosts={"example.edu"}),
    )

    urls = [page.result.final_url for page in pages]
    assert "https://example.edu/" in urls
    assert "https://example.edu/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education" in urls
    assert "https://example.edu/catalogue/undergraduate/majors" in urls
    assert "https://example.edu/news/alumni-programmes" not in urls
    assert "https://example.edu/summer/pre-university-programme" not in urls


def test_discovery_uses_global_priority_frontier_under_page_budget():
    fetcher = GlobalPriorityFetcher()

    pages = discover(
        "https://example.edu/",
        fetcher,
        DiscoveryConfig(max_pages=3, max_depth=2, allowed_hosts={"example.edu"}),
    )

    urls = [page.result.final_url for page in pages]
    assert urls == [
        "https://example.edu/",
        "https://example.edu/admissions",
        "https://example.edu/programmes",
    ]
    assert "https://example.edu/about" not in fetcher.fetched
    assert "https://example.edu/news" not in fetcher.fetched


def test_discovery_global_frontier_dedupes_url_seen_from_multiple_sources():
    fetcher = DuplicatePriorityFetcher()

    pages = discover(
        "https://example.edu/",
        fetcher,
        DiscoveryConfig(max_pages=5, max_depth=2, allowed_hosts={"example.edu"}),
    )

    urls = [page.result.final_url for page in pages]
    assert urls.count("https://example.edu/programmes") == 1
    assert fetcher.fetched.count("https://example.edu/programmes") == 1


def test_discovery_adds_sitemap_relevant_urls_to_priority_frontier():
    fetcher = SitemapDiscoveryFetcher()

    pages = discover(
        "https://example.edu/",
        fetcher,
        DiscoveryConfig(max_pages=2, max_depth=1, allowed_hosts={"example.edu"}),
    )

    urls = [page.result.final_url for page in pages]
    assert urls == [
        "https://example.edu/",
        "https://example.edu/programmes/computing",
    ]
    assert "https://example.edu/sitemap.xml" in fetcher.fetched
    assert "https://example.edu/privacy-notice.pdf" not in fetcher.fetched
    assert "https://external.example.com/admissions" not in fetcher.fetched


def test_discovery_uses_common_path_probe_as_low_priority_fallback():
    fetcher = PathProbeFallbackFetcher()

    pages = discover(
        "https://example.edu/",
        fetcher,
        DiscoveryConfig(max_pages=2, max_depth=1, allowed_hosts={"example.edu"}),
    )

    urls = [page.result.final_url for page in pages]
    assert urls == [
        "https://example.edu/",
        "https://example.edu/undergraduate-programmes",
    ]
    assert "https://example.edu/programmes" in fetcher.fetched
    assert "https://example.edu/programmes" not in urls


def test_discovery_extra_candidates_enter_priority_frontier():
    fetcher = ExtraCandidateFetcher()

    pages = discover(
        "https://example.edu/",
        fetcher,
        DiscoveryConfig(
            max_pages=2,
            max_depth=1,
            allowed_hosts={"example.edu"},
            extra_candidates=("https://example.edu/undergraduate-programmes",),
        ),
    )

    urls = [page.result.final_url for page in pages]
    assert urls == [
        "https://example.edu/",
        "https://example.edu/undergraduate-programmes",
    ]
    assert "https://example.edu/about" not in fetcher.fetched


def test_relevance_diagnostics_exposes_programme_source_path_hint():
    diagnostics = relevance_diagnostics(
        AdmissionsProgrammeRelevanceStrategy(),
        "https://example.edu/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education",
        "School of Computing Undergraduate Education",
        "Bachelor of Computing in Computer Science.",
    )

    assert diagnostics.strategy == "admissions_programme_profile"
    assert "programme_source_path_hint:/programmes" in diagnostics.signals
    assert "programme_source_path_hint:/undergraduate-education" in diagnostics.signals
    assert "profile_programme_catalog_source" in diagnostics.signals


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


class ProgrammeCatalogPriorityFetcher:
    engine = "fixture"

    def fetch(self, url: str) -> FetchResult:
        if url == "https://example.edu/":
            text = "University home"
            links = [
                "https://example.edu/news/alumni-programmes",
                "https://example.edu/summer/pre-university-programme",
                "https://example.edu/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education",
                "https://example.edu/catalogue/undergraduate/majors",
                "https://example.edu/admissions",
            ]
        else:
            text = "Undergraduate degree programmes and majors"
            links = []
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title="Programmes",
            content_type="text/html",
            retrieved_at="2026-06-15T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=text,
            links=links,
            source=source_from_text(source_url=url, title="Programmes", source_type=SourceType.HTML, text=text),
        )


class GlobalPriorityFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://example.edu/":
            text = "University home"
            links = [
                "https://example.edu/about",
                "https://example.edu/news",
                "https://example.edu/admissions",
            ]
        elif url == "https://example.edu/admissions":
            text = "Undergraduate admissions application requirements"
            links = ["https://example.edu/programmes"]
        elif url == "https://example.edu/programmes":
            text = "Undergraduate degree programmes and majors"
            links = []
        else:
            text = "Corporate news and alumni updates"
            links = []
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title="Test Page",
            content_type="text/html",
            retrieved_at="2026-06-15T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=text,
            links=links,
            source=source_from_text(source_url=url, title="Test Page", source_type=SourceType.HTML, text=text),
        )


class DuplicatePriorityFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://example.edu/":
            text = "University home"
            links = [
                "https://example.edu/admissions",
                "https://example.edu/programmes",
            ]
        elif url == "https://example.edu/admissions":
            text = "Undergraduate admissions"
            links = ["https://example.edu/programmes"]
        else:
            text = "Undergraduate degree programmes and majors"
            links = []
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title="Test Page",
            content_type="text/html",
            retrieved_at="2026-06-15T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=text,
            links=links,
            source=source_from_text(source_url=url, title="Test Page", source_type=SourceType.HTML, text=text),
        )


class SitemapDiscoveryFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://example.edu/":
            return _fetch_result(url, text="University home", links=["https://example.edu/about"])
        if url == "https://example.edu/sitemap.xml":
            text = """
            <urlset>
              <url><loc>https://example.edu/news</loc></url>
              <url><loc>https://example.edu/programmes/computing</loc></url>
              <url><loc>https://example.edu/privacy-notice.pdf</loc></url>
              <url><loc>https://external.example.com/admissions</loc></url>
            </urlset>
            """
            return _fetch_result(url, text=text, title="Sitemap", source_type=SourceType.OTHER, content_type="application/xml")
        if url == "https://example.edu/sitemap_index.xml":
            return _fetch_result(url, status=404, text="not found")
        if url == "https://example.edu/programmes/computing":
            return _fetch_result(url, text="Undergraduate degree programmes Bachelor of Computing", title="Programmes")
        return _fetch_result(url, text="About the university", title="About")


class PathProbeFallbackFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://example.edu/":
            return _fetch_result(url, text="University home", links=[])
        if url == "https://example.edu/undergraduate-programmes":
            return _fetch_result(url, text="Undergraduate degree programmes Bachelor of Science", title="Undergraduate Programmes")
        return _fetch_result(url, status=404, text="not found")


class ExtraCandidateFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://example.edu/":
            return _fetch_result(url, text="University home", links=["https://example.edu/about"])
        if url == "https://example.edu/undergraduate-programmes":
            return _fetch_result(url, text="Undergraduate degree programmes Bachelor of Science", title="Undergraduate Programmes")
        return _fetch_result(url, text="About the university", title="About")


def _fetch_result(
    url: str,
    *,
    status: int = 200,
    text: str,
    title: str = "Test Page",
    links: list[str] | None = None,
    source_type: SourceType = SourceType.HTML,
    content_type: str = "text/html",
) -> FetchResult:
    source = source_from_text(source_url=url, title=title, source_type=source_type, text=text)
    return FetchResult(
        url=url,
        final_url=url,
        status=status,
        title=title,
        content_type=content_type,
        retrieved_at="2026-06-15T00:00:00+00:00",
        engine="fixture",
        text=text,
        markdown=text,
        links=links or [],
        source=source if 200 <= status < 400 else None,
    )
