from copy import deepcopy
from pathlib import Path

from university_admissions_crawler.extractor.llm_provider import LLMCandidateClaim, validate_llm_candidates
from university_admissions_crawler.extractor.pdf_extractor import FixturePDFExtractor, MissingPDFExtractor
from university_admissions_crawler.extractor.schema import SourceType, WarningCode
from university_admissions_crawler.evidence.provenance import evidence_from_source, source_from_text
from university_admissions_crawler.pipeline.incremental_diff import _programme_catalog_diff
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan
from university_admissions_crawler.reports.render_report import render_markdown_report


ROOT = Path("tests/fixtures/mini_university_site")


def test_fixture_pdf_extractor_returns_page_indexed_text():
    source = source_from_text(source_url="https://fixture.test/admissions/prospectus.pdf", source_type=SourceType.PDF, text="PDF PAGE 1\nA\n---PAGE 2---\nMathematics required")
    result = FixturePDFExtractor().extract(source, "PDF PAGE 1\nA\n---PAGE 2---\nMathematics required")
    assert result.pages[1].page_number == 2
    assert "Mathematics required" in result.pages[1].text


def test_missing_pdf_extractor_warns_without_crashing():
    source = source_from_text(source_url="https://fixture.test/a.pdf", source_type=SourceType.PDF, text="")
    result = MissingPDFExtractor().extract(source, "")
    assert result.pages == []
    assert result.warnings[0].code == WarningCode.OPTIONAL_DEPENDENCY_MISSING


def test_llm_candidates_without_evidence_are_rejected():
    source = source_from_text(source_url="https://x.edu", text="Apply by 31 January 2027.")
    evidence = evidence_from_source(claim_path="/admissions/application_periods/0/value", source=source, snippet="Apply by 31 January 2027.")
    result = validate_llm_candidates(
        [
            LLMCandidateClaim("/admissions/application_periods/0/value", "31 January 2027", "Apply by 31 January 2027.", source_url="https://x.edu"),
            LLMCandidateClaim("/fees/0/value", "Free tuition", "Tuition is free."),
        ],
        [evidence],
        "Apply by 31 January 2027.",
    )
    assert len(result.accepted) == 1
    assert result.warnings[0].code == WarningCode.LLM_UNSUPPORTED_CLAIM


def test_llm_candidate_with_wrong_source_url_is_rejected():
    source = source_from_text(source_url="https://x.edu", text="Apply by 31 January 2027.")
    evidence = evidence_from_source(claim_path="/admissions/application_periods/0/value", source=source, snippet="Apply by 31 January 2027.")
    result = validate_llm_candidates(
        [LLMCandidateClaim("/admissions/application_periods/0/value", "31 January 2027", "Apply by 31 January 2027.", source_url="https://other.edu")],
        [evidence],
        "Apply by 31 January 2027.",
    )
    assert not result.accepted
    assert result.warnings[0].code == WarningCode.LLM_UNSUPPORTED_CLAIM


def test_llm_candidate_with_valid_snippet_but_wrong_claim_path_is_rejected():
    source = source_from_text(source_url="https://x.edu", text="Apply by 31 January 2027.")
    evidence = evidence_from_source(claim_path="/admissions/application_periods/0/value", source=source, snippet="Apply by 31 January 2027.")
    result = validate_llm_candidates(
        [LLMCandidateClaim("/fees/0/value", "31 January 2027", "Apply by 31 January 2027.")],
        [evidence],
        "Apply by 31 January 2027.",
    )
    assert not result.accepted
    assert result.warnings[0].code == WarningCode.LLM_UNSUPPORTED_CLAIM


def test_incremental_diff_records_changed_sources_and_fields():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()
    previous["sources"][0]["content_hash"] = "changed"
    previous["institution"]["country_or_region"]["value"] = "Atlantis"
    data2 = run_fixture_scan(ROOT, previous_result=previous)
    diff = data2.run.config["diff"]
    assert diff["baseline"] == "provided"
    assert diff["changed_sources"]
    assert "/institution/country_or_region" in diff["changed_fields"]
    warning_policy = diff["field_warning_policy"]
    assert warning_policy == {
        "strategy": "stable-semantic-v3",
        "raw_changed_field_count": 1,
        "stable_path_count": 1,
        "stable_path_warning_count": 1,
        "stable_path_warning_truncated_count": 0,
        "legacy_index_path_count": 0,
        "legacy_index_warnings_suppressed": 0,
        "legacy_semantic_warning_emitted": False,
        "structured_index_path_count": 0,
        "structured_index_warnings_suppressed": 0,
        "structured_semantic_warning_count": 0,
        "structured_semantic_warning_fields": [],
        "emitted_warning_count": 1,
    }
    assert any(
        warning.code == WarningCode.INCREMENTAL_CHANGE
        and warning.field == "/institution/country_or_region"
        for warning in data2.warnings
    )


