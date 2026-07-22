from copy import deepcopy
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from university_admissions_crawler.evidence.provenance import evidence_from_source, source_from_text
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    ClaimStatus,
    Confidence,
    FieldValue,
    Institution,
    ProgrammeRecord,
    ProgrammeCatalogRecord,
    RequirementRecord,
    RunMetadata,
    WarningCode,
    WarningRecord,
)
from university_admissions_crawler.pipeline.output_writer import write_result_files
from university_admissions_crawler.pipeline.incremental_diff import apply_incremental_diff
from university_admissions_crawler.reports.structured_export import (
    STRUCTURED_OUTPUT_SCHEMA_VERSION,
    STRUCTURED_PROGRAMME_CATALOG_CSV_FIELDS,
    STRUCTURED_REQUIREMENT_RECORD_SPECS,
    write_structured_batch_outputs,
    write_structured_outputs,
)


def _structured_data(
    *,
    university_id: str = "example-u",
    institution_name: str = "Example University",
    homepage_url: str = "https://example.edu",
) -> AdmissionsData:
    catalog_url = homepage_url.rstrip("/") + "/catalogue/undergraduate/majors"
    source = source_from_text(
        source_url=catalog_url,
        title="Undergraduate Catalogue",
        text="Bachelor of Computing in Computer Science.",
        retrieved_at="2026-06-01T00:00:00+00:00",
    )
    evidence = evidence_from_source(
        claim_path="/programme_catalog/0/name",
        source=source,
        snippet="Bachelor of Computing in Computer Science.",
        confidence=Confidence.HIGH,
    )
    application_evidence = evidence_from_source(
        claim_path="/admissions/application_periods/0/value",
        source=source,
        snippet="Applications close on 31 January 2027.",
        confidence=Confidence.HIGH,
    )
    fee_evidence = evidence_from_source(
        claim_path="/fees/0/value",
        source=source,
        snippet="Tuition fee is SGD 32000 per year.",
        confidence=Confidence.MEDIUM,
    )
    legacy_programme_evidence = evidence_from_source(
        claim_path="/programmes/0/name",
        source=source,
        snippet="Bachelor of Computing in Computer Science.",
        confidence=Confidence.MEDIUM,
    )
    data = AdmissionsData(
        institution=Institution(
            name=FieldValue(value=institution_name, status=ClaimStatus.KNOWN, confidence=Confidence.HIGH),
            homepage_url=homepage_url,
        ),
        run=RunMetadata(
            input_url=homepage_url,
            retrieved_at="2026-06-01T00:00:00+00:00",
            config={
                "university_id": university_id,
                "coverage": {"found": ["programmes"], "missing": ["fees"]},
                "missing_reasons": {
                    "fees": {
                        "reason": "attempted_no_match",
                        "canonical_reason": "attempted_no_match",
                        "action_target": "extractor",
                        "attempt_count": 1,
                        "source_urls": [source.source_url],
                        "next_action": "improve_extractor_or_context_gate",
                        "note": "No supported fee pattern matched.",
                    }
                },
                "programme_catalog_summary": {
                    "candidate_source_count": 1,
                    "accepted_row_count": 1,
                    "accepted_to_candidate_source_ratio": 1.0,
                    "quality_adjustment_applied": True,
                    "quality_adjusted_accepted_row_count": 1,
                    "quality_excluded_accepted_row_count": 0,
                    "quality_exclusion_reason_counts": {},
                    "quality_adjusted_accepted_to_candidate_source_ratio": 1.0,
                    "raw_low_row_yield": False,
                    "low_row_yield": False,
                    "probable_incomplete_catalog": False,
                    "catalog_complete": True,
                    "catalog_completeness_status": "complete",
                    "canonical_catalog_captured": True,
                    "canonical_catalog_accepted": True,
                    "candidate_conservation_expected_count": 1,
                    "candidate_conservation_observed_count": 1,
                    "candidate_unknown_decision_count": 0,
                    "candidate_conservation_proven": True,
                    "identified_catalog_section_count": 1,
                    "processed_catalog_section_count": 1,
                    "catalog_section_conservation_proven": True,
                    "quarantined_candidate_count": 0,
                    "source_role_counts": {"canonical_catalog": 1},
                    "accepted_by_source_role": {"canonical_catalog": 1},
                    "catalog_completeness_basis": ["canonical_catalog_captured"],
                    "catalog_completeness_failure_reasons": [],
                    "catalog_completeness_failure_stages": [],
                    "catalog_completeness_failure_stage_counts": {},
                    "recommended_next_action": "none",
                },
            },
        ),
        sources=[source],
        evidence=[evidence, application_evidence, fee_evidence, legacy_programme_evidence],
    )
    data.admissions.application_periods.append(
        RequirementRecord(
            "application deadline",
            FieldValue(
                value="31 January 2027",
                raw_text="Applications close on 31 January 2027.",
                parsed={"deadline": "2027-01-31"},
                parse_status="parsed",
                status=ClaimStatus.KNOWN,
                confidence=Confidence.HIGH,
                evidence=["/admissions/application_periods/0/value"],
            ),
        )
    )
    data.fees.append(
        RequirementRecord(
            "tuition/fees",
            FieldValue(
                value="SGD 32000 per year",
                raw_text="Tuition fee is SGD 32000 per year.",
                parsed=[{"currency": "SGD", "amount": 32000, "billing_period": "year"}],
                parse_status="parsed",
                status=ClaimStatus.KNOWN,
                confidence=Confidence.MEDIUM,
                evidence=["/fees/0/value"],
            ),
        )
    )
    data.programmes.append(
        ProgrammeRecord(
            name=FieldValue(
                value="Bachelor of Computing in Computer Science",
                status=ClaimStatus.KNOWN,
                confidence=Confidence.MEDIUM,
                evidence=["/programmes/0/name"],
            ),
            degree=FieldValue(value="Bachelor of Computing", status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM),
            faculty_or_school=FieldValue(value="School of Computing", status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM),
            source_url=source.source_url,
            evidence=["/programmes/0/name"],
        )
    )
    data.programme_catalog.append(
        ProgrammeCatalogRecord(
            name="Bachelor of Computing in Computer Science",
            faculty_or_school="School of Computing",
            degree_or_award="Bachelor of Computing (Honours) in Computer Science",
            category="degree_programme",
            mode="full-time",
            duration_or_units="four-year",
            admissions_choice_name="Computer Science",
            specialisations_or_majors=["Artificial Intelligence", "Algorithms"],
            source_url=source.source_url,
            evidence_snippet="Bachelor of Computing in Computer Science.",
            evidence_confidence=Confidence.HIGH,
            evidence_path="/programme_catalog/0/name",
            parse_status="parsed",
            warnings=[
                WarningRecord(
                    WarningCode.NEEDS_MANUAL_CHECK,
                    "category_inferred: Programme category was inferred from row text.",
                    field="/programme_catalog/0/name",
                    source_urls=[source.source_url],
                )
            ],
        )
    )
    return data


