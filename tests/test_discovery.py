from pathlib import Path

from university_admissions_crawler.crawler.discovery import DiscoveryConfig, discover, normalize_url
from university_admissions_crawler.crawler.fetcher import FetchResult, FixtureFetcher
from university_admissions_crawler.crawler.filters import score_url
from university_admissions_crawler.crawler.programme_sources import (
    classify_programme_source_role,
    institution_profile_programme_urls,
    is_explicit_programme_detail_source,
)
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


def test_discovery_marks_redirected_external_final_url_non_official():
    class RedirectFetcher:
        engine = "fixture"

        def fetch(self, url: str) -> FetchResult:
            text = "Undergraduate admissions"
            final_url = "https://mirror.example.com/admissions"
            return FetchResult(
                url=url,
                final_url=final_url,
                status=200,
                title="Admissions",
                content_type="text/html",
                retrieved_at="2026-06-15T00:00:00+00:00",
                engine=self.engine,
                text=text,
                markdown=text,
                source=source_from_text(source_url=final_url, title="Admissions", text=text),
            )

    pages = discover("https://example.edu/", RedirectFetcher(), DiscoveryConfig(max_pages=1, max_depth=0))

    assert pages[0].result.source.is_official is False


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


def test_programme_source_roles_keep_current_bulletin_and_old_cohort_distinct():
    current = classify_programme_source_role(
        "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education",
        "NUS Bulletin AY2025/26 - School of Computing Undergraduate Education",
        "Undergraduate Programmes\nProgramme | Degree\nComputer Science | Bachelor of Computing",
    )
    old_cohort = classify_programme_source_role(
        "https://www.ntu.edu.sg/computing/admissions/undergraduate-programmes/minorprogrammes/minor-in-computing/ay2020-21-and-earlier-cohorts",
        "Minor in Computing | AY2020-21 and Earlier Cohorts",
    )

    assert current.role == "faculty_catalog"
    assert old_cohort.role == "curriculum_or_old_cohort"


def test_programme_source_role_does_not_promote_generic_catalog_descendants():
    catalog = classify_programme_source_role(
        "https://example.edu/hass/admissions/programmes",
        "Undergraduate Programmes",
    )
    internship = classify_programme_source_role(
        "https://example.edu/hass/admissions/programmes/internships",
        "Internships",
    )
    postgraduate = classify_programme_source_role(
        "https://example.edu/centre/programmes/postgraduate-programmes/instructors",
        "Instructors",
    )
    structured_descendant = classify_programme_source_role(
        "https://example.edu/hass/admissions/programmes/overview",
        "Programme Overview",
        "Programme | Degree\nHistory | Bachelor of Arts",
    )
    undergraduate_index = classify_programme_source_role(
        "https://example.edu/programmes/undergraduate",
        "Undergraduate Programmes",
    )

    assert catalog.role == "faculty_catalog"
    assert undergraduate_index.role == "faculty_catalog"
    assert internship.role == "unrelated"
    assert postgraduate.role == "unrelated"
    assert structured_descendant.role == "faculty_catalog"


def test_singular_undergraduate_programme_path_is_a_bounded_detail_source():
    detail = classify_programme_source_role(
        "https://example.edu/education/undergraduate-programme/bachelor-of-accountancy",
        "Bachelor of Accountancy",
    )

    assert detail.role == "programme_detail"
    assert detail.source_family == "example.edu/education/undergraduate-programme"


def test_explicit_programme_detail_gate_excludes_generic_descendant_pages():
    detail_url = "https://example.edu/engineering/undergraduate-programmes/detail/bachelor-of-engineering-in-robotics"
    activity_url = "https://example.edu/engineering/undergraduate-programmes/student-activities"

    assert is_explicit_programme_detail_source(detail_url, "Bachelor of Engineering in Robotics")
    assert not is_explicit_programme_detail_source(activity_url, "Student Activities")
    assert classify_programme_source_role(activity_url, "Student Activities").role == "programme_detail"


def test_ntu_profile_candidate_is_domain_scoped_and_canonical_first():
    fetcher = NtuCanonicalFirstFetcher()
    config = DiscoveryConfig(max_pages=2, max_depth=1, allowed_hosts={"www.ntu.edu.sg"})

    pages = discover("https://www.ntu.edu.sg/admissions/undergraduate", fetcher, config)

    assert [page.result.final_url for page in pages] == [
        "https://www.ntu.edu.sg/admissions/undergraduate",
        "https://www.ntu.edu.sg/education/degree-programmes",
    ]
    assert pages[1].source_role == "canonical_catalog"
    assert "https://www.ntu.edu.sg/hass/admissions/programmes/undergraduate-programmes/detail/programme-1" not in fetcher.fetched
    assert institution_profile_programme_urls("https://www.nus.edu.sg/admissions") == ()


