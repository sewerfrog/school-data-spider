from university_admissions_crawler.evidence.provenance import evidence_from_source, source_from_text
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    Confidence,
    FieldValue,
    Institution,
    ProgrammeCatalogRecord,
    RequirementRecord,
    RunMetadata,
    SourceType,
    WarningCode,
    attach_validation_warnings,
)


def make_data():
    source = source_from_text(
        source_url="https://example.edu/admissions",
        title="Admissions",
        text="Apply by 31 Jan. International applicants need English.",
    )
    evidence = evidence_from_source(
        claim_path="/admissions/application_periods/0/value",
        source=source,
        snippet="Apply by 31 Jan.",
        confidence=Confidence.HIGH,
    )
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(input_url="https://example.edu"),
        sources=[source],
        evidence=[evidence],
    )
    data.admissions.application_periods.append(
        RequirementRecord(
            label="application deadline",
            value=FieldValue(
                value="31 Jan",
                status="known",
                confidence=Confidence.HIGH,
                evidence=["/admissions/application_periods/0/value"],
            ),
        )
    )
    return data


def test_non_unknown_claim_with_matching_evidence_has_no_missing_warning():
    data = attach_validation_warnings(make_data())
    assert not [w for w in data.warnings if w.code == WarningCode.MISSING_EVIDENCE]


def test_non_unknown_nested_claim_without_evidence_gets_warning():
    data = make_data()
    data.admissions.required_documents.append(
        RequirementRecord(
            label="passport",
            value=FieldValue(value="passport copy", status="known", confidence=Confidence.MEDIUM),
        )
    )

    attach_validation_warnings(data)

    missing = [w for w in data.warnings if w.code == WarningCode.MISSING_EVIDENCE]
    assert missing
    assert any("required_documents" in (w.field or "") for w in missing)
    assert data.confidence == Confidence.LOW


def test_unknown_and_manual_check_fields_do_not_require_evidence():
    data = make_data()
    data.admissions.required_documents.append(
        RequirementRecord(
            label="transcript",
            value=FieldValue.unknown("Document list not found", "/admissions/required_documents/0/value"),
        )
    )
    data.admissions.english_requirements.append(
        RequirementRecord(
            label="english",
            value=FieldValue.manual_check("Conflicting English requirements", "/admissions/english_requirements/0/value"),
        )
    )

    attach_validation_warnings(data)

    missing_fields = {w.field for w in data.warnings if w.code == WarningCode.MISSING_EVIDENCE}
    assert "/admissions/required_documents/0/value" not in missing_fields
    assert "/admissions/english_requirements/0/value" not in missing_fields


def test_source_and_evidence_serialize_enums_as_strings():
    data = make_data()
    dumped = data.to_dict()
    assert dumped["sources"][0]["source_type"] == "html"
    assert dumped["evidence"][0]["confidence"] == "high"


def test_pdf_evidence_can_carry_page_number():
    source = source_from_text(
        source_url="https://example.edu/prospectus.pdf",
        source_type=SourceType.PDF,
        title="Prospectus",
        text="page 2 prerequisites",
    )
    evidence = evidence_from_source(
        claim_path="/programmes/0/prerequisites/0/value",
        source=source,
        snippet="Mathematics required",
        page_number=2,
    )

    assert evidence.source_type == SourceType.PDF
    assert evidence.page_number == 2


def test_programme_catalog_record_serializes_without_replacing_programmes():
    data = make_data()
    claim_path = "/programme_catalog/0/name"
    data.programme_catalog.append(
        ProgrammeCatalogRecord(
            name="Data Science and Analytics",
            faculty_or_school="College of Humanities and Sciences",
            degree_or_award="Bachelor of Science",
            category="undergraduate",
            mode="full-time",
            duration_or_units="4 years",
            admissions_choice_name="Humanities and Sciences",
            specialisations_or_majors=["Data Science and Analytics"],
            source_url="https://example.edu/programmes/data-science",
            evidence_snippet="Data Science and Analytics is offered by the College of Humanities and Sciences.",
            evidence_confidence=Confidence.HIGH,
            evidence_path=claim_path,
            parse_status="parsed",
        )
    )
    data.evidence.append(
        evidence_from_source(
            claim_path=claim_path,
            source=data.sources[0],
            snippet="Data Science and Analytics is offered by the College of Humanities and Sciences.",
            confidence=Confidence.HIGH,
        )
    )

    attach_validation_warnings(data)
    dumped = data.to_dict()

    assert dumped["programmes"] == []
    assert dumped["programme_catalog"][0]["name"] == "Data Science and Analytics"
    assert dumped["programme_catalog"][0]["evidence_confidence"] == "high"
    assert dumped["programme_catalog"][0]["specialisations_or_majors"] == ["Data Science and Analytics"]
    assert not [w for w in data.warnings if w.code == WarningCode.MISSING_EVIDENCE and "programme_catalog" in (w.field or "")]


def test_programme_catalog_record_requires_row_level_provenance():
    data = make_data()
    data.programme_catalog.append(
        ProgrammeCatalogRecord(
            name="Computer Science",
            source_url="",
            evidence_snippet="",
            evidence_path="",
        )
    )

    attach_validation_warnings(data)

    missing = [w for w in data.warnings if w.code == WarningCode.MISSING_EVIDENCE and "programme_catalog" in (w.field or "")]
    assert missing
    assert "source_url" in missing[0].message
    assert "evidence_snippet" in missing[0].message
    assert "evidence_path" in missing[0].message
