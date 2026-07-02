import json
from pathlib import Path

from university_admissions_crawler.classifier.page_classifier import classify_page
from university_admissions_crawler.crawler.admissions_context import has_admissions_contact_context, has_undergraduate_admissions_context, has_undergraduate_fee_context
from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import FetchResult, FixtureFetcher
from university_admissions_crawler.crawler.filters import canonicalize_url
from university_admissions_crawler.extractor.schema import WarningCode
from university_admissions_crawler.extractor.llm_provider import MockClassificationAssistProvider, MockStructuredExtractionProvider
from university_admissions_crawler.extractor.html_extractor import extract_contact, extract_english_requirement, extract_fee
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import SourceType
from university_admissions_crawler.pipeline.diagnostics import _missing_reasons, llm_structured_validation_summary
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan, run_scan
from university_admissions_crawler.pipeline.source_planning import attach_source_plan_diagnostics
from university_admissions_crawler.reports.programme_catalog_csv import render_programme_catalog_csv
from university_admissions_crawler.extractor.llm_provider import MockSourcePlanProvider

ROOT = Path("tests/fixtures/mini_university_site")
LLM_STRUCTURED_ROOT = Path("tests/fixtures/llm_structured_extraction")
SAVED = Path("tests/fixtures/saved_sources")
NUS_CATALOG_SAMPLES = Path("tests/fixtures/programme_catalog/nus/source_samples.json")


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


def test_offline_fixture_pipeline_populates_programme_catalog_without_replacing_programmes():
    data = run_fixture_scan(ROOT)
    from university_admissions_crawler.extractor.schema import resolve_claim_path

    assert any(programme.name.value == "Bachelor of Engineering" for programme in data.programmes)
    assert any(row.name == "Bachelor of Engineering" for row in data.programme_catalog)
    catalog_row = next(row for row in data.programme_catalog if row.name == "Bachelor of Engineering")
    assert catalog_row.category == "degree_programme"
    assert catalog_row.source_url == "https://fixture.test/programmes/index.html"
    assert resolve_claim_path(data, catalog_row.evidence_path) == catalog_row.name
    assert any(item.claim_path == catalog_row.evidence_path for item in data.evidence)
    assert any(
        attempt["field"] == "programme_catalog" and attempt["extractor"] == "extract_programme_catalog"
        for entry in data.run.config["extraction_diagnostics"]
        for attempt in entry["attempts"]
    )


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


def test_live_pdf_without_enabled_pdf_parser_warns_instead_of_fixture_parsing():
    class LivePDFTextFetcher:
        engine = "live-http"

        def fetch(self, url: str) -> FetchResult:
            source = source_from_text(
                source_url=url,
                title="Prospectus",
                source_type=SourceType.PDF,
                text="PDF PAGE 1\nMathematics required",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
            )
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                title="Prospectus",
                content_type="application/pdf",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
                text="PDF PAGE 1\nMathematics required",
                source=source,
            )

    data = run_scan(
        "https://example.edu/prospectus.pdf",
        LivePDFTextFetcher(),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"example.edu"}),
    )

    assert any(w.code == WarningCode.OPTIONAL_DEPENDENCY_MISSING and w.field == "https://example.edu/prospectus.pdf" for w in data.warnings)
    assert not any(item.source_url == "https://example.edu/prospectus.pdf" for item in data.evidence)


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


def test_pipeline_marks_nus_incapsula_page_as_blocked_challenge():
    blocked_url = "https://www.nus.edu.sg/oam/undergraduate-programmes"
    text = (SAVED / "nus/incapsula_challenge.html").read_text(encoding="utf-8")
    fetcher = _SavedSinglePageFetcher(
        {
            blocked_url: ("Request unsuccessful", text),
        }
    )

    data = run_scan(
        blocked_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"www.nus.edu.sg"}, allowed_domains={"nus.edu.sg"}),
    )

    assert not data.programmes
    assert not data.fees
    assert not data.admissions.application_periods
    blocked_entry = next(item for item in data.run.config["source_strategy"] if item["url"] == blocked_url)
    assert blocked_entry["strategy"] == "blocked_or_challenge"
    assert data.run.config["source_strategy_summary"]["blocked_or_challenge"] == 1
    blocked_diagnostics = next(item for item in data.run.config["extraction_diagnostics"] if item["url"] == blocked_url)
    assert blocked_diagnostics["source_acquisition_status"] == "blocked_or_challenge"
    assert blocked_diagnostics["attempts"] == []
    assert data.run.config["missing_reasons"]["programmes"]["reason"] == "blocked_or_challenge"
    assert data.run.config["missing_reasons"]["programmes"]["legacy_reason"] == "source_not_crawled"
    assert data.run.config["missing_reasons"]["programmes"]["action_target"] == "source_acquisition"
    assert blocked_url in data.run.config["missing_reasons"]["programmes"]["source_urls"]
    template = data.run.config["template_completeness"]
    assert template["fields"]["programmes"]["status_flags"] == ["source_blocked_or_challenge"]
    assert template["fields"]["programmes"]["next_action"] == "improve_source_discovery_or_llm_source_navigation"
    assert blocked_url in template["fields"]["programmes"]["source_urls"]