def test_discovery_limits_bounded_programme_detail_source_family():
    fetcher = SourceFamilyBudgetFetcher()
    config = DiscoveryConfig(
        max_pages=10,
        max_depth=1,
        allowed_hosts={"example.edu"},
        programme_source_family_budget=2,
    )

    pages = discover("https://example.edu/", fetcher, config)

    detail_pages = [page for page in pages if page.source_role == "programme_detail"]
    skipped = [
        item
        for item in config.frontier_diagnostics
        if item.get("reason") == "programme_source_family_budget_exhausted"
    ]
    assert len(detail_pages) == 2
    assert len(skipped) == 3
    assert {item["source_family"] for item in skipped} == {"example.edu/hass/undergraduate-programmes"}
    assert {item["family_budget"] for item in skipped} == {2}
    assert {item["family_budget_policy"] for item in skipped} == {"default"}


def test_discovery_scopes_lower_detail_budget_to_faculty_catalog_and_unbacked_families():
    fetcher = FacultyCatalogScopedBudgetFetcher()
    config = DiscoveryConfig(
        max_pages=10,
        max_depth=1,
        allowed_hosts={"example.edu"},
        programme_source_family_budget=2,
        programme_detail_faculty_catalog_family_budget=1,
        programme_detail_unbacked_family_budget=1,
    )

    pages = discover("https://example.edu/", fetcher, config)

    faculty_details = [
        page
        for page in pages
        if page.source_role == "programme_detail"
        and page.source_family == "example.edu/hass/programmes"
    ]
    other_details = [
        page
        for page in pages
        if page.source_role == "programme_detail"
        and page.source_family == "example.edu/education/undergraduate-programme"
    ]
    skipped = [
        item
        for item in config.frontier_diagnostics
        if item.get("reason") == "programme_source_family_budget_exhausted"
    ]
    faculty_skipped = [item for item in skipped if item["source_family"] == "example.edu/hass/programmes"]
    other_skipped = [
        item
        for item in skipped
        if item["source_family"] == "example.edu/education/undergraduate-programme"
    ]
    assert len(faculty_details) == 1
    assert len(other_details) == 1
    assert len(faculty_skipped) == 2
    assert {item["family_budget"] for item in faculty_skipped} == {1}
    assert {item["family_budget_policy"] for item in faculty_skipped} == {
        "faculty_catalog_backed_detail"
    }
    assert len(other_skipped) == 2
    assert {item["family_budget"] for item in other_skipped} == {1}
    assert {item["family_budget_policy"] for item in other_skipped} == {
        "catalog_unbacked_detail"
    }


def test_discovery_can_capture_unfetched_programme_details_for_targeted_second_phase():
    fetcher = SourceFamilyBudgetFetcher()
    config = DiscoveryConfig(
        max_pages=2,
        max_depth=1,
        allowed_hosts={"example.edu"},
        programme_source_family_budget=5,
        capture_pending_frontier=True,
    )

    pages = discover("https://example.edu/", fetcher, config)

    pending = [item for item in config.frontier_diagnostics if item.get("decision") == "pending"]
    assert len(pages) == 2
    assert len(pending) == 4
    assert all(item["reason"] == "page_budget_reserved" for item in pending)
    assert all(item["queued_source_role"] == "programme_detail" for item in pending)
    assert all(isinstance(item["depth"], int) for item in pending)
    assert all(isinstance(item["score"], int) for item in pending)
    assert all(isinstance(item["order"], int) for item in pending)
    assert all(item["source_url"] == "https://example.edu/" for item in pending)


