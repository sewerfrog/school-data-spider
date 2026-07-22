import json
import contextlib
import io
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from university_admissions_crawler.cli import main
from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import FetchResult
from university_admissions_crawler.crawler.relevance import keyword_plan_from_query
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.llm_provider import MockSourcePlanProvider
from university_admissions_crawler.extractor.schema import AdmissionsData, Institution, RunMetadata, SourceType
from university_admissions_crawler.pipeline.output_writer import write_result_files
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan, run_scan
from university_admissions_crawler.pipeline.source_planning import attach_source_plan_diagnostics
from university_admissions_crawler.reports.render_report import render_markdown_report

ROOT = Path("tests/fixtures/mini_university_site")


def test_markdown_report_contains_evidence_and_no_verdict():
    data = run_fixture_scan(ROOT)
    report = render_markdown_report(data)
    assert "Evidence appendix" in report
    assert "Warnings / Manual check" in report
    assert "## Extraction Diagnostics" in report
    assert "`application_periods`" in report
    assert report.index("## Extraction Diagnostics") < report.index("## Facts")
    assert "Discovered categories" in report
    assert "application_deadlines" in report
    assert "Required documents include transcripts and passport copy" in report
    assert "Admissions verdict: not provided" in report
    assert "you can" not in report.lower()


def test_markdown_report_shows_missing_reasons_before_facts_when_fields_are_missing():
    data = run_fixture_scan(ROOT, seed_url="https://fixture.test/realistic-admissions.html", max_pages=1, max_depth=0)
    report = render_markdown_report(data)

    assert "## Template Completeness Diagnostics" in report
    assert report.index("## Template Completeness Diagnostics") < report.index("## Facts")
    assert "- Next actions:" in report
    assert "## Missing Reasons" in report
    assert report.index("## Missing Reasons") < report.index("## Facts")
    assert "`accepted_qualifications`" in report
    assert "  - action target:" in report
    assert "  - compatibility reason:" in report
    assert "  - capability:" in report
    assert "they do not prove the official site lacks the field" in report


def test_markdown_report_marks_parsed_clean_candidates():
    data = run_fixture_scan(ROOT, seed_url="https://fixture.test/realistic-admissions.html", max_pages=1, max_depth=0)
    report = render_markdown_report(data)
    assert "parse `parsed`" in report
    assert '"amount": 45000' in report
    assert '"test_name": "IELTS"' in report


def test_markdown_report_shows_keyword_plan_only_as_diagnostics():
    data = run_fixture_scan(ROOT, keyword_plan=keyword_plan_from_query("fees tuition"))
    report = render_markdown_report(data)

    assert "## Keyword Plan" in report
    assert "- Query: fees tuition" in report
    assert report.index("## Keyword Plan") < report.index("## Facts")


def test_cli_fixture_smoke_writes_json_and_markdown():
    with TemporaryDirectory() as tmp:
        code = main([str(ROOT), "--fixture", "--output-dir", tmp])
        assert code == 0
        result = Path(tmp) / "result.json"
        report = Path(tmp) / "report.md"
        sources_dir = Path(tmp) / "sources"
        assert result.exists()
        assert report.exists()
        assert sources_dir.exists()
        assert list(sources_dir.glob("*.json"))
        data = json.loads(result.read_text())
        assert data["sources"]
        assert data["evidence"]
        assert data["warnings"]
        assert data["discovered_categories"]
        assert data["run"]["config"]["max_pages"] == 20
        assert data["run"]["config"]["max_depth"] == 3
        assert data["run"]["config"]["programme_detail_targeted_reserve"] == 0
        assert data["run"]["config"]["extraction_diagnostics_summary"]["attempts_count"] > 0
        assert set(data["run"]["config"]["missing_reasons"]) == set(data["run"]["config"]["coverage"]["missing"])
        assert "keyword_plan" not in data["run"]["config"]
        assert "llm_source_plan" not in data["run"]["config"]
        assert "Evidence appendix" in report.read_text()


def test_cli_fixture_records_explicit_keyword_query_plan():
    with TemporaryDirectory() as tmp:
        code = main([str(ROOT), "--fixture", "--keyword-query", "undergraduate admissions IELTS fees", "--output-dir", tmp])
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        keyword_plan = data["run"]["config"]["keyword_plan"]
        assert keyword_plan["query"] == "undergraduate admissions IELTS fees"
        assert keyword_plan["source"] == "user"
        assert keyword_plan["positive_keywords"] == ["undergraduate", "admissions", "ielts", "fees"]
        assert "/admissions" in keyword_plan["url_hints"]
        assert "/fees" in keyword_plan["url_hints"]
        assert data["run"]["config"]["relevance_strategy"] == "admissions_programme_profile"


