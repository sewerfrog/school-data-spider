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
from university_admissions_crawler.reports.structured_export import (
    STRUCTURED_OUTPUT_SCHEMA_VERSION,
    STRUCTURED_PROGRAMME_CATALOG_CSV_FIELDS,
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
                "programme_catalog_summary": {"accepted_row_count": 1, "probable_incomplete_catalog": False},
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
        assert manifest["counts"]["programmes_legacy"] == 1
        assert manifest["counts"]["facts"] == 4
        assert manifest["files"]["programme_catalog_jsonl"] == "records/programme_catalog.jsonl"
        assert manifest["files"]["fees_jsonl"] == "records/fees.jsonl"
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
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        first_dir = root / "example-u"
        second_dir = root / "second-u"
        write_structured_outputs(first, first_dir / "structured")
        write_structured_outputs(second, second_dir / "structured")

        paths = write_structured_batch_outputs([first_dir, second_dir], root / "structured")

        assert paths["all_programme_catalog"] == root / "structured" / "all_programme_catalog.jsonl"
        programme_rows = _read_jsonl(root / "structured" / "all_programme_catalog.jsonl")
        missing_rows = _read_jsonl(root / "structured" / "all_missing_fields.jsonl")
        source_rows = _read_jsonl(root / "structured" / "all_sources.jsonl")

        assert [row["university_id"] for row in programme_rows] == ["example-u", "second-u"]
        assert [row["university_id"] for row in missing_rows] == ["example-u", "second-u"]
        assert [row["university_id"] for row in source_rows] == ["example-u", "second-u"]
        assert {row["schema_version"] for row in programme_rows} == {STRUCTURED_OUTPUT_SCHEMA_VERSION}


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
