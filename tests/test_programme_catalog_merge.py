import json

import pytest

from university_admissions_crawler.crawler.types import FetchResult
from university_admissions_crawler.evidence.provenance import evidence_from_source, source_from_text
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    Institution,
    ProgrammeCatalogRecord,
    RunMetadata,
    SourceType,
    WarningCode,
    WarningRecord,
    attach_validation_warnings,
)
from university_admissions_crawler.pipeline.api_catalog_capture import _extract_json_api_claims_and_catalog
from university_admissions_crawler.pipeline.api_catalog_pagination import ApiCatalogPaginationOutcome
from university_admissions_crawler.pipeline.category_extraction import ExtractionDiagnosticsRecorder
from university_admissions_crawler.pipeline.programme_catalog_merge import merge_programme_catalog_records


def _data(*sources):
    return AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(input_url="https://example.edu"),
        sources=list(sources),
    )


def _bundle(
    source,
    *,
    index: int,
    name: str = "Computer Science",
    award: str | None = "Bachelor of Computing in Computer Science",
    category: str = "degree_programme",
    faculty: str | None = None,
    mode: str | None = None,
    specialisations: list[str] | None = None,
    with_faculty_evidence: bool = False,
    primary_source_urls: list[str] | None = None,
):
    claim_path = f"/programme_catalog/{index}/name"
    row = ProgrammeCatalogRecord(
        name=name,
        degree_or_award=award,
        category=category,
        faculty_or_school=faculty,
        mode=mode,
        specialisations_or_majors=list(specialisations or ()),
        source_url=source.source_url,
        evidence_snippet=f"{name} | {award or ''}",
        evidence_path=claim_path,
        warnings=[
            WarningRecord(
                WarningCode.NEEDS_MANUAL_CHECK,
                "missing_faculty: Programme row does not expose a faculty or school.",
                field=claim_path,
                source_urls=[source.source_url],
            )
        ]
        if faculty is None
        else [],
    )
    evidence = [evidence_from_source(claim_path=claim_path, source=source, snippet=row.evidence_snippet)]
    diagnostic = {
        "source_url": source.source_url,
        "decision": "accepted",
        "reason": "accepted_parsed",
        "claim_path": claim_path,
        "name": name,
        "category": category,
    }
    if with_faculty_evidence:
        faculty_path = f"/programme_catalog/{index}/faculty_or_school"
        evidence.append(evidence_from_source(claim_path=faculty_path, source=source, snippet=faculty or ""))
        diagnostic["field_evidence_paths"] = {"faculty_or_school": faculty_path}
    if primary_source_urls:
        diagnostic["primary_source_urls"] = primary_source_urls
    return (row, evidence), diagnostic


def _merge(data, bundle, diagnostic, role):
    outcome = merge_programme_catalog_records(
        data,
        [bundle],
        source_role=role,
        candidate_diagnostics=[diagnostic],
    )
    data.run.config.setdefault("programme_catalog_candidate_diagnostics", []).append(diagnostic)
    return outcome


def test_canonical_row_stays_primary_and_faculty_row_only_enriches_missing_fields():
    canonical = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Computer Science | Bachelor of Computing in Computer Science",
    )
    faculty = source_from_text(
        source_url="https://example.edu/computing/programmes",
        title="Computing Programmes",
        text="Computer Science | School of Computing | Full-time",
    )
    data = _data(canonical, faculty)
    canonical_bundle, canonical_diagnostic = _bundle(canonical, index=0)
    faculty_bundle, faculty_diagnostic = _bundle(
        faculty,
        index=1,
        faculty="School of Computing",
        mode="full-time",
    )

    _merge(data, canonical_bundle, canonical_diagnostic, "canonical_catalog")
    outcome = _merge(data, faculty_bundle, faculty_diagnostic, "faculty_catalog")

    assert len(data.programme_catalog) == 1
    row = data.programme_catalog[0]
    assert row.source_url == canonical.source_url
    assert row.faculty_or_school == "School of Computing"
    assert row.mode == "full-time"
    assert not any("missing_faculty:" in warning.message for warning in row.warnings)
    assert outcome.appended_count == 0
    assert outcome.merged_count == 1
    assert outcome.evidence_count == 2
    assert faculty_diagnostic["decision"] == "context"
    assert faculty_diagnostic["reason"] == "lower_priority_source_enriched_row"
    assert faculty_diagnostic["matched_claim_path"] == row.evidence_path
    assert data.run.config["programme_catalog_row_provenance"][row.evidence_path]["source_role"] == "canonical_catalog"

    attach_validation_warnings(data)
    assert not [warning for warning in data.warnings if warning.code == WarningCode.MISSING_EVIDENCE]