def test_pipeline_mock_source_planning_triggers_on_blocked_source_without_changing_facts():
    blocked_url = "https://www.nus.edu.sg/oam/undergraduate-programmes"
    text = (SAVED / "nus/incapsula_challenge.html").read_text(encoding="utf-8")
    fetcher = _SavedSinglePageFetcher(
        {
            blocked_url: ("Request unsuccessful", text),
        }
    )
    data = run_scan(
        blocked_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"www.nus.edu.sg"}, allowed_domains={"nus.edu.sg"}),
    )

    attach_source_plan_diagnostics(
        data,
        MockSourcePlanProvider(
            {
                "candidate_urls": [
                    {
                        "url": "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/",
                        "reason": "Official NUS Bulletin programmes index.",
                        "expected_category": "programme_list",
                    },
                    {
                        "url": "https://example.com/nus/admissions",
                        "reason": "Unofficial mirror should be rejected.",
                        "expected_category": "undergraduate_admissions",
                    },
                    {
                        "url": "http://www.nus.edu.sg/admissions",
                        "reason": "Non-HTTPS candidate should be rejected.",
                        "expected_category": "undergraduate_admissions",
                    },
                ],
                "candidate_queries": ["site:nus.edu.sg undergraduate admissions"],
                "warnings": [],
            }
        ),
    )

    assert not data.programmes
    assert not data.fees
    source_plan = data.run.config["llm_source_plan"]
    assert source_plan["enabled"] is True
    assert source_plan["triggered"] is True
    assert source_plan["applied"] is False
    assert source_plan["trigger_reasons"] == ["blocked_or_challenge_source", "all_core_fields_missing"]
    assert source_plan["candidate_urls"]
    assert source_plan["accepted_candidate_urls"] == [
        {
            "url": "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/",
            "reason": "Official NUS Bulletin programmes index.",
            "expected_category": "programme_list",
            "validation_status": "accepted",
        }
    ]
    rejected = {item["url"]: item["rejection_reason"] for item in source_plan["rejected_candidate_urls"]}
    assert rejected["https://example.com/nus/admissions"] == "outside_allowed_domain"
    assert rejected["http://www.nus.edu.sg/admissions"] == "non_https"
    assert source_plan["candidate_queries"]


def test_pipeline_nus_mock_source_planning_regression_keeps_candidates_diagnostic_only():
    blocked_url = "https://www.nus.edu.sg/oam/undergraduate-programmes"
    text = (SAVED / "nus/incapsula_challenge.html").read_text(encoding="utf-8")
    payload = json.loads((Path("tests/fixtures/llm/source_plan_nus.json")).read_text(encoding="utf-8"))
    fetcher = _SavedSinglePageFetcher(
        {
            blocked_url: ("Request unsuccessful", text),
        }
    )

    data = run_scan(
        blocked_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_hosts={"www.nus.edu.sg"}, allowed_domains={"nus.edu.sg"}),
    )
    attach_source_plan_diagnostics(data, MockSourcePlanProvider(payload))

    assert fetcher.fetched == [blocked_url]
    assert data.run.config["source_strategy"][0]["strategy"] == "blocked_or_challenge"
    assert data.run.config["missing_reasons"]["programmes"]["reason"] == "blocked_or_challenge"
    assert not data.programmes
    assert not data.fees
    assert not data.admissions.application_periods

    source_plan = data.run.config["llm_source_plan"]
    assert source_plan["triggered"] is True
    assert source_plan["applied"] is False
    accepted_urls = [item["url"] for item in source_plan["accepted_candidate_urls"]]
    assert accepted_urls == [
        "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/",
        "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education/",
        "https://chs.nus.edu.sg/programmes/",
    ]
    assert all(item["validation_status"] == "accepted" for item in source_plan["accepted_candidate_urls"])
    rejected = {item["url"]: item["rejection_reason"] for item in source_plan["rejected_candidate_urls"]}
    assert rejected == {
        "https://example.com/nus/admissions": "outside_allowed_domain",
    }
    assert source_plan["candidate_queries"] == [
        "site:nus.edu.sg undergraduate admissions application period NUS",
        "site:nus.edu.sg nus bulletin undergraduate programmes",
    ]
    source_urls = {source.source_url for source in data.sources}
    assert set(accepted_urls).isdisjoint(source_urls)


def test_pipeline_source_planning_crawls_validated_candidate_without_creating_model_facts():
    seed_url = "https://example.edu/"
    programme_url = "https://example.edu/programmes"
    fetcher = SourcePlanningFrontierFetcher(
        {
            seed_url: ("Access Denied", "Access denied. Please enable JavaScript and complete the captcha.", []),
            programme_url: ("Undergraduate Programmes", "Bachelor of Science\nBachelor of Engineering", []),
        }
    )

    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=3, max_depth=1, allowed_hosts={"example.edu"}),
        source_plan_provider=MockSourcePlanProvider(
            {
                "candidate_urls": [
                    {
                        "url": programme_url,
                        "reason": "Official programmes page candidate.",
                        "expected_category": "programme_list",
                    }
                ],
                "candidate_path_patterns": ["/programmes"],
                "candidate_queries": [],
                "warnings": [],
            }
        ),
    )

    source_plan = data.run.config["llm_source_plan"]
    assert source_plan["triggered"] is True
    assert source_plan["applied"] is True
    assert source_plan["applied_candidate_urls"] == [programme_url]
    assert source_plan["budget_skipped_candidate_urls"] == []
    assert source_plan["accepted_candidate_urls"][0]["crawl_status"] == "crawled"
    assert programme_url in fetcher.fetched
    assert any(source.source_url == programme_url for source in data.sources)
    assert {programme.name.value for programme in data.programmes} >= {"Bachelor of Science", "Bachelor of Engineering"}
    assert all(item.source_url == programme_url for item in data.evidence if item.claim_path.startswith("/programmes/"))