def _read_jsonl(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_write_structured_outputs_creates_cleaning_artifacts_with_joinable_ids():
    data = _structured_data()
    with TemporaryDirectory() as tmp:
        paths = write_structured_outputs(data, Path(tmp) / "structured")
        structured = Path(tmp) / "structured"

        assert paths["manifest"] == structured / "manifest.json"
        manifest = json.loads((structured / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["schema_version"] == STRUCTURED_OUTPUT_SCHEMA_VERSION
        assert manifest["run_id"] == "2026-06-01T00-00-00-00-00__example-u"
        assert manifest["counts"]["programme_catalog"] == 1
        assert manifest["counts"]["application_periods"] == 1
        assert manifest["counts"]["fees"] == 1
        assert manifest["counts"]["international_requirements"] == 0
        assert manifest["counts"]["standardized_tests"] == 0
        assert manifest["counts"]["selection_tests_or_interviews"] == 0
        assert manifest["counts"]["visa"] == 0
        assert manifest["counts"]["housing"] == 0
        assert manifest["counts"]["programmes_legacy"] == 1
        assert manifest["counts"]["facts"] == 4
        assert manifest["files"]["programme_catalog_jsonl"] == "records/programme_catalog.jsonl"
        assert manifest["files"]["fees_jsonl"] == "records/fees.jsonl"
        assert manifest["files"]["international_requirements_jsonl"] == "records/international_requirements.jsonl"
        assert manifest["files"]["standardized_tests_jsonl"] == "records/standardized_tests.jsonl"
        assert manifest["files"]["selection_tests_or_interviews_jsonl"] == "records/selection_tests_or_interviews.jsonl"
        assert manifest["files"]["visa_jsonl"] == "records/visa.jsonl"
        assert manifest["files"]["housing_jsonl"] == "records/housing.jsonl"
        assert manifest["files"]["programmes_legacy_jsonl"] == "records/programmes_legacy.jsonl"

        sources = _read_jsonl(structured / "sources.jsonl")
        evidence = _read_jsonl(structured / "evidence.jsonl")
        programme_rows = _read_jsonl(structured / "records" / "programme_catalog.jsonl")
        application_rows = _read_jsonl(structured / "records" / "application_periods.jsonl")
        fee_rows = _read_jsonl(structured / "records" / "fees.jsonl")
        legacy_programme_rows = _read_jsonl(structured / "records" / "programmes_legacy.jsonl")
        facts = _read_jsonl(structured / "facts.jsonl")
        assert {row["record_type"] for row in facts} == {
            "programme_catalog",
            "application_periods",
            "fees",
            "programmes_legacy",
        }
        assert programme_rows[0] in facts

        row = programme_rows[0]
        assert row["record_id"].startswith("programme_catalog__")
        assert row["record_id"] != "programme-catalog-001"
        assert row["normalized_programme_name_key"] == "bachelor-of-computing-in-computer-science"
        assert row["value"]["name"] == "Bachelor of Computing in Computer Science"
        assert row["quality_flags"] == ["category_inferred"]
        assert row["needs_review"] is True

        assert row["source_refs"][0]["source_id"] == sources[0]["source_id"]
        assert row["evidence_refs"][0]["evidence_id"] == evidence[0]["evidence_id"]
        assert evidence[0]["source_id"] == sources[0]["source_id"]
        assert sources[0]["normalized_source_host"] == "example.edu"
        assert sources[0]["normalized_source_path"] == "/catalogue/undergraduate/majors"

        application_row = application_rows[0]
        assert application_row["record_id"].startswith("application_periods__")
        assert application_row["value"]["label"] == "application deadline"
        assert application_row["value"]["parsed"] == {"deadline": "2027-01-31"}
        assert application_row["source_refs"][0]["source_id"] == sources[0]["source_id"]
        assert application_row["evidence_refs"][0]["claim_path"] == "/admissions/application_periods/0/value"

        fee_row = fee_rows[0]
        assert fee_row["record_id"].startswith("fees__")
        assert fee_row["value"]["value"] == "SGD 32000 per year"
        assert fee_row["value"]["parsed"][0]["amount"] == 32000
        assert fee_row["quality_flags"] == []
        assert fee_row["needs_review"] is False

        legacy_row = legacy_programme_rows[0]
        assert legacy_row["record_id"].startswith("programmes_legacy__")
        assert legacy_row["normalized_programme_name_key"] == "bachelor-of-computing-in-computer-science"
        assert legacy_row["value"]["legacy_semantics"].startswith("Compatibility programme record")
        assert legacy_row["value"]["name"] == "Bachelor of Computing in Computer Science"

        missing = _read_jsonl(structured / "missing_fields.jsonl")
        assert missing[0]["field_key"] == "fees"
        assert missing[0]["reason"] == "attempted_no_match"
        assert missing[0]["action_target"] == "extractor"

        warnings = _read_jsonl(structured / "warnings.jsonl")
        assert warnings[0]["scope"] == "programme_catalog"
        assert warnings[0]["record_id"] == row["record_id"]

        diagnostics = json.loads((structured / "diagnostics.json").read_text(encoding="utf-8"))
        assert "diff" not in diagnostics["diagnostics"]
        assert diagnostics["programme_catalog_completeness"] == {
            "status": "complete",
            "catalog_complete": True,
            "probable_incomplete": False,
            "canonical_catalog": {"captured": True, "accepted": True},
            "candidate_conservation": {
                "expected_count": 1,
                "observed_count": 1,
                "unknown_decision_count": 0,
                "proven": True,
            },
            "section_conservation": {
                "identified_count": 1,
                "processed_count": 1,
                "proven": True,
            },
            "row_yield": {
                "candidate_source_count": 1,
                "accepted_row_count": 1,
                "accepted_to_candidate_source_ratio": 1.0,
                "quality_adjustment_applied": True,
                "quality_adjusted_accepted_row_count": 1,
                "quality_excluded_accepted_row_count": 0,
                "quality_exclusion_reason_counts": {},
                "quality_adjusted_accepted_to_candidate_source_ratio": 1.0,
                "raw_low_row_yield": False,
                "low_row_yield": False,
            },
            "quarantined_candidate_count": 0,
            "source_role_counts": {"canonical_catalog": 1},
            "accepted_by_source_role": {"canonical_catalog": 1},
            "basis": ["canonical_catalog_captured"],
            "failure_reasons": [],
            "failure_stages": [],
            "failure_stage_counts": {},
            "recommended_next_action": "none",
        }


def test_structured_outputs_cover_all_incremental_requirement_collections():
    data = _structured_data()
    records = (
        (
            data.admissions.international_requirements,
            "international_requirements",
            "international requirement",
        ),
        (data.admissions.standardized_tests, "standardized_tests", "standardized test"),
        (
            data.admissions.selection_tests_or_interviews,
            "selection_tests_or_interviews",
            "selection interview",
        ),
        (data.visa, "visa", "student visa"),
        (data.housing, "housing", "student housing"),
    )
    for target, _record_type, label in records:
        target.append(
            RequirementRecord(
                label,
                FieldValue(
                    value=f"Known {label}",
                    status=ClaimStatus.KNOWN,
                    confidence=Confidence.MEDIUM,
                ),
            )
        )

    with TemporaryDirectory() as tmp:
        structured = Path(tmp) / "structured"
        write_structured_outputs(data, structured)
        manifest = json.loads((structured / "manifest.json").read_text(encoding="utf-8"))
        facts = _read_jsonl(structured / "facts.jsonl")
        exported = {
            record_type: _read_jsonl(structured / "records" / f"{record_type}.jsonl")
            for _target, record_type, _label in records
        }

    for _target, record_type, _label in records:
        assert manifest["counts"][record_type] == 1
        assert manifest["files"][f"{record_type}_jsonl"] == f"records/{record_type}.jsonl"
        assert len(exported[record_type]) == 1
        assert exported[record_type][0]["record_type"] == record_type
        assert exported[record_type][0] in facts


def test_structured_diagnostics_preserve_incremental_diff_and_semantic_warning():
    data = _structured_data()
    previous = data.to_dict()
    retired_fee = deepcopy(previous["fees"][0])
    retired_fee["label"] = "retired fee"
    retired_fee["value"]["value"] = "SGD 1,000"
    previous["fees"].append(retired_fee)
    apply_incremental_diff(data, previous)

    with TemporaryDirectory() as tmp:
        structured = Path(tmp) / "structured"
        write_structured_outputs(data, structured)
        diagnostics = json.loads((structured / "diagnostics.json").read_text(encoding="utf-8"))
        warnings = _read_jsonl(structured / "warnings.jsonl")

    assert diagnostics["diagnostics"]["diff"] == data.run.config["diff"]
    incremental_warning = next(row for row in warnings if row["code"] == "incremental_change")
    assert incremental_warning["scope"] == "run"
    assert incremental_warning["field"] == "/fees"
    assert incremental_warning["message"].endswith("0 added, 1 removed, 0 changed rows.")


def test_structured_programme_catalog_exposes_optional_field_evidence_refs_without_changing_csv():
    data = _structured_data()
    field_paths = {
        "degree_or_award": "/programme_catalog/0/degree_or_award",
        "faculty_or_school": "/programme_catalog/0/faculty_or_school",
    }
    for field_name, claim_path in field_paths.items():
        data.evidence.append(
            evidence_from_source(
                claim_path=claim_path,
                source=data.sources[0],
                snippet=f"Inherited context for {field_name}",
                confidence=Confidence.MEDIUM,
            )
        )
    data.run.config["programme_catalog_field_evidence"] = {
        "/programme_catalog/0/name": field_paths,
    }
    data.run.config["programme_catalog_candidate_diagnostics"] = [
        {
            "source_url": data.sources[0].source_url,
            "candidate_text": "Bachelor of Computing in Computer Science",
            "decision": "accepted",
            "reason": "accepted_parsed",
            "parser_stage": "emit_row",
            "field_evidence_paths": field_paths,
        }
    ]

    with TemporaryDirectory() as tmp:
        structured = Path(tmp) / "structured"
        write_structured_outputs(data, structured)

        row = _read_jsonl(structured / "records" / "programme_catalog.jsonl")[0]
        evidence_rows = _read_jsonl(structured / "evidence.jsonl")
        diagnostics = json.loads((structured / "diagnostics.json").read_text(encoding="utf-8"))
        csv_header = (structured / "records" / "programme_catalog.csv").read_text(encoding="utf-8").splitlines()[0]

    assert row["raw"]["field_evidence_paths"] == field_paths
    assert row["evidence_refs"][0] == {
        "evidence_id": row["evidence_refs"][0]["evidence_id"],
        "claim_path": "/programme_catalog/0/name",
    }
    assert {(item["field"], item["claim_path"]) for item in row["evidence_refs"][1:]} == set(field_paths.items())
    assert set(field_paths.values()).issubset({item["claim_path"] for item in evidence_rows})
    assert diagnostics["diagnostics"]["programme_catalog_candidate_diagnostics"][0]["reason"] == "accepted_parsed"
    assert diagnostics["diagnostics"]["programme_catalog_field_evidence"] == {
        "/programme_catalog/0/name": field_paths,
    }
    assert csv_header.split(",") == list(STRUCTURED_PROGRAMME_CATALOG_CSV_FIELDS)


def test_structured_completeness_contract_preserves_failure_reasons_and_stages():
    data = _structured_data()
    summary = data.run.config["programme_catalog_summary"]
    summary.update(
        {
            "catalog_complete": False,
            "probable_incomplete_catalog": True,
            "catalog_completeness_status": "probable_incomplete",
            "canonical_catalog_accepted": False,
            "catalog_completeness_basis": ["canonical_catalog_captured"],
            "catalog_completeness_failure_reasons": [
                "canonical_catalog_accepted",
                "no_manual_review_rows",
            ],
            "catalog_completeness_failure_stages": ["segmentation", "entity_gate"],
            "catalog_completeness_failure_stage_counts": {"segmentation": 1, "entity_gate": 1},
            "recommended_next_action": "review_catalog_warnings",
        }
    )

    with TemporaryDirectory() as tmp:
        structured = Path(tmp) / "structured"
        write_structured_outputs(data, structured)
        diagnostics = json.loads((structured / "diagnostics.json").read_text(encoding="utf-8"))

    completeness = diagnostics["programme_catalog_completeness"]
    assert completeness["status"] == "probable_incomplete"
    assert completeness["canonical_catalog"]["accepted"] is False
    assert completeness["basis"] == ["canonical_catalog_captured"]
    assert completeness["failure_reasons"] == [
        "canonical_catalog_accepted",
        "no_manual_review_rows",
    ]
    assert completeness["failure_stages"] == ["segmentation", "entity_gate"]
    assert completeness["failure_stage_counts"] == {"segmentation": 1, "entity_gate": 1}
    assert completeness["recommended_next_action"] == "review_catalog_warnings"


def test_structured_programme_catalog_csv_is_cleaning_friendly():
    data = _structured_data()
    with TemporaryDirectory() as tmp:
        write_structured_outputs(data, Path(tmp) / "structured")
        csv_path = Path(tmp) / "structured" / "records" / "programme_catalog.csv"
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))

        assert rows
        assert list(rows[0]) == list(STRUCTURED_PROGRAMME_CATALOG_CSV_FIELDS)
        row = rows[0]
        assert row["record_id"].startswith("programme_catalog__")
        assert row["specialisations_or_majors"] == "Artificial Intelligence; Algorithms"
        assert row["quality_flags"] == "category_inferred"
        assert row["warnings_count"] == "1"
        assert row["needs_review"] == "true"
        assert row["source_id"]
        assert row["evidence_id"]


def test_write_result_files_preserves_legacy_outputs_and_adds_structured_directory():
    data = _structured_data()
    with TemporaryDirectory() as tmp:
        result_path, report_path = write_result_files(data, tmp)

        assert result_path == Path(tmp) / "result.json"
        assert report_path == Path(tmp) / "report.md"
        assert (Path(tmp) / "programme_catalog.csv").exists()
        assert (Path(tmp) / "structured" / "manifest.json").exists()
        assert (Path(tmp) / "structured" / "records" / "programme_catalog.jsonl").exists()
        assert (Path(tmp) / "structured" / "records" / "fees.jsonl").exists()
        assert json.loads(result_path.read_text(encoding="utf-8"))["programme_catalog"]


def test_write_structured_batch_outputs_merges_batch_cleaning_tables():
    first = _structured_data()
    second = _structured_data(
        university_id="second-u",
        institution_name="Second University",
        homepage_url="https://second.example.edu",
    )
    first.visa.append(
        RequirementRecord(
            "student visa",
            FieldValue(value="Visa guidance", status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM),
        )
    )
    second.housing.append(
        RequirementRecord(
            "student housing",
            FieldValue(value="Housing guidance", status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM),
        )
    )
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        first_dir = root / "example-u"
        second_dir = root / "second-u"
        write_structured_outputs(first, first_dir / "structured")
        write_structured_outputs(second, second_dir / "structured")

        paths = write_structured_batch_outputs([first_dir, second_dir], root / "structured")

        assert paths["manifest"] == root / "structured" / "manifest.json"
        assert paths["all_programme_catalog"] == root / "structured" / "all_programme_catalog.jsonl"
        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        programme_rows = _read_jsonl(root / "structured" / "all_programme_catalog.jsonl")
        missing_rows = _read_jsonl(root / "structured" / "all_missing_fields.jsonl")
        source_rows = _read_jsonl(root / "structured" / "all_sources.jsonl")
        application_rows = _read_jsonl(root / "structured" / "all_application_periods.jsonl")
        visa_rows = _read_jsonl(root / "structured" / "all_visa.jsonl")
        housing_rows = _read_jsonl(root / "structured" / "all_housing.jsonl")

        assert [row["university_id"] for row in programme_rows] == ["example-u", "second-u"]
        assert [row["university_id"] for row in missing_rows] == ["example-u", "second-u"]
        assert [row["university_id"] for row in source_rows] == ["example-u", "second-u"]
        assert [row["university_id"] for row in application_rows] == ["example-u", "second-u"]
        assert [row["university_id"] for row in visa_rows] == ["example-u"]
        assert [row["university_id"] for row in housing_rows] == ["second-u"]
        assert {row["schema_version"] for row in programme_rows} == {STRUCTURED_OUTPUT_SCHEMA_VERSION}
        assert manifest["schema_version"] == STRUCTURED_OUTPUT_SCHEMA_VERSION
        assert manifest["output_type"] == "batch"
        assert manifest["university_output_count"] == 2
        assert manifest["input_directory_names"] == ["example-u", "second-u"]
        assert manifest["counts"]["all_application_periods"] == 2
        assert manifest["counts"]["all_visa"] == 1
        assert manifest["counts"]["all_housing"] == 1
        assert manifest["input_coverage"]["all_application_periods"] == {
            "expected_file_count": 2,
            "present_file_count": 2,
            "missing_file_count": 0,
            "nonempty_file_count": 2,
            "empty_file_count": 0,
            "missing_input_directory_names": [],
            "nonempty_input_directory_names": ["example-u", "second-u"],
            "empty_input_directory_names": [],
            "all_input_files_present": True,
        }
        assert manifest["input_coverage"]["all_visa"] == {
            "expected_file_count": 2,
            "present_file_count": 2,
            "missing_file_count": 0,
            "nonempty_file_count": 1,
            "empty_file_count": 1,
            "missing_input_directory_names": [],
            "nonempty_input_directory_names": ["example-u"],
            "empty_input_directory_names": ["second-u"],
            "all_input_files_present": True,
        }
        assert manifest["input_coverage"]["all_international_requirements"] == {
            "expected_file_count": 2,
            "present_file_count": 2,
            "missing_file_count": 0,
            "nonempty_file_count": 0,
            "empty_file_count": 2,
            "missing_input_directory_names": [],
            "nonempty_input_directory_names": [],
            "empty_input_directory_names": ["example-u", "second-u"],
            "all_input_files_present": True,
        }
        assert set(manifest["input_coverage"]) == set(manifest["counts"]) == set(manifest["files"])
        assert set(manifest["input_validation"]) == set(manifest["counts"])
        assert manifest["input_validation_summary"] == {
            "table_count": len(manifest["counts"]),
            "row_count": sum(manifest["counts"].values()),
            "valid_row_count": sum(manifest["counts"].values()),
            "invalid_row_count": 0,
            "invalid_file_count": 0,
            "invalid_table_count": 0,
            "all_rows_valid": True,
        }
        assert manifest["reference_index_coverage"]["sources"]["usable_identifier_count"] == 2
        expected_evidence_identifier_count = sum(
            len(_read_jsonl(university_dir / "structured" / "evidence.jsonl"))
            for university_dir in (first_dir, second_dir)
        )
        assert (
            manifest["reference_index_coverage"]["evidence"]["usable_identifier_count"]
            == expected_evidence_identifier_count
        )
        assert manifest["reference_index_coverage"]["sources"]["all_index_files_readable"] is True
        assert manifest["reference_index_coverage"]["evidence"]["all_index_files_readable"] is True
        assert manifest["evidence_validation"]["invalid_row_count"] == 0
        assert manifest["evidence_validation"]["all_rows_valid"] is True
        assert manifest["batch_validation"] == {
            "status": "valid",
            "ready_for_structured_consumption": True,
            "reason_codes": [],
            "metrics": {
                "university_output_count": 2,
                "missing_input_file_count": 0,
                "invalid_input_file_count": 0,
                "invalid_input_row_count": 0,
                "missing_reference_index_file_count": 0,
                "unreadable_reference_index_file_count": 0,
                "invalid_reference_identifier_row_count": 0,
                "duplicate_reference_identifier_count": 0,
                "duplicate_reference_identifier_row_count": 0,
                "invalid_evidence_file_count": 0,
                "invalid_evidence_row_count": 0,
            },
            "note": (
                "This verdict covers structured artifact integrity, not crawl or "
                "admissions-data completeness."
            ),
        }
        for coverage in manifest["input_coverage"].values():
            assert (
                coverage["present_file_count"] + coverage["missing_file_count"]
                == coverage["expected_file_count"]
            )
            assert (
                coverage["nonempty_file_count"] + coverage["empty_file_count"]
                == coverage["present_file_count"]
            )
        for validation in manifest["input_validation"].values():
            assert validation["row_count"] == validation["valid_row_count"]
            assert validation["invalid_row_count"] == 0
            assert validation["all_rows_valid"] is True
        for record_type, _path in STRUCTURED_REQUIREMENT_RECORD_SPECS:
            key = f"all_{record_type}"
            assert paths[key] == root / "structured" / f"{key}.jsonl"
            assert manifest["files"][key] == f"{key}.jsonl"
            assert key in manifest["counts"]


def test_structured_batch_validation_is_incomplete_for_missing_input_file_only():
    data = _structured_data(university_id="incomplete-u")
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        university_dir = root / "incomplete-u"
        write_structured_outputs(data, university_dir / "structured")
        (university_dir / "structured" / "records" / "visa.jsonl").unlink()

        write_structured_batch_outputs([university_dir], root / "structured")

        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["batch_validation"] == {
            "status": "incomplete",
            "ready_for_structured_consumption": False,
            "reason_codes": ["missing_input_files"],
            "metrics": {
                "university_output_count": 1,
                "missing_input_file_count": 1,
                "invalid_input_file_count": 0,
                "invalid_input_row_count": 0,
                "missing_reference_index_file_count": 0,
                "unreadable_reference_index_file_count": 0,
                "invalid_reference_identifier_row_count": 0,
                "duplicate_reference_identifier_count": 0,
                "duplicate_reference_identifier_row_count": 0,
                "invalid_evidence_file_count": 0,
                "invalid_evidence_row_count": 0,
            },
            "note": (
                "This verdict covers structured artifact integrity, not crawl or "
                "admissions-data completeness."
            ),
        }


def test_structured_batch_validation_is_incomplete_without_university_inputs():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)

        write_structured_batch_outputs([], root / "structured")

        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["batch_validation"] == {
            "status": "incomplete",
            "ready_for_structured_consumption": False,
            "reason_codes": ["no_university_inputs"],
            "metrics": {
                "university_output_count": 0,
                "missing_input_file_count": 0,
                "invalid_input_file_count": 0,
                "invalid_input_row_count": 0,
                "missing_reference_index_file_count": 0,
                "unreadable_reference_index_file_count": 0,
                "invalid_reference_identifier_row_count": 0,
                "duplicate_reference_identifier_count": 0,
                "duplicate_reference_identifier_row_count": 0,
                "invalid_evidence_file_count": 0,
                "invalid_evidence_row_count": 0,
            },
            "note": (
                "This verdict covers structured artifact integrity, not crawl or "
                "admissions-data completeness."
            ),
        }


