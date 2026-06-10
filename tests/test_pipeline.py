from pathlib import Path

from university_admissions_crawler.crawler.admissions_context import has_admissions_contact_context, has_undergraduate_fee_context
from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import FetchResult, FixtureFetcher
from university_admissions_crawler.extractor.schema import WarningCode
from university_admissions_crawler.extractor.html_extractor import extract_contact, extract_english_requirement, extract_fee
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import SourceType
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan, run_scan

ROOT = Path("tests/fixtures/mini_university_site")
SAVED = Path("tests/fixtures/saved_sources")


def test_offline_fixture_pipeline_discovers_extracts_and_warns():
    data = run_fixture_scan(ROOT)
    urls = {source.source_url for source in data.sources}
    assert "https://fixture.test/" in urls
    assert "https://fixture.test/admissions/index.html" in urls
    assert "https://fixture.test/programmes/index.html" in urls
    assert any(record.value.value == "31 January 2027" for record in data.admissions.application_periods)
    assert any("English" in record.value.value for record in data.admissions.english_requirements)
    assert any(programme.name.value == "Bachelor of Engineering" for programme in data.programmes)
    assert any(programme.prerequisites and programme.prerequisites[0].value.value == "Mathematics required" for programme in data.programmes)
    assert data.evidence
    assert any(w.code == WarningCode.NEEDS_MANUAL_CHECK for w in data.warnings)
    assert any(w.code == WarningCode.CONFLICT for w in data.warnings)
    assert any(w.code == WarningCode.STALE_PAGE for w in data.warnings)


def test_offline_fixture_pipeline_has_no_missing_evidence_for_known_claims():
    data = run_fixture_scan(ROOT)
    assert not [w for w in data.warnings if w.code == WarningCode.MISSING_EVIDENCE]


def test_pipeline_evidence_paths_resolve_to_real_claims():
    data = run_fixture_scan(ROOT)
    from university_admissions_crawler.extractor.schema import resolve_claim_path
    for item in data.evidence:
        resolve_claim_path(data, item.claim_path)



def test_pipeline_serializes_to_jsonable_dict():
    data = run_fixture_scan(ROOT)
    dumped = data.to_dict()
    assert dumped["institution"]["homepage_url"] == "https://fixture.test/"
    assert dumped["sources"]
    assert dumped["warnings"]


def test_pdf_prerequisite_evidence_uses_fixture_page_number():
    data = run_fixture_scan(ROOT)
    pdf_items = [item for item in data.evidence if item.source_url.endswith(".pdf")]
    assert pdf_items
    assert pdf_items[0].page_number == 2


def test_external_subdomain_source_and_evidence_urls_are_preserved():
    data = run_fixture_scan(ROOT, max_pages=30)
    assert any(source.source_url == "https://apply.fixture.test/apply.html" for source in data.sources)
    assert any(item.source_url == "https://apply.fixture.test/apply.html" for item in data.evidence)
    assert all("fixture.test/apply.fixture.test" not in source.source_url for source in data.sources)


def test_undergraduate_application_entry_has_single_current_value_evidence():
    data = run_fixture_scan(ROOT, max_pages=30)
    entry_path = "/admissions/undergraduate_application_entry"
    entry_items = [item for item in data.evidence if item.claim_path == entry_path]
    assert len(entry_items) == 1
    assert entry_items[0].source_url == data.admissions.undergraduate_application_entry.value


def test_pipeline_extracts_public_json_api_claims():
    data = run_fixture_scan(ROOT, max_pages=30)
    assert any(source.source_url.endswith("/api/programmes.json") and source.source_type == "json" for source in data.sources)
    assert any(programme.name.value == "Bachelor of Science" for programme in data.programmes)
    assert any(record.value.value == "15 February 2027" for record in data.admissions.application_periods)
    assert any(record.value.value == "SGD 32000 per year" for record in data.fees)


def test_pipeline_uses_html_table_text_for_extraction():
    result = FixtureFetcher(ROOT).fetch("https://fixture.test/table-fees.html")
    assert "International undergraduate | Tuition is SGD 45000 per year." in result.markdown
    record, evidence = extract_fee(result.markdown, result.source, "/fees/0/value")
    assert record.value.value == "Tuition is SGD 45000 per year."
    assert record.value.parsed[0]["currency"] == "SGD"
    assert record.value.parsed[0]["amount"] == 45000
    assert evidence


def test_pipeline_attaches_core_coverage_and_source_strategy():
    data = run_fixture_scan(ROOT, max_pages=30)
    coverage = data.run.config["coverage"]
    assert coverage["found_count"] > 0
    assert "coverage_ratio" in coverage
    assert data.run.config["source_strategy_summary"]["html_page"] >= 1


