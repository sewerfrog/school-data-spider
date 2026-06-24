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
from university_admissions_crawler.extractor.schema import SourceType
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

    assert "## Missing Reasons" in report
    assert report.index("## Missing Reasons") < report.index("## Facts")
    assert "`accepted_qualifications`" in report
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
        assert data["run"]["config"]["relevance_strategy"] == "rule_based"


def test_cli_fixture_mock_llm_generates_reviewable_keyword_plan():
    with TemporaryDirectory() as tmp:
        code = main(
            [
                str(ROOT),
                "--fixture",
                "--keyword-query",
                "undergraduate admissions IELTS fees",
                "--enable-llm",
                "--llm-provider",
                "mock",
                "--output-dir",
                tmp,
            ]
        )
        assert code == 0
        data = json.loads((Path(tmp) / "result.json").read_text())
        report = (Path(tmp) / "report.md").read_text()
        assert data["run"]["config"]["keyword_plan"]["source"] == "llm"
        assert data["run"]["config"]["llm_keyword_plan"]["provider"] == "mock"
        assert data["run"]["config"]["llm_keyword_plan"]["fallback"] is False
        assert "## LLM Keyword Plan Diagnostics" in report


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
    assert "- Blocked/challenge sources: 1" in report
    assert "- Accepted candidate URLs: 1" in report
    assert "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/" in report
    assert "- Rejected candidate URLs: 1" in report
    assert "https://example.com/nus/admissions" in report
    assert "rejected `outside_allowed_domain`" in report
    assert "source planning diagnostics are not admissions facts" in report


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
    data = run_fixture_scan(ROOT, max_pages=1, max_depth=0)
    with TemporaryDirectory() as tmp:
        result_path, report_path = write_result_files(data, tmp)
        assert result_path == Path(tmp) / "result.json"
        assert report_path == Path(tmp) / "report.md"
        assert json.loads(result_path.read_text(encoding="utf-8"))["sources"]
        assert "Evidence appendix" in report_path.read_text(encoding="utf-8")


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
            main([str(ROOT), "--fixture", "--keyword-query", "fees", "--enable-llm", "--llm-provider", "openai"])
        except SystemExit as exc:
            assert exc.code != 0
        else:
            raise AssertionError("real LLM providers should remain guarded")


def test_cli_live_http_writes_json_and_markdown_from_local_server():
    with TemporaryDirectory() as out_tmp:
        with patch("university_admissions_crawler.cli.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
            code = main(
                [
                    "https://example.edu/",
                    "--enable-live-network",
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
        assert any(item["source_url"].endswith("/admissions.html") for item in data["evidence"])
        assert "Evidence appendix" in (Path(out_tmp) / "report.md").read_text()


def test_cli_auto_live_infers_domain_and_writes_coverage():
    with TemporaryDirectory() as out_tmp:
        with patch("university_admissions_crawler.cli.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
            code = main(
                [
                    "https://example.edu/",
                    "--auto",
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
        assert data["run"]["config"]["allowed_domains"] == ["example.edu"]
        assert data["run"]["config"]["coverage"]["found_count"] > 0
        assert "Core Field Coverage" in (Path(out_tmp) / "report.md").read_text()


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
                            "allowed_domains": ["example.edu"],
                            "max_pages": 2,
                            "max_depth": 1,
                            "mode": "live-http",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch("university_admissions_crawler.cli.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
            code = main(["--config", str(config_path), "--output-dir", out_tmp])
        assert code == 0
        result = Path(out_tmp) / "example-u" / "result.json"
        report = Path(out_tmp) / "example-u" / "report.md"
        assert result.exists()
        assert report.exists()
        data = json.loads(result.read_text())
        assert data["institution"]["name"]["value"] == "Example University"
        assert data["run"]["config"]["university_id"] == "example-u"


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
        with patch("university_admissions_crawler.cli.LiveHTTPFetcher", _FakeLiveHTTPFetcher):
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
        pass

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
