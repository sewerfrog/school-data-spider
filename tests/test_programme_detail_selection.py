from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    Institution,
    ProgrammeCatalogRecord,
    RunMetadata,
)
from university_admissions_crawler.pipeline.programme_detail_selection import (
    select_targeted_programme_detail_candidates,
    targeted_programme_detail_family_reserve,
)


def test_targeted_detail_family_reserve_preserves_the_total_family_cap():
    assert [
        targeted_programme_detail_family_reserve(reserve, family_budget=4)
        for reserve in range(5)
    ] == [0, 1, 2, 2, 3]
    assert targeted_programme_detail_family_reserve(reserve_limit=4, family_budget=2) == 2


def test_targeted_detail_selection_matches_unresolved_rows_and_rejects_orphan_family():
    canonical_url = "https://www.ntu.edu.sg/education/degree-programmes"
    hass_catalog_url = "https://www.ntu.edu.sg/hass/admissions/programmes"
    chinese_detail_url = (
        "https://www.ntu.edu.sg/hass/admissions/programmes/undergraduate-programmes/detail/"
        "bachelor-of-arts-(hons)-in-double-major---chinese-and-english"
    )
    orphan_detail_url = chinese_detail_url.replace("/hass/", "/spms/")
    robotics_primary_url = (
        "https://www.ntu.edu.sg/education/undergraduate-programme/"
        "bachelor-of-engineering-in-robotics"
    )
    data = AdmissionsData(
        institution=Institution(homepage_url="https://www.ntu.edu.sg/"),
        run=RunMetadata(
            input_url="https://www.ntu.edu.sg/",
            config={
                "source_strategy": [
                    {"url": canonical_url, "source_role": "canonical_catalog"},
                    {"url": hass_catalog_url, "source_role": "faculty_catalog"},
                ],
                "programme_catalog_row_provenance": {
                    "/programme_catalog/0/name": {"primary_source_urls": []},
                    "/programme_catalog/1/name": {"primary_source_urls": [robotics_primary_url]},
                    "/programme_catalog/2/name": {"primary_source_urls": []},
                },
            },
        ),
        sources=[
            source_from_text(source_url=canonical_url, title="Degree Programmes", text="Programme | Degree"),
            source_from_text(source_url=hass_catalog_url, title="HASS Programmes", text="Undergraduate Programmes"),
        ],
        programme_catalog=[
            _row("Chinese and English", 0),
            _row("Robotics", 1),
            _row("Business", 2, faculty="Nanyang Business School"),
        ],
    )
    entries = [
        _frontier_entry(
            chinese_detail_url,
            family="www.ntu.edu.sg/hass/admissions",
            decision="pending",
            score=40,
        ),
        _frontier_entry(
            orphan_detail_url,
            family="www.ntu.edu.sg/spms/admissions",
            decision="pending",
            score=90,
        ),
        _frontier_entry(
            robotics_primary_url,
            family="www.ntu.edu.sg/education/undergraduate-programme",
            decision="skipped",
            score=20,
        ),
        _frontier_entry(
            "https://www.ntu.edu.sg/business/admissions/detail/bachelor-of-business",
            family="www.ntu.edu.sg/business/admissions",
            decision="pending",
            score=100,
        ),
    ]

    selected = select_targeted_programme_detail_candidates(data, entries, limit=2, family_budget=4)

    assert [item.url for item in selected] == [chinese_detail_url, robotics_primary_url]
    assert [item.row_name for item in selected] == ["Chinese and English", "Robotics"]
    diagnostics = data.run.config["programme_catalog_targeted_detail_selection"]
    assert diagnostics["selected_count"] == 2
    assert diagnostics["rejection_reason_counts"] == {
        "detail_source_family_without_catalog_context": 1,
        "no_unresolved_row_match": 1,
    }
    assert diagnostics["ranking_policy"] == (
        "faculty_catalog_backing_then_catalog_row_order_with_one_exploration"
    )
    assert diagnostics["relevance_score_role"] == "diagnostic_only"
    assert diagnostics["exploration_quota"] == 1
    assert diagnostics["candidate_tier_counts"] == {
        "catalog_backed_exploration": 1,
        "faculty_catalog_backed": 1,
    }
    assert diagnostics["selected_tier_counts"] == diagnostics["candidate_tier_counts"]
    assert diagnostics["selected"][0]["backing_catalog_roles"] == ["faculty_catalog"]
    assert diagnostics["selected"][1]["backing_catalog_roles"] == ["canonical_catalog"]


