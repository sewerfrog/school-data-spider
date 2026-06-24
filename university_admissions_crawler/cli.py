"""CLI entry point for evidence-first fixture and guarded live scans."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import LiveHTTPFetcher, PlaywrightBrowserFetcher
from university_admissions_crawler.crawler.relevance import build_relevance_strategy
from university_admissions_crawler.evidence.store import load_previous_result
from university_admissions_crawler.extractor.llm_provider import MockClassificationAssistProvider, MockKeywordPlanProvider, MockSourcePlanProvider, generate_keyword_plan_with_fallback
from university_admissions_crawler.extractor.pdf_extractor import PypdfPDFExtractor
from university_admissions_crawler.pipeline.batch import _run_batch
from university_admissions_crawler.pipeline.diagnostics import inferred_allowed_domain
from university_admissions_crawler.pipeline.output_writer import write_result_files
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan, run_scan
from university_admissions_crawler.pipeline.source_planning import attach_source_plan_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence-first university admissions crawler MVP")
    parser.add_argument("input", nargs="?", help="Fixture root path for --fixture mode, live URL, or omitted with --config")
    parser.add_argument("--config", help="JSON university config file for batch live scans")
    parser.add_argument("--fixture", action="store_true", help="Run against a local fixture directory")
    parser.add_argument("--seed-url", default="https://fixture.test/", help="Seed URL for fixture mode")
    parser.add_argument("--output-dir", default="outputs/university-scan", help="Directory for result.json and report.md")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--allowed-host", action="append", default=[], help="Additional allowed host; repeatable")
    parser.add_argument("--allowed-domain", action="append", default=[], help="Additional allowed domain; repeatable")
    parser.add_argument("--previous-result", help="Optional prior result.json for incremental diff warnings")
    parser.add_argument("--auto", action="store_true", help="Infer live crawl domain policy from the input URL; intended for one-URL university scans")
    parser.add_argument("--enable-live-network", action="store_true", help="Enable guarded live HTTP crawling for the input URL")
    parser.add_argument("--smoke", action="store_true", help="Use conservative smoke caps unless explicit max values are supplied")
    parser.add_argument("--enable-llm", action="store_true", help="Guarded future LLM mode; unsupported in this offline MVP")
    parser.add_argument("--llm-provider", choices=["mock", "openai", "anthropic", "gemini"], help="Reserved provider selector for future guarded LLM mode")
    parser.add_argument("--enable-classification-assist", action="store_true", help="Record mock LLM diagnostics for low-confidence page classifications; does not change extraction")
    parser.add_argument("--enable-source-planning", action="store_true", help="Record mock LLM diagnostics with candidate official source hints; does not crawl candidates or change facts")
    parser.add_argument("--keyword-query", help="Optional user keyword query recorded as a reviewable keyword plan; does not change crawl behavior yet")
    parser.add_argument("--relevance-strategy", default="rule-based", choices=["rule-based", "bm25-like"], help="Opt-in discovery relevance strategy; default preserves existing rule-based scoring")
    parser.add_argument("--enable-browser", action="store_true", help="Use Playwright browser-backed live crawling for JavaScript-rendered pages")
    parser.add_argument("--enable-pdf", action="store_true", help="Use optional pypdf parser for live PDF sources")
    parser.add_argument("--browser-wait-until", default="networkidle", choices=["commit", "domcontentloaded", "load", "networkidle"], help="Playwright page.goto wait condition")
    parser.add_argument("--browser-headed", action="store_true", help="Run the Playwright browser visibly instead of headless")
    parser.add_argument("--timeout-seconds", type=float, default=15.0, help="Per-page fetch timeout")
    parser.add_argument("--user-agent", help="Optional user-agent string for live fetchers")
    parser.add_argument("--enable-scrapegraph", action="store_true", help="Guarded future ScrapeGraphAI mode; unsupported in this offline MVP")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.llm_provider and not args.enable_llm:
        parser.error("--llm-provider requires --enable-llm.")
    if args.enable_classification_assist and not args.enable_llm:
        parser.error("--enable-classification-assist requires --enable-llm.")
    if args.enable_source_planning and not args.enable_llm:
        parser.error("--enable-source-planning requires --enable-llm.")
    if args.enable_llm and args.llm_provider != "mock":
        parser.error("Only --llm-provider mock is supported for guarded keyword-plan generation.")
    if args.enable_llm and not args.keyword_query and not args.enable_classification_assist and not args.enable_source_planning:
        parser.error("--enable-llm requires --keyword-query, --enable-classification-assist, or --enable-source-planning.")
    if args.enable_scrapegraph:
        parser.error("ScrapeGraphAI mode is guarded and not implemented in this offline MVP.")
    if args.config:
        return _run_batch(parser, args)
    if not args.input:
        parser.error("input is required unless --config is supplied.")
    if args.fixture and (args.enable_live_network or args.enable_browser):
        parser.error("--fixture cannot be combined with live network/browser modes.")
    if args.auto and not args.fixture:
        args.enable_live_network = True
    if not args.fixture and not (args.enable_live_network or args.enable_browser):
        parser.error("Use --fixture for a local fixture scan, or explicitly pass --enable-live-network / --enable-browser for live crawling.")
    max_pages = min(args.max_pages, 20) if args.smoke else args.max_pages
    max_depth = min(args.max_depth, 2) if args.smoke else args.max_depth
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_result = load_previous_result(args.previous_result)
    source_output_dir = output_dir / "sources"
    llm_keyword_plan_diagnostics = None
    keyword_plan_override = None
    classification_assist_provider = MockClassificationAssistProvider() if args.enable_classification_assist else None
    source_plan_provider = MockSourcePlanProvider() if args.enable_source_planning else None
    if args.enable_llm and args.keyword_query:
        llm_result = generate_keyword_plan_with_fallback(args.keyword_query, MockKeywordPlanProvider())
        keyword_plan_override = llm_result.keyword_plan
        llm_keyword_plan_diagnostics = llm_result.diagnostics
    try:
        keyword_plan, relevance_strategy = build_relevance_strategy(
            relevance_strategy=args.relevance_strategy,
            keyword_query=args.keyword_query,
            keyword_plan=keyword_plan_override,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.fixture:
        data = run_fixture_scan(
            args.input,
            seed_url=args.seed_url,
            max_pages=max_pages,
            max_depth=max_depth,
            previous_result=previous_result,
            allowed_hosts=set(args.allowed_host),
            allowed_domains=set(args.allowed_domain),
            keyword_plan=keyword_plan,
            relevance_strategy=relevance_strategy,
            source_output_dir=source_output_dir,
            classification_assist_provider=classification_assist_provider,
        )
        if llm_keyword_plan_diagnostics is not None:
            data.run.config["llm_keyword_plan"] = llm_keyword_plan_diagnostics
        if source_plan_provider is not None:
            attach_source_plan_diagnostics(data, source_plan_provider)
    else:
        seed_url = _require_live_url(parser, args.input)
        fetcher = (
            PlaywrightBrowserFetcher(
                timeout_seconds=args.timeout_seconds,
                wait_until=args.browser_wait_until,
                user_agent=args.user_agent,
                headless=not args.browser_headed,
            )
            if args.enable_browser
            else LiveHTTPFetcher(timeout_seconds=args.timeout_seconds, user_agent=args.user_agent)
        )
        data = run_scan(
            seed_url,
            fetcher,
            DiscoveryConfig(
                max_pages=max_pages,
                max_depth=max_depth,
                allowed_hosts=set(args.allowed_host),
                allowed_domains=_allowed_domains_for(seed_url, args.allowed_domain, args.auto),
                keyword_plan=keyword_plan,
                relevance_strategy=relevance_strategy,
            ),
            previous_result=previous_result,
            pdf_extractor=PypdfPDFExtractor() if args.enable_pdf else None,
            source_output_dir=source_output_dir,
            classification_assist_provider=classification_assist_provider,
        )
        if llm_keyword_plan_diagnostics is not None:
            data.run.config["llm_keyword_plan"] = llm_keyword_plan_diagnostics
        if source_plan_provider is not None:
            attach_source_plan_diagnostics(data, source_plan_provider)
    result_path, report_path = write_result_files(data, output_dir)
    print(f"Wrote {result_path}")
    print(f"Wrote {report_path}")
    return 0


def _allowed_domains_for(seed_url: str, explicit_domains: list[str], infer: bool) -> set[str]:
    domains = set(explicit_domains)
    if infer:
        inferred = inferred_allowed_domain(seed_url)
        if inferred:
            domains.add(inferred)
    return domains


def _require_live_url(parser: argparse.ArgumentParser, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parser.error("Live crawling input must be an absolute http(s) URL.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