def test_incremental_diff_without_baseline_exposes_zeroed_warning_policy():
    data = run_fixture_scan(ROOT)

    assert data.run.config["diff"]["field_warning_policy"] == {
        "strategy": "stable-semantic-v3",
        "raw_changed_field_count": 0,
        "stable_path_count": 0,
        "stable_path_warning_count": 0,
        "stable_path_warning_truncated_count": 0,
        "legacy_index_path_count": 0,
        "legacy_index_warnings_suppressed": 0,
        "legacy_semantic_warning_emitted": False,
        "structured_index_path_count": 0,
        "structured_index_warnings_suppressed": 0,
        "structured_semantic_warning_count": 0,
        "structured_semantic_warning_fields": [],
        "emitted_warning_count": 0,
    }


def test_incremental_impact_uses_order_independent_collection_identities():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()
    previous["sources"].reverse()
    previous["programme_catalog"].reverse()
    previous["programmes"].reverse()

    current = run_fixture_scan(ROOT, previous_result=previous)

    diff = current.run.config["diff"]
    assert diff["source_mix"]["stable"] is True
    assert diff["programme_catalog"]["stable"] is True
    assert diff["legacy_programmes"]["stable"] is True
    assert any(path.startswith("/programmes/") for path in diff["changed_fields"])
    warning_policy = diff["field_warning_policy"]
    assert warning_policy["legacy_index_path_count"] > 0
    assert warning_policy["legacy_index_warnings_suppressed"] == warning_policy["legacy_index_path_count"]
    assert warning_policy["legacy_semantic_warning_emitted"] is False
    assert not [warning for warning in current.warnings if warning.code == WarningCode.INCREMENTAL_CHANGE]
    assert diff["assessment"] == {
        "source_mix_changed": False,
        "authoritative_catalog_stable": True,
        "authoritative_catalog_gain": False,
        "authoritative_catalog_regression": False,
        "legacy_programmes_stable": True,
        "structured_collections_stable": True,
        "source_mix_only_change": False,
    }


def test_incremental_impact_replaces_real_legacy_index_change_with_semantic_warning():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()
    previous["programmes"][0]["prerequisites"][0]["value"]["value"] = "Algebra required"

    current = run_fixture_scan(ROOT, previous_result=previous)

    diff = current.run.config["diff"]
    assert diff["changed_fields"] == ["/programmes/0/prerequisites/0/value"]
    assert diff["legacy_programmes"]["added_count"] == 0
    assert diff["legacy_programmes"]["removed_count"] == 0
    assert diff["legacy_programmes"]["changed_row_count"] == 1
    assert diff["field_warning_policy"]["legacy_index_warnings_suppressed"] == 1
    assert diff["field_warning_policy"]["legacy_semantic_warning_emitted"] is True
    incremental_warnings = [warning for warning in current.warnings if warning.code == WarningCode.INCREMENTAL_CHANGE]
    assert len(incremental_warnings) == 1
    assert incremental_warnings[0].field == "/programmes"
    assert incremental_warnings[0].message.endswith("0 added, 0 removed, 1 changed rows.")


def test_incremental_impact_ignores_reordered_duplicate_requirement_rows():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()
    previous["admissions"]["application_periods"].reverse()

    current = run_fixture_scan(ROOT, previous_result=previous)

    diff = current.run.config["diff"]
    assert len(diff["structured_collections"]) == 12
    collection = diff["structured_collections"]["admissions.application_periods"]
    assert collection["field"] == "/admissions/application_periods"
    assert collection["stable"] is True
    assert any(path.startswith("/admissions/application_periods/") for path in diff["changed_fields"])
    warning_policy = diff["field_warning_policy"]
    assert warning_policy["structured_index_path_count"] > 0
    assert warning_policy["structured_index_warnings_suppressed"] == warning_policy["structured_index_path_count"]
    assert warning_policy["structured_semantic_warning_count"] == 0
    assert not [warning for warning in current.warnings if warning.code == WarningCode.INCREMENTAL_CHANGE]