def test_realistic_fixture_extracts_specific_core_fields_without_nav_noise():
    data = run_fixture_scan(ROOT, seed_url="https://fixture.test/realistic-admissions.html", max_pages=1, max_depth=0)
    assert any(record.value.value == "2 June 2026, 9am to 22 June 2026, 5pm" for record in data.admissions.application_periods)
    period = next(record for record in data.admissions.application_periods if record.value.value == "2 June 2026, 9am to 22 June 2026, 5pm")
    assert period.value.parse_status == "parsed"
    assert period.value.parsed["open_date"] == "2 June 2026, 9am"
    assert period.value.parsed["deadline"] == "22 June 2026, 5pm"
    assert any("IELTS 6.5" in record.value.value and "TOEFL 90" in record.value.value for record in data.admissions.english_requirements)
    english = next(record for record in data.admissions.english_requirements if "IELTS 6.5" in record.value.value)
    assert english.value.parse_status == "parsed"
    assert any(item["test_name"] == "IELTS" and item["overall_score"] == 6.5 for item in english.value.parsed)
    assert any("S$45,000 per year" in record.value.value for record in data.fees)
    fee = next(record for record in data.fees if "S$45,000 per year" in record.value.value)
    assert fee.value.parse_status == "parsed"
    assert fee.value.parsed[0]["currency"] == "SGD"
    assert fee.value.parsed[0]["amount"] == 45000
    assert any(programme.name.value == "Bachelor of Data Science and Artificial Intelligence" for programme in data.programmes)
    assert any(programme.name.value == "Bachelor of Business" for programme in data.programmes)
    assert not any("Alumni News Giving Staff Jobs" in record.value.value for record in data.fees)


def test_english_extractor_rejects_polyu_style_false_positive_programme_lists():
    text = (
        "Programme Entrance Requirements and Subject Weightings JUPAS Score Calculator "
        "English and Applied Linguistics - BA (Hons) Bachelor of Science Bachelor of Business "
        "Select a Programme Quick Links General University Requirements."
    )
    source = source_from_text(source_url="https://www.polyu.edu.hk/study/ug/admissions/jupas", source_type=SourceType.HTML, title="JUPAS Admissions", text=text)
    record, evidence = extract_english_requirement(text, source, "/admissions/english_requirements/0/value")
    assert record is None
    assert evidence == []


def test_english_extractor_rejects_hku_generic_ielts_toefl_mention_without_scores():
    text = (SAVED / "hku/3e3a3cdfa2c4d708.txt").read_text(encoding="utf-8")
    source = source_from_text(
        source_url="https://admissions.hku.hk/apply/international-qualifications",
        source_type=SourceType.HTML,
        title="International Qualifications",
        text=text,
    )
    record, evidence = extract_english_requirement(text, source, "/admissions/english_requirements/0/value")
    assert record is None
    assert evidence == []


def test_fee_extractor_parses_hku_tuition_rows_from_saved_source():
    text = (SAVED / "hku/386d94a09ffd4eb7.txt").read_text(encoding="utf-8")
    source = source_from_text(
        source_url="https://admissions.hku.hk/fees-and-scholarships/fees",
        source_type=SourceType.HTML,
        title="Tuition and Living Expenses",
        text=text,
    )
    record, evidence = extract_fee(text, source, "/fees/0/value")
    assert record is not None
    assert evidence
    amounts = {(item["currency"], item["amount"], item["student_group"]) for item in record.value.parsed}
    assert ("HKD", 47000, "local") in amounts
    assert ("HKD", 224000, "non-local non-STEM") in amounts
    assert ("HKD", 249000, "non-local STEM") in amounts
    assert record.value.raw_text
    assert record.value.parse_status == "parsed"


def test_english_extractor_parses_ntu_saved_scores():
    text = (SAVED / "ntu/347ce27695edcec6.txt").read_text(encoding="utf-8")
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/admissions/undergraduate/admission-guide/international-qualifications",
        source_type=SourceType.HTML,
        title="International Qualifications",
        text=text,
    )
    record, evidence = extract_english_requirement(text, source, "/admissions/english_requirements/0/value")
    assert record is not None
    assert evidence
    assert any(item["test_name"] == "IELTS" and item["overall_score"] == 6 and item["component_scores"]["writing"] == 6 for item in record.value.parsed)
    assert any(item["test_name"] == "TOEFL iBT" and item["overall_score"] == 90 and item["component_scores"]["verbal"] == 25 for item in record.value.parsed)
    assert any(item["test_name"] == "TOEFL iBT" and item["overall_score"] == 4.5 and item["component_scores"]["speaking"] == 4.5 for item in record.value.parsed)
    assert any(item["test_name"] == "PTE Academic" and item["overall_score"] == 55 for item in record.value.parsed)


