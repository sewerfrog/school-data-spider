from pathlib import Path

from university_admissions_crawler.crawler.discovery import DiscoveryConfig, discover, normalize_url
from university_admissions_crawler.crawler.fetcher import FixtureFetcher
from university_admissions_crawler.crawler.filters import score_url
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