def test_incremental_impact_replaces_real_requirement_index_change_with_collection_warning():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()
    previous["admissions"]["accepted_qualifications"][0]["value"]["value"] = "Retired qualification"

    current = run_fixture_scan(ROOT, previous_result=previous)

    diff = current.run.config["diff"]
    assert diff["changed_fields"] == ["/admissions/accepted_qualifications/0/value"]
    collection = diff["structured_collections"]["admissions.accepted_qualifications"]
    assert collection["added_count"] == 0
    assert collection["removed_count"] == 0
    assert collection["changed_row_count"] == 1
    warning_policy = diff["field_warning_policy"]
    assert warning_policy["structured_index_warnings_suppressed"] == 1
    assert warning_policy["structured_semantic_warning_count"] == 1
    assert warning_policy["structured_semantic_warning_fields"] == [
        "/admissions/accepted_qualifications"
    ]
    assert diff["assessment"]["structured_collections_stable"] is False
    incremental_warnings = [warning for warning in current.warnings if warning.code == WarningCode.INCREMENTAL_CHANGE]
    assert len(incremental_warnings) == 1
    assert incremental_warnings[0].field == "/admissions/accepted_qualifications"
    assert incremental_warnings[0].message == (
        "Structured collection changed since previous result: "
        "0 added, 0 removed, 1 changed rows."
    )
    report = render_markdown_report(current)
    assert "Structured requirement collections: tracked 12, changed 1" in report
    assert (
        "structured index paths retained 1, structured index warnings suppressed 1, "
        "warnings emitted 1"
    ) in report


def test_incremental_impact_warns_for_removed_requirement_without_raw_changed_path():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()
    retired_fee = deepcopy(previous["fees"][0])
    retired_fee["label"] = "retired fee"
    retired_fee["value"]["value"] = "SGD 1,000"
    previous["fees"].append(retired_fee)

    current = run_fixture_scan(ROOT, previous_result=previous)

    diff = current.run.config["diff"]
    assert diff["changed_fields"] == []
    assert diff["structured_collections"]["fees"]["removed_count"] == 1
    warning_policy = diff["field_warning_policy"]
    assert warning_policy["structured_index_path_count"] == 0
    assert warning_policy["structured_semantic_warning_fields"] == ["/fees"]
    assert warning_policy["emitted_warning_count"] == 1
    incremental_warnings = [warning for warning in current.warnings if warning.code == WarningCode.INCREMENTAL_CHANGE]
    assert len(incremental_warnings) == 1
    assert incremental_warnings[0].field == "/fees"
    assert incremental_warnings[0].message.endswith("0 added, 1 removed, 0 changed rows.")


def test_incremental_impact_marks_source_mix_only_change():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()
    previous["sources"][0]["source_url"] = "https://fixture.test/replaced-source"

    current = run_fixture_scan(ROOT, previous_result=previous)

    diff = current.run.config["diff"]
    assert diff["source_mix"]["symmetric_difference_count"] == 2
    assert diff["programme_catalog"]["stable"] is True
    assert diff["legacy_programmes"]["stable"] is True
    assert diff["assessment"]["source_mix_only_change"] is True


def test_incremental_impact_does_not_mark_source_mix_only_when_requirement_changes():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()
    previous["sources"][0]["source_url"] = "https://fixture.test/replaced-source"
    previous["admissions"]["accepted_qualifications"][0]["value"]["value"] = "Retired qualification"

    current = run_fixture_scan(ROOT, previous_result=previous)

    assessment = current.run.config["diff"]["assessment"]
    assert assessment["source_mix_changed"] is True
    assert assessment["structured_collections_stable"] is False
    assert assessment["source_mix_only_change"] is False


