"""Batch scan orchestration for configured universities."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from university_admissions_crawler.config_loader import SMOKE_MAX_DEPTH, SMOKE_MAX_PAGES, UniversityConfig, load_university_configs
from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import BrowserFallbackFetcher, LiveHTTPFetcher, PlaywrightBrowserFetcher
from university_admissions_crawler.crawler.relevance import build_relevance_strategy
from university_admissions_crawler.extractor.pdf_extractor import PypdfPDFExtractor
from university_admissions_crawler.extractor.schema import AdmissionsData, Institution, RunMetadata, attach_validation_warnings
from university_admissions_crawler.pipeline.diagnostics import inferred_allowed_domain
from university_admissions_crawler.pipeline.llm_runtime import attach_llm_runtime_config, llm_providers_for_args
from university_admissions_crawler.pipeline.merge import merge_data
from university_admissions_crawler.pipeline.output_writer import write_result_files
from university_admissions_crawler.pipeline.run_university_scan import run_scan
from university_admissions_crawler.reports.structured_export import write_structured_batch_outputs


def _run_batch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.fixture:
        parser.error("--config batch mode currently supports live/browser scans, not fixture scans.")
    configs = load_university_configs(args.config)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    university_output_dirs: list[Path] = []
    for university in configs:
        try:
            data = _run_university_config(args, university)
        except ValueError as exc:
            parser.error(str(exc))
        if university.name and data.institution.name.is_unknownish:
            data.institution.name.value = university.name
        out_dir = output_root / university.id
        result_path, report_path = write_result_files(data, out_dir)
        university_output_dirs.append(out_dir)
        print(f"Wrote {result_path}")
        print(f"Wrote {report_path}")
    write_structured_batch_outputs(university_output_dirs, output_root / "structured")
    return 0


def _run_university_config(args: argparse.Namespace, university: UniversityConfig) -> AdmissionsData:
    combined: AdmissionsData | None = None
    max_pages, max_depth = _scan_limits_for_config(args, university)
    keyword_plan, relevance_strategy = build_relevance_strategy(
        relevance_strategy=university.relevance_strategy,
        keyword_query=university.keyword_query,
    )
    classification_assist_provider, programme_catalog_assist_provider, source_plan_provider, structured_extraction_provider = llm_providers_for_args(args)
    for seed_url in university.seed_urls:
        fetcher = _fetcher_for_mode(
            seed_url,
            university.mode,
            timeout_seconds=args.timeout_seconds,
            wait_until=args.browser_wait_until,
            user_agent=args.user_agent,
            headless=not args.browser_headed,
        )
        data = run_scan(
            _live_url(seed_url),
            fetcher,
            DiscoveryConfig(
                max_pages=max_pages,
                max_depth=max_depth,
                allowed_hosts=set(args.allowed_host) | set(university.allowed_hosts),
                allowed_domains=set(args.allowed_domain) | set(university.allowed_domains) | _allowed_domains_for(seed_url, [], True),
                keyword_plan=keyword_plan,
                relevance_strategy=relevance_strategy,
            ),
            pdf_extractor=PypdfPDFExtractor() if args.enable_pdf else None,
            source_output_dir=Path(args.output_dir) / university.id / "sources",
            classification_assist_provider=classification_assist_provider,
            programme_catalog_assist_provider=programme_catalog_assist_provider,
            source_plan_provider=source_plan_provider,
            structured_extraction_provider=structured_extraction_provider,
        )
        combined = data if combined is None else merge_data(combined, data)
    if combined is None:
        combined = AdmissionsData(institution=Institution(homepage_url=""), run=RunMetadata(input_url=""))
    combined.institution.name.value = university.name
    combined.institution.homepage_url = university.seed_urls[0]
    combined.run.config["university_id"] = university.id
    combined.run.config["seed_urls"] = university.seed_urls
    attach_llm_runtime_config(combined, args)
    return attach_validation_warnings(combined)


def _scan_limits_for_config(args: argparse.Namespace, university: UniversityConfig) -> tuple[int, int]:
    max_pages = min(args.max_pages, SMOKE_MAX_PAGES) if args.smoke else args.max_pages
    max_depth = min(args.max_depth, SMOKE_MAX_DEPTH) if args.smoke else args.max_depth
    return university.max_pages or max_pages, university.max_depth or max_depth


def _fetcher_for_mode(seed_url: str, mode: str, *, timeout_seconds: float, wait_until: str, user_agent: str | None, headless: bool):
    if mode in {"browser", "playwright", "playwright-browser"}:
        return BrowserFallbackFetcher(
            LiveHTTPFetcher(timeout_seconds=timeout_seconds, user_agent=user_agent),
            PlaywrightBrowserFetcher(timeout_seconds=timeout_seconds, wait_until=wait_until, user_agent=user_agent, headless=headless),
            seed_url=seed_url,
        )
    if mode in {"live-http", "http"}:
        return LiveHTTPFetcher(timeout_seconds=timeout_seconds, user_agent=user_agent)
    raise ValueError(f"Unsupported university config mode: {mode}")


def _allowed_domains_for(seed_url: str, explicit_domains: list[str], infer: bool) -> set[str]:
    domains = set(explicit_domains)
    if infer:
        inferred = inferred_allowed_domain(seed_url)
        if inferred:
            domains.add(inferred)
    return domains


def _live_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Live crawling input must be an absolute http(s) URL: {value}")
    return value