def test_structured_batch_outputs_accept_legacy_directories_without_requirement_files():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        legacy_structured = root / "legacy-u" / "structured"
        legacy_structured.mkdir(parents=True)
        (legacy_structured / "sources.jsonl").write_text(
            json.dumps(
                {
                    "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                    "university_id": "legacy-u",
                    "source_url": "https://legacy.example.edu",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        write_structured_batch_outputs([root / "legacy-u"], root / "structured")
        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        source_rows = _read_jsonl(root / "structured" / "all_sources.jsonl")

        assert [row["university_id"] for row in source_rows] == ["legacy-u"]
        assert manifest["input_validation_summary"] == {
            "table_count": len(STRUCTURED_REQUIREMENT_RECORD_SPECS) + 3,
            "row_count": 1,
            "valid_row_count": 0,
            "invalid_row_count": 1,
            "invalid_file_count": 1,
            "invalid_table_count": 1,
            "all_rows_valid": False,
        }
        assert manifest["input_validation"]["all_sources"] == {
            "row_count": 1,
            "valid_row_count": 0,
            "invalid_row_count": 1,
            "invalid_file_count": 1,
            "invalid_input_directory_names": ["legacy-u"],
            "reason_counts": {
                "missing_required_field:run_id": 1,
                "missing_required_field:source_id": 1,
            },
            "invalid_files": [
                {
                    "input_directory_name": "legacy-u",
                    "source_file": "structured/sources.jsonl",
                    "row_count": 1,
                    "valid_row_count": 0,
                    "invalid_row_count": 1,
                    "reason_counts": {
                        "missing_required_field:run_id": 1,
                        "missing_required_field:source_id": 1,
                    },
                }
            ],
            "all_rows_valid": False,
        }
        assert manifest["reference_index_coverage"]["sources"]["invalid_identifier_row_count"] == 1
        assert manifest["reference_index_coverage"]["evidence"]["missing_input_directory_names"] == [
            "legacy-u"
        ]
        assert {
            "invalid_reference_identifier_rows",
            "missing_reference_index_files",
        } <= set(manifest["batch_validation"]["reason_codes"])
        assert manifest["input_coverage"]["all_sources"] == {
            "expected_file_count": 1,
            "present_file_count": 1,
            "missing_file_count": 0,
            "nonempty_file_count": 1,
            "empty_file_count": 0,
            "missing_input_directory_names": [],
            "nonempty_input_directory_names": ["legacy-u"],
            "empty_input_directory_names": [],
            "all_input_files_present": True,
        }
        for record_type, _path in STRUCTURED_REQUIREMENT_RECORD_SPECS:
            key = f"all_{record_type}"
            assert manifest["counts"][key] == 0
            assert (root / "structured" / f"{key}.jsonl").read_text(encoding="utf-8") == ""
            assert manifest["input_coverage"][key] == {
                "expected_file_count": 1,
                "present_file_count": 0,
                "missing_file_count": 1,
                "nonempty_file_count": 0,
                "empty_file_count": 0,
                "missing_input_directory_names": ["legacy-u"],
                "nonempty_input_directory_names": [],
                "empty_input_directory_names": [],
                "all_input_files_present": False,
            }


def test_structured_batch_outputs_audit_invalid_row_envelopes_without_dropping_rows():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        input_path = root / "example-u" / "structured" / "records" / "programme_catalog.jsonl"
        input_path.parent.mkdir(parents=True)
        input_rows = [
            {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "run_id": "run-example-u",
                "university_id": "example-u",
                "record_type": "programme_catalog",
                "record_id": "programme_catalog__valid",
                "value": {},
                "source_refs": [],
                "evidence_refs": [],
            },
            {
                "schema_version": "structured-output-v0",
                "university_id": "wrong-u",
                "record_type": "fees",
            },
            {"university_id": "example-u", "record_type": "programme_catalog"},
            {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "record_type": "programme_catalog",
            },
            {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "university_id": "example-u",
            },
            {"schema_version": 1, "university_id": 2, "record_type": []},
            [],
        ]
        input_path.write_text(
            "".join(json.dumps(row) + "\n" for row in input_rows),
            encoding="utf-8",
        )

        write_structured_batch_outputs([root / "example-u"], root / "structured")

        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        aggregate_rows = _read_jsonl(root / "structured" / "all_programme_catalog.jsonl")
        validation = manifest["input_validation"]["all_programme_catalog"]

        assert aggregate_rows == input_rows
        assert validation == {
            "row_count": 7,
            "valid_row_count": 1,
            "invalid_row_count": 6,
            "invalid_file_count": 1,
            "invalid_input_directory_names": ["example-u"],
            "reason_counts": {
                "invalid_record_type": 1,
                "invalid_schema_version": 1,
                "invalid_university_id": 1,
                "missing_schema_version": 1,
                "missing_record_type": 1,
                "missing_university_id": 1,
                "record_type_mismatch": 1,
                "row_not_object": 1,
                "schema_version_mismatch": 1,
                "university_id_mismatch": 1,
            },
            "invalid_files": [
                {
                    "input_directory_name": "example-u",
                    "source_file": "structured/records/programme_catalog.jsonl",
                    "row_count": 7,
                    "valid_row_count": 1,
                    "invalid_row_count": 6,
                    "reason_counts": {
                        "invalid_record_type": 1,
                        "invalid_schema_version": 1,
                        "invalid_university_id": 1,
                        "missing_schema_version": 1,
                        "missing_record_type": 1,
                        "missing_university_id": 1,
                        "record_type_mismatch": 1,
                        "row_not_object": 1,
                        "schema_version_mismatch": 1,
                        "university_id_mismatch": 1,
                    },
                }
            ],
            "all_rows_valid": False,
        }
        assert manifest["input_validation_summary"] == {
            "table_count": len(STRUCTURED_REQUIREMENT_RECORD_SPECS) + 3,
            "row_count": 7,
            "valid_row_count": 1,
            "invalid_row_count": 6,
            "invalid_file_count": 1,
            "invalid_table_count": 1,
            "all_rows_valid": False,
        }


def test_structured_batch_outputs_audit_required_fields_and_unresolved_references():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        university_dir = root / "example-u"
        structured = university_dir / "structured"
        records = structured / "records"
        records.mkdir(parents=True)
        source_rows = [
            {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "run_id": "run-example-u",
                "university_id": "example-u",
                "source_id": "source-1",
                "source_url": "https://example.edu/catalogue",
            }
        ]
        evidence_rows = [
            {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "run_id": "run-example-u",
                "university_id": "example-u",
                "evidence_id": "evidence-1",
                "source_id": "source-1",
            }
        ]
        programme_rows = [
            {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "run_id": "run-example-u",
                "university_id": "example-u",
                "record_type": "programme_catalog",
                "record_id": "programme_catalog__valid",
                "value": {},
                "source_refs": [{"source_id": "source-1"}],
                "evidence_refs": [{"evidence_id": "evidence-1"}],
            },
            {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "university_id": "example-u",
                "record_type": "programme_catalog",
                "record_id": "",
                "value": [],
                "source_refs": "not-a-list",
                "evidence_refs": [],
            },
            {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "run_id": "run-example-u",
                "university_id": "example-u",
                "record_type": "programme_catalog",
                "record_id": "programme_catalog__broken-refs",
                "value": {},
                "source_refs": [[], {}, {"source_id": 3}, {"source_id": "missing-source"}],
                "evidence_refs": [[], {}, {"evidence_id": 4}, {"evidence_id": "missing-evidence"}],
            },
        ]
        for path, rows in (
            (structured / "sources.jsonl", source_rows),
            (structured / "evidence.jsonl", evidence_rows),
            (records / "programme_catalog.jsonl", programme_rows),
        ):
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

        write_structured_batch_outputs([university_dir], root / "structured")

        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        aggregate_rows = _read_jsonl(root / "structured" / "all_programme_catalog.jsonl")
        validation = manifest["input_validation"]["all_programme_catalog"]

        assert aggregate_rows == programme_rows
        assert validation["row_count"] == 3
        assert validation["valid_row_count"] == 1
        assert validation["invalid_row_count"] == 2
        assert validation["reason_counts"] == {
            "empty_required_string:record_id": 1,
            "invalid_evidence_ref": 1,
            "invalid_evidence_ref_id": 1,
            "invalid_required_field_type:source_refs": 1,
            "invalid_required_field_type:value": 1,
            "invalid_source_ref": 1,
            "invalid_source_ref_id": 1,
            "missing_evidence_ref_id": 1,
            "missing_required_field:run_id": 1,
            "missing_source_ref_id": 1,
            "unresolved_evidence_ref": 1,
            "unresolved_source_ref": 1,
        }
        assert manifest["input_validation_summary"] == {
            "table_count": len(STRUCTURED_REQUIREMENT_RECORD_SPECS) + 3,
            "row_count": 4,
            "valid_row_count": 2,
            "invalid_row_count": 2,
            "invalid_file_count": 1,
            "invalid_table_count": 1,
            "all_rows_valid": False,
        }
        assert manifest["reference_index_coverage"] == {
            "sources": {
                "expected_file_count": 1,
                "present_file_count": 1,
                "readable_file_count": 1,
                "missing_file_count": 0,
                "unreadable_file_count": 0,
                "missing_input_directory_names": [],
                "unreadable_input_directory_names": [],
                "invalid_identifier_input_directory_names": [],
                "duplicate_identifier_input_directory_names": [],
                "usable_identifier_count": 1,
                "invalid_identifier_row_count": 0,
                "duplicate_identifier_count": 0,
                "duplicate_identifier_row_count": 0,
                "all_index_files_readable": True,
            },
            "evidence": {
                "expected_file_count": 1,
                "present_file_count": 1,
                "readable_file_count": 1,
                "missing_file_count": 0,
                "unreadable_file_count": 0,
                "missing_input_directory_names": [],
                "unreadable_input_directory_names": [],
                "invalid_identifier_input_directory_names": [],
                "duplicate_identifier_input_directory_names": [],
                "usable_identifier_count": 1,
                "invalid_identifier_row_count": 0,
                "duplicate_identifier_count": 0,
                "duplicate_identifier_row_count": 0,
                "all_index_files_readable": True,
            },
        }


def test_structured_batch_outputs_report_unreadable_evidence_index_without_dropping_rows():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        university_dir = root / "example-u"
        structured = university_dir / "structured"
        records = structured / "records"
        records.mkdir(parents=True)
        programme_row = {
            "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
            "run_id": "run-example-u",
            "university_id": "example-u",
            "record_type": "programme_catalog",
            "record_id": "programme_catalog__unreadable-evidence-index",
            "value": {},
            "source_refs": [],
            "evidence_refs": [{"evidence_id": "evidence-1"}],
        }
        (records / "programme_catalog.jsonl").write_text(
            json.dumps(programme_row) + "\n",
            encoding="utf-8",
        )
        (structured / "evidence.jsonl").write_text("{invalid-json\n", encoding="utf-8")

        write_structured_batch_outputs([university_dir], root / "structured")

        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        assert _read_jsonl(root / "structured" / "all_programme_catalog.jsonl") == [programme_row]
        assert manifest["input_validation"]["all_programme_catalog"]["reason_counts"] == {
            "evidence_reference_index_unavailable": 1
        }
        assert manifest["reference_index_coverage"]["evidence"] == {
            "expected_file_count": 1,
            "present_file_count": 1,
            "readable_file_count": 0,
            "missing_file_count": 0,
            "unreadable_file_count": 1,
            "missing_input_directory_names": [],
            "unreadable_input_directory_names": ["example-u"],
            "invalid_identifier_input_directory_names": [],
            "duplicate_identifier_input_directory_names": [],
            "usable_identifier_count": 0,
            "invalid_identifier_row_count": 0,
            "duplicate_identifier_count": 0,
            "duplicate_identifier_row_count": 0,
            "all_index_files_readable": False,
        }
        assert "unreadable_reference_index_files" in manifest["batch_validation"]["reason_codes"]
        assert manifest["batch_validation"]["metrics"]["unreadable_reference_index_file_count"] == 1


def test_structured_batch_outputs_audit_duplicate_indexes_and_evidence_source_links():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        university_dir = root / "example-u"
        structured = university_dir / "structured"
        records = structured / "records"
        records.mkdir(parents=True)

        def source_row(source_id: str, suffix: str) -> dict:
            return {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "run_id": "run-example-u",
                "university_id": "example-u",
                "source_id": source_id,
                "source_url": f"https://example.edu/{suffix}",
            }

        def evidence_row(evidence_id: str, source_id: object = "source-1") -> dict:
            row = {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "run_id": "run-example-u",
                "university_id": "example-u",
                "evidence_id": evidence_id,
            }
            if source_id is not None:
                row["source_id"] = source_id
            return row

        source_rows = [
            source_row("source-1", "one"),
            source_row("source-duplicate", "duplicate-a"),
            source_row("source-duplicate", "duplicate-b"),
        ]
        evidence_rows = [
            evidence_row("evidence-1"),
            evidence_row("evidence-2", "missing-source"),
            evidence_row("evidence-3", None),
            evidence_row("evidence-4", 4),
            evidence_row("evidence-5", "source-duplicate"),
            evidence_row("evidence-duplicate"),
            evidence_row("evidence-duplicate"),
        ]
        programme_row = {
            "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
            "run_id": "run-example-u",
            "university_id": "example-u",
            "record_type": "programme_catalog",
            "record_id": "programme_catalog__ambiguous-refs",
            "value": {},
            "source_refs": [{"source_id": "source-duplicate"}],
            "evidence_refs": [{"evidence_id": "evidence-duplicate"}],
        }
        for path, rows in (
            (structured / "sources.jsonl", source_rows),
            (structured / "evidence.jsonl", evidence_rows),
            (records / "programme_catalog.jsonl", [programme_row]),
        ):
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

        write_structured_batch_outputs([university_dir], root / "structured")

        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        assert _read_jsonl(root / "structured" / "all_sources.jsonl") == source_rows
        assert _read_jsonl(root / "structured" / "all_programme_catalog.jsonl") == [programme_row]
        assert manifest["input_validation"]["all_sources"]["reason_counts"] == {
            "duplicate_source_id": 2
        }
        assert manifest["input_validation"]["all_programme_catalog"]["reason_counts"] == {
            "ambiguous_evidence_ref": 1,
            "ambiguous_source_ref": 1,
        }
        assert manifest["input_validation_summary"] == {
            "table_count": len(STRUCTURED_REQUIREMENT_RECORD_SPECS) + 3,
            "row_count": 4,
            "valid_row_count": 1,
            "invalid_row_count": 3,
            "invalid_file_count": 2,
            "invalid_table_count": 2,
            "all_rows_valid": False,
        }
        assert manifest["reference_index_coverage"]["sources"]["usable_identifier_count"] == 1
        assert manifest["reference_index_coverage"]["sources"]["duplicate_identifier_count"] == 1
        assert manifest["reference_index_coverage"]["sources"]["duplicate_identifier_row_count"] == 2
        assert manifest["reference_index_coverage"]["evidence"]["usable_identifier_count"] == 5
        assert manifest["reference_index_coverage"]["evidence"]["duplicate_identifier_count"] == 1
        assert manifest["reference_index_coverage"]["evidence"]["duplicate_identifier_row_count"] == 2
        assert manifest["evidence_validation"] == {
            "row_count": 7,
            "valid_row_count": 1,
            "invalid_row_count": 6,
            "invalid_file_count": 1,
            "invalid_input_directory_names": ["example-u"],
            "reason_counts": {
                "ambiguous_source_ref": 1,
                "duplicate_evidence_id": 2,
                "invalid_source_ref_id": 1,
                "missing_source_ref_id": 1,
                "unresolved_source_ref": 1,
            },
            "all_rows_valid": False,
        }
        assert manifest["batch_validation"]["status"] == "invalid"
        assert manifest["batch_validation"]["ready_for_structured_consumption"] is False
        assert manifest["batch_validation"]["reason_codes"] == [
            "duplicate_reference_identifiers",
            "invalid_evidence_rows",
            "invalid_input_rows",
            "missing_input_files",
        ]
        assert manifest["batch_validation"]["metrics"]["duplicate_reference_identifier_count"] == 2
        assert manifest["batch_validation"]["metrics"]["duplicate_reference_identifier_row_count"] == 4


def test_structured_batch_outputs_audit_duplicate_record_ids_across_record_tables():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        university_dir = root / "example-u"
        records = university_dir / "structured" / "records"
        records.mkdir(parents=True)

        def record_row(record_type: str) -> dict:
            return {
                "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
                "run_id": "run-example-u",
                "university_id": "example-u",
                "record_type": record_type,
                "record_id": "shared-record-id",
                "value": {},
                "source_refs": [],
                "evidence_refs": [],
            }

        programme_rows = [record_row("programme_catalog"), record_row("programme_catalog")]
        fee_rows = [record_row("fees")]
        (records / "programme_catalog.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in programme_rows),
            encoding="utf-8",
        )
        (records / "fees.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in fee_rows),
            encoding="utf-8",
        )

        write_structured_batch_outputs([university_dir], root / "structured")

        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        assert _read_jsonl(root / "structured" / "all_programme_catalog.jsonl") == programme_rows
        assert _read_jsonl(root / "structured" / "all_fees.jsonl") == fee_rows
        assert manifest["input_validation"]["all_programme_catalog"]["reason_counts"] == {
            "duplicate_record_id": 2
        }
        assert manifest["input_validation"]["all_fees"]["reason_counts"] == {
            "duplicate_record_id": 1
        }
        assert manifest["input_validation_summary"] == {
            "table_count": len(STRUCTURED_REQUIREMENT_RECORD_SPECS) + 3,
            "row_count": 3,
            "valid_row_count": 0,
            "invalid_row_count": 3,
            "invalid_file_count": 2,
            "invalid_table_count": 2,
            "all_rows_valid": False,
        }


def test_structured_batch_outputs_report_unavailable_source_index_for_evidence_links():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        university_dir = root / "example-u"
        structured = university_dir / "structured"
        structured.mkdir(parents=True)
        evidence_row = {
            "schema_version": STRUCTURED_OUTPUT_SCHEMA_VERSION,
            "run_id": "run-example-u",
            "university_id": "example-u",
            "evidence_id": "evidence-1",
            "source_id": "source-1",
        }
        (structured / "evidence.jsonl").write_text(
            json.dumps(evidence_row) + "\n",
            encoding="utf-8",
        )

        write_structured_batch_outputs([university_dir], root / "structured")

        manifest = json.loads((root / "structured" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["evidence_validation"] == {
            "row_count": 1,
            "valid_row_count": 0,
            "invalid_row_count": 1,
            "invalid_file_count": 1,
            "invalid_input_directory_names": ["example-u"],
            "reason_counts": {"source_reference_index_unavailable": 1},
            "all_rows_valid": False,
        }
        assert manifest["reference_index_coverage"]["sources"]["missing_input_directory_names"] == [
            "example-u"
        ]
        assert "missing_reference_index_files" in manifest["batch_validation"]["reason_codes"]
        assert manifest["batch_validation"]["metrics"]["missing_reference_index_file_count"] == 1


def test_structured_outputs_exist_even_without_programme_catalog():
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(input_url="https://example.edu", retrieved_at="2026-06-01T00:00:00+00:00"),
    )
    with TemporaryDirectory() as tmp:
        write_result_files(data, tmp)
        structured = Path(tmp) / "structured"

        assert not (Path(tmp) / "programme_catalog.csv").exists()
        assert (structured / "manifest.json").exists()
        assert (structured / "sources.jsonl").read_text(encoding="utf-8") == ""
        assert (structured / "records" / "programme_catalog.jsonl").read_text(encoding="utf-8") == ""
        assert (structured / "records" / "fees.jsonl").read_text(encoding="utf-8") == ""
        assert (structured / "records" / "application_periods.jsonl").read_text(encoding="utf-8") == ""
        assert (structured / "records" / "programmes_legacy.jsonl").read_text(encoding="utf-8") == ""
        csv_text = (structured / "records" / "programme_catalog.csv").read_text(encoding="utf-8")
        assert csv_text.splitlines()[0].split(",") == list(STRUCTURED_PROGRAMME_CATALOG_CSV_FIELDS)