def test_later_canonical_row_replaces_faculty_provenance_without_losing_nonconflicting_fields():
    faculty = source_from_text(
        source_url="https://example.edu/computing/programmes",
        title="Computing Programmes",
        text="Computer Science | School of Computing | Full-time",
    )
    canonical = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Computer Science | Bachelor of Computing | College of Computing",
    )
    data = _data(faculty, canonical)
    faculty_bundle, faculty_diagnostic = _bundle(
        faculty,
        index=0,
        faculty="School of Computing",
        mode="full-time",
        primary_source_urls=["https://example.edu/computing/computer-science"],
    )
    canonical_bundle, canonical_diagnostic = _bundle(
        canonical,
        index=1,
        faculty="College of Computing",
        primary_source_urls=["https://example.edu/programmes/computer-science"],
    )

    _merge(data, faculty_bundle, faculty_diagnostic, "faculty_catalog")
    outcome = _merge(data, canonical_bundle, canonical_diagnostic, "canonical_catalog")

    assert len(data.programme_catalog) == 1
    row = data.programme_catalog[0]
    assert row.source_url == canonical.source_url
    assert row.evidence_path == "/programme_catalog/0/name"
    assert row.faculty_or_school == "College of Computing"
    assert row.mode == "full-time"
    assert outcome.replaced_count == 1
    assert faculty_diagnostic["decision"] == "context"
    assert faculty_diagnostic["reason"] == "replaced_by_higher_priority_source"
    replacement = data.run.config["programme_catalog_merge_diagnostics"][-1]
    assert replacement["decision"] == "replaced"
    assert replacement["previous_source_role"] == "faculty_catalog"
    assert replacement["enriched_fields"] == ["mode"]
    assert replacement["conflicting_fields"] == ["faculty_or_school"]
    assert data.run.config["programme_catalog_row_provenance"][row.evidence_path]["primary_source_urls"] == [
        "https://example.edu/programmes/computer-science",
        "https://example.edu/computing/computer-science",
    ]
    assert {item.source_url for item in data.evidence} == {canonical.source_url, faculty.source_url}
    conflict = next(warning for warning in row.warnings if warning.message.startswith("conflicting_faculty_or_school:"))
    assert conflict.code == WarningCode.NEEDS_MANUAL_CHECK
    assert conflict.field == row.evidence_path
    assert set(conflict.source_urls) == {canonical.source_url, faculty.source_url}

    attach_validation_warnings(data)
    assert not [warning for warning in data.warnings if warning.code == WarningCode.MISSING_EVIDENCE]


def test_award_display_variants_merge_and_enrich_with_field_evidence():
    canonical = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Data Science and Artificial Intelligence | Bachelor of Computing in Data Science & Artificial Intelligence",
    )
    faculty = source_from_text(
        source_url="https://example.edu/computing/programmes",
        title="Computing Programmes",
        text="Bachelor of Computing (Hons) in Data Science and Artificial Intelligence | School of Computing",
    )
    data = _data(canonical, faculty)
    canonical_bundle, canonical_diagnostic = _bundle(
        canonical,
        index=0,
        name="Data Science and Artificial Intelligence",
        award="Bachelor of Computing in Data Science & Artificial Intelligence",
    )
    faculty_bundle, faculty_diagnostic = _bundle(
        faculty,
        index=1,
        name="Bachelor of Computing (Hons) in Data Science and Artificial Intelligence",
        award="Bachelor of Computing (Hons) in Data Science and Artificial Intelligence",
        faculty="School of Computing",
        with_faculty_evidence=True,
    )

    _merge(data, canonical_bundle, canonical_diagnostic, "canonical_catalog")
    outcome = _merge(data, faculty_bundle, faculty_diagnostic, "faculty_catalog")

    assert len(data.programme_catalog) == 1
    row = data.programme_catalog[0]
    assert row.name == "Data Science and Artificial Intelligence"
    assert row.degree_or_award == "Bachelor of Computing in Data Science & Artificial Intelligence"
    assert row.faculty_or_school == "School of Computing"
    assert not row.warnings
    assert outcome.merged_count == 1
    assert faculty_diagnostic["reason"] == "lower_priority_source_enriched_row"
    assert faculty_diagnostic["enriched_fields"] == ["faculty_or_school"]
    assert faculty_diagnostic["conflicting_fields"] == []
    mapping = data.run.config["programme_catalog_enrichment_evidence"][row.evidence_path]
    assert mapping["faculty_or_school"] == {
        "claim_path": "/programme_catalog/0/faculty_or_school",
        "source_url": faculty.source_url,
    }


