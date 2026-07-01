"""CLI entry point for evidence-first fixture and guarded live scans."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from university_admissions_crawler.config_loader import (
    DEFAULT_TIMEOUT_SECONDS,
    FIXTURE_DEFAULT_MAX_DEPTH,
    FIXTURE_DEFAULT_MAX_PAGES,
    LIVE_DEFAULT_MAX_DEPTH,
    LIVE_DEFAULT_MAX_PAGES,
    SMOKE_MAX_DEPTH,
    SMOKE_MAX_PAGES,
)
from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import BrowserFallbackFetcher, LiveHTTPFetcher, PlaywrightBrowserFetcher
from university_admissions_crawler.crawler.relevance import build_relevance_strategy
from university_admissions_crawler.evidence.store import load_previous_result
from university_admissions_crawler.extractor.pdf_extractor import PypdfPDFExtractor
from university_admissions_crawler.pipeline.batch import _run_batch
from university_admissions_crawler.pipeline.diagnostics import inferred_allowed_domain
from university_admissions_crawler.pipeline.llm_runtime import attach_llm_runtime_config, llm_providers_for_args, resolve_llm_provider_name
from university_admissions_crawler.pipeline.output_writer import write_result_files
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan, run_scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evidence-first university admissions crawler MVP")
    parser.add_argument("input", nargs="?", help="Fixture root path for --fixture mode, live URL, or omitted with --config")
    parser.add_argument("--config", help="JSON university config file for batch live scans")
    parser.add_argument("--fixture", action="store_true", help="Run against a local fixture directory")
    parser.add_argument("--seed-url", default="https://fixture.test/", help="Seed URL for fixture mode")
    parser.add_argument("--output-dir", default="outputs/university-scan", help="Directory for result.json and report.md")
    parser.add_argument("--max-pages", type=int, help="Maximum pages to crawl; defaults to 80 for live scans and 20 for fixtures")
    parser.add_argument("--max-depth", type=int, help="Maximum link depth; defaults to 4 for live scans and 3 for fixtures")
    parser.add_argument("--allowed-host", action="append", default=[], help="Additional allowed host; repeatable")
    parser.add_argument("--allowed-domain", action="append", default=[], help="Additional allowed domain; repeatable")
    parser.add_argument("--previous-result", help="Optional prior result.json for incremental diff warnings")
    parser.add_argument("--auto", action="store_true", help="Compatibility flag; live one-URL scans now infer domain policy by default")
    parser.add_argument("--enable-live-network", action="store_true", help="Compatibility flag; live HTTP crawling is the default for non-fixture URLs")
    parser.add_argument("--smoke", action="store_true", help="Use conservative smoke caps unless explicit max values are supplied")
    parser.add_argument("--enable-llm", action="store_true", help="Compatibility flag; live scans enable LLM-assisted crawling by default unless --no-llm is supplied")
    parser.add_argument("--no-llm", action="store_true", help="Disable default LLM-assisted crawling for live scans")
    parser.add_argument("--deterministic-only", action="store_true", help="Alias for --no-llm; run without hosted or mock LLM providers")
    parser.add_argument("--llm-provider", choices=["auto", "mock", "openai", "anthropic", "gemini", "none"], help="LLM provider; default auto uses UAC_LLM_PROVIDER or OPENAI_API_KEY when available")
    parser.add_argument("--enable-classification-assist", action="store_true", help="Record mock LLM diagnostics for low-confidence page classifications; does not change extraction")
    parser.add_argument("--enable-source-planning", action="store_true", help="Use guarded mock LLM source candidates as crawl frontier hints; facts still require fetched evidence")
    parser.add_argument("--enable-llm-structured-extraction", action="store_true", help="Run guarded LLM structured extraction fallback on captured sources; only validated candidates may write missing facts")
    parser.add_argument("--keyword-query", help="Optional deterministic debug keyword query for keyword-assisted relevance diagnostics")
    parser.add_argument(
        "--relevance-strategy",
        default="admissions-programme",
        choices=["admissions-programme", "rule-based", "bm25-like"],
        help="Discovery relevance strategy; default uses the built-in admissions/programme profile",
    )
    parser.add_argument("--enable-browser", action="store_true", help="Enable HTTP-first Playwright fallback for JavaScript-rendered live pages")
    parser.add_argument("--enable-pdf", action="store_true", help="Use optional pypdf parser for live PDF sources")
    parser.add_argument("--browser-wait-until", default="domcontentloaded", choices=["commit", "domcontentloaded", "load", "networkidle"], help="Playwright page.goto wait condition")
    parser.add_argument("--browser-headed", action="store_true", help="Run the Playwright browser visibly instead of headless")
    parser.add_argument("--timeout-seconds", type=float, help="Per-page fetch timeout; defaults to 60 seconds for live scans")
    parser.add_argument("--user-agent", help="Optional user-agent string for live fetchers")
    parser.add_argument("--enable-scrapegraph", action="store_true", help="Guarded future ScrapeGraphAI mode; unsupported in this offline MVP")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _resolve_runtime_defaults(args)
    if (args.no_llm or args.deterministic_only) and (
        args.enable_llm or args.llm_provider or args.enable_classification_assist or args.enable_source_planning or args.enable_llm_structured_extraction
    ):
        parser.error("--no-llm/--deterministic-only cannot be combined with LLM provider or feature flags.")
    if args.llm_provider and args.llm_provider != "none" and not args.enable_llm:
        parser.error("--llm-provider requires --enable-llm.")
    if args.enable_classification_assist and not args.enable_llm:
        parser.error("--enable-classification-assist requires --enable-llm.")
    if args.enable_source_planning and not args.enable_llm:
        parser.error("--enable-source-planning requires --enable-llm.")
    if args.enable_llm_structured_extraction and not args.enable_llm:
        parser.error("--enable-llm-structured-extraction requires --enable-llm.")
    if args.enable_llm and args.resolved_llm_provider in {"anthropic", "gemini"}:
        parser.error("--llm-provider anthropic/gemini are reserved and not implemented.")
    if args.enable_llm and not args.enable_classification_assist and not args.enable_source_planning and not args.enable_llm_structured_extraction:
        parser.error("--enable-llm requires --enable-classification-assist, --enable-source-planning, or --enable-llm-structured-extraction.")
    if args.enable_scrapegraph:
        parser.error("ScrapeGraphAI mode is guarded and not implemented in this offline MVP.")
    if args.config:
        return _run_batch(parser, args)
    if not args.input:
        parser.error("input is required unless --config is supplied.")
    if args.fixture and (args.enable_live_network or args.enable_browser):
        parser.error("--fixture cannot be combined with live network/browser modes.")
    if not args.fixture and (args.auto or not args.enable_browser):
        args.enable_live_network = True
    max_pages = min(args.max_pages, SMOKE_MAX_PAGES) if args.smoke else args.max_pages
    max_depth = min(args.max_depth, SMOKE_MAX_DEPTH) if args.smoke else args.max_depth
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_result = load_previous_result(args.previous_result)
    source_output_dir = output_dir / "sources"
    classification_assist_provider, programme_catalog_assist_provider, source_plan_provider, structured_extraction_provider = llm_providers_for_args(args)
    try:
        keyword_plan, relevance_strategy = build_relevance_strategy(
            relevance_strategy=args.relevance_strategy,
            keyword_query=args.keyword_query,
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
            programme_catalog_assist_provider=programme_catalog_assist_provider,
            source_plan_provider=source_plan_provider,
            structured_extraction_provider=structured_extraction_provider,
        )
    else:
        seed_url = _require_live_url(parser, args.input)
        fetcher = (
            _browser_fallback_fetcher(seed_url, args)
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
                allowed_domains=_allowed_domains_for(seed_url, args.allowed_domain, True),
                keyword_plan=keyword_plan,
                relevance_strategy=relevance_strategy,
            ),
            previous_result=previous_result,
            pdf_extractor=PypdfPDFExtractor() if args.enable_pdf else None,
            source_output_dir=source_output_dir,
            classification_assist_provider=classification_assist_provider,
            programme_catalog_assist_provider=programme_catalog_assist_provider,
            source_plan_provider=source_plan_provider,
            structured_extraction_provider=structured_extraction_provider,
        )
    attach_llm_runtime_config(data, args)
    result_path, report_path = write_result_files(data, output_dir)
    print(f"Wrote {result_path}")
    print(f"Wrote {report_path}")
    return 0


def _browser_fallback_fetcher(seed_url: str, args: argparse.Namespace) -> BrowserFallbackFetcher:
    return BrowserFallbackFetcher(
        LiveHTTPFetcher(timeout_seconds=args.timeout_seconds, user_agent=args.user_agent),
        PlaywrightBrowserFetcher(
            timeout_seconds=args.timeout_seconds,
            wait_until=args.browser_wait_until,
            user_agent=args.user_agent,
            headless=not args.browser_headed,
        ),
        seed_url=seed_url,
    )


def _allowed_domains_for(seed_url: str, explicit_domains: list[str], infer: bool) -> set[str]:
    domains = set(explicit_domains)
    if infer:
        inferred = inferred_allowed_domain(seed_url)
        if inferred:
            domains.add(inferred)
    return domains


def _resolve_runtime_defaults(args: argparse.Namespace) -> None:
    live_profile = not args.fixture
    if args.max_pages is None:
        args.max_pages = LIVE_DEFAULT_MAX_PAGES if live_profile else FIXTURE_DEFAULT_MAX_PAGES
    if args.max_depth is None:
        args.max_depth = LIVE_DEFAULT_MAX_DEPTH if live_profile else FIXTURE_DEFAULT_MAX_DEPTH
    if args.timeout_seconds is None:
        args.timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    if live_profile and not args.no_llm and not args.deterministic_only:
        args.enable_llm = True
        args.enable_classification_assist = True
        args.enable_source_planning = True
        args.enable_llm_structured_extraction = True
    args.resolved_llm_provider = resolve_llm_provider_name(args.llm_provider) if args.enable_llm else None


def _require_live_url(parser: argparse.ArgumentParser, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parser.error("Live crawling input must be an absolute http(s) URL.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