def test_canonical_detail_links_are_not_starved_by_generic_programme_descendants():
    fetcher = CanonicalDetailPriorityFetcher()
    config = DiscoveryConfig(
        max_pages=4,
        max_depth=2,
        allowed_hosts={"www.ntu.edu.sg"},
        programme_source_family_budget=2,
        programme_detail_faculty_catalog_family_budget=1,
        programme_detail_unbacked_family_budget=1,
    )

    pages = discover("https://www.ntu.edu.sg/admissions/undergraduate", fetcher, config)

    assert [page.result.final_url for page in pages] == [
        "https://www.ntu.edu.sg/admissions/undergraduate",
        "https://www.ntu.edu.sg/education/degree-programmes",
        "https://www.ntu.edu.sg/education/undergraduate-programme/bachelor-of-accountancy",
        "https://www.ntu.edu.sg/education/undergraduate-programme/bachelor-of-business",
    ]
    assert not any("/scholarships/" in url for url in fetcher.fetched)
    detail_entries = [
        item
        for item in config.frontier_diagnostics
        if item.get("decision") == "fetched"
        and "/education/undergraduate-programme/" in str(item.get("url"))
    ]
    assert len(detail_entries) == 2
    assert all(item["queued_source_role"] == "programme_detail" for item in detail_entries)
    assert all("canonical_catalog_detail_link" in item["queued_reason_signals"] for item in detail_entries)


def test_canonical_detail_budget_survives_candidate_frontier_deduplication():
    fetcher = CanonicalAlreadyQueuedDetailFetcher()
    config = DiscoveryConfig(
        max_pages=4,
        max_depth=2,
        allowed_hosts={"example.edu"},
        programme_source_family_budget=2,
        programme_detail_faculty_catalog_family_budget=1,
        programme_detail_unbacked_family_budget=1,
    )

    pages = discover("https://example.edu/", fetcher, config)

    detail_pages = [page for page in pages if page.source_role == "programme_detail"]
    assert len(detail_pages) == 2
    assert {page.result.final_url for page in detail_pages} == {
        "https://example.edu/education/undergraduate-programme/accountancy",
        "https://example.edu/education/undergraduate-programme/business",
    }


def test_related_compound_detail_uses_remaining_family_budget_before_plain_sibling():
    fetcher = RelatedCompoundDetailPriorityFetcher()
    config = DiscoveryConfig(
        max_pages=4,
        max_depth=3,
        allowed_hosts={"example.edu"},
        programme_source_family_budget=2,
        relevance_strategy=RelatedCompoundDetailTestRelevanceStrategy(),
    )

    pages = discover("https://example.edu/", fetcher, config)

    assert [page.result.final_url for page in pages] == [
        "https://example.edu/",
        "https://example.edu/hass/admissions/programmes",
        "https://example.edu/hass/admissions/programmes/detail/bachelor-of-arts-in-english",
        "https://example.edu/hass/admissions/programmes/detail/double-major-in-history-and-philosophy",
    ]
    assert "https://example.edu/hass/admissions/programmes/detail/bachelor-of-arts-in-history" not in fetcher.fetched
    compound_entry = next(
        item
        for item in config.frontier_diagnostics
        if item.get("url", "").endswith("/double-major-in-history-and-philosophy")
    )
    assert "related_compound_programme_detail_link" in compound_entry["queued_reason_signals"]


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


class NtuCanonicalFirstFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://www.ntu.edu.sg/admissions/undergraduate":
            return _fetch_result(
                url,
                text="Undergraduate admissions",
                title="Undergraduate Admissions | NTU Singapore",
                links=[
                    f"https://www.ntu.edu.sg/hass/admissions/programmes/undergraduate-programmes/detail/programme-{index}"
                    for index in range(1, 6)
                ],
            )
        if url == "https://www.ntu.edu.sg/education/degree-programmes":
            return _fetch_result(
                url,
                text="Programme | Degree Title\nComputer Science | Bachelor of Computing in Computer Science",
                title="Degree Programmes | NTU Singapore",
            )
        return _fetch_result(url, status=404, text="not found")


class SourceFamilyBudgetFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://example.edu/":
            return _fetch_result(
                url,
                text="University home",
                links=[
                    *[
                        f"https://example.edu/hass/undergraduate-programmes/detail/programme-{index}"
                        for index in range(1, 6)
                    ],
                    "https://example.edu/admissions",
                ],
            )
        if "/detail/" in url:
            return _fetch_result(url, text="Bachelor of Arts in Example Studies", title="Bachelor of Arts in Example Studies")
        if url == "https://example.edu/admissions":
            return _fetch_result(url, text="Undergraduate admissions", title="Admissions")
        return _fetch_result(url, status=404, text="not found")