def test_pipeline_source_planning_reports_budget_skipped_candidate():
    seed_url = "https://example.edu/"
    programme_url = "https://example.edu/programmes"
    fetcher = SourcePlanningFrontierFetcher(
        {
            seed_url: ("Access Denied", "Access denied. Please enable JavaScript and complete the captcha.", []),
            programme_url: ("Undergraduate Programmes", "Bachelor of Science", []),
        }
    )

    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=1, allowed_hosts={"example.edu"}),
        source_plan_provider=MockSourcePlanProvider(
            {
                "candidate_urls": [
                    {
                        "url": programme_url,
                        "reason": "Official programmes page candidate.",
                        "expected_category": "programme_list",
                    }
                ],
                "candidate_queries": [],
                "warnings": [],
            }
        ),
    )

    source_plan = data.run.config["llm_source_plan"]
    assert source_plan["triggered"] is True
    assert source_plan["applied"] is False
    assert source_plan["applied_candidate_urls"] == []
    assert source_plan["budget_skipped_candidate_urls"] == [programme_url]
    assert source_plan["accepted_candidate_urls"][0]["crawl_status"] == "budget_skipped"
    assert programme_url not in fetcher.fetched


def test_pipeline_llm_structured_extraction_fallback_writes_validated_missing_facts():
    seed_url = "https://example.edu/"
    fee_url = "https://example.edu/admissions/undergraduate/fees"
    snippet = "Undergraduate admissions tuition fees are published annually on the official fee schedule."
    fetcher = SourcePlanningFrontierFetcher(
        {
            seed_url: ("Home", "Undergraduate admissions home", [fee_url]),
            fee_url: ("Undergraduate admissions fees", snippet, []),
        }
    )
    class SourceAwareStructuredProvider(MockStructuredExtractionProvider):
        def extract_structured_candidate_payload(self, source, allowed_claim_paths, schema):
            self.requests.append(
                {
                    "source_url": source.source_url,
                    "allowed_claim_paths": allowed_claim_paths,
                    "schema": schema,
                }
            )
            if source.source_url != fee_url:
                return {"candidate_facts": [], "warnings": []}
            return {
                "candidate_facts": [
                        {
                            "claim_path": "admissions.fees",
                            "value": "published annually",
                            "evidence_snippet": snippet,
                            "source_url": fee_url,
                            "confidence": 0.8,
                        },
                        {
                            "claim_path": "admissions.fees",
                            "value": "published monthly",
                            "evidence_snippet": snippet,
                            "source_url": fee_url,
                            "confidence": 0.8,
                    },
                ],
                "warnings": ["mock warning"],
            }

    provider = SourceAwareStructuredProvider()

    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=3, max_depth=1, allowed_hosts={"example.edu"}),
        structured_extraction_provider=provider,
    )

    diagnostics = data.run.config["llm_structured_extraction"]
    assert diagnostics["enabled"] is True
    assert diagnostics["triggered"] is True
    assert diagnostics["applied_to_facts"] is True
    assert diagnostics["applied_count"] == 1
    assert "core_field_missing" in diagnostics["trigger_reasons"]
    assert diagnostics["source_urls_used"][0] == fee_url
    assert seed_url in diagnostics["source_urls_used"]
    assert diagnostics["candidate_count"] == 2
    assert diagnostics["accepted_count"] == 1
    assert diagnostics["rejected_count"] == 1
    assert diagnostics["accepted_claim_paths"] == {"admissions.fees": 1}
    assert diagnostics["reject_reasons"] == {"value_not_in_snippet": 1}
    assert diagnostics["write_status_counts"] == {"applied": 1, "not_applicable": 1}
    assert diagnostics["results"][0]["extractor"] == "llm_fallback_validated"
    assert diagnostics["results"][0]["validation_status"] == "accepted"
    assert diagnostics["results"][0]["write_status"] == "applied"
    assert diagnostics["results"][0]["evidence_path"] == "/fees/0/value"
    assert diagnostics["results"][1]["validation_status"] == "rejected"
    assert diagnostics["warnings"] == ["mock warning"]
    assert provider.requests[0]["source_url"] == fee_url
    assert provider.requests[0]["allowed_claim_paths"]
    assert "fees" not in data.run.config["coverage"]["missing"]
    assert "fees" in data.run.config["coverage"]["found"]
    assert "fees" not in data.run.config["missing_reasons"]
    assert data.run.config["template_completeness"]["fields"]["fees"]["status"] == "found"
    assert data.fees[0].label == "tuition/fees"
    assert data.fees[0].value.value == "published annually"
    assert data.fees[0].value.raw_text == snippet
    assert data.fees[0].value.parse_status == "llm_fallback_validated"
    assert data.fees[0].value.evidence == ["/fees/0/value"]
    assert data.evidence[-1].claim_path == "/fees/0/value"
    assert data.evidence[-1].source_url == fee_url
    assert data.evidence[-1].snippet == snippet
    assert not data.programmes


