import csv
import io
from tempfile import TemporaryDirectory
from pathlib import Path

from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    ClaimStatus,
    Confidence,
    FieldValue,
    Institution,
    ProgrammeCatalogRecord,
    RunMetadata,
)
from university_admissions_crawler.pipeline.output_writer import write_result_files
from university_admissions_crawler.reports.programme_catalog_csv import PROGRAMME_CATALOG_CSV_FIELDS, render_programme_catalog_csv


def _catalog_data() -> AdmissionsData:
    source = source_from_text(
        source_url="https://example.edu/catalogue/undergraduate/majors",
        title="Undergraduate Catalogue",
        text="Bachelor of Computing in Computer Science.",
        retrieved_at="2026-06-01T00:00:00+00:00",
    )
    data = AdmissionsData(
        institution=Institution(
            name=FieldValue(value="Example University", status=ClaimStatus.KNOWN, confidence=Confidence.HIGH),
            homepage_url="https://example.edu",
        ),
        run=RunMetadata(input_url="https://example.edu", config={"university_id": "example-u"}),
        sources=[source],
    )
    data.programme_catalog.append(
        ProgrammeCatalogRecord(
            name="Bachelor of Computing in Computer Science",
            faculty_or_school="School of Computing",
            degree_or_award="Bachelor of Computing (Honours) in Computer Science",
            category="degree_programme",
            mode="full-time",
            duration_or_units="four-year / at least 160 units",
            admissions_choice_name="Common Computer Science Programmes",
            specialisations_or_majors=["Artificial Intelligence", "Algorithms"],
            source_url=source.source_url,
            evidence_snippet="Bachelor of Computing in Computer Science.",
            evidence_confidence=Confidence.HIGH,
            evidence_path="/programme_catalog/0/name",
            parse_status="parsed",
        )
    )
    return data


def test_render_programme_catalog_csv_uses_stable_field_order_and_source_metadata():
    text = render_programme_catalog_csv(_catalog_data())
    header = text.splitlines()[0].split(",")
    rows = list(csv.DictReader(io.StringIO(text)))

    assert header == list(PROGRAMME_CATALOG_CSV_FIELDS)
    assert len(rows) == 1
    row = rows[0]
    assert row["university_id"] == "example-u"
    assert row["university_name"] == "Example University"
    assert row["programme_id"] == "programme-catalog-001"
    assert row["name"] == "Bachelor of Computing in Computer Science"
    assert row["specialisations_or_majors"] == "Artificial Intelligence; Algorithms"
    assert row["source_title"] == "Undergraduate Catalogue"
    assert row["evidence_snippet"] == "Bachelor of Computing in Computer Science."
    assert row["evidence_confidence"] == "high"
    assert row["parse_status"] == "parsed"
    assert row["retrieved_at"] == "2026-06-01T00:00:00+00:00"


def test_write_result_files_writes_programme_catalog_csv_when_catalog_exists():
    with TemporaryDirectory() as tmp:
        result_path, report_path = write_result_files(_catalog_data(), tmp)
        csv_path = Path(tmp) / "programme_catalog.csv"

        assert result_path.exists()
        assert report_path.exists()
        assert csv_path.exists()
        assert "Bachelor of Computing in Computer Science" in csv_path.read_text(encoding="utf-8")


def test_write_result_files_does_not_write_programme_catalog_csv_for_empty_catalog():
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(input_url="https://example.edu"),
    )
    with TemporaryDirectory() as tmp:
        write_result_files(data, tmp)

        assert not (Path(tmp) / "programme_catalog.csv").exists()