class FacultyCatalogScopedBudgetFetcher:
    engine = "fixture"

    def fetch(self, url: str) -> FetchResult:
        if url == "https://example.edu/":
            return _fetch_result(
                url,
                text="University home",
                links=[
                    "https://example.edu/hass/programmes",
                    *[
                        f"https://example.edu/hass/programmes/detail/faculty-{index}"
                        for index in range(1, 4)
                    ],
                    *[
                        "https://example.edu/education/undergraduate-programme/"
                        f"general-{index}"
                        for index in range(1, 4)
                    ],
                ],
            )
        if url == "https://example.edu/hass/programmes":
            return _fetch_result(
                url,
                text="Programme | Degree Title\nEnglish | Bachelor of Arts in English",
                title="Undergraduate Programmes | School of Humanities",
            )
        if "/detail/" in url or "/undergraduate-programme/" in url:
            return _fetch_result(
                url,
                text="Bachelor of Arts in Example Studies",
                title="Bachelor of Arts in Example Studies",
            )
        return _fetch_result(url, status=404, text="not found")


class CanonicalDetailPriorityFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url == "https://www.ntu.edu.sg/admissions/undergraduate":
            return _fetch_result(
                url,
                text="Undergraduate admissions",
                title="Undergraduate Admissions | NTU Singapore",
                links=[
                    f"https://www.ntu.edu.sg/admissions/undergraduate/scholarships/noise-{index}"
                    for index in range(1, 6)
                ],
            )
        if url == "https://www.ntu.edu.sg/education/degree-programmes":
            return _fetch_result(
                url,
                text=(
                    "Programme | Degree Title\n"
                    "Accountancy | Bachelor of Accountancy\n"
                    "Business | Bachelor of Business"
                ),
                title="Degree Programmes | NTU Singapore",
                links=[
                    "https://www.ntu.edu.sg/education/undergraduate-programme/bachelor-of-accountancy",
                    "https://www.ntu.edu.sg/education/undergraduate-programme/bachelor-of-business",
                ],
            )
        if "/education/undergraduate-programme/" in url:
            return _fetch_result(
                url,
                text="Bachelor programme | Nanyang Business School",
                title="Bachelor Programme | Nanyang Business School | NTU Singapore",
            )
        return _fetch_result(url, text="Undergraduate scholarship", title="Undergraduate Scholarship")


class CanonicalAlreadyQueuedDetailFetcher:
    engine = "fixture"

    def fetch(self, url: str) -> FetchResult:
        accountancy_url = "https://example.edu/education/undergraduate-programme/accountancy"
        business_url = "https://example.edu/education/undergraduate-programme/business"
        if url == "https://example.edu/":
            return _fetch_result(
                url,
                text="University home",
                links=[accountancy_url, "https://example.edu/degree-programmes"],
            )
        if url == "https://example.edu/degree-programmes":
            return _fetch_result(
                url,
                text="Programme | Degree Title\nAccountancy | Bachelor of Accountancy",
                title="Degree Programmes",
                links=[accountancy_url, business_url],
            )
        if url in {accountancy_url, business_url}:
            return _fetch_result(url, text="Bachelor programme", title="Bachelor Programme")
        return _fetch_result(url, status=404, text="not found")


class RelatedCompoundDetailTestRelevanceStrategy:
    name = "related_compound_detail_test"

    def score(self, url: str, title: str | None = None, text: str | None = None) -> int:
        if url.endswith("/bachelor-of-arts-in-english"):
            return 10
        if url.endswith("/bachelor-of-arts-in-history"):
            return 9
        return 0

    def should_follow(self, url: str, policy) -> bool:
        return policy.is_allowed(url)


class RelatedCompoundDetailPriorityFetcher:
    engine = "fixture"

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        catalog_url = "https://example.edu/hass/admissions/programmes"
        english_url = f"{catalog_url}/detail/bachelor-of-arts-in-english"
        history_url = f"{catalog_url}/detail/bachelor-of-arts-in-history"
        compound_url = f"{catalog_url}/detail/double-major-in-history-and-philosophy"
        if url == "https://example.edu/":
            return _fetch_result(url, text="University home", links=[catalog_url])
        if url == catalog_url:
            return _fetch_result(
                url,
                text="Undergraduate Programmes\nBachelor of Arts in English\nBachelor of Arts in History",
                title="Undergraduate Programmes",
                links=[english_url, history_url],
            )
        if url == english_url:
            return _fetch_result(
                url,
                text="Bachelor of Arts in English",
                title="Bachelor of Arts in English",
                links=[compound_url],
            )
        return _fetch_result(url, text="Bachelor programme", title="Bachelor Programme")


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