def test_cli_fixture_accepts_explicit_rule_based_relevance_strategy():
    with TemporaryDirectory() as tmp:
        code = main([str(ROOT), "--fixture", "--relevance-strategy", "rule-based", "--output-dir", tmp])
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        assert data["run"]["config"]["relevance_strategy"] == "rule_based"


def test_cli_fixture_mock_source_planning_records_diagnostics_only():
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--seed-url",
                "https://fixture.test/realistic-admissions.html",
                "--max-pages",
                "1",
                "--max-depth",
                "0",
                "--enable-llm",
                "--llm-provider",
                "mock",
                "--enable-source-planning",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        source_plan = data["run"]["config"]["llm_source_plan"]
        assert source_plan["enabled"] is True
        assert source_plan["triggered"] is False
        assert source_plan["applied"] is False
        assert source_plan["candidate_urls"] == []
        assert source_plan["candidate_queries"] == []


def test_markdown_report_shows_source_planning_diagnostics_before_facts():
    seed_url = "https://www.nus.edu.sg/oam/undergraduate-programmes"
    text = Path("tests/fixtures/saved_sources/nus/incapsula_challenge.html").read_text(encoding="utf-8")
    data = run_scan(
        seed_url,
        _SinglePageFetcher(text),
        DiscoveryConfig(max_pages=1, max_depth=0, allowed_domains={"nus.edu.sg"}),
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
                        "reason": "Unofficial mirror-like page.",
                        "expected_category": "undergraduate_admissions",
                    },
                ],
                "candidate_queries": ["site:nus.edu.sg nus bulletin undergraduate programmes"],
                "warnings": [],
            }
        ),
    )

    report = render_markdown_report(data)

    assert "## Source Planning Diagnostics" in report
    assert report.index("## Source Planning Diagnostics") < report.index("## Facts")
    assert "- Enabled: True" in report
    assert "- Triggered: True" in report
    assert "- Applied: False" in report
    assert "- Crawled accepted candidate URLs: 0" in report
    assert "- Budget-skipped accepted candidate URLs: 0" in report
    assert "- Blocked/challenge sources: 1" in report
    assert "- Accepted candidate URLs: 1" in report
    assert "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/" in report
    assert "- Rejected candidate URLs: 1" in report
    assert "https://example.com/nus/admissions" in report
    assert "rejected `outside_allowed_domain`" in report
    assert "source planning diagnostics are not admissions facts" in report


