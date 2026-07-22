from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    Institution,
    PageCategory,
    ProgrammeCatalogRecord,
    RunMetadata,
    WarningCode,
    WarningRecord,
)
from university_admissions_crawler.pipeline.diagnostics import attach_run_diagnostics


def _catalog_data(
    *,
    source_role: str = "canonical_catalog",
    decisions: tuple[str, ...] = ("accepted",),
) -> AdmissionsData:
    source = source_from_text(
        source_url="https://example.edu/programmes",
        title="Undergraduate Programmes",
        text="Undergraduate Programmes | Computer Science | Bachelor of Computing",
    )
    row = ProgrammeCatalogRecord(
        name="Computer Science",
        degree_or_award="Bachelor of Computing",
        category="degree_programme",
        source_url=source.source_url,
        evidence_snippet="Computer Science | Bachelor of Computing",
        evidence_path="/programme_catalog/0/name",
    )
    candidate_diagnostics: list[dict[str, object]] = []
    for index, decision in enumerate(decisions):
        candidate_diagnostics.append(
            {
                "source_url": source.source_url,
                "decision": decision,
                "reason": "accepted_parsed" if decision == "accepted" else f"test_{decision}",
                "candidate_shape": "table_row",
                "block_kind": "table_row",
                "section_path": ["Undergraduate Programmes"],
                "source_role": source_role,
                "structural_anchor": "programme_table_row",
                "claim_path": row.evidence_path if index == 0 and decision == "accepted" else None,
            }
        )
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(
            input_url="https://example.edu",
            config={
                "source_strategy": [
                    {
                        "url": source.source_url,
                        "category": str(PageCategory.PROGRAMME_LIST),
                        "strategy": "html_page",
                        "source_role": source_role,
                    }
                ],
                "programme_catalog_candidate_diagnostics": candidate_diagnostics,
                "programme_catalog_row_provenance": {
                    row.evidence_path: {
                        "source_url": source.source_url,
                        "source_role": source_role,
                    }
                },
            },
        ),
        sources=[source],
        programme_catalog=[row],
    )
    attach_run_diagnostics(data)
    return data


def test_canonical_html_catalog_is_complete_only_with_conserved_ledgers():
    summary = _catalog_data().run.config["programme_catalog_summary"]

    assert summary["source_role_counts"] == {"canonical_catalog": 1}
    assert summary["accepted_by_source_role"] == {"canonical_catalog": 1}
    assert summary["canonical_catalog_captured"] is True
    assert summary["canonical_catalog_accepted"] is True
    assert summary["candidate_conservation_expected_count"] == 1
    assert summary["candidate_conservation_observed_count"] == 1
    assert summary["candidate_conservation_proven"] is True
    assert summary["identified_catalog_section_count"] == 1
    assert summary["processed_catalog_section_count"] == 1
    assert summary["catalog_section_conservation_proven"] is True
    assert summary["catalog_complete"] is True
    assert summary["catalog_completeness_status"] == "complete"
    assert summary["catalog_completeness_failure_reasons"] == []
    assert summary["catalog_completeness_failure_stages"] == []
    assert summary["catalog_completeness_failure_stage_counts"] == {}
    assert summary["probable_incomplete_catalog"] is False
    assert summary["recommended_next_action"] == "none"


def test_quarantined_candidate_is_conserved_but_prevents_complete_status():
    summary = _catalog_data(decisions=("accepted", "quarantined")).run.config["programme_catalog_summary"]

    assert summary["candidate_conservation_proven"] is True
    assert summary["catalog_section_conservation_proven"] is True
    assert summary["quarantined_candidate_count"] == 1
    assert summary["catalog_complete"] is False
    assert summary["catalog_completeness_failure_reasons"] == ["no_quarantined_candidates"]
    assert summary["catalog_completeness_failure_stages"] == ["entity_gate"]
    assert summary["catalog_completeness_failure_stage_counts"] == {"entity_gate": 1}
    assert summary["probable_incomplete_catalog"] is True
    assert summary["recommended_next_action"] == "review_quarantined_catalog_candidates"