def test_incremental_impact_separates_source_catalog_and_legacy_changes():
    data = run_fixture_scan(ROOT)
    previous = data.to_dict()

    current_only_source = previous["sources"].pop(0)
    baseline_only_source = deepcopy(current_only_source)
    baseline_only_source["source_url"] = "https://fixture.test/retired-source"
    previous["sources"].append(baseline_only_source)

    previous_catalog_row = previous["programme_catalog"][0]
    previous_catalog_row["degree_or_award"] = None
    previous_catalog_row["faculty_or_school"] = "Retired Faculty"
    previous_catalog_row["category"] = "retired_category"
    retired_catalog_row = deepcopy(previous_catalog_row)
    retired_catalog_row["name"] = "Retired Programme"
    retired_catalog_row["degree_or_award"] = "Bachelor of Retired Studies"
    previous["programme_catalog"].append(retired_catalog_row)

    current_only_programme = previous["programmes"].pop(0)
    retired_programme = deepcopy(current_only_programme)
    retired_programme["name"]["value"] = "Retired Legacy Programme"
    retired_programme["source_url"] = "https://fixture.test/retired-programme"
    previous["programmes"].append(retired_programme)

    current = run_fixture_scan(ROOT, previous_result=previous)

    diff = current.run.config["diff"]
    source_mix = diff["source_mix"]
    assert source_mix["added_urls"] == [current_only_source["source_url"]]
    assert source_mix["removed_urls"] == [baseline_only_source["source_url"]]
    assert source_mix["symmetric_difference_count"] == 2

    catalog = diff["programme_catalog"]
    assert catalog["baseline_count"] == 2
    assert catalog["current_count"] == 1
    assert catalog["added_count"] == 0
    assert catalog["removed_count"] == 1
    assert catalog["changed_row_count"] == 1
    assert catalog["gained_field_count"] == 1
    assert catalog["lost_field_count"] == 1
    assert catalog["changed_field_count"] == 1
    catalog_change = catalog["field_changes"][0]
    assert catalog_change["gained"] == {"degree_or_award": "Bachelor of Science"}
    assert catalog_change["lost"] == {"faculty_or_school": "Retired Faculty"}
    assert catalog_change["changed"] == {
        "category": {"before": "retired_category", "after": "degree_programme"}
    }

    legacy = diff["legacy_programmes"]
    assert legacy["added_count"] == 1
    assert legacy["removed_count"] == 1
    warning_policy = diff["field_warning_policy"]
    assert warning_policy["legacy_index_path_count"] > 0
    assert warning_policy["legacy_index_warnings_suppressed"] == warning_policy["legacy_index_path_count"]
    assert warning_policy["legacy_semantic_warning_emitted"] is True
    assert warning_policy["emitted_warning_count"] == 1
    incremental_warnings = [warning for warning in current.warnings if warning.code == WarningCode.INCREMENTAL_CHANGE]
    assert len(incremental_warnings) == 1
    assert incremental_warnings[0].field == "/programmes"
    assert incremental_warnings[0].message == (
        "Compatibility programme collection changed since previous result: "
        "1 added, 1 removed, 0 changed rows."
    )
    assert diff["assessment"]["authoritative_catalog_gain"] is True
    assert diff["assessment"]["authoritative_catalog_regression"] is True
    assert diff["assessment"]["legacy_programmes_stable"] is False
    report = render_markdown_report(current)
    assert "## Incremental Impact" in report
    assert "Unique source URL mix:" in report and "symmetric difference 2" in report
    assert "gained fields 1, lost fields 1" in report
    assert "Compatibility programmes: 3 -> 3, added 1, removed 1" in report
    assert "Structured requirement collections: tracked 12, changed 0" in report
    assert "Incremental field warnings: stable-semantic-v3" in report
    assert (
        f"unstable legacy index paths retained {warning_policy['legacy_index_path_count']}"
        in report
    )
    assert (
        f"index warnings suppressed {warning_policy['legacy_index_warnings_suppressed']}"
        in report
    )


def test_incremental_catalog_diff_keeps_same_name_different_awards_distinct():
    mechanical = {
        "name": "Bachelor of Engineering",
        "degree_or_award": "Bachelor of Engineering (Mechanical Engineering)",
        "faculty_or_school": "College of Engineering",
        "category": "degree_programme",
    }
    civil = {
        "name": "Bachelor of Engineering",
        "degree_or_award": "Bachelor of Engineering (Civil Engineering)",
        "faculty_or_school": "College of Engineering",
        "category": "degree_programme",
    }
    previous = [deepcopy(mechanical), deepcopy(civil)]
    current = [deepcopy(civil), deepcopy(mechanical)]

    stable = _programme_catalog_diff(current, previous)

    assert stable["baseline_count"] == 2
    assert stable["current_count"] == 2
    assert stable["stable"] is True

    current[0]["mode"] = "Full-time"
    changed = _programme_catalog_diff(current, previous)

    assert changed["added_count"] == 0
    assert changed["removed_count"] == 0
    assert changed["changed_row_count"] == 1
    assert changed["gained_field_count"] == 1
    assert changed["field_changes"][0]["name"] == "Bachelor of Engineering"
