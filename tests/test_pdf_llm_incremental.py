from pathlib import Path

from university_admissions_crawler.extractor.llm_provider import LLMCandidateClaim, validate_llm_candidates
from university_admissions_crawler.extractor.pdf_extractor import FixturePDFExtractor, MissingPDFExtractor
from university_admissions_crawler.extractor.schema import SourceType, WarningCode
from university_admissions_crawler.evidence.provenance import evidence_from_source, source_from_text
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan


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
    previous["admissions"]["application_periods"][0]["value"]["value"] = "1 January 1900"
    data2 = run_fixture_scan(ROOT, previous_result=previous)
    diff = data2.run.config["diff"]
    assert diff["baseline"] == "provided"
    assert diff["changed_sources"]
    assert any("/admissions/application_periods/0/value" in path for path in diff["changed_fields"])
    assert any(w.code == WarningCode.INCREMENTAL_CHANGE for w in data2.warnings)