def test_warning_only_accepted_row_prevents_complete_status_without_removing_fact():
    data = _catalog_data()
    data.programme_catalog[0].warnings.append(
        WarningRecord(
            WarningCode.NEEDS_MANUAL_CHECK,
            "test_warning: Accepted row still requires review.",
            field="/programme_catalog/0/name",
        )
    )

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert len(data.programme_catalog) == 1
    assert summary["raw_needs_review_count"] == 0
    assert summary["manual_review_count"] == 1
    assert summary["quality_adjustment_applied"] is True
    assert summary["quality_adjusted_accepted_row_count"] == 0
    assert summary["quality_excluded_accepted_row_count"] == 1
    assert summary["quality_exclusion_reason_counts"] == {"needs_manual_check_warning": 1}
    assert summary["catalog_complete"] is False
    assert summary["catalog_completeness_failure_reasons"] == [
        "no_manual_review_rows",
        "row_yield_not_suspicious",
    ]
    assert summary["catalog_completeness_failure_stages"] == ["segmentation", "entity_gate"]
    assert summary["recommended_next_action"] == "review_catalog_warnings"


def test_raw_parse_status_is_excluded_from_quality_adjusted_count():
    data = _catalog_data()
    data.programme_catalog[0].parse_status = "raw_needs_manual_review"

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert len(data.programme_catalog) == 1
    assert summary["raw_needs_review_count"] == 1
    assert summary["manual_review_count"] == 1
    assert summary["quality_adjusted_accepted_row_count"] == 0
    assert summary["quality_excluded_accepted_row_count"] == 1
    assert summary["quality_exclusion_reason_counts"] == {"raw_needs_manual_review": 1}
    assert summary["recommended_next_action"] == "manual_review_raw_rows"


def test_unknown_candidate_decision_breaks_candidate_and_section_conservation():
    summary = _catalog_data(decisions=("accepted", "pending")).run.config["programme_catalog_summary"]

    assert summary["candidate_conservation_expected_count"] == 2
    assert summary["candidate_conservation_observed_count"] == 1
    assert summary["candidate_unknown_decision_count"] == 1
    assert summary["candidate_conservation_proven"] is False
    assert summary["identified_catalog_section_count"] == 1
    assert summary["processed_catalog_section_count"] == 0
    assert summary["catalog_section_conservation_proven"] is False
    assert summary["catalog_complete"] is False
    assert summary["catalog_completeness_failure_reasons"] == [
        "candidate_conservation_proven",
        "catalog_section_conservation_proven",
    ]
    assert summary["catalog_completeness_failure_stages"] == ["completeness_proof"]
    assert summary["catalog_completeness_failure_stage_counts"] == {"completeness_proof": 2}
    assert summary["recommended_next_action"] == "repair_candidate_conservation"


def test_faculty_catalog_cannot_claim_complete_without_canonical_source():
    summary = _catalog_data(source_role="faculty_catalog").run.config["programme_catalog_summary"]

    assert summary["source_role_counts"] == {"faculty_catalog": 1}
    assert summary["accepted_by_source_role"] == {"faculty_catalog": 1}
    assert summary["canonical_catalog_captured"] is False
    assert summary["canonical_catalog_accepted"] is False
    assert summary["catalog_complete"] is False
    assert summary["catalog_completeness_failure_reasons"] == [
        "canonical_catalog_captured",
        "canonical_catalog_accepted",
        "catalog_section_conservation_proven",
    ]
    assert summary["catalog_completeness_failure_stages"] == [
        "discovery",
        "segmentation",
        "completeness_proof",
    ]
    assert summary["catalog_completeness_failure_stage_counts"] == {
        "discovery": 1,
        "segmentation": 1,
        "completeness_proof": 1,
    }
    assert summary["recommended_next_action"] == "capture_canonical_catalog"