@pytest.mark.parametrize(
    ("canonical_name", "canonical_award", "faculty_name"),
    [
        (
            "Artificial Intelligence and Society",
            "Bachelor of Computing in Artificial Intelligence & Society",
            "Bachelor of Computing (Hons) in Artificial Intelligence (AI) and Society",
        ),
        (
            "Computer Engineering",
            "Bachelor of Engineering (Computer Engineering)",
            "Bachelor of Engineering (Hons) in Computer Engineering",
        ),
        (
            "Environmental Engineering",
            "Bachelor of Engineering (Environmental Engineering)",
            "Bachelor of Engineering in Environmental Engineering",
        ),
        (
            "Economics and Media Analytics",
            "Bachelor of Social Sciences in Economics and Media Analytics",
            "Bachelor of Social Sciences (Honours) - Economics and Media Analytics",
        ),
        (
            "Psychology and Media Analytics",
            "Bachelor of Social Sciences in Psychology and Media Analytics",
            "Bachelor of Social Sciences (Honours) - Psychology and Media Analytics",
        ),
    ],
)
def test_cross_source_display_variants_merge_only_after_strict_identity_misses(
    canonical_name,
    canonical_award,
    faculty_name,
):
    canonical = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text=f"{canonical_name} | {canonical_award}",
    )
    faculty = source_from_text(
        source_url="https://example.edu/faculty/programmes",
        title="Faculty Programmes",
        text=f"{faculty_name} | Example School",
    )
    data = _data(canonical, faculty)
    canonical_bundle, canonical_diagnostic = _bundle(
        canonical,
        index=0,
        name=canonical_name,
        award=canonical_award,
        primary_source_urls=["https://example.edu/programmes/canonical-detail"],
    )
    faculty_bundle, faculty_diagnostic = _bundle(
        faculty,
        index=1,
        name=faculty_name,
        award=faculty_name,
        faculty="Example School",
        with_faculty_evidence=True,
        primary_source_urls=["https://example.edu/programmes/faculty-detail"],
    )

    _merge(data, canonical_bundle, canonical_diagnostic, "canonical_catalog")
    outcome = _merge(data, faculty_bundle, faculty_diagnostic, "faculty_catalog")

    assert len(data.programme_catalog) == 1
    row = data.programme_catalog[0]
    assert row.name == canonical_name
    assert row.degree_or_award == canonical_award
    assert row.faculty_or_school == "Example School"
    assert not any("missing_faculty:" in warning.message for warning in row.warnings)
    assert outcome.merged_count == 1
    assert outcome.appended_count == 0
    assert faculty_diagnostic["match_method"] == "cross_source_display_variant"
    assert data.run.config["programme_catalog_merge_diagnostics"][-1]["match_method"] == (
        "cross_source_display_variant"
    )
    assert data.run.config["programme_catalog_row_provenance"][row.evidence_path]["primary_source_urls"] == [
        "https://example.edu/programmes/canonical-detail",
        "https://example.edu/programmes/faculty-detail",
    ]