def test_markdown_report_shows_source_planning_crawl_status():
    seed_url = "https://example.edu/"
    programme_url = "https://example.edu/programmes"
    data = run_scan(
        seed_url,
        _SourcePlanningReportFetcher(
            {
                seed_url: ("Access Denied", "Access denied. Please enable JavaScript and complete the captcha.", []),
                programme_url: ("Undergraduate Programmes", "Bachelor of Science", []),
            }
        ),
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

    report = render_markdown_report(data)

    assert "- Applied: True" in report
    assert "- Crawled accepted candidate URLs: 1" in report
    assert "- Budget-skipped accepted candidate URLs: 0" in report
    assert "https://example.edu/programmes (`programme_list`) crawl `crawled`" in report
    assert "- Candidate path patterns:" in report
    assert "  - /programmes" in report


def test_markdown_report_shows_programme_catalog_diagnostics_before_facts():
    data = run_fixture_scan(ROOT)
    report = render_markdown_report(data)

    assert "## Programme Catalog Diagnostics" in report
    assert report.index("## Programme Catalog Diagnostics") < report.index("## Facts")
    assert "- Candidate rows:" in report
    assert "- Accepted rows:" in report
    assert "- Candidate sources:" in report
    assert "- Crawled catalog sources:" in report
    assert "- Raw-needs-review rows:" in report
    assert "- Probable incomplete catalog:" in report
    assert "- Recommended next action:" in report
    assert "- Programme types:" in report
    assert "- Sources:" in report
    assert "https://fixture.test/programmes/index.html" in report
    assert "programme catalog diagnostics summarize table extraction and are not admissions facts" in report


def test_markdown_report_shows_zero_row_catalog_candidate_sources():
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(
            input_url="https://example.edu",
            config={
                "programme_catalog_summary": {
                    "candidate_count": 0,
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "candidate_source_count": 1,
                    "crawled_catalog_source_count": 1,
                    "accepted_row_count": 0,
                    "raw_needs_review_count": 0,
                    "catalog_complete": False,
                    "catalog_completeness_status": "probable_incomplete",
                    "canonical_catalog_captured": True,
                    "canonical_catalog_accepted": False,
                    "candidate_conservation_expected_count": 5,
                    "candidate_conservation_observed_count": 5,
                    "candidate_conservation_proven": True,
                    "identified_catalog_section_count": 1,
                    "processed_catalog_section_count": 1,
                    "catalog_section_conservation_proven": True,
                    "quarantined_candidate_count": 0,
                    "source_role_counts": {"canonical_catalog": 1},
                    "accepted_by_source_role": {},
                    "catalog_completeness_basis": ["candidate_conservation_proven"],
                    "catalog_completeness_failure_reasons": ["canonical_catalog_accepted"],
                    "catalog_completeness_failure_stages": ["segmentation"],
                    "catalog_completeness_failure_stage_counts": {"segmentation": 1},
                    "accepted_to_candidate_source_ratio": 0.0,
                    "low_row_yield": False,
                    "source_status_counts": {"dynamic_shell_no_rows": 1, "parsed_zero_rows": 1},
                    "catalog_source_family_counts": {"example.edu/undergraduate-programmes": 1},
                    "api_candidate_zero_reason": "browser_capture_no_network_json",
                    "false_positive_rejected_count": 0,
                    "candidate_diagnostic_count": 5,
                    "candidate_rejected_count": 2,
                    "candidate_context_count": 1,
                    "html_false_positive_rejected_count": 1,
                    "entity_gate_rejected_count": 1,
                    "accepted_without_structural_anchor_count": 0,
                    "institution_context_mismatch_count": 1,
                    "section_context_captured_count": 1,
                    "section_context_inherited_count": 1,
                    "group_context_captured_count": 0,
                    "group_context_inherited_count": 0,
                    "field_evidence_row_count": 1,
                    "field_evidence_path_count": 1,
                    "candidate_decision_counts": {"accepted": 2, "context": 1, "rejected": 2},
                    "candidate_rejection_reasons": {"admissions_explainer": 1, "unknown_table_shape": 1},
                    "candidate_context_reason_counts": {"section_context_captured": 1},
                    "accepted_candidate_shape_counts": {"section_context_candidate": 1, "text": 1},
                    "candidate_block_kind_counts": {"heading": 2, "list_item": 1, "paragraph": 2},
                    "accepted_source_role_counts": {"faculty_catalog": 2},
                    "accepted_structural_anchor_counts": {"faculty_degree_heading": 1, "programme_primary_link": 1},
                    "field_evidence_field_counts": {"faculty_or_school": 1},
                    "probable_incomplete_catalog": True,
                    "recommended_next_action": "discover_public_catalog_api",
                    "sources_count": 0,
                }
            },
        ),
    )

    report = render_markdown_report(data)

    assert "## Programme Catalog Diagnostics" in report
    assert "- Candidate rows: 0" in report
    assert "- Candidate sources: 1" in report
    assert "- Catalog completeness status: `probable_incomplete`" in report
    assert "- Catalog complete: False" in report
    assert "- Canonical catalog captured: True" in report
    assert "- Canonical catalog accepted: False" in report
    assert "- Candidate conservation: 5/5 (proven: True)" in report
    assert "- Catalog section conservation: 1/1 (proven: True)" in report
    assert "- Catalog source roles: `canonical_catalog`: 1" in report
    assert "- Completeness failure stages: `segmentation`: 1" in report
    assert "- Completeness proof basis: `candidate_conservation_proven`" in report
    assert "- Completeness proof failures: `canonical_catalog_accepted`" in report
    assert "- Catalog source statuses: `dynamic_shell_no_rows`: 1, `parsed_zero_rows`: 1" in report
    assert "- API candidate zero reason: `browser_capture_no_network_json`" in report
    assert "- False-positive rejected rows: 0" in report
    assert "- Programme candidate diagnostics: 5" in report
    assert "- Programme rejected candidates: 2" in report
    assert "- Programme false-positive candidate rejections: 1" in report
    assert "- Entity-gate rejections: 1" in report
    assert "- Accepted rows missing structural anchor: 0" in report
    assert "- Institution-context mismatches: 1" in report
    assert "- Section contexts captured: 1" in report
    assert "- Section-context accepted rows: 1" in report
    assert "- Field-evidence paths: 1" in report
    assert "- Programme rejection reasons: `admissions_explainer`: 1, `unknown_table_shape`: 1" in report
    assert "- Accepted source roles: `faculty_catalog`: 2" in report
    assert "- Accepted structural anchors: `faculty_degree_heading`: 1, `programme_primary_link`: 1" in report
    assert "- Field-evidence fields: `faculty_or_school`: 1" in report
    assert "- Catalog source families: `example.edu/undergraduate-programmes`: 1" in report
    assert "- Recommended next action: `discover_public_catalog_api`" in report


