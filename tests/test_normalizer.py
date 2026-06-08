from university_admissions_crawler.evidence.provenance import evidence_from_source, source_from_text
from university_admissions_crawler.extractor.normalizer import normalize_admissions_data
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    ClaimStatus,
    Confidence,
    FieldValue,
    Institution,
    RequirementRecord,
    RunMetadata,
    WarningCode,
)


def test_conflicting_values_are_preserved_and_warned():
    source_a = source_from_text(source_url="https://x.edu/a", title="A", text="Deadline: 1 Jan 2027")
    source_b = source_from_text(source_url="https://x.edu/b", title="B", text="Deadline: 2 Jan 2027")
    data = AdmissionsData(Institution(homepage_url="https://x.edu"), RunMetadata(input_url="https://x.edu"), sources=[source_a, source_b])
    for index, (source, value) in enumerate([(source_a, "1 January 2027"), (source_b, "2 January 2027")]):
        path = f"/admissions/application_periods/{index}/value"
        data.admissions.application_periods.append(
            RequirementRecord("application deadline", FieldValue(value=value, status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[path]))
        )
        data.evidence.append(evidence_from_source(claim_path=path, source=source, snippet=f"Deadline: {value}"))

    normalize_admissions_data(data)

    assert len(data.admissions.application_periods) == 2
    assert any(w.code == WarningCode.CONFLICT for w in data.warnings)
    assert data.confidence == Confidence.LOW


def test_stale_source_academic_year_warns():
    source = source_from_text(source_url="https://x.edu/old", title="Old", text="Admissions")
    source.academic_year = "2024/2025"
    data = AdmissionsData(Institution(homepage_url="https://x.edu"), RunMetadata(input_url="https://x.edu"), sources=[source])
    normalize_admissions_data(data)
    assert any(w.code == WarningCode.STALE_PAGE for w in data.warnings)


def test_non_official_source_warns_for_supported_claim():
    source = source_from_text(source_url="https://rankings.example/admissions", title="Mirror", text="Apply by 1 Jan 2027", is_official=False)
    path = "/admissions/application_periods/0/value"
    data = AdmissionsData(Institution(homepage_url="https://x.edu"), RunMetadata(input_url="https://x.edu"), sources=[source])
    data.admissions.application_periods.append(
        RequirementRecord("application deadline", FieldValue(value="1 January 2027", status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[path]))
    )
    data.evidence.append(evidence_from_source(claim_path=path, source=source, snippet="Apply by 1 Jan 2027"))
    normalize_admissions_data(data)
    assert any(w.code == WarningCode.NON_OFFICIAL_SOURCE for w in data.warnings)


def test_ambiguous_applicant_group_warns_when_required_context_missing():
    source = source_from_text(source_url="https://x.edu/fees", title="Fees", text="Fees are SGD 32000.")
    path = "/fees/0/value"
    data = AdmissionsData(Institution(homepage_url="https://x.edu"), RunMetadata(input_url="https://x.edu"), sources=[source])
    data.fees.append(
        RequirementRecord(
            "tuition/fees",
            FieldValue(value="SGD 32000", status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[path]),
            requires_applicant_group=True,
        )
    )
    data.evidence.append(evidence_from_source(claim_path=path, source=source, snippet="Fees are SGD 32000."))
    normalize_admissions_data(data)
    assert any(w.code == WarningCode.AMBIGUOUS_APPLICANT_GROUP for w in data.warnings)