def test_cross_source_display_variant_does_not_merge_different_degree_families():
    canonical = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Computer Engineering | Bachelor of Engineering (Computer Engineering)",
    )
    faculty = source_from_text(
        source_url="https://example.edu/faculty/programmes",
        title="Faculty Programmes",
        text="Bachelor of Science in Computer Engineering | Example School",
    )
    data = _data(canonical, faculty)
    canonical_bundle, canonical_diagnostic = _bundle(
        canonical,
        index=0,
        name="Computer Engineering",
        award="Bachelor of Engineering (Computer Engineering)",
    )
    faculty_bundle, faculty_diagnostic = _bundle(
        faculty,
        index=1,
        name="Bachelor of Science in Computer Engineering",
        award="Bachelor of Science in Computer Engineering",
        faculty="Example School",
    )

    _merge(data, canonical_bundle, canonical_diagnostic, "canonical_catalog")
    outcome = _merge(data, faculty_bundle, faculty_diagnostic, "faculty_catalog")

    assert len(data.programme_catalog) == 2
    assert outcome.appended_count == 1
    assert "match_method" not in faculty_diagnostic


def test_cross_source_display_variant_does_not_collapse_second_major_degree_families():
    business_source = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Bachelor of Business with Second Major in Sustainability",
    )
    accountancy_source = source_from_text(
        source_url="https://example.edu/faculty/programmes",
        title="Faculty Programmes",
        text="Bachelor of Accountancy with Second Major in Sustainability",
    )
    data = _data(business_source, accountancy_source)
    business_bundle, business_diagnostic = _bundle(
        business_source,
        index=0,
        name="Bachelor of Business with Second Major in Sustainability",
        award="Bachelor of Business with Second Major in Sustainability",
    )
    accountancy_bundle, accountancy_diagnostic = _bundle(
        accountancy_source,
        index=1,
        name="Bachelor of Accountancy with Second Major in Sustainability",
        award="Bachelor of Accountancy with Second Major in Sustainability",
    )

    _merge(data, business_bundle, business_diagnostic, "canonical_catalog")
    outcome = _merge(data, accountancy_bundle, accountancy_diagnostic, "faculty_catalog")

    assert len(data.programme_catalog) == 2
    assert outcome.appended_count == 1
    assert {row.name for row in data.programme_catalog} == {
        "Bachelor of Business with Second Major in Sustainability",
        "Bachelor of Accountancy with Second Major in Sustainability",
    }
    assert "match_method" not in accountancy_diagnostic


def test_cross_source_display_variant_does_not_merge_json_api_rows():
    canonical = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Artificial Intelligence and Society",
    )
    api_source = source_from_text(
        source_url="https://example.edu/api/programmes",
        source_type=SourceType.JSON,
        title="Programmes API",
        text="Bachelor of Computing (Hons) in Artificial Intelligence (AI) and Society",
    )
    data = _data(canonical, api_source)
    canonical_bundle, canonical_diagnostic = _bundle(
        canonical,
        index=0,
        name="Artificial Intelligence and Society",
        award="Bachelor of Computing in Artificial Intelligence & Society",
    )
    api_bundle, api_diagnostic = _bundle(
        api_source,
        index=1,
        name="Bachelor of Computing (Hons) in Artificial Intelligence (AI) and Society",
        award="Bachelor of Computing (Hons) in Artificial Intelligence (AI) and Society",
        faculty="Example School",
    )

    _merge(data, canonical_bundle, canonical_diagnostic, "canonical_catalog")
    outcome = _merge(data, api_bundle, api_diagnostic, "faculty_catalog")

    assert len(data.programme_catalog) == 2
    assert outcome.appended_count == 1
    assert "match_method" not in api_diagnostic