def test_markdown_report_shows_completeness_failure_before_any_catalog_candidate_is_found():
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(
            input_url="https://example.edu",
            config={
                "programme_catalog_summary": {
                    "candidate_count": 0,
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "candidate_source_count": 0,
                    "catalog_complete": False,
                    "catalog_completeness_status": "probable_incomplete",
                    "catalog_completeness_basis": ["no_quarantined_candidates"],
                    "catalog_completeness_failure_reasons": ["canonical_catalog_captured"],
                    "catalog_completeness_failure_stages": ["discovery"],
                    "catalog_completeness_failure_stage_counts": {"discovery": 1},
                    "probable_incomplete_catalog": True,
                }
            },
        ),
    )

    report = render_markdown_report(data)

    assert "## Programme Catalog Diagnostics" in report
    assert "- Candidate rows: 0" in report
    assert "- Candidate sources: 0" in report
    assert "- Catalog completeness status: `probable_incomplete`" in report
    assert "- Completeness failure stages: `discovery`: 1" in report
    assert "- Completeness proof failures: `canonical_catalog_captured`" in report


def test_markdown_report_explains_quality_adjusted_row_yield():
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(
            input_url="https://example.edu",
            config={
                "programme_catalog_summary": {
                    "candidate_count": 4,
                    "accepted_count": 4,
                    "rejected_count": 0,
                    "candidate_source_count": 5,
                    "accepted_row_count": 4,
                    "accepted_to_candidate_source_ratio": 0.8,
                    "quality_adjustment_applied": True,
                    "quality_adjusted_accepted_row_count": 1,
                    "quality_excluded_accepted_row_count": 3,
                    "quality_adjusted_accepted_to_candidate_source_ratio": 0.2,
                    "quality_exclusion_reason_counts": {
                        "accepted_manual_review": 1,
                        "missing_structural_anchor": 1,
                        "name_quality_failed": 1,
                    },
                    "raw_low_row_yield": False,
                    "low_row_yield": True,
                    "catalog_complete": False,
                    "catalog_completeness_status": "probable_incomplete",
                    "catalog_completeness_basis": [],
                    "catalog_completeness_failure_reasons": ["row_yield_not_suspicious"],
                    "catalog_completeness_failure_stage_counts": {"segmentation": 1},
                }
            },
        ),
    )

    report = render_markdown_report(data)

    assert "- Accepted/source ratio: 0.8" in report
    assert "- Quality-adjusted accepted rows: 1" in report
    assert "- Quality-excluded accepted rows: 3" in report
    assert "- Quality-adjusted accepted/source ratio: 0.2" in report
    assert (
        "- Quality exclusion reasons: `accepted_manual_review`: 1, "
        "`missing_structural_anchor`: 1, `name_quality_failed`: 1"
    ) in report
    assert "- Raw low row yield: False" in report
    assert "- Low row yield: True" in report
    assert "- Completeness proof failures: `row_yield_not_suspicious`" in report


def test_cli_fixture_mock_classification_assist_records_diagnostics_only():
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--seed-url",
                "https://fixture.test/blog.html",
                "--max-pages",
                "1",
                "--max-depth",
                "0",
                "--enable-llm",
                "--llm-provider",
                "mock",
                "--enable-classification-assist",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        report = (Path(tmp) / "report.md").read_text()
        diagnostics = data["run"]["config"]["classification_assist"]
        summary = data["run"]["config"]["classification_assist_summary"]
        assert diagnostics[0]["rule_category"] == "undergraduate_admissions"
        assert diagnostics[0]["candidate"]["category"] == "undergraduate_admissions"
        assert diagnostics[0]["applied"] is False
        assert summary["entries_count"] == 1
        assert summary["applied_count"] == 0
        assert summary["disagreement_count"] == 0
        assert data["discovered_categories"][0]["category"] == "undergraduate_admissions"
        assert "## Classification Assist Diagnostics" in report
        assert "- Entries: 1" in report
        assert "- Applied entries: 0" in report
        assert "- Rule/candidate disagreements: 0" in report
        assert "classification assist is diagnostics-only and does not change facts" in report
        assert "candidate `undergraduate_admissions`" in report


def test_cli_fixture_classification_assist_records_zero_trigger_summary():
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--seed-url",
                "https://fixture.test/admissions/index.html",
                "--max-pages",
                "1",
                "--max-depth",
                "0",
                "--enable-llm",
                "--llm-provider",
                "mock",
                "--enable-classification-assist",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        report = (Path(tmp) / "report.md").read_text()

        assert data["run"]["config"]["classification_assist"] == []
        summary = data["run"]["config"]["classification_assist_summary"]
        assert summary["entries_count"] == 0
        assert summary["fallback_count"] == 0
        assert summary["applied_count"] == 0
        assert summary["disagreement_count"] == 0
        assert "## Classification Assist Diagnostics" not in report