def test_english_extractor_supports_score_before_ielts_name():
    source = source_from_text(
        source_url="https://example.edu/admissions/undergraduate/requirements",
        source_type=SourceType.HTML,
        title="English language requirements",
        text="Applicants must obtain an overall band of 7 in the IELTS, with no subtest below 6.5.",
    )
    record, _ = extract_english_requirement(source.title + " " + "Applicants must obtain an overall band of 7 in the IELTS, with no subtest below 6.5.", source, "/admissions/english_requirements/0/value")
    assert record is not None
    assert record.value.parsed[0]["test_name"] == "IELTS"
    assert record.value.parsed[0]["overall_score"] == 7
    assert record.value.parsed[0]["component_scores"]["minimum_component"] == 6.5


def test_saved_polyu_noise_pages_do_not_pass_core_context_gates_or_contact_extraction():
    contact_text = (SAVED / "polyu/06ee85c60541773c.txt").read_text(encoding="utf-8")
    hall_text = (SAVED / "polyu/d780f9f68077c714.txt").read_text(encoding="utf-8")
    phd_text = (SAVED / "polyu/e5811e8bced1de9c.txt").read_text(encoding="utf-8")
    assert not has_admissions_contact_context("https://www.polyu.edu.hk/contact-us/form.php", "Contact Us", contact_text)
    assert not has_undergraduate_fee_context("https://www.polyu.edu.hk/sao/student-resources-and-support-section/residential-life/hall-admission/hall-fees/", "Hall Fees", hall_text)
    assert not has_undergraduate_fee_context("https://www.polyu.edu.hk/gs/prospective-students/fellowship-scholarship-schemes/", "Hong Kong PhD Fellowship Scheme Applications", phd_text)
    source = source_from_text(source_url="https://www.polyu.edu.hk/contact-us/form.php", source_type=SourceType.HTML, title="Contact Us", text=contact_text)
    record, evidence = extract_contact(contact_text, source, "/contacts/0/value")
    assert record is None
    assert evidence == []


def test_pipeline_does_not_extract_polyu_hall_or_phd_fees_from_saved_sources():
    fetcher = _SavedSinglePageFetcher(
        {
            "https://fixture.test/": ("Home", '<a href="https://www.polyu.edu.hk/sao/student-resources-and-support-section/residential-life/hall-admission/hall-fees/">Hall</a><a href="https://www.polyu.edu.hk/gs/prospective-students/fellowship-scholarship-schemes/">PhD</a>'),
            "https://www.polyu.edu.hk/sao/student-resources-and-support-section/residential-life/hall-admission/hall-fees/": ("Hall Fees", (SAVED / "polyu/d780f9f68077c714.txt").read_text(encoding="utf-8")),
            "https://www.polyu.edu.hk/gs/prospective-students/fellowship-scholarship-schemes/": ("Hong Kong PhD Fellowship Scheme Applications", (SAVED / "polyu/e5811e8bced1de9c.txt").read_text(encoding="utf-8")),
        }
    )
    data = run_scan(
        "https://fixture.test/",
        fetcher,
        DiscoveryConfig(max_pages=5, max_depth=1, allowed_hosts={"fixture.test"}, allowed_domains={"polyu.edu.hk"}),
    )
    assert not data.fees


def test_pipeline_does_not_extract_ntu_graduate_tuition_from_saved_source():
    text = (SAVED / "ntu/359466af0e460cb9.txt").read_text(encoding="utf-8")
    fetcher = _SavedSinglePageFetcher(
        {
            "https://fixture.test/": ("Home", '<a href="https://www.ntu.edu.sg/admissions/graduate/financialmatters/pgtuitionfees">Graduate tuition</a>'),
            "https://www.ntu.edu.sg/admissions/graduate/financialmatters/pgtuitionfees": ("Tuition Fees", text),
        }
    )
    data = run_scan(
        "https://fixture.test/",
        fetcher,
        DiscoveryConfig(max_pages=3, max_depth=1, allowed_hosts={"fixture.test"}, allowed_domains={"ntu.edu.sg"}),
    )
    assert not data.fees


class _SavedSinglePageFetcher:
    engine = "saved-single-page"

    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url: str) -> FetchResult:
        title, text = self.pages[url]
        links = []
        if url == "https://fixture.test/":
            import re

            links = re.findall(r'href="([^"]+)"', text)
        source = source_from_text(source_url=url, title=title, source_type=SourceType.HTML, text=text, retrieved_at="2026-06-01T00:00:00+00:00", engine=self.engine)
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title=title,
            content_type="text/html",
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=text,
            links=links,
            source=source,
        )