def test_pipeline_llm_structured_extraction_does_not_overwrite_existing_fee_fact():
    seed_url = "https://example.edu/"
    fee_url = "https://example.edu/admissions/undergraduate/fees"
    snippet = "Undergraduate admissions tuition fee is SGD 20,000 per year."
    llm_snippet = "Undergraduate admissions tuition fee is SGD 99,000 per year."
    fetcher = SourcePlanningFrontierFetcher(
        {
            seed_url: ("Home", "Undergraduate admissions home", [fee_url]),
            fee_url: ("Undergraduate admissions fees", f"{snippet} {llm_snippet}", []),
        }
    )

    class SourceAwareStructuredProvider(MockStructuredExtractionProvider):
        def extract_structured_candidate_payload(self, source, allowed_claim_paths, schema):
            self.requests.append(
                {
                    "source_url": source.source_url,
                    "allowed_claim_paths": allowed_claim_paths,
                    "schema": schema,
                }
            )
            if source.source_url != fee_url:
                return {"candidate_facts": [], "warnings": []}
            return {
                "candidate_facts": [
                    {
                        "claim_path": "admissions.fees",
                        "value": "SGD 99,000",
                        "evidence_snippet": llm_snippet,
                        "source_url": fee_url,
                        "confidence": 0.8,
                    }
                ],
                "warnings": [],
            }

    provider = SourceAwareStructuredProvider()

    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=3, max_depth=1, allowed_hosts={"example.edu"}),
        structured_extraction_provider=provider,
    )

    diagnostics = data.run.config["llm_structured_extraction"]
    assert diagnostics["accepted_count"] == 1
    assert diagnostics["applied_count"] == 0
    assert diagnostics["applied_to_facts"] is False
    assert diagnostics["write_status_counts"] == {"existing_value": 1}
    assert diagnostics["results"][0]["write_status"] == "existing_value"
    assert len(data.fees) == 1
    assert data.fees[0].value.value == "tuition fee is SGD 20,000 per year."
    assert "SGD 99,000" not in data.fees[0].value.value
    assert data.fees[0].value.parse_status != "llm_fallback_validated"


def test_fixture_school_llm_structured_extraction_repairs_missing_fee_field():
    fee_url = "https://fixture.test/admissions/undergraduate/fees.html"
    programme_url = "https://fixture.test/programmes/index.html"
    valid_snippet = "For undergraduate admissions, the annual tuition charge for international students is published in the official applicant fee schedule."
    programme_snippet = "The undergraduate programme catalogue includes the Data Futures Bachelor pathway for applicants interested in analytics and public policy."

    class FixtureSchoolStructuredProvider(MockStructuredExtractionProvider):
        def extract_structured_candidate_payload(self, source, allowed_claim_paths, schema):
            self.requests.append(
                {
                    "source_url": source.source_url,
                    "allowed_claim_paths": allowed_claim_paths,
                    "schema": schema,
                }
            )
            if source.source_url == programme_url:
                return {
                    "candidate_facts": [
                        {
                            "claim_path": "programme_catalog[].name",
                            "value": "Data Futures Bachelor pathway",
                            "evidence_snippet": programme_snippet,
                            "source_url": programme_url,
                            "confidence": 0.78,
                        }
                    ],
                    "warnings": [],
                }
            if source.source_url != fee_url:
                return {"candidate_facts": [], "warnings": []}
            return {
                "candidate_facts": [
                    {
                        "claim_path": "admissions.fees",
                        "value": "annual tuition charge for international students",
                        "evidence_snippet": valid_snippet,
                        "source_url": fee_url,
                        "confidence": 0.82,
                    },
                    {
                        "claim_path": "admissions.fees",
                        "value": "annual tuition charge for international students",
                        "evidence_snippet": "This snippet is not present in the captured source.",
                        "source_url": fee_url,
                        "confidence": 0.82,
                    },
                    {
                        "claim_path": "admissions.fees",
                        "value": "amount shown in the appendix",
                        "evidence_snippet": valid_snippet,
                        "source_url": fee_url,
                        "confidence": 0.82,
                    },
                    {
                        "claim_path": "admissions.fees",
                        "value": "annual tuition charge for international students",
                        "evidence_snippet": valid_snippet,
                        "source_url": "https://fixture.test/admissions/undergraduate/not-crawled.html",
                        "confidence": 0.82,
                    },
                ],
                "warnings": [],
            }

    provider = FixtureSchoolStructuredProvider()

    data = run_fixture_scan(
        LLM_STRUCTURED_ROOT,
        max_pages=5,
        max_depth=2,
        structured_extraction_provider=provider,
    )

    diagnostics = data.run.config["llm_structured_extraction"]
    assert diagnostics["triggered"] is True
    assert diagnostics["applied_to_facts"] is True
    assert diagnostics["candidate_count"] == 5
    assert diagnostics["accepted_count"] == 2
    assert diagnostics["rejected_count"] == 3
    assert diagnostics["applied_count"] == 2
    assert diagnostics["reject_reasons"] == {
        "snippet_not_found": 1,
        "source_not_captured": 1,
        "value_not_in_snippet": 1,
    }
    assert diagnostics["accepted_claim_paths"] == {"admissions.fees": 1, "programme_catalog[].name": 1}
    assert diagnostics["write_status_counts"] == {"applied": 2, "not_applicable": 3}
    applied_results = [result for result in diagnostics["results"] if result.get("write_status") == "applied"]
    assert {result["evidence_path"] for result in applied_results} == {"/fees/0/value", "/programme_catalog/0/name"}
    assert all(result["extractor"] == "llm_fallback_validated" for result in applied_results)
    assert all(result["validation_status"] == "accepted" for result in applied_results)
    assert "fees" in data.run.config["coverage"]["found"]
    assert "fees" not in data.run.config["coverage"]["missing"]
    assert "fees" not in data.run.config["missing_reasons"]
    assert data.run.config["template_completeness"]["fields"]["fees"]["status"] == "found"
    assert len(data.fees) == 1
    assert data.fees[0].label == "tuition/fees"
    assert data.fees[0].value.value == "annual tuition charge for international students"
    assert data.fees[0].value.raw_text == valid_snippet
    assert data.fees[0].value.parse_status == "llm_fallback_validated"
    assert data.fees[0].value.evidence == ["/fees/0/value"]
    assert data.evidence[-1].claim_path == "/fees/0/value"
    assert data.evidence[-1].source_url == fee_url
    assert data.evidence[-1].snippet == valid_snippet
    fee_request = next(request for request in provider.requests if request["source_url"] == fee_url)
    assert "admissions.fees" in fee_request["allowed_claim_paths"]
    programme_row = data.programme_catalog[0]
    assert programme_row.name == "Data Futures Bachelor pathway"
    assert programme_row.source_url == programme_url
    assert programme_row.evidence_snippet == programme_snippet
    assert programme_row.evidence_path == "/programme_catalog/0/name"
    assert programme_row.parse_status == "llm_fallback_validated"
    csv_text = render_programme_catalog_csv(data)
    assert "programme_id,name,faculty_or_school" in csv_text
    assert "programme-catalog-001,Data Futures Bachelor pathway" in csv_text
    assert "llm_fallback_validated" in csv_text


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
    extraction_summary = data.run.config["extraction_diagnostics_summary"]
    missing_reasons = data.run.config["missing_reasons"]
    template = data.run.config["template_completeness"]
    field_capabilities = data.run.config["field_capability_matrix"]
    assert coverage["found_count"] > 0
    assert "coverage_ratio" in coverage
    assert set(field_capabilities) == set(coverage["found"]) | set(coverage["missing"])
    assert field_capabilities["fees"]["discovery_categories"] == ["fees"]
    assert field_capabilities["fees"]["context_gates"] == ["has_undergraduate_fee_context", "has_undergraduate_admissions_context"]
    assert field_capabilities["fees"]["deterministic_extractors"] == ["extract_fee"]
    assert field_capabilities["fees"]["structured_llm_fallback"] is True
    assert field_capabilities["fees"]["llm_claim_paths"] == ["admissions.fees"]
    assert template["fields_total"] == coverage["core_fields_total"]
    assert template["found_count"] == coverage["found_count"]
    assert set(template["fields"]) == set(coverage["found"]) | set(coverage["missing"])
    assert template["fields"]["fees"]["capability"] == field_capabilities["fees"]
    assert template["fields"]["application_periods"]["status_flags"] == ["source_found"]
    assert template["fields"]["application_periods"]["next_action"] == "none"
    assert data.run.config["source_strategy_summary"]["html_page"] >= 1
    assert extraction_summary["sources_count"] == len(data.run.config["extraction_diagnostics"])
    assert extraction_summary["attempts_count"] > 0
    assert extraction_summary["sources_with_extractions"] > 0
    assert "application_periods" in extraction_summary["field_status_counts"]
    assert any(item["attempts"] for item in data.run.config["extraction_diagnostics"])
    attempts = [attempt for item in data.run.config["extraction_diagnostics"] for attempt in item["attempts"]]
    assert all({"field", "extractor", "status", "reason", "record_count", "evidence_count"} <= attempt.keys() for attempt in attempts)
    assert any(attempt["field"] == "fees" and attempt["extractor"] == "extract_fee" for attempt in attempts)
    assert set(missing_reasons) == set(coverage["missing"])
    assert all(
        details["reason"]
        in {
            "source_not_found",
            "attempted_no_match",
            "context_gate_failed",
            "raw_needs_manual_review",
            "blocked_or_challenge",
            "portal_or_login_required",
            "manual_check_required",
        }
        for details in missing_reasons.values()
    )
    assert all(details["capability"]["diagnostics_reasons"] for details in missing_reasons.values())
    assert all(details["action_target"] for details in missing_reasons.values())
    assert all(
        details["next_action"]
        in {
            "none",
            "improve_source_discovery_or_llm_source_navigation",
            "improve_extractor_or_context_gate",
            "manual_check_required",
        }
        for details in template["fields"].values()
    )
    assert "probable_incomplete_catalog" in template["programme_catalog"]
    assert data.run.config["relevance_strategy"] == "admissions_programme_profile"
    strategy_entries = data.run.config["source_strategy"]
    admissions_entry = next(item for item in strategy_entries if item["url"] == "https://fixture.test/admissions/index.html")
    assert isinstance(admissions_entry["discovery_score"], int)
    assert admissions_entry["relevance_strategy"] == "admissions_programme_profile"
    assert "positive_keyword:admission" in admissions_entry["discovery_signals"]
    assert "path_relevance_hint:/admission" in admissions_entry["discovery_signals"]
    assert "profile_positive:/admission" in admissions_entry["discovery_signals"]


