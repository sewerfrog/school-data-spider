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
                    "accepted_to_candidate_source_ratio": 0.0,
                    "low_row_yield": False,
                    "source_status_counts": {"dynamic_shell_no_rows": 1, "parsed_zero_rows": 1},
                    "probable_incomplete_catalog": True,
                    "recommended_next_action": "enable_browser_or_api_capture",
                    "sources_count": 0,
                }
            },
        ),
    )

    report = render_markdown_report(data)

    assert "## Programme Catalog Diagnostics" in report
    assert "- Candidate rows: 0" in report
    assert "- Candidate sources: 1" in report
    assert "- Catalog source statuses: `dynamic_shell_no_rows`: 1, `parsed_zero_rows`: 1" in report
    assert "- Recommended next action: `enable_browser_or_api_capture`" in report


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
        assert result.exists()
        assert report.exists()
        data = json.loads(result.read_text())
        assert data["institution"]["name"]["value"] == "Example University"
        assert data["run"]["config"]["university_id"] == "example-u"
        assert data["run"]["config"]["allowed_domains"] == ["example.edu"]
        assert data["run"]["config"]["max_pages"] == 80
        assert data["run"]["config"]["max_depth"] == 4


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
