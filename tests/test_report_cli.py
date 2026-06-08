import json
import contextlib
import io
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from university_admissions_crawler.cli import main
from university_admissions_crawler.crawler.fetcher import FetchResult
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.schema import SourceType
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan
from university_admissions_crawler.reports.render_report import render_markdown_report

ROOT = Path("tests/fixtures/mini_university_site")


def test_markdown_report_contains_evidence_and_no_verdict():
    data = run_fixture_scan(ROOT)
    report = render_markdown_report(data)
    assert "Evidence appendix" in report
    assert "Warnings / Manual check" in report
    assert "Discovered categories" in report
    assert "application_deadlines" in report
    assert "Required documents include transcripts and passport copy" in report
    assert "Admissions verdict: not provided" in report
    assert "you can" not in report.lower()


def test_markdown_report_marks_parsed_clean_candidates():
    data = run_fixture_scan(ROOT, seed_url="https://fixture.test/realistic-admissions.html", max_pages=1, max_depth=0)
    report = render_markdown_report(data)
    assert "parse `parsed`" in report
    assert '"amount": 45000' in report
    assert '"test_name": "IELTS"' in report


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
        assert "Evidence appendix" in report.read_text()


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