def test_missing_reasons_prefers_no_match_over_context_gate_when_both_exist():
    reasons = _missing_reasons(
        {"missing": ["fees"]},
        [
            {
                "url": "https://example.edu/admissions/fees",
                "attempts": [
                    {
                        "field": "fees",
                        "extractor": "extract_fee",
                        "status": "skipped",
                        "reason": "context_gate_failed",
                    }
                ],
            },
            {
                "url": "https://example.edu/admissions/tuition",
                "attempts": [
                    {
                        "field": "fees",
                        "extractor": "extract_fee",
                        "status": "no_match",
                        "reason": "category_route",
                    }
                ],
            },
        ],
        [],
    )

    assert reasons["fees"]["reason"] == "attempted_no_match"
    assert reasons["fees"]["attempts"] == 2
    assert reasons["fees"]["capability"]["deterministic_extractors"] == ["extract_fee"]
    assert reasons["fees"]["capability"]["llm_claim_paths"] == ["admissions.fees"]
    assert reasons["fees"]["source_urls"] == [
        "https://example.edu/admissions/fees",
        "https://example.edu/admissions/tuition",
    ]


def test_missing_reasons_prefers_portal_over_generic_manual_check():
    reasons = _missing_reasons(
        {"missing": ["required_documents"]},
        [
            {
                "url": "https://example.edu/admissions/requirements",
                "attempts": [
                    {
                        "field": "required_documents",
                        "extractor": "extract_required_document",
                        "status": "skipped",
                        "reason": "existing_value",
                    }
                ],
            }
        ],
        [
            {
                "url": "https://apply.example.edu/login",
                "strategy": "application_portal",
            }
        ],
    )

    assert reasons["required_documents"]["reason"] == "portal_or_login_required"
    assert reasons["required_documents"]["legacy_reason"] == "application_portal_unreachable"
    assert reasons["required_documents"]["action_target"] == "portal_or_manual_review"
    assert reasons["required_documents"]["source_urls"] == [
        "https://example.edu/admissions/requirements",
    ]