def test_targeted_detail_selection_uses_catalog_row_order_instead_of_keyword_score():
    catalog_url = "https://example.edu/degree-programmes"
    alpha_url = "https://example.edu/degree-programmes/detail/bachelor-of-arts-in-alpha-studies"
    english_url = "https://example.edu/degree-programmes/detail/bachelor-of-arts-in-english-studies"
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu/"),
        run=RunMetadata(
            input_url="https://example.edu/",
            config={
                "source_strategy": [{"url": catalog_url, "source_role": "canonical_catalog"}],
                "programme_catalog_row_provenance": {
                    "/programme_catalog/0/name": {"primary_source_urls": []},
                    "/programme_catalog/1/name": {"primary_source_urls": []},
                },
            },
        ),
        programme_catalog=[
            _row("Alpha Studies", 0),
            _row("English Studies", 1),
        ],
    )
    entries = [
        _frontier_entry(
            english_url,
            family="example.edu/degree-programmes",
            decision="pending",
            score=100,
        ),
        _frontier_entry(
            alpha_url,
            family="example.edu/degree-programmes",
            decision="pending",
            score=10,
        ),
    ]

    selected = select_targeted_programme_detail_candidates(data, entries, limit=1, family_budget=4)

    assert [item.row_name for item in selected] == ["Alpha Studies"]
    diagnostics = data.run.config["programme_catalog_targeted_detail_selection"]
    assert diagnostics["eligible_row_count"] == 2
    assert diagnostics["selected"][0]["score"] == 10
    assert diagnostics["exploration_quota"] == 0


def test_targeted_detail_selection_uses_faculty_backing_with_one_exploration_slot():
    canonical_url = "https://example.edu/degree-programmes"
    faculty_catalog_url = "https://example.edu/arts/programmes"
    canonical_alpha_url = "https://example.edu/undergraduate-programme/bachelor-of-arts-in-alpha"
    canonical_beta_url = "https://example.edu/undergraduate-programme/bachelor-of-arts-in-beta"
    faculty_urls = [
        f"{faculty_catalog_url}/detail/bachelor-of-arts-in-faculty-{suffix}"
        for suffix in ("one", "two", "three")
    ]
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu/"),
        run=RunMetadata(
            input_url="https://example.edu/",
            config={
                "source_strategy": [
                    {"url": canonical_url, "source_role": "canonical_catalog"},
                    {"url": faculty_catalog_url, "source_role": "faculty_catalog"},
                ],
                "programme_catalog_row_provenance": {
                    "/programme_catalog/0/name": {"primary_source_urls": [canonical_alpha_url]},
                    "/programme_catalog/1/name": {"primary_source_urls": []},
                    "/programme_catalog/2/name": {"primary_source_urls": []},
                    "/programme_catalog/3/name": {"primary_source_urls": []},
                    "/programme_catalog/4/name": {"primary_source_urls": [canonical_beta_url]},
                },
            },
        ),
        programme_catalog=[
            _row("Alpha", 0),
            _row("Faculty One", 1),
            _row("Faculty Two", 2),
            _row("Faculty Three", 3),
            _row("Beta", 4),
        ],
    )
    entries = [
        _frontier_entry(
            f"{faculty_catalog_url}/detail/discovery-page",
            family="example.edu/arts/programmes",
            decision="fetched",
            score=200,
        ),
        _frontier_entry(
            canonical_beta_url,
            family="example.edu/undergraduate-programme",
            decision="pending",
            score=100,
        ),
        *[
            _frontier_entry(
                url,
                family="example.edu/arts/programmes",
                decision="skipped",
                score=20 + index,
            )
            for index, url in enumerate(faculty_urls)
        ],
        _frontier_entry(
            canonical_alpha_url,
            family="example.edu/undergraduate-programme",
            decision="pending",
            score=10,
        ),
    ]

    selected = select_targeted_programme_detail_candidates(data, entries, limit=4, family_budget=4)

    assert [item.row_name for item in selected] == [
        "Faculty One",
        "Faculty Two",
        "Faculty Three",
        "Alpha",
    ]
    assert [item.selection_tier for item in selected] == [
        "faculty_catalog_backed",
        "faculty_catalog_backed",
        "faculty_catalog_backed",
        "catalog_backed_exploration",
    ]
    diagnostics = data.run.config["programme_catalog_targeted_detail_selection"]
    assert diagnostics["exploration_quota"] == 1
    assert diagnostics["selected_tier_counts"] == {
        "catalog_backed_exploration": 1,
        "faculty_catalog_backed": 3,
    }
    assert 1 + diagnostics["selected_tier_counts"]["faculty_catalog_backed"] == 4


def _row(name: str, index: int, *, faculty: str | None = None) -> ProgrammeCatalogRecord:
    return ProgrammeCatalogRecord(
        name=name,
        faculty_or_school=faculty,
        category="degree_programme",
        source_url="https://www.ntu.edu.sg/education/degree-programmes",
        evidence_snippet=name,
        evidence_path=f"/programme_catalog/{index}/name",
    )


def _frontier_entry(
    url: str,
    *,
    family: str,
    decision: str,
    score: int,
) -> dict[str, object]:
    return {
        "url": url,
        "decision": decision,
        "reason": "programme_source_family_budget_exhausted" if decision == "skipped" else "page_budget_reserved",
        "source_role": "programme_detail",
        "queued_source_role": "programme_detail",
        "source_family": family,
        "depth": 3,
        "score": score,
        "order": score,
        "queued_reason_signals": ["programme_detail_path_or_title"],
    }