def test_cli_fixture_bm25_like_relevance_strategy_is_opt_in():
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--keyword-query",
                "fees tuition international",
                "--relevance-strategy",
                "bm25-like",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        assert data["run"]["config"]["relevance_strategy"] == "bm25_like"
        assert any(item["relevance_strategy"] == "bm25_like" for item in data["run"]["config"]["source_strategy"])


def test_cli_bm25_like_relevance_strategy_requires_keyword_query():
    with redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        try:
            main([str(ROOT), "--fixture", "--relevance-strategy", "bm25-like"])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("bm25-like relevance strategy should require --keyword-query")


def test_write_result_files_writes_json_and_markdown():
    data = run_fixture_scan(ROOT, seed_url="https://fixture.test/admissions/index.html", max_pages=1, max_depth=0)
    with TemporaryDirectory() as tmp:
        result_path, report_path = write_result_files(data, tmp)
        assert result_path == Path(tmp) / "result.json"
        assert report_path == Path(tmp) / "report.md"
        assert json.loads(result_path.read_text(encoding="utf-8"))["sources"]
        assert "Evidence appendix" in report_path.read_text(encoding="utf-8")
        assert not (Path(tmp) / "programme_catalog.csv").exists()


def test_cli_smoke_flag_caps_depth_and_provider_flags_are_guarded():
    with TemporaryDirectory() as tmp:
        code = main([str(ROOT), "--fixture", "--smoke", "--max-pages", "100", "--max-depth", "9", "--output-dir", tmp])
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        assert data["run"]["config"]["max_pages"] == 20
        assert data["run"]["config"]["max_depth"] == 2

    with redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        try:
            main([str(ROOT), "--fixture", "--enable-llm"])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("guarded LLM flag should exit non-zero")

    with redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        try:
            main([str(ROOT), "--fixture", "--keyword-query", "fees", "--enable-llm", "--llm-provider", "mock"])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("keyword-query should not enable LLM keyword-plan generation")

    with redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        try:
            main([str(ROOT), "--fixture", "--enable-classification-assist"])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("classification assist should require guarded LLM opt-in")

    with redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        try:
            main([str(ROOT), "--fixture", "--enable-source-planning"])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("source planning should require guarded LLM opt-in")

    with redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        try:
            main([str(ROOT), "--fixture", "--enable-llm-structured-extraction"])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("structured extraction should require guarded LLM opt-in")

    with redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        try:
            main([str(ROOT), "--fixture", "--enable-llm", "--llm-provider", "anthropic", "--enable-source-planning"])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("unimplemented hosted providers should remain guarded")


def test_cli_fixture_openai_source_planning_fails_closed_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--seed-url",
                "https://fixture.test/blog.html",
                "--max-pages",
                "1",
                "--max-depth",
                "0",
                "--enable-llm",
                "--llm-provider",
                "openai",
                "--enable-source-planning",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        source_plan = data["run"]["config"]["llm_source_plan"]
        assert source_plan["provider"] == "openai"
        assert source_plan["fallback"] is True
        assert "llm_source_plan_fallback" in source_plan["warnings"]


def test_cli_fixture_openai_chat_source_planning_fails_closed_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--seed-url",
                "https://fixture.test/blog.html",
                "--max-pages",
                "1",
                "--max-depth",
                "0",
                "--enable-llm",
                "--llm-provider",
                "openai-chat",
                "--enable-source-planning",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        source_plan = data["run"]["config"]["llm_source_plan"]
        assert source_plan["provider"] == "openai-chat"
        assert source_plan["fallback"] is True
        assert source_plan["error_type"] == "RuntimeError"
        assert "llm_source_plan_fallback" in source_plan["warnings"]


def test_cli_fixture_openai_structured_extraction_fails_closed_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--seed-url",
                "https://fixture.test/realistic-admissions.html",
                "--max-pages",
                "1",
                "--max-depth",
                "0",
                "--enable-llm",
                "--llm-provider",
                "openai",
                "--enable-llm-structured-extraction",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        diagnostics = data["run"]["config"]["llm_structured_extraction"]
        assert diagnostics["provider"] == "openai"
        assert diagnostics["candidate_count"] >= 1
        assert diagnostics["rejected_count"] == diagnostics["candidate_count"]
        assert any(result.get("error_type") == "RuntimeError" for result in diagnostics["results"])
        assert diagnostics["applied_to_facts"] is False