def test_missing_reasons_prefers_source_acquisition_failure_for_blocked_source_attempts():
    blocked_url = "https://www.nus.edu.sg/oam/undergraduate-programmes"
    reasons = _missing_reasons(
        {"missing": ["programmes"]},
        [
            {
                "url": blocked_url,
                "source_acquisition_status": "blocked_or_challenge",
                "attempts": [
                    {
                        "field": "programmes",
                        "extractor": "extract_programmes",
                        "status": "no_match",
                        "reason": "category_route",
                    }
                ],
            }
        ],
        [
            {
                "url": blocked_url,
                "strategy": "blocked_or_challenge",
            }
        ],
    )

    assert reasons["programmes"]["reason"] == "blocked_or_challenge"
    assert reasons["programmes"]["legacy_reason"] == "source_not_crawled"
    assert reasons["programmes"]["action_target"] == "source_acquisition"
    assert reasons["programmes"]["attempts"] == 1
    assert reasons["programmes"]["attempted_extractors"] == ["extract_programmes"]
    assert reasons["programmes"]["capability"]["discovery_categories"] == ["programme_list", "programme_prerequisites"]
    assert reasons["programmes"]["source_urls"] == [blocked_url]


def test_missing_reasons_scope_blocked_sources_to_field_capability_categories():
    blocked_url = "https://example.edu/programmes"
    reasons = _missing_reasons(
        {"missing": ["fees"]},
        [],
        [
            {
                "url": blocked_url,
                "category": "programme_list",
                "strategy": "blocked_or_challenge",
            }
        ],
    )

    assert reasons["fees"]["reason"] == "source_not_found"
    assert reasons["fees"]["legacy_reason"] == "not_attempted"
    assert reasons["fees"]["action_target"] == "discovery_or_classifier"
    assert reasons["fees"]["source_urls"] == []


def test_template_completeness_marks_budget_skipped_source_plan_candidate():
    seed_url = "https://example.edu/"
    programme_url = "https://example.edu/programmes"
    fetcher = SourcePlanningFrontierFetcher(
        {
            seed_url: ("Access Denied", "Access denied. Please enable JavaScript and complete the captcha.", []),
            programme_url: ("Undergraduate Programmes", "Bachelor of Science", []),
        }
    )

    data = run_scan(
        seed_url,
        fetcher,
        DiscoveryConfig(max_pages=1, max_depth=1, allowed_hosts={"example.edu"}),
        source_plan_provider=MockSourcePlanProvider(
            {
                "candidate_urls": [
                    {
                        "url": programme_url,
                        "reason": "Official programmes page candidate.",
                        "expected_category": "programme_list",
                    }
                ],
                "candidate_queries": [],
                "warnings": [],
            }
        ),
    )

    template = data.run.config["template_completeness"]
    assert template["fields"]["programmes"]["status_flags"] == ["source_budget_skipped"]
    assert template["fields"]["programmes"]["source_urls"] == [programme_url]
    assert template["fields"]["programmes"]["next_action"] == "improve_source_discovery_or_llm_source_navigation"


def test_pipeline_nus_saved_catalog_sample_discovers_official_sources_and_evidence_paths():
    fixture = json.loads(NUS_CATALOG_SAMPLES.read_text(encoding="utf-8"))
    homepage = fixture["university"]["homepage_url"] + "/"
    sources = fixture["sources"]
    sample_pages = {
        canonicalize_url(sample["source_url"]): (sample["source_title"], sample["text"], [])
        for sample in sources
    }
    business_url = sources[0]["source_url"]
    chs_url = "https://chs.nus.edu.sg/programmes"
    fetcher = _SavedOfficialSiteFetcher(
        {
            homepage: (
                "National University of Singapore",
                "NUS undergraduate admissions and programmes",
                [
                    "https://nus.edu.sg/oam/undergraduate-programmes",
                    business_url,
                    chs_url,
                    "https://www.nus.edu.sg/about",
                ],
            ),
            **sample_pages,
            "https://www.nus.edu.sg/about": ("About NUS", "About NUS research and campus life", []),
        }
    )

    data = run_scan(
        homepage,
        fetcher,
        DiscoveryConfig(max_pages=4, max_depth=1, allowed_domains={"nus.edu.sg"}),
    )

    fetched_urls = {source.source_url for source in data.sources}
    assert business_url in fetched_urls
    assert chs_url in fetched_urls
    assert "https://www.nus.edu.sg/about" not in fetcher.fetched
    assert _category_for(data, business_url) == SourceType.HTML
    assert _page_category_for(data, business_url) == "programme_list"
    _assert_catalog_row_with_evidence(data, "Bachelor of Business Administration with Honours", business_url)
    _assert_catalog_row_with_evidence(data, "CHS Primary Major: Chinese Languages and Cultures", chs_url)


