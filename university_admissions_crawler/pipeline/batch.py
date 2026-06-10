"""Batch scan orchestration for configured universities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from university_admissions_crawler.config_loader import UniversityConfig, load_university_configs
from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import LiveHTTPFetcher, PlaywrightBrowserFetcher
from university_admissions_crawler.extractor.pdf_extractor import PypdfPDFExtractor
from university_admissions_crawler.extractor.schema import AdmissionsData, Institution, RunMetadata, attach_validation_warnings
from university_admissions_crawler.pipeline.diagnostics import inferred_allowed_domain
from university_admissions_crawler.pipeline.merge import _merge_data
from university_admissions_crawler.pipeline.run_university_scan import run_scan
from university_admissions_crawler.reports.render_report import render_markdown_report


def _run_batch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.fixture:
        parser.error("--config batch mode currently supports live/browser scans, not fixture scans.")
    configs = load_university_configs(args.config)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    for university in configs:
        data = _run_university_config(args, university)
        if university.name and data.institution.name.is_unknownish:
            data.institution.name.value = university.name
        out_dir = output_root / university.id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(json.dumps(data.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "report.md").write_text(render_markdown_report(data), encoding="utf-8")
        print(f"Wrote {out_dir / 'result.json'}")
        print(f"Wrote {out_dir / 'report.md'}")
    return 0


def _run_university_config(args: argparse.Namespace, university: UniversityConfig) -> AdmissionsData:
    combined: AdmissionsData | None = None
    max_pages = university.max_pages or (min(args.max_pages, 20) if args.smoke else args.max_pages)
    max_depth = university.max_depth or (min(args.max_depth, 2) if args.smoke else args.max_depth)
    for seed_url in university.seed_urls:
        fetcher = _fetcher_for_mode(
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
            ),
            pdf_extractor=PypdfPDFExtractor() if args.enable_pdf else None,
            source_output_dir=Path(args.output_dir) / university.id / "sources",
        )
        combined = data if combined is None else _merge_data(combined, data)
    if combined is None:
        combined = AdmissionsData(institution=Institution(homepage_url=""), run=RunMetadata(input_url=""))
    combined.institution.name.value = university.name
    combined.institution.homepage_url = university.seed_urls[0]
    combined.run.config["university_id"] = university.id
    combined.run.config["seed_urls"] = university.seed_urls
    return attach_validation_warnings(combined)


def _fetcher_for_mode(mode: str, *, timeout_seconds: float, wait_until: str, user_agent: str | None, headless: bool):
    if mode in {"browser", "playwright", "playwright-browser"}:
        return PlaywrightBrowserFetcher(timeout_seconds=timeout_seconds, wait_until=wait_until, user_agent=user_agent, headless=headless)
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
