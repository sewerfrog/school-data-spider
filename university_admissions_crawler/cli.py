"""CLI entry point for evidence-first fixture and guarded live scans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from university_admissions_crawler.config_loader import UniversityConfig, load_university_configs
from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import LiveHTTPFetcher, PlaywrightBrowserFetcher
from university_admissions_crawler.evidence.store import load_previous_result
from university_admissions_crawler.extractor.pdf_extractor import PypdfPDFExtractor
from university_admissions_crawler.extractor.schema import AdmissionsData, EvidenceItem, FieldValue, Institution, RequirementRecord, RunMetadata, attach_validation_warnings
from university_admissions_crawler.pipeline.diagnostics import inferred_allowed_domain
from university_admissions_crawler.pipeline.run_university_scan import run_fixture_scan, run_scan
from university_admissions_crawler.reports.render_report import render_markdown_report


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
    if args.enable_llm or args.llm_provider:
        parser.error("LLM providers are guarded optional future capabilities and are not implemented in this offline MVP.")
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
    if args.fixture:
        data = run_fixture_scan(
            args.input,
            seed_url=args.seed_url,
            max_pages=max_pages,
            max_depth=max_depth,
            previous_result=previous_result,
            allowed_hosts=set(args.allowed_host),
            allowed_domains=set(args.allowed_domain),
            source_output_dir=source_output_dir,
        )
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
            ),
            previous_result=previous_result,
            pdf_extractor=PypdfPDFExtractor() if args.enable_pdf else None,
            source_output_dir=source_output_dir,
        )
    result_path = output_dir / "result.json"
    report_path = output_dir / "report.md"
    result_path.write_text(json.dumps(data.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_markdown_report(data), encoding="utf-8")
    print(f"Wrote {result_path}")
    print(f"Wrote {report_path}")
    return 0


def _run_batch(parser: argparse.ArgumentParser, args) -> int:
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


def _run_university_config(args, university: UniversityConfig) -> AdmissionsData:
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


def _merge_data(target: AdmissionsData, other: AdmissionsData) -> AdmissionsData:
    target.sources.extend(other.sources)
    _merge_requirement_list(target.admissions.application_periods, other.admissions.application_periods, target.evidence, other.evidence, "/admissions/application_periods")
    _merge_requirement_list(target.admissions.required_documents, other.admissions.required_documents, target.evidence, other.evidence, "/admissions/required_documents")
    _merge_requirement_list(target.admissions.english_requirements, other.admissions.english_requirements, target.evidence, other.evidence, "/admissions/english_requirements")
    _merge_requirement_list(target.admissions.accepted_qualifications, other.admissions.accepted_qualifications, target.evidence, other.evidence, "/admissions/accepted_qualifications")
    _merge_programmes(target, other)
    _merge_requirement_list(target.fees, other.fees, target.evidence, other.evidence, "/fees")
    _merge_requirement_list(target.scholarships, other.scholarships, target.evidence, other.evidence, "/scholarships")
    _merge_requirement_list(target.visa, other.visa, target.evidence, other.evidence, "/visa")
    _merge_requirement_list(target.housing, other.housing, target.evidence, other.evidence, "/housing")
    _merge_requirement_list(target.contacts, other.contacts, target.evidence, other.evidence, "/contacts")
    target.discovered_categories.extend(other.discovered_categories)
    target.warnings.extend(other.warnings)
    return target


def _merge_requirement_list(
    target_records: list[RequirementRecord],
    other_records: list[RequirementRecord],
    target_evidence: list[EvidenceItem],
    other_evidence: list[EvidenceItem],
    base_path: str,
) -> None:
    for record in other_records:
        old_paths = list(record.value.evidence)
        new_path = f"{base_path}/{len(target_records)}/value"
        _repoint_field(record.value, new_path)
        target_records.append(record)
        _copy_matching_evidence(other_evidence, target_evidence, old_paths, new_path)


def _merge_programmes(target: AdmissionsData, other: AdmissionsData) -> None:
    for programme in other.programmes:
        programme_index = len(target.programmes)
        old_name_paths = list(programme.name.evidence)
        name_path = f"/programmes/{programme_index}/name"
        _repoint_field(programme.name, name_path)
        programme.evidence = [name_path]
        for prereq_index, prereq in enumerate(programme.prerequisites):
            old_prereq_paths = list(prereq.value.evidence)
            prereq_path = f"/programmes/{programme_index}/prerequisites/{prereq_index}/value"
            _repoint_field(prereq.value, prereq_path)
            _copy_matching_evidence(other.evidence, target.evidence, old_prereq_paths, prereq_path)
        target.programmes.append(programme)
        _copy_matching_evidence(other.evidence, target.evidence, old_name_paths, name_path)


def _repoint_field(field: FieldValue, claim_path: str) -> None:
    if not field.is_unknownish:
        field.evidence = [claim_path]


def _copy_matching_evidence(source: list[EvidenceItem], dest: list[EvidenceItem], old_paths: list[str], new_path: str) -> None:
    wanted = set(old_paths)
    for item in source:
        if item.claim_path in wanted:
            item.claim_path = new_path
            dest.append(item)


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


def _require_live_url(parser: argparse.ArgumentParser, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parser.error("Live crawling input must be an absolute http(s) URL.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