def test_pipeline_hku_saved_catalog_sample_discovers_cards_and_evidence_paths():
    programme_url = "https://admissions.hku.hk/programmes/undergraduate-programmes"
    fetcher = _SavedOfficialSiteFetcher(
        {
            "https://www.hku.hk/": (
                "HKU",
                "HKU admissions undergraduate courses",
                [
                    "https://admissions.hku.hk/",
                    programme_url,
                    "https://www.hku.hk/about",
                ],
            ),
            "https://admissions.hku.hk/": (
                "Admissions Office",
                "Undergraduate admissions apply to HKU.",
                [programme_url],
            ),
            programme_url: _saved_source_page("hku", "programme_catalog_undergraduate_courses", title="Undergraduate Courses"),
            "https://www.hku.hk/about": ("About HKU", "Research excellence and campus history", []),
        }
    )

    data = run_scan(
        "https://www.hku.hk/",
        fetcher,
        DiscoveryConfig(max_pages=4, max_depth=2, allowed_domains={"hku.hk"}),
    )

    assert programme_url in {source.source_url for source in data.sources}
    assert _page_category_for(data, programme_url) == "programme_list"
    _assert_catalog_row_with_evidence(data, "Bachelor of Arts in Architectural Studies", programme_url)
    _assert_catalog_row_with_evidence(data, "Bachelor of Business Administration", programme_url)


def test_pipeline_ntu_saved_catalog_sample_discovers_programmes_and_evidence_paths():
    programme_url = "https://www.ntu.edu.sg/hass/admissions/programmes"
    fetcher = _SavedOfficialSiteFetcher(
        {
            "https://www.ntu.edu.sg/": (
                "NTU Singapore",
                "NTU undergraduate admissions",
                [
                    "https://www.ntu.edu.sg/admissions/undergraduate",
                    programme_url,
                    "https://www.ntu.edu.sg/news",
                ],
            ),
            "https://www.ntu.edu.sg/admissions/undergraduate": (
                "Undergraduate Admissions",
                "Undergraduate admissions application guide and programmes.",
                [programme_url],
            ),
            programme_url: _saved_source_page("ntu", "programme_catalog_hass"),
            "https://www.ntu.edu.sg/news": ("NTU News", "Alumni and research news", []),
        }
    )

    data = run_scan(
        "https://www.ntu.edu.sg/",
        fetcher,
        DiscoveryConfig(max_pages=4, max_depth=2, allowed_domains={"ntu.edu.sg"}),
    )

    assert programme_url in {source.source_url for source in data.sources}
    assert _page_category_for(data, programme_url) == "programme_list"
    _assert_catalog_row_with_evidence(data, "Bachelor of Fine Arts (BFA) in Design Art", programme_url)
    _assert_catalog_row_with_evidence(data, "Bachelor of Social Sciences (Hons)", programme_url)


def test_pipeline_polyu_saved_catalog_sample_discovers_choice_table_and_evidence_paths():
    programme_url = "https://www.polyu.edu.hk/study/ug/admissions/jupas"
    fetcher = _SavedOfficialSiteFetcher(
        {
            "https://www.polyu.edu.hk/": (
                "PolyU",
                "PolyU undergraduate admissions and study options",
                [
                    "https://www.polyu.edu.hk/study/ug/",
                    programme_url,
                    "https://www.polyu.edu.hk/contact-us/form.php",
                ],
            ),
            "https://www.polyu.edu.hk/study/ug/": (
                "Undergraduate Study",
                "Undergraduate admissions programme choices.",
                [programme_url],
            ),
            programme_url: _saved_source_page("polyu", "programme_catalog_jupas", title="JUPAS Undergraduate Programmes"),
            "https://www.polyu.edu.hk/contact-us/form.php": ("Contact Us", "General enquiry form", []),
        }
    )

    data = run_scan(
        "https://www.polyu.edu.hk/",
        fetcher,
        DiscoveryConfig(max_pages=4, max_depth=2, allowed_domains={"polyu.edu.hk"}),
    )

    assert programme_url in {source.source_url for source in data.sources}
    assert _page_category_for(data, programme_url) == "programme_list"
    _assert_catalog_row_with_evidence(data, "Architectural Studies", programme_url)
    _assert_catalog_row_with_evidence(data, "Computing and AI", programme_url)


def test_classification_assist_records_low_confidence_diagnostics_without_changing_rule_category():
    data = run_fixture_scan(
        ROOT,
        seed_url="https://fixture.test/blog.html",
        max_pages=1,
        max_depth=0,
        classification_assist_provider=MockClassificationAssistProvider(
            {
                "category": "irrelevant",
                "reason": "Mock assist treats the student blog as not admissions facts.",
                "confidence": "low",
                "signals": ["blog"],
            }
        ),
    )

    assert data.discovered_categories[0].category == "undergraduate_admissions"
    diagnostics = data.run.config["classification_assist"]
    assert diagnostics[0]["rule_category"] == "undergraduate_admissions"
    assert diagnostics[0]["rule_score"] == 1
    assert diagnostics[0]["candidate"]["category"] == "irrelevant"
    assert diagnostics[0]["applied"] is False
    summary = data.run.config["classification_assist_summary"]
    assert summary["entries_count"] == 1
    assert summary["fallback_count"] == 0
    assert summary["applied_count"] == 0
    assert summary["disagreement_count"] == 1
    assert summary["rule_categories"] == {"undergraduate_admissions": 1}
    assert summary["candidate_categories"] == {"irrelevant": 1}
    assert not data.admissions.application_periods


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