def test_faculty_conflict_warning_uses_field_evidence_sources_after_enrichment():
    canonical = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Communication Studies | Bachelor of Communication Studies",
    )
    college = source_from_text(
        source_url="https://example.edu/college/programmes",
        title="College Programmes",
        text="Bachelor of Communication Studies | College of Humanities",
    )
    school = source_from_text(
        source_url="https://example.edu/school/programmes",
        title="School Programmes",
        text="Bachelor of Communication Studies (Honours) | School of Communication",
    )
    data = _data(canonical, college, school)
    canonical_bundle, canonical_diagnostic = _bundle(
        canonical,
        index=0,
        name="Communication Studies",
        award="Bachelor of Communication Studies",
    )
    college_bundle, college_diagnostic = _bundle(
        college,
        index=1,
        name="Bachelor of Communication Studies",
        award="Bachelor of Communication Studies",
        faculty="College of Humanities",
        with_faculty_evidence=True,
    )
    school_bundle, school_diagnostic = _bundle(
        school,
        index=2,
        name="Bachelor of Communication Studies (Honours)",
        award="Bachelor of Communication Studies (Honours)",
        faculty="School of Communication",
        with_faculty_evidence=True,
    )

    _merge(data, canonical_bundle, canonical_diagnostic, "canonical_catalog")
    _merge(data, college_bundle, college_diagnostic, "faculty_catalog")
    _merge(data, school_bundle, school_diagnostic, "faculty_catalog")

    row = data.programme_catalog[0]
    conflict = next(warning for warning in row.warnings if warning.message.startswith("conflicting_faculty_or_school:"))
    assert row.faculty_or_school == "College of Humanities"
    assert set(conflict.source_urls) == {college.source_url, school.source_url}
    assert canonical.source_url not in conflict.source_urls


def test_same_name_with_different_award_or_category_remains_distinct_and_ambiguous_row_is_quarantined():
    source = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Bachelor of Engineering programmes",
    )
    data = _data(source)
    mechanical, mechanical_diagnostic = _bundle(
        source,
        index=0,
        name="Bachelor of Engineering",
        award="Bachelor of Engineering in Mechanical Engineering",
    )
    civil, civil_diagnostic = _bundle(
        source,
        index=1,
        name="Bachelor of Engineering",
        award="Bachelor of Engineering in Civil Engineering",
    )
    major, major_diagnostic = _bundle(
        source,
        index=2,
        name="Bachelor of Engineering",
        award="Bachelor of Engineering in Mechanical Engineering",
        category="major",
    )
    ambiguous, ambiguous_diagnostic = _bundle(
        source,
        index=3,
        name="Bachelor of Engineering",
        award=None,
    )

    _merge(data, mechanical, mechanical_diagnostic, "canonical_catalog")
    _merge(data, civil, civil_diagnostic, "canonical_catalog")
    _merge(data, major, major_diagnostic, "canonical_catalog")
    outcome = _merge(data, ambiguous, ambiguous_diagnostic, "faculty_catalog")

    assert len(data.programme_catalog) == 3
    assert {(row.category, row.degree_or_award) for row in data.programme_catalog} == {
        ("degree_programme", "Bachelor of Engineering in Mechanical Engineering"),
        ("degree_programme", "Bachelor of Engineering in Civil Engineering"),
        ("major", "Bachelor of Engineering in Mechanical Engineering"),
    }
    assert outcome.quarantined_count == 1
    assert ambiguous_diagnostic["decision"] == "quarantined"
    assert ambiguous_diagnostic["reason"] == "ambiguous_programme_identity"
    assert ambiguous_diagnostic["compatible_match_count"] == 2


def test_non_latin_programme_names_do_not_collapse_to_the_same_identity():
    source = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="计算机科学 | 数据科学 | 理学学士",
    )
    data = _data(source)
    computer_science, computer_science_diagnostic = _bundle(
        source,
        index=0,
        name="计算机科学",
        award="理学学士",
    )
    data_science, data_science_diagnostic = _bundle(
        source,
        index=1,
        name="数据科学",
        award="理学学士",
    )

    first_outcome = _merge(data, computer_science, computer_science_diagnostic, "canonical_catalog")
    second_outcome = _merge(data, data_science, data_science_diagnostic, "canonical_catalog")

    assert first_outcome.appended_count == 1
    assert second_outcome.appended_count == 1
    assert [row.name for row in data.programme_catalog] == ["计算机科学", "数据科学"]


