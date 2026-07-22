import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from university_admissions_crawler.crawler.html_text import extract_html_text_document
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.programme_catalog import extract_programme_catalog


FIXTURES = Path(__file__).parent / "fixtures" / "programme_catalog" / "ntu_live_regressions"
MANIFEST = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in MANIFEST["cases"]}


def _extract_case(case_id: str):
    case = CASES[case_id]
    html = (FIXTURES / case["file"]).read_text(encoding="utf-8")
    document = extract_html_text_document(html)
    text = document.plain_text
    source = source_from_text(
        source_url=case["source_url"],
        title=case["title"],
        text=text,
    )
    diagnostics: list[dict[str, object]] = []
    rows = extract_programme_catalog(
        text,
        source,
        candidate_diagnostics=diagnostics,
        content_blocks=document.blocks,
    )
    return rows, diagnostics


def test_ntu_live_regression_manifest_is_complete_and_official():
    assert MANIFEST["fixture_kind"] == "minimal_reproduction"
    assert MANIFEST["derived_from"] == {
        "failure_output": "outputs/ntu-live-20260717",
        "canonical_reference": "https://www.ntu.edu.sg/education/degree-programmes",
    }
    assert set(CASES) == {
        "canonical_degree_table",
        "canonical_degree_table_with_eligibility",
        "ccds_json_ld_course_cards",
        "ccds_visible_css",
        "curriculum_care_serve_learn",
        "detail_related_programmes",
        "hass_title_pipe",
        "old_cohort_minor",
    }

    for case in CASES.values():
        assert (FIXTURES / case["file"]).is_file()
        assert urlparse(case["source_url"]).hostname == "www.ntu.edu.sg"
        assert case["expected_source_role"] in {
            "canonical_catalog",
            "curriculum_or_old_cohort",
            "faculty_catalog",
            "programme_detail",
        }
        assert isinstance(case["expected_names"], list)
        assert isinstance(case["forbidden_name_fragments"], list)
        assert isinstance(case["expected_rejection_reasons"], list)


def test_ntu_canonical_degree_table_is_the_positive_control():
    case = CASES["canonical_degree_table"]
    rows, diagnostics = _extract_case(case["id"])
    by_name = {row.name: (row, evidence) for row, evidence in rows}

    assert list(by_name) == case["expected_names"]
    assert {name: row.degree_or_award for name, (row, _evidence) in by_name.items()} == case["expected_awards"]
    category_review_names = {
        row.name
        for row, _evidence in by_name.values()
        if any(warning.message.startswith("category_inferred:") for warning in row.warnings)
    }
    assert category_review_names == {"Medicine"}
    assert all(evidence for _row, evidence in by_name.values())
    assert all(item.source_url == case["source_url"] for _row, evidence in by_name.values() for item in evidence)
    assert [item["decision"] for item in diagnostics].count("accepted") == len(case["expected_names"])
    rejected_reasons = {item["reason"] for item in diagnostics if item["decision"] == "rejected"}
    assert set(case["expected_rejection_reasons"]).issubset(rejected_reasons)


def test_ntu_canonical_degree_table_closes_scope_before_eligibility_tables():
    case = CASES["canonical_degree_table_with_eligibility"]
    rows, diagnostics = _extract_case(case["id"])

    assert [row.name for row, _evidence in rows] == case["expected_names"]
    rejected = [
        item
        for item in diagnostics
        if item["reason"] == "minor_or_second_major_eligibility_table"
    ]
    assert {item["parser_branch"] for item in rejected} == {
        "non_catalog_table_header",
        "non_catalog_table_row",
    }
    assert not any("All except:" in row.name for row, _evidence in rows)


def test_ntu_old_cohort_minor_does_not_create_degree_rows():
    rows, diagnostics = _extract_case("old_cohort_minor")

    assert rows == []
    assert any(item["decision"] == "rejected" and item["reason"] == "course_or_curriculum_row" for item in diagnostics)
    assert {item["source_role"] for item in diagnostics} == {"curriculum_or_old_cohort"}


@pytest.mark.parametrize(
    "case_id",
    [
        "hass_title_pipe",
        "ccds_json_ld_course_cards",
        "ccds_visible_css",
        "curriculum_care_serve_learn",
        "detail_related_programmes",
    ],
)
def test_ntu_live_regressions_extract_only_structurally_anchored_programmes(case_id: str):
    case = CASES[case_id]
    rows, diagnostics = _extract_case(case_id)
    names = [row.name for row, _evidence in rows]

    assert names == case["expected_names"]
    assert not any(
        warning.message.startswith("category_inferred:")
        for row, _evidence in rows
        for warning in row.warnings
    )
    assert not any(fragment in name for fragment in case["forbidden_name_fragments"] for name in names)
    accepted = [item for item in diagnostics if item["decision"] == "accepted"]
    assert len(accepted) == len(case["expected_names"])
    assert {item["source_role"] for item in accepted} == {case["expected_source_role"]}
    assert all(item["block_kind"] for item in accepted)
    assert all(item["structural_anchor"] for item in accepted)
    assert all(item["name_quality_passed"] is True for item in accepted)
    assert all(item["institution_consistent"] is True for item in accepted)
    rejection_reasons = {item["reason"] for item in diagnostics if item["decision"] == "rejected"}
    assert set(case["expected_rejection_reasons"]).issubset(rejection_reasons)


def test_ntu_ccds_json_ld_cards_use_course_names_and_primary_links():
    rows, diagnostics = _extract_case("ccds_json_ld_course_cards")

    assert all(row.name == row.degree_or_award for row, _evidence in rows)
    assert not any(row.name in {"Computing", "Business"} for row, _evidence in rows)
    accepted = [item for item in diagnostics if item["decision"] == "accepted"]
    assert {item["parser_branch"] for item in accepted} == {"card_candidate"}
    assert {item["block_kind"] for item in accepted} == {"card"}
    assert {item["structural_anchor"] for item in accepted} == {"programme_primary_link"}
    assert all(row.faculty_or_school == "College of Computing and Data Science" for row, _evidence in rows)
    for row, evidence in rows:
        faculty_path = row.evidence_path.rsplit("/", 1)[0] + "/faculty_or_school"
        assert any(
            item.claim_path == faculty_path and "College of Computing and Data Science" in item.snippet
            for item in evidence
        )
    assert all("faculty_or_school" in item["field_evidence_paths"] for item in accepted)