def test_ntu_undergraduate_tuition_saved_source_extracts_fee_table_reference():
    fee_url = "https://www.ntu.edu.sg/admissions/undergraduate/financial-matters/tuition-fees"
    title = "Tuition Fees | NTU Singapore"
    text = (SAVED / "ntu/980551993bc03f86.txt").read_text(encoding="utf-8")

    classification = classify_page(fee_url, title, text)
    assert classification.category == "fees"
    assert has_undergraduate_admissions_context(fee_url, title, text)
    assert has_undergraduate_fee_context(fee_url, title, text)
    record, evidence = extract_fee(text, source_from_text(source_url=fee_url, source_type=SourceType.HTML, title=title, text=text), "/fees/0/value")
    assert record is not None
    assert evidence
    assert "Tuition Fees For Semester 1 and 2" in record.value.value
    assert record.value.parsed == []
    assert record.value.parse_status == "raw_needs_manual_review"

    fetcher = _SavedSinglePageFetcher(
        {
            "https://fixture.test/": ("Home", f'<a href="{fee_url}">NTU undergraduate tuition fees</a>'),
            fee_url: (title, text),
        }
    )
    data = run_scan(
        "https://fixture.test/",
        fetcher,
        DiscoveryConfig(max_pages=3, max_depth=1, allowed_hosts={"fixture.test"}, allowed_domains={"ntu.edu.sg"}),
    )

    assert data.fees
    assert "fees" not in data.run.config["coverage"]["missing"]
    fee_diagnostics = next(item for item in data.run.config["extraction_diagnostics"] if item["url"] == fee_url)
    assert any(
        attempt["field"] == "fees" and attempt["extractor"] == "extract_fee" and attempt["status"] == "extracted" and attempt["reason"] == "category_route"
        for attempt in fee_diagnostics["attempts"]
    )


def test_ntu_undergraduate_tuition_amount_rows_parse_when_source_contains_values():
    fee_url = "https://www.ntu.edu.sg/admissions/undergraduate/financial-matters/tuition-fees"
    title = "Tuition Fees | NTU Singapore"
    text = (
        "Tuition Fees | NTU Singapore Undergraduate Financial Matters Tuition Fees "
        "Full-Time Programmes Tuition Fees For Semester 1 and 2 Accepted programme offer in 2026 | "
        "Singapore Citizen S$8,250 per year | "
        "Permanent Resident S$11,550 per year | "
        "International Student S$17,950 per year."
    )
    source = source_from_text(source_url=fee_url, source_type=SourceType.HTML, title=title, text=text)

    record, evidence = extract_fee(text, source, "/fees/0/value")

    assert record is not None
    assert evidence
    assert record.value.parse_status == "parsed"
    parsed = {(item["currency"], item["amount"], item["student_group"], item["billing_period"]) for item in record.value.parsed}
    assert ("SGD", 8250, "local", "per year") in parsed
    assert ("SGD", 11550, "permanent resident", "per year") in parsed
    assert ("SGD", 17950, "non-local", "per year") in parsed


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
        self.fetched = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
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


class _SavedOfficialSiteFetcher:
    engine = "saved-official-site"

    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url not in self.pages:
            return FetchResult(
                url=url,
                final_url=url,
                status=404,
                title="Not Found",
                content_type="text/plain",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
            )
        title, text, links = self.pages[url]
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
            links=list(links),
            source=source,
        )


def _saved_source_page(school: str, slug: str, *, title: str | None = None) -> tuple[str, str, list[str]]:
    base = SAVED / school / slug
    meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    text = base.with_suffix(".txt").read_text(encoding="utf-8")
    return title or meta["title"], text, []


def _page_category_for(data, url: str) -> str:
    record = next(item for item in data.discovered_categories if item.source_url == url)
    return str(record.category)


def _category_for(data, url: str) -> SourceType:
    source = next(item for item in data.sources if item.source_url == url)
    return source.source_type


def _assert_catalog_row_with_evidence(data, name: str, source_url: str) -> None:
    from university_admissions_crawler.extractor.schema import resolve_claim_path

    row = next(item for item in data.programme_catalog if item.name == name)
    assert row.source_url == source_url
    assert row.evidence_path.startswith("/programme_catalog/")
    assert row.evidence_path.endswith("/name")
    assert resolve_claim_path(data, row.evidence_path) == row.name
    evidence = next(item for item in data.evidence if item.claim_path == row.evidence_path)
    assert evidence.source_url == source_url
    assert row.name in evidence.snippet


class SourcePlanningFrontierFetcher:
    engine = "source-planning-frontier"

    def __init__(self, pages):
        self.pages = pages
        self.fetched = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        if url not in self.pages:
            return FetchResult(
                url=url,
                final_url=url,
                status=404,
                title="Not Found",
                content_type="text/plain",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
            )
        title, text, links = self.pages[url]
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
            links=list(links),
            source=source,
        )


def test_llm_structured_validation_summary_counts_reject_reasons_and_claim_paths():
    summary = llm_structured_validation_summary(
        [
            {
                "accepted": True,
                "candidate": {
                    "claim_path": "admissions.fees",
                    "value": "SGD 20,000",
                    "evidence_snippet": "Undergraduate admissions tuition fee is SGD 20,000 per year.",
                    "source_url": "https://example.edu/admissions/fees",
                    "confidence": 0.8,
                },
            },
            {
                "accepted": False,
                "reject_reason": "snippet_not_found",
                "candidate": {
                    "claim_path": "admissions.fees",
                    "value": "SGD 30,000",
                    "evidence_snippet": "Tuition fee is SGD 30,000.",
                    "source_url": "https://example.edu/admissions/fees",
                    "confidence": 0.8,
                },
            },
            {
                "accepted": False,
                "reject_reason": "source_not_captured",
                "candidate": None,
            },
        ]
    )

    assert summary["candidate_count"] == 3
    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] == 2
    assert summary["accepted_claim_paths"] == {"admissions.fees": 1}
    assert summary["reject_reasons"] == {"snippet_not_found": 1, "source_not_captured": 1}