def test_cli_fixture_mock_llm_structured_extraction_records_report_diagnostics():
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--seed-url",
                "https://fixture.test/realistic-admissions.html",
                "--max-pages",
                "1",
                "--max-depth",
                "0",
                "--enable-llm",
                "--llm-provider",
                "mock",
                "--enable-llm-structured-extraction",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        diagnostics = data["run"]["config"]["llm_structured_extraction"]
        assert diagnostics["enabled"] is True
        assert diagnostics["provider"] == "mock"
        assert diagnostics["applied_to_facts"] is False
        assert "results" in diagnostics
        assert "source_urls_used" in diagnostics
        report = (Path(tmp) / "report.md").read_text()
        assert "## LLM Structured Extraction Diagnostics" in report
        assert report.index("## LLM Structured Extraction Diagnostics") < report.index("## Facts")
        assert "- Applied to facts: False" in report


def test_cli_live_http_writes_json_and_markdown_from_local_server():
    with TemporaryDirectory() as out_tmp:
        with patch("university_admissions_crawler.cli.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
            code = main(
                [
                    "https://example.edu/",
                    "--output-dir",
                    out_tmp,
                    "--max-pages",
                    "5",
                    "--max-depth",
                    "1",
                ]
            )
        assert code == 0
        data = json.loads((Path(out_tmp) / "result.json").read_text())
        assert data["sources"]
        assert data["evidence"]
        assert data["run"]["config"]["allowed_domains"] == ["example.edu"]
        assert data["run"]["config"]["programme_detail_targeted_effective_reserve"] == 1
        assert any(item["source_url"].endswith("/admissions.html") for item in data["evidence"])
        assert "Evidence appendix" in (Path(out_tmp) / "report.md").read_text()


def test_cli_live_defaults_infer_domain_and_use_homepage_first_limits(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("UAC_LLM_PROVIDER", raising=False)
    with TemporaryDirectory() as out_tmp:
        with patch("university_admissions_crawler.cli.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
            code = main(
                [
                    "https://example.edu/",
                    "--output-dir",
                    out_tmp,
                ]
            )
        assert code == 0
        data = json.loads((Path(out_tmp) / "result.json").read_text())
        assert data["run"]["config"]["allowed_domains"] == ["example.edu"]
        assert data["run"]["config"]["max_pages"] == 80
        assert data["run"]["config"]["max_depth"] == 4
        assert data["run"]["config"]["programme_detail_targeted_reserve"] == 4
        assert data["run"]["config"]["programme_detail_targeted_effective_reserve"] == 4
        assert data["run"]["config"]["llm_runtime"]["enabled"] is True
        assert data["run"]["config"]["llm_runtime"]["provider"] == "none"
        assert data["run"]["config"]["llm_runtime"]["features"]["source_planning"] is True
        assert data["run"]["config"]["llm_runtime"]["features"]["structured_extraction"] is True
        assert data["run"]["config"]["coverage"]["found_count"] > 0
        assert "Core Field Coverage" in (Path(out_tmp) / "report.md").read_text()


def test_cli_live_can_disable_default_llm_assist(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with TemporaryDirectory() as out_tmp:
        with patch("university_admissions_crawler.cli.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
            code = main(
                [
                    "https://example.edu/",
                    "--no-llm",
                    "--output-dir",
                    out_tmp,
                    "--max-pages",
                    "5",
                    "--max-depth",
                    "1",
                ]
            )
        assert code == 0
        data = json.loads((Path(out_tmp) / "result.json").read_text())
        assert data["run"]["config"]["llm_runtime"]["enabled"] is False
        assert data["run"]["config"]["llm_runtime"]["provider"] == "none"
        assert "llm_source_plan" not in data["run"]["config"]
        assert "llm_structured_extraction" not in data["run"]["config"]


def test_cli_browser_defaults_use_domcontentloaded_and_sixty_second_timeout():
    with TemporaryDirectory() as out_tmp:
        _RecordingBrowserFetcher.fetch_calls = []
        with (
            patch("university_admissions_crawler.cli.LiveHTTPFetcher", _FakeLiveHTTPFetcher),
            patch("university_admissions_crawler.cli.PlaywrightBrowserFetcher", _RecordingBrowserFetcher),
        ):
            code = main(["https://example.edu/", "--enable-browser", "--output-dir", out_tmp, "--max-pages", "1", "--max-depth", "0"])
        assert code == 0
        assert _RecordingBrowserFetcher.last_kwargs["timeout_seconds"] == 60.0
        assert _RecordingBrowserFetcher.last_kwargs["wait_until"] == "domcontentloaded"
        assert _RecordingBrowserFetcher.fetch_calls == []


def test_cli_browser_mode_falls_back_only_for_js_shell():
    with TemporaryDirectory() as out_tmp:
        _RecordingBrowserFetcher.fetch_calls = []
        with (
            patch("university_admissions_crawler.cli.LiveHTTPFetcher", _JsShellLiveHTTPFetcher),
            patch("university_admissions_crawler.cli.PlaywrightBrowserFetcher", _RecordingBrowserFetcher),
        ):
            code = main(["https://example.edu/", "--enable-browser", "--output-dir", out_tmp, "--max-pages", "1", "--max-depth", "0"])
        assert code == 0
        assert _RecordingBrowserFetcher.fetch_calls == ["https://example.edu/"]
        data = json.loads((Path(out_tmp) / "result.json").read_text())
        assert data["sources"][0]["engine"] == "browser-test"


def test_cli_config_batch_writes_per_university_outputs():
    with TemporaryDirectory() as config_tmp, TemporaryDirectory() as out_tmp:
        config_path = Path(config_tmp) / "universities.json"
        config_path.write_text(
            json.dumps(
                {
                    "universities": [
                        {
                            "id": "example-u",
                            "name": "Example University",
                            "seed_urls": ["https://example.edu/"],
                            "mode": "live-http",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch("university_admissions_crawler.pipeline.batch.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
            code = main(["--config", str(config_path), "--output-dir", out_tmp])
        assert code == 0
        result = Path(out_tmp) / "example-u" / "result.json"
        report = Path(out_tmp) / "example-u" / "report.md"
        batch_structured = Path(out_tmp) / "structured"
        assert result.exists()
        assert report.exists()
        assert (batch_structured / "manifest.json").exists()
        assert (batch_structured / "all_programme_catalog.jsonl").exists()
        assert (batch_structured / "all_missing_fields.jsonl").exists()
        assert (batch_structured / "all_sources.jsonl").exists()
        assert (batch_structured / "all_application_periods.jsonl").exists()
        assert (batch_structured / "all_visa.jsonl").exists()
        assert (batch_structured / "all_housing.jsonl").exists()
        batch_manifest = json.loads((batch_structured / "manifest.json").read_text(encoding="utf-8"))
        assert batch_manifest["university_output_count"] == 1
        assert batch_manifest["input_directory_names"] == ["example-u"]
        assert batch_manifest["files"]["all_visa"] == "all_visa.jsonl"
        assert batch_manifest["input_coverage"]["all_visa"]["present_file_count"] == 1
        assert batch_manifest["input_coverage"]["all_visa"]["missing_file_count"] == 0
        assert batch_manifest["input_coverage"]["all_visa"]["all_input_files_present"] is True
        assert batch_manifest["input_validation_summary"]["invalid_row_count"] == 12
        assert batch_manifest["input_validation_summary"]["all_rows_valid"] is False
        assert batch_manifest["input_validation"]["all_application_periods"]["reason_counts"] == {
            "duplicate_record_id": 6
        }
        assert batch_manifest["input_validation"]["all_required_documents"]["reason_counts"] == {
            "duplicate_record_id": 6
        }
        assert batch_manifest["input_validation"]["all_visa"]["all_rows_valid"] is True
        assert batch_manifest["reference_index_coverage"]["sources"]["all_index_files_readable"] is True
        assert batch_manifest["reference_index_coverage"]["evidence"]["all_index_files_readable"] is True
        assert batch_manifest["evidence_validation"]["invalid_row_count"] == 0
        assert batch_manifest["evidence_validation"]["all_rows_valid"] is True
        assert batch_manifest["batch_validation"]["status"] == "invalid"
        assert batch_manifest["batch_validation"]["ready_for_structured_consumption"] is False
        assert batch_manifest["batch_validation"]["reason_codes"] == ["invalid_input_rows"]
        assert batch_manifest["batch_validation"]["metrics"]["invalid_input_row_count"] == 12
        all_sources = [
            json.loads(line)
            for line in (batch_structured / "all_sources.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert all_sources
        assert {row["university_id"] for row in all_sources} == {"example-u"}
        data = json.loads(result.read_text())
        assert data["institution"]["name"]["value"] == "Example University"
        assert data["run"]["config"]["university_id"] == "example-u"
        assert data["run"]["config"]["allowed_domains"] == ["example.edu"]
        assert data["run"]["config"]["max_pages"] == 80
        assert data["run"]["config"]["max_depth"] == 4
        assert data["run"]["config"]["programme_detail_targeted_reserve"] == 4


def test_cli_config_batch_accepts_opt_in_keyword_plan_and_relevance_strategy():
    with TemporaryDirectory() as config_tmp, TemporaryDirectory() as out_tmp:
        config_path = Path(config_tmp) / "universities.json"
        config_path.write_text(
            json.dumps(
                {
                    "universities": [
                        {
                            "id": "example-u",
                            "name": "Example University",
                            "seed_urls": ["https://example.edu/"],
                            "allowed_domains": ["example.edu"],
                            "max_pages": 2,
                            "max_depth": 1,
                            "mode": "live-http",
                            "keyword_query": "fees tuition international",
                            "relevance_strategy": "bm25-like",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch("university_admissions_crawler.pipeline.batch.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
            code = main(["--config", str(config_path), "--output-dir", out_tmp])
        assert code == 0
        data = json.loads((Path(out_tmp) / "example-u" / "result.json").read_text())
        report = (Path(out_tmp) / "example-u" / "report.md").read_text()
        assert data["run"]["config"]["keyword_plan"]["query"] == "fees tuition international"
        assert data["run"]["config"]["relevance_strategy"] == "bm25_like"
        assert "## Keyword Plan" in report


def test_cli_config_batch_bm25_like_requires_keyword_query():
    with TemporaryDirectory() as config_tmp, TemporaryDirectory() as out_tmp:
        config_path = Path(config_tmp) / "universities.json"
        config_path.write_text(
            json.dumps(
                {
                    "id": "example-u",
                    "name": "Example University",
                    "seed_urls": ["https://example.edu/"],
                    "relevance_strategy": "bm25-like",
                }
            ),
            encoding="utf-8",
        )
        with redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            try:
                main(["--config", str(config_path), "--output-dir", out_tmp])
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError("batch bm25-like relevance strategy should require keyword_query")


class _FakeLiveHTTPFetcher:
    engine = "live-http-test"

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def fetch(self, url: str) -> FetchResult:
        if url.endswith("/"):
            text = '<title>Live Test University</title><a href="https://example.edu/admissions.html">Undergraduate Admissions</a>'
            source = source_from_text(
                source_url=url,
                source_type=SourceType.HTML,
                title="Live Test University",
                text=text,
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
            )
            return FetchResult(
                url=url,
                final_url=url,
                status=200,
                title="Live Test University",
                content_type="text/html",
                retrieved_at="2026-06-01T00:00:00+00:00",
                engine=self.engine,
                text=text,
                markdown="Live Test University Undergraduate Admissions",
                links=["https://example.edu/admissions.html"],
                source=source,
            )
        text = "Applicants should apply by 31 January 2027. Required documents include transcripts and passport copy."
        source = source_from_text(
            source_url=url,
            source_type=SourceType.HTML,
            title="Undergraduate Admissions",
            text=text,
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
        )
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title="Undergraduate Admissions",
            content_type="text/html",
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown=text,
            source=source,
        )


class _RecordingBrowserFetcher(_FakeLiveHTTPFetcher):
    engine = "browser-test"
    last_kwargs = {}
    fetch_calls = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).last_kwargs = kwargs

    def fetch(self, url: str) -> FetchResult:
        type(self).fetch_calls.append(url)
        return super().fetch(url)


class _JsShellLiveHTTPFetcher(_FakeLiveHTTPFetcher):
    engine = "live-http-js-shell-test"

    def fetch(self, url: str) -> FetchResult:
        text = "<title>Example University</title><div id='root'></div><script src='/app.js'></script><script src='/vendor.js'></script>"
        source = source_from_text(
            source_url=url,
            source_type=SourceType.HTML,
            title="Example University",
            text=text,
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
        )
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title="Example University",
            content_type="text/html",
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
            text=text,
            markdown="Example University",
            links=[],
            source=source,
        )


class _SinglePageFetcher:
    engine = "single-page-test"

    def __init__(self, text: str) -> None:
        self.text = text

    def fetch(self, url: str) -> FetchResult:
        source = source_from_text(
            source_url=url,
            source_type=SourceType.HTML,
            title="Request unsuccessful",
            text=self.text,
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
        )
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            title="Request unsuccessful",
            content_type="text/html",
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
            text=self.text,
            markdown=self.text,
            links=[],
            source=source,
        )


class _SourcePlanningReportFetcher:
    engine = "source-planning-report-test"

    def __init__(self, pages):
        self.pages = pages

    def fetch(self, url: str) -> FetchResult:
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
        source = source_from_text(
            source_url=url,
            source_type=SourceType.HTML,
            title=title,
            text=text,
            retrieved_at="2026-06-01T00:00:00+00:00",
            engine=self.engine,
        )
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