def test_skipped_duplicate_rebases_later_row_and_field_evidence_without_gaps():
    source = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Computer Science and Data Science",
    )
    data = _data(source)
    first, first_diagnostic = _bundle(source, index=0, faculty="School of Computing")
    duplicate, duplicate_diagnostic = _bundle(source, index=1, faculty="School of Computing")
    unique, unique_diagnostic = _bundle(
        source,
        index=2,
        name="Data Science",
        award="Bachelor of Science in Data Science",
        faculty="School of Computing",
        with_faculty_evidence=True,
    )
    unique[0].warnings.append(
        WarningRecord(
            WarningCode.NEEDS_MANUAL_CHECK,
            "test warning",
            field="/programme_catalog/2/name",
        )
    )

    _merge(data, first, first_diagnostic, "canonical_catalog")
    outcome = merge_programme_catalog_records(
        data,
        [duplicate, unique],
        source_role="canonical_catalog",
        candidate_diagnostics=[duplicate_diagnostic, unique_diagnostic],
    )

    assert outcome.appended_count == 1
    assert outcome.merged_count == 1
    assert [row.evidence_path for row in data.programme_catalog] == [
        "/programme_catalog/0/name",
        "/programme_catalog/1/name",
    ]
    assert {item.claim_path for item in data.evidence} == {
        "/programme_catalog/0/name",
        "/programme_catalog/1/name",
        "/programme_catalog/1/faculty_or_school",
    }
    assert data.programme_catalog[1].warnings[-1].field == "/programme_catalog/1/name"
    assert unique_diagnostic["claim_path"] == "/programme_catalog/1/name"
    assert unique_diagnostic["field_evidence_paths"] == {
        "faculty_or_school": "/programme_catalog/1/faculty_or_school"
    }
    assert data.run.config["programme_catalog_field_evidence"]["/programme_catalog/1/name"] == {
        "faculty_or_school": "/programme_catalog/1/faculty_or_school"
    }


def test_unproven_api_catalog_enriches_canonical_row_through_shared_merge_path():
    canonical = source_from_text(
        source_url="https://example.edu/degree-programmes",
        title="Degree Programmes",
        text="Computer Science | Bachelor of Computing in Computer Science",
    )
    api_text = json.dumps(
        {
            "items": [
                {
                    "programmeName": "Computer Science",
                    "degree": "Bachelor of Computing in Computer Science",
                    "school": "School of Computing",
                }
            ]
        }
    )
    api_source = source_from_text(
        source_url="https://example.edu/api/programmes",
        source_type=SourceType.JSON,
        title="Programmes API",
        text=api_text,
    )
    data = _data(canonical, api_source)
    canonical_bundle, canonical_diagnostic = _bundle(canonical, index=0)
    _merge(data, canonical_bundle, canonical_diagnostic, "canonical_catalog")
    extraction_attempts: list[dict[str, object]] = []

    _extract_json_api_claims_and_catalog(
        data,
        FetchResult(
            url=api_source.source_url,
            final_url=api_source.source_url,
            status=200,
            title=api_source.title,
            content_type="application/json",
            retrieved_at=api_source.retrieved_at,
            engine="test",
            text=api_text,
            source=api_source,
        ),
        ExtractionDiagnosticsRecorder(extraction_attempts),
        pagination_outcome=ApiCatalogPaginationOutcome(initial_url=api_source.source_url),
        page_index=1,
        is_completion_page=True,
    )

    assert len(data.programme_catalog) == 1
    row = data.programme_catalog[0]
    assert row.source_url == canonical.source_url
    assert row.faculty_or_school == "School of Computing"
    assert data.run.config["programme_catalog_api_diagnostics"][0]["source_role"] == "faculty_catalog"
    assert data.run.config["programme_catalog_api_diagnostics"][0]["api_completeness_proven"] is False
    assert data.run.config["programme_catalog_merge_diagnostics"][-1]["reason"] == "lower_priority_source_enriched_row"
    assert extraction_attempts[-1] == {
        "field": "programme_catalog",
        "extractor": "extract_programme_catalog_api",
        "status": "extracted",
        "reason": "json_api",
        "record_count": 1,
        "evidence_count": 1,
        "claim_path": "/programme_catalog",
    }

    attach_validation_warnings(data)
    assert not [warning for warning in data.warnings if warning.code == WarningCode.MISSING_EVIDENCE]
