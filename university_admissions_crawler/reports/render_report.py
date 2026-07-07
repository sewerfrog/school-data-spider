"""Markdown report rendering for evidence-first admissions output."""

from __future__ import annotations

import json

from university_admissions_crawler.extractor.schema import AdmissionsData, FieldValue, RequirementRecord


def render_markdown_report(data: AdmissionsData) -> str:
    lines: list[str] = []
    lines.append("# University Admissions Evidence Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Input URL: {data.run.input_url}")
    lines.append(f"- Retrieved at: {data.run.retrieved_at}")
    lines.append(f"- Sources captured: {len(data.sources)}")
    lines.append(f"- Evidence items: {len(data.evidence)}")
    lines.append(f"- Overall confidence: {data.confidence}")
    lines.append("- Admissions verdict: not provided; this report is evidence only.")
    lines.append("")
    _coverage(lines, data)
    _keyword_plan(lines, data)
    _classification_assist(lines, data)
    _source_strategy(lines, data)
    _source_planning(lines, data)
    _programme_catalog_browser_capture(lines, data)
    _programme_catalog_static_asset_discovery(lines, data)
    _api_catalog_discovery(lines, data)
    _template_completeness(lines, data)
    _programme_catalog_diagnostics(lines, data)
    _extraction_diagnostics(lines, data)
    _llm_structured_extraction(lines, data)
    _missing_reasons(lines, data)

    lines.append("## Discovered categories")
    lines.append("")
    if data.discovered_categories:
        for record in data.discovered_categories:
            signals = f" signals: {', '.join(record.signals)}" if record.signals else ""
            lines.append(f"- `{record.category}` — {record.title or record.source_url} ({record.source_url}), score {record.score}.{signals}")
    else:
        lines.append("- None recorded")
    lines.append("")

    lines.append("## Facts")
    lines.append("")
    _field(lines, "Undergraduate application entry", data.admissions.undergraduate_application_entry, data)
    _requirements(lines, "Application periods", data.admissions.application_periods)
    _requirements(lines, "English requirements", data.admissions.english_requirements)
    _requirements(lines, "Required documents", data.admissions.required_documents, data)
    _requirements(lines, "Accepted qualifications", data.admissions.accepted_qualifications, data)
    if data.programmes:
        lines.append("### Programmes")
        for programme in data.programmes:
            lines.append(f"- {programme.name.value} (source: {programme.source_url or 'unknown'})")
            for item in _evidence_for(data, programme.name.evidence):
                page = f", page {item.page_number}" if item.page_number else ""
                lines.append(f"  - evidence: {item.source_url}{page} — {item.snippet}")
            for prereq in programme.prerequisites:
                lines.append(f"  - {prereq.label}: {prereq.value.value}")
                for item in _evidence_for(data, prereq.value.evidence):
                    page = f", page {item.page_number}" if item.page_number else ""
                    lines.append(f"    - evidence: {item.source_url}{page} — {item.snippet}")
        lines.append("")
    _requirements(lines, "Fees", data.fees, data)
    _requirements(lines, "Scholarships", data.scholarships, data)
    _requirements(lines, "Visa / student pass", data.visa, data)
    _requirements(lines, "Housing", data.housing, data)
    _requirements(lines, "Contacts", data.contacts, data)

    lines.append("## Warnings / Manual check")
    lines.append("")
    if data.warnings:
        for warning in data.warnings:
            lines.append(f"- `{warning.code}` {warning.field or ''}: {warning.message}")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Sources")
    lines.append("")
    for source in data.sources:
        page = f", page {source.page_number}" if source.page_number else ""
        lines.append(f"- [{source.title or source.source_url}]({source.source_url}) — `{source.source_type}` retrieved {source.retrieved_at}{page}")
    lines.append("")

    lines.append("## Evidence appendix")
    lines.append("")
    for item in data.evidence:
        page = f", page {item.page_number}" if item.page_number else ""
        lines.append(f"- `{item.claim_path}` [{item.confidence}] {item.source_url}{page}: {item.snippet}")
    lines.append("")
    return "\n".join(lines)


def _coverage(lines: list[str], data: AdmissionsData) -> None:
    coverage = data.run.config.get("coverage")
    if not isinstance(coverage, dict):
        return
    lines.append("## Core Field Coverage")
    lines.append("")
    lines.append(f"- Found: {coverage.get('found_count', 0)}/{coverage.get('core_fields_total', 0)}")
    missing = coverage.get("missing") or []
    if missing:
        lines.append(f"- Missing: {', '.join(str(item) for item in missing)}")
    else:
        lines.append("- Missing: none")
    lines.append("- Note: coverage reports field completeness; overall confidence reports evidence quality for extracted claims.")
    lines.append("")


def _keyword_plan(lines: list[str], data: AdmissionsData) -> None:
    keyword_plan = data.run.config.get("keyword_plan")
    if not isinstance(keyword_plan, dict):
        return
    lines.append("## Keyword Plan")
    lines.append("")
    lines.append(f"- Source: `{keyword_plan.get('source', 'unknown')}`")
    lines.append(f"- Query: {keyword_plan.get('query', '')}")
    positives = keyword_plan.get("positive_keywords") or []
    if positives:
        lines.append(f"- Positive keywords: {', '.join(str(item) for item in positives)}")
    url_hints = keyword_plan.get("url_hints") or []
    if url_hints:
        lines.append(f"- URL hints: {', '.join(str(item) for item in url_hints)}")
    warnings = keyword_plan.get("warnings") or []
    if warnings:
        lines.append(f"- Warnings: {', '.join(str(item) for item in warnings)}")
    lines.append("")


def _classification_assist(lines: list[str], data: AdmissionsData) -> None:
    diagnostics = data.run.config.get("classification_assist")
    if not isinstance(diagnostics, list) or not diagnostics:
        return
    entries = [item for item in diagnostics if isinstance(item, dict)]
    if not entries:
        return

    providers = sorted({str(item.get("provider", "unknown")) for item in entries})
    summary = data.run.config.get("classification_assist_summary")
    if not isinstance(summary, dict):
        summary = {}
    fallback_count = summary.get("fallback_count")
    if not isinstance(fallback_count, int):
        fallback_count = sum(1 for item in entries if item.get("fallback") is True)
    applied_count = summary.get("applied_count")
    if not isinstance(applied_count, int):
        applied_count = sum(1 for item in entries if item.get("applied") is True)
    disagreement_count = summary.get("disagreement_count")

    lines.append("## Classification Assist Diagnostics")
    lines.append("")
    lines.append(f"- Entries: {len(entries)}")
    lines.append(f"- Providers: {', '.join(f'`{provider}`' for provider in providers)}")
    lines.append(f"- Fallback entries: {fallback_count}")
    lines.append(f"- Applied entries: {applied_count}")
    if isinstance(disagreement_count, int):
        lines.append(f"- Rule/candidate disagreements: {disagreement_count}")
    lines.append("- Note: classification assist is diagnostics-only and does not change facts.")
    lines.append("")
    for entry in entries[:20]:
        candidate = entry.get("candidate")
        candidate_category = "none"
        candidate_confidence = "unknown"
        candidate_signals = []
        if isinstance(candidate, dict):
            candidate_category = str(candidate.get("category", "unknown"))
            candidate_confidence = str(candidate.get("confidence", "unknown"))
            raw_signals = candidate.get("signals") or []
            if isinstance(raw_signals, list):
                candidate_signals = [str(signal) for signal in raw_signals]
        lines.append(
            f"- {entry.get('url', 'unknown')}: rule `{entry.get('rule_category', 'unknown')}` score {entry.get('rule_score', 'unknown')} "
            f"-> candidate `{candidate_category}` confidence `{candidate_confidence}`, applied {entry.get('applied', False)}"
        )
        if candidate_signals:
            lines.append(f"  - candidate signals: {', '.join(candidate_signals)}")
        if entry.get("fallback") is True:
            error = entry.get("error")
            error_type = entry.get("error_type", "unknown")
            lines.append(f"  - fallback: {error_type}{': ' + str(error) if error else ''}")
    if len(entries) > 20:
        lines.append(f"- Omitted entries: {len(entries) - 20}")
    lines.append("")


def _source_strategy(lines: list[str], data: AdmissionsData) -> None:
    summary = data.run.config.get("source_strategy_summary")
    if not isinstance(summary, dict) or not summary:
        return
    lines.append("## Source Strategy")
    lines.append("")
    for label, count in summary.items():
        lines.append(f"- `{label}`: {count}")
    lines.append("")


def _source_planning(lines: list[str], data: AdmissionsData) -> None:
    diagnostics = data.run.config.get("llm_source_plan")
    if not isinstance(diagnostics, dict):
        return

    summary = data.run.config.get("source_strategy_summary")
    blocked_count = 0
    if isinstance(summary, dict):
        raw_count = summary.get("blocked_or_challenge")
        if isinstance(raw_count, int):
            blocked_count = raw_count

    lines.append("## Source Planning Diagnostics")
    lines.append("")
    lines.append(f"- Enabled: {diagnostics.get('enabled', False)}")
    lines.append(f"- Triggered: {diagnostics.get('triggered', False)}")
    lines.append(f"- Provider: `{diagnostics.get('provider', 'unknown')}`")
    lines.append(f"- Fallback: {diagnostics.get('fallback', False)}")
    lines.append(f"- Applied: {diagnostics.get('applied', False)}")
    lines.append(f"- Blocked/challenge sources: {blocked_count}")
    triggers = diagnostics.get("trigger_reasons") or []
    if isinstance(triggers, list) and triggers:
        lines.append(f"- Trigger reasons: {', '.join(f'`{trigger}`' for trigger in triggers)}")
    applied_urls = diagnostics.get("applied_candidate_urls") or []
    budget_skipped_urls = diagnostics.get("budget_skipped_candidate_urls") or []
    if isinstance(applied_urls, list):
        lines.append(f"- Crawled accepted candidate URLs: {len(applied_urls)}")
    if isinstance(budget_skipped_urls, list):
        lines.append(f"- Budget-skipped accepted candidate URLs: {len(budget_skipped_urls)}")
    _source_plan_candidates(lines, "Accepted candidate URLs", diagnostics.get("accepted_candidate_urls") or [])
    _source_plan_candidates(lines, "Rejected candidate URLs", diagnostics.get("rejected_candidate_urls") or [])
    path_patterns = diagnostics.get("candidate_path_patterns") or []
    if isinstance(path_patterns, list) and path_patterns:
        lines.append("- Candidate path patterns:")
        for pattern in path_patterns[:10]:
            lines.append(f"  - {pattern}")
        if len(path_patterns) > 10:
            lines.append(f"  - Omitted path patterns: {len(path_patterns) - 10}")
    queries = diagnostics.get("candidate_queries") or []
    if isinstance(queries, list) and queries:
        lines.append("- Candidate queries:")
        for query in queries[:10]:
            lines.append(f"  - {query}")
        if len(queries) > 10:
            lines.append(f"  - Omitted queries: {len(queries) - 10}")
    warnings = diagnostics.get("warnings") or []
    if isinstance(warnings, list) and warnings:
        lines.append(f"- Warnings: {', '.join(str(warning) for warning in warnings)}")
    note = diagnostics.get("note")
    if note:
        lines.append(f"- Note: {note}")
    lines.append("- Note: source planning diagnostics are not admissions facts.")
    lines.append("")


def _source_plan_candidates(lines: list[str], title: str, candidates: object) -> None:
    items = [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []
    lines.append(f"- {title}: {len(items)}")
    for item in items[:10]:
        url = item.get("url", "unknown")
        category = item.get("expected_category", "unknown")
        reason = item.get("reason", "")
        line = f"  - {url} (`{category}`)"
        if title.startswith("Rejected"):
            line += f" rejected `{item.get('rejection_reason', 'unknown')}`"
        elif item.get("crawl_status"):
            line += f" crawl `{item.get('crawl_status')}`"
        if reason:
            line += f": {reason}"
        lines.append(line)
    if len(items) > 10:
        lines.append(f"  - Omitted candidates: {len(items) - 10}")


def _api_catalog_discovery(lines: list[str], data: AdmissionsData) -> None:
    summary = data.run.config.get("programme_catalog_api_discovery_summary")
    if not isinstance(summary, dict):
        return
    candidate_count = summary.get("api_catalog_candidate_count", 0)
    if not candidate_count:
        return
    candidates = data.run.config.get("programme_catalog_api_candidates")
    items = [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []

    lines.append("## API Catalog Discovery Diagnostics")
    lines.append("")
    lines.append(f"- API candidate endpoints: {candidate_count}")
    lines.append(f"- Captured JSON endpoints: {summary.get('captured_json_count', 0)}")
    lines.append(f"- Browser network candidates: {summary.get('browser_network_candidate_count', 0)}")
    lines.append(f"- Network bodies available: {summary.get('network_body_available_count', 0)}")
    lines.append(f"- Rejected endpoints: {summary.get('rejected_count', 0)}")
    statuses = summary.get("api_candidate_status_counts")
    if isinstance(statuses, dict) and statuses:
        lines.append(f"- Candidate statuses: {_format_counts(statuses)}")
    reasons = summary.get("api_candidate_reason_counts")
    if isinstance(reasons, dict) and reasons:
        lines.append(f"- Candidate reasons: {_format_counts(reasons)}")
    capture = data.run.config.get("programme_catalog_api_capture")
    if isinstance(capture, dict):
        attempted = capture.get("attempted_urls")
        captured = capture.get("captured_urls")
        rejected = capture.get("rejected_urls")
        network_body_urls = capture.get("network_body_urls")
        lines.append(f"- Safe capture attempted endpoints: {len(attempted) if isinstance(attempted, list) else 0}")
        lines.append(f"- Safe capture accepted rows: {capture.get('accepted_row_count', 0)}")
        lines.append(f"- Safe capture budget hit: {capture.get('budget_hit', False)}")
        if isinstance(network_body_urls, list) and network_body_urls:
            lines.append(f"- Safe capture used browser network bodies: {len(network_body_urls)}")
        if isinstance(captured, list) and captured:
            lines.append(f"- Safe captured JSON endpoints: {len(captured)}")
        if isinstance(rejected, list) and rejected:
            lines.append("- Safe capture rejected endpoints:")
            for item in rejected[:10]:
                if isinstance(item, dict):
                    lines.append(f"  - {item.get('url', 'unknown')} rejected `{item.get('reason', 'unknown')}`")
            if len(rejected) > 10:
                lines.append(f"  - Omitted rejected endpoints: {len(rejected) - 10}")
    lines.append("- Candidates:")
    for item in items[:10]:
        lines.append(
            f"  - {item.get('api_candidate_url', 'unknown')} "
            f"`{item.get('api_candidate_status', 'unknown')}` from {item.get('api_candidate_source_page', 'unknown')}"
        )
        reason = item.get("api_candidate_reason")
        if reason:
            lines.append(f"    - reason: `{reason}`")
        size = item.get("api_response_size_bytes")
        if isinstance(size, int):
            lines.append(f"    - response bytes: {size}")
        network_method = item.get("api_network_method")
        network_content_type = item.get("api_network_content_type")
        if network_method or network_content_type:
            lines.append(
                f"    - network: method `{network_method or 'unknown'}`, "
                f"content `{network_content_type or 'unknown'}`, "
                f"body captured {item.get('api_network_body_available', False)}"
            )
    if len(items) > 10:
        lines.append(f"  - Omitted candidates: {len(items) - 10}")
    note = summary.get("note")
    if note:
        lines.append(f"- Note: {note}")
    lines.append("- Note: Candidate discovery alone does not create admissions facts; only captured official JSON rows with evidence are applied.")
    lines.append("")


def _programme_catalog_browser_capture(lines: list[str], data: AdmissionsData) -> None:
    diagnostics = data.run.config.get("programme_catalog_browser_capture")
    if not isinstance(diagnostics, dict) or not diagnostics.get("triggered"):
        return
    attempted = diagnostics.get("attempted_urls")
    captured = diagnostics.get("captured_urls")
    rejected = diagnostics.get("rejected_urls")
    lines.append("## Programme Catalog Browser Capture Diagnostics")
    lines.append("")
    lines.append(f"- Triggered: {diagnostics.get('triggered', False)}")
    lines.append(f"- Attempted pages: {len(attempted) if isinstance(attempted, list) else 0}")
    lines.append(f"- Captured pages: {len(captured) if isinstance(captured, list) else 0}")
    lines.append(f"- Network responses: {diagnostics.get('network_response_count', 0)}")
    lines.append(f"- Network bodies: {diagnostics.get('network_body_count', 0)}")
    if isinstance(rejected, list) and rejected:
        lines.append("- Rejected pages:")
        for item in rejected[:10]:
            if isinstance(item, dict):
                line = f"  - {item.get('url', 'unknown')} rejected `{item.get('reason', 'unknown')}`"
                message = item.get("message")
                if message:
                    line += f": {message}"
                lines.append(line)
        if len(rejected) > 10:
            lines.append(f"  - Omitted rejected pages: {len(rejected) - 10}")
    note = diagnostics.get("note")
    if note:
        lines.append(f"- Note: {note}")
    lines.append("")


def _programme_catalog_static_asset_discovery(lines: list[str], data: AdmissionsData) -> None:
    diagnostics = data.run.config.get("programme_catalog_static_asset_discovery")
    if not isinstance(diagnostics, dict) or not diagnostics.get("triggered"):
        return
    source_pages = diagnostics.get("candidate_source_pages")
    candidate_assets = diagnostics.get("candidate_asset_urls")
    fetched_assets = diagnostics.get("fetched_asset_urls")
    rejected_assets = diagnostics.get("rejected_asset_urls")
    api_urls = diagnostics.get("candidate_api_urls")
    lines.append("## Programme Catalog Static Asset Discovery Diagnostics")
    lines.append("")
    lines.append(f"- Triggered: {diagnostics.get('triggered', False)}")
    lines.append(f"- Candidate source pages: {len(source_pages) if isinstance(source_pages, list) else 0}")
    lines.append(f"- Candidate static assets: {len(candidate_assets) if isinstance(candidate_assets, list) else 0}")
    lines.append(f"- Fetched static assets: {len(fetched_assets) if isinstance(fetched_assets, list) else 0}")
    lines.append(f"- API endpoint hints from assets: {diagnostics.get('endpoint_hint_count', 0)}")
    if isinstance(api_urls, list) and api_urls:
        lines.append("- Candidate API endpoints from assets:")
        for url in api_urls[:10]:
            lines.append(f"  - {url}")
        if len(api_urls) > 10:
            lines.append(f"  - Omitted API endpoints: {len(api_urls) - 10}")
    if isinstance(rejected_assets, list) and rejected_assets:
        lines.append("- Rejected static assets:")
        for item in rejected_assets[:10]:
            if isinstance(item, dict):
                line = f"  - {item.get('url', 'unknown')} rejected `{item.get('reason', 'unknown')}`"
                message = item.get("message")
                if message:
                    line += f": {message}"
                lines.append(line)
        if len(rejected_assets) > 10:
            lines.append(f"  - Omitted rejected static assets: {len(rejected_assets) - 10}")
    note = diagnostics.get("note")
    if note:
        lines.append(f"- Note: {note}")
    lines.append("")


def _programme_catalog_diagnostics(lines: list[str], data: AdmissionsData) -> None:
    summary = data.run.config.get("programme_catalog_summary")
    if not isinstance(summary, dict) or not summary:
        return
    candidate_count = summary.get("candidate_count", 0)
    rejected_count = summary.get("rejected_count", 0)
    candidate_source_count = summary.get("candidate_source_count", 0)
    if not candidate_count and not rejected_count and not candidate_source_count:
        return

    lines.append("## Programme Catalog Diagnostics")
    lines.append("")
    lines.append(f"- Candidate rows: {candidate_count}")
    lines.append(f"- Accepted rows: {summary.get('accepted_count', 0)}")
    lines.append(f"- Rejected rows: {rejected_count}")
    lines.append(f"- Candidate sources: {candidate_source_count}")
    lines.append(f"- Crawled catalog sources: {summary.get('crawled_catalog_source_count', 0)}")
    lines.append(f"- Accepted row count: {summary.get('accepted_row_count', summary.get('accepted_count', 0))}")
    lines.append(f"- Raw-needs-review rows: {summary.get('raw_needs_review_count', 0)}")
    ratio = summary.get("accepted_to_candidate_source_ratio")
    if ratio is not None:
        lines.append(f"- Accepted/source ratio: {ratio}")
    if (
        summary.get("api_response_count")
        or summary.get("api_catalog_candidate_count")
        or summary.get("api_endpoint_candidate_count")
        or summary.get("browser_network_candidate_count")
        or summary.get("network_body_available_count")
    ):
        lines.append(f"- API catalog candidates: {summary.get('api_catalog_candidate_count', 0)}")
        lines.append(f"- API endpoint candidates: {summary.get('api_endpoint_candidate_count', 0)}")
        lines.append(f"- Browser network candidates: {summary.get('browser_network_candidate_count', 0)}")
        lines.append(f"- Network bodies available: {summary.get('network_body_available_count', 0)}")
        lines.append(f"- API responses: {summary.get('api_response_count', 0)}")
        lines.append(f"- API pages: {summary.get('api_page_count', 0)}")
        lines.append(f"- API accepted rows: {summary.get('api_accepted_row_count', 0)}")
        lines.append(f"- API rejected rows: {summary.get('api_rejected_row_count', 0)}")
        if summary.get("api_total_count") is not None:
            lines.append(f"- API total count: {summary.get('api_total_count')}")
        lines.append(f"- API pagination complete: {summary.get('api_pagination_complete', False)}")
        lines.append(f"- API pagination incomplete: {summary.get('api_pagination_incomplete', False)}")
        if summary.get("api_filter_candidate_dimensions"):
            lines.append(f"- API filter candidate dimensions: {_format_dimensions(summary.get('api_filter_candidate_dimensions'))}")
        if summary.get("api_filter_dimensions"):
            lines.append(f"- API filter dimensions used: {_format_dimensions(summary.get('api_filter_dimensions'))}")
        if summary.get("api_filter_attempted_url_count") or summary.get("api_filter_fetched_url_count"):
            lines.append(f"- API filter attempted URLs: {summary.get('api_filter_attempted_url_count', 0)}")
            lines.append(f"- API filter fetched URLs: {summary.get('api_filter_fetched_url_count', 0)}")
            lines.append(f"- API filter rejected URLs: {summary.get('api_filter_rejected_url_count', 0)}")
            lines.append(f"- API filter budget hit: {summary.get('api_filter_enumeration_budget_hit', False)}")
        lines.append(f"- HTML fallback used: {summary.get('html_fallback_used', False)}")
        if summary.get("api_to_csv_ratio") is not None:
            lines.append(f"- API/CSV row ratio: {summary.get('api_to_csv_ratio')}")
    lines.append(f"- Low row yield: {summary.get('low_row_yield', False)}")
    lines.append(f"- Probable incomplete catalog: {summary.get('probable_incomplete_catalog', False)}")
    if summary.get("api_candidate_zero_reason"):
        lines.append(f"- API candidate zero reason: `{summary.get('api_candidate_zero_reason')}`")
    lines.append(f"- False-positive rejected rows: {summary.get('false_positive_rejected_count', 0)}")
    lines.append(f"- Recommended next action: `{summary.get('recommended_next_action', 'none')}`")
    source_statuses = summary.get("source_status_counts")
    if isinstance(source_statuses, dict) and source_statuses:
        lines.append(f"- Catalog source statuses: {_format_counts(source_statuses)}")
    catalog_families = summary.get("catalog_source_family_counts")
    if isinstance(catalog_families, dict) and catalog_families:
        lines.append(f"- Catalog source families: {_format_counts(catalog_families)}")
    accepted_families = summary.get("accepted_source_family_counts")
    if isinstance(accepted_families, dict) and accepted_families:
        lines.append(f"- Accepted source families: {_format_counts(accepted_families)}")
    if summary.get("source_family_bias"):
        lines.append(f"- Source family bias: `{summary.get('dominant_source_family', 'unknown')}`")
        reason = summary.get("source_family_bias_reason")
        if reason:
            lines.append(f"  - reason: {reason}")
    lines.append(f"- Duplicate rows: {summary.get('duplicate_count', 0)}")
    lines.append(f"- Manual-review rows: {summary.get('manual_review_count', 0)}")
    lines.append(f"- Row warnings: {summary.get('warning_count', 0)}")
    programme_types = summary.get("by_programme_type")
    if isinstance(programme_types, dict) and programme_types:
        lines.append(f"- Programme types: {_format_counts(programme_types)}")
    faculties = summary.get("by_faculty_or_school")
    if isinstance(faculties, dict) and faculties:
        lines.append(f"- Faculties/schools: {_format_counts(faculties)}")
    parse_statuses = summary.get("parse_status_counts")
    if isinstance(parse_statuses, dict) and parse_statuses:
        lines.append(f"- Parse statuses: {_format_counts(parse_statuses)}")
    lines.append(f"- Sources: {summary.get('sources_count', 0)}")
    source_urls = summary.get("source_urls") or []
    if isinstance(source_urls, list) and source_urls:
        lines.append("- Source URLs:")
        for url in source_urls[:10]:
            lines.append(f"  - {url}")
        if len(source_urls) > 10:
            lines.append(f"  - Omitted source URLs: {len(source_urls) - 10}")
    duplicate_names = summary.get("duplicate_names") or []
    if isinstance(duplicate_names, list) and duplicate_names:
        lines.append("- Duplicate names:")
        for item in duplicate_names[:10]:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('name', 'unknown')}: {item.get('count', 0)}")
        if len(duplicate_names) > 10:
            lines.append(f"  - Omitted duplicate names: {len(duplicate_names) - 10}")
    note = summary.get("note")
    if note:
        lines.append(f"- Note: {note}")
    lines.append("- Note: programme catalog diagnostics summarize table extraction and are not admissions facts.")
    lines.append("")


def _template_completeness(lines: list[str], data: AdmissionsData) -> None:
    diagnostics = data.run.config.get("template_completeness")
    if not isinstance(diagnostics, dict) or not diagnostics:
        return
    fields = diagnostics.get("fields")
    if not isinstance(fields, dict) or not fields:
        return

    lines.append("## Template Completeness Diagnostics")
    lines.append("")
    lines.append(f"- Found: {diagnostics.get('found_count', 0)}/{diagnostics.get('fields_total', 0)}")
    status_counts = diagnostics.get("status_counts")
    if isinstance(status_counts, dict) and status_counts:
        lines.append(f"- Status flags: {_format_counts(status_counts)}")
    next_action_counts = diagnostics.get("next_action_counts")
    if isinstance(next_action_counts, dict) and next_action_counts:
        lines.append(f"- Next actions: {_format_counts(next_action_counts)}")
    programme_catalog = diagnostics.get("programme_catalog")
    if isinstance(programme_catalog, dict):
        lines.append(
            "- Programme catalog: "
            f"candidate sources {programme_catalog.get('candidate_source_count', 0)}, "
            f"crawled catalog sources {programme_catalog.get('crawled_catalog_source_count', 0)}, "
            f"accepted rows {programme_catalog.get('accepted_row_count', 0)}, "
            f"API pages {programme_catalog.get('api_page_count', 0)}, "
            f"API accepted rows {programme_catalog.get('api_accepted_row_count', 0)}, "
            f"API pagination incomplete {programme_catalog.get('api_pagination_incomplete', False)}, "
            f"HTML fallback used {programme_catalog.get('html_fallback_used', False)}, "
            f"raw-needs-review rows {programme_catalog.get('raw_needs_review_count', 0)}, "
            f"low row yield {programme_catalog.get('low_row_yield', False)}, "
            f"probable incomplete {programme_catalog.get('probable_incomplete_catalog', False)}, "
            f"next action `{programme_catalog.get('next_action', 'none')}`"
        )
    lines.append("- Fields:")
    for field, details in fields.items():
        if not isinstance(details, dict):
            continue
        flags = details.get("status_flags") or []
        flags_text = ", ".join(f"`{flag}`" for flag in flags) if isinstance(flags, list) and flags else "`unknown`"
        lines.append(
            f"  - `{field}`: {details.get('status', 'unknown')} "
            f"({flags_text}); next `{details.get('next_action', 'manual_check_required')}`"
        )
        source_urls = details.get("source_urls") or []
        if isinstance(source_urls, list) and source_urls:
            lines.append(f"    - sources: {', '.join(str(url) for url in source_urls[:5])}")
    note = diagnostics.get("note")
    if note:
        lines.append(f"- Note: {note}")
    lines.append("")


def _extraction_diagnostics(lines: list[str], data: AdmissionsData) -> None:
    summary = data.run.config.get("extraction_diagnostics_summary")
    if not isinstance(summary, dict) or not summary:
        return
    lines.append("## Extraction Diagnostics")
    lines.append("")
    lines.append(f"- Sources diagnosed: {summary.get('sources_count', 0)}")
    lines.append(f"- Sources with extractions: {summary.get('sources_with_extractions', 0)}")
    lines.append(f"- Extractor attempts: {summary.get('attempts_count', 0)}")
    status_counts = summary.get("status_counts")
    if isinstance(status_counts, dict) and status_counts:
        lines.append(f"- Status counts: {_format_counts(status_counts)}")
    reason_counts = summary.get("reason_counts")
    if isinstance(reason_counts, dict) and reason_counts:
        lines.append(f"- Reason counts: {_format_counts(reason_counts)}")
    field_status_counts = summary.get("field_status_counts")
    if isinstance(field_status_counts, dict) and field_status_counts:
        lines.append("- Field outcomes:")
        for field, counts in field_status_counts.items():
            if isinstance(counts, dict):
                lines.append(f"  - `{field}`: {_format_counts(counts)}")
    lines.append("- Note: extraction diagnostics are observational and do not change facts.")
    lines.append("")


def _llm_structured_extraction(lines: list[str], data: AdmissionsData) -> None:
    diagnostics = data.run.config.get("llm_structured_extraction")
    if not isinstance(diagnostics, dict):
        return
    if not diagnostics.get("enabled") and not diagnostics.get("triggered"):
        return

    lines.append("## LLM Structured Extraction Diagnostics")
    lines.append("")
    lines.append(f"- Enabled: {diagnostics.get('enabled', False)}")
    lines.append(f"- Triggered: {diagnostics.get('triggered', False)}")
    lines.append(f"- Provider: `{diagnostics.get('provider', 'unknown')}`")
    lines.append(f"- Candidates: {diagnostics.get('candidate_count', 0)}")
    lines.append(f"- Accepted: {diagnostics.get('accepted_count', 0)}")
    lines.append(f"- Rejected: {diagnostics.get('rejected_count', 0)}")
    lines.append(f"- Applied to facts: {diagnostics.get('applied_to_facts', False)}")
    lines.append(f"- Applied count: {diagnostics.get('applied_count', 0)}")
    triggers = diagnostics.get("trigger_reasons") or []
    if isinstance(triggers, list) and triggers:
        lines.append(f"- Trigger reasons: {', '.join(f'`{trigger}`' for trigger in triggers)}")
    accepted_claim_paths = diagnostics.get("accepted_claim_paths")
    if isinstance(accepted_claim_paths, dict) and accepted_claim_paths:
        lines.append(f"- Accepted claim paths: {_format_counts(accepted_claim_paths)}")
    reject_reasons = diagnostics.get("reject_reasons")
    if isinstance(reject_reasons, dict) and reject_reasons:
        lines.append(f"- Reject reasons: {_format_counts(reject_reasons)}")
    write_status_counts = diagnostics.get("write_status_counts")
    if isinstance(write_status_counts, dict) and write_status_counts:
        lines.append(f"- Write statuses: {_format_counts(write_status_counts)}")
    source_urls = diagnostics.get("source_urls_used") or []
    if isinstance(source_urls, list) and source_urls:
        lines.append("- Source URLs used:")
        for url in source_urls[:10]:
            lines.append(f"  - {url}")
        if len(source_urls) > 10:
            lines.append(f"  - Omitted source URLs: {len(source_urls) - 10}")
    results = diagnostics.get("results") or []
    if isinstance(results, list) and results:
        lines.append("- Candidate results:")
        for result in results[:10]:
            if not isinstance(result, dict):
                continue
            candidate = result.get("candidate")
            claim_path = "unknown"
            source_url = str(result.get("source_url", "unknown"))
            if isinstance(candidate, dict):
                claim_path = str(candidate.get("claim_path", "unknown"))
                source_url = str(candidate.get("source_url", source_url))
            status = result.get("validation_status", "accepted" if result.get("accepted") else "rejected")
            write_status = result.get("write_status", "not_applicable")
            line = f"  - `{claim_path}` from {source_url}: validation `{status}`, write `{write_status}`"
            evidence_path = result.get("evidence_path")
            if evidence_path:
                line += f", evidence `{evidence_path}`"
            reject_reason = result.get("reject_reason")
            if reject_reason:
                line += f", rejected `{reject_reason}`"
            lines.append(line)
        if len(results) > 10:
            lines.append(f"  - Omitted candidate results: {len(results) - 10}")
    warnings = diagnostics.get("warnings") or []
    if isinstance(warnings, list) and warnings:
        lines.append(f"- Warnings: {', '.join(str(warning) for warning in warnings)}")
    note = diagnostics.get("note")
    if note:
        lines.append(f"- Note: {note}")
    lines.append("- Note: LLM structured extraction can only apply candidates that passed deterministic evidence validation.")
    lines.append("")


def _missing_reasons(lines: list[str], data: AdmissionsData) -> None:
    missing_reasons = data.run.config.get("missing_reasons")
    if not isinstance(missing_reasons, dict) or not missing_reasons:
        return
    lines.append("## Missing Reasons")
    lines.append("")
    for field, details in missing_reasons.items():
        if not isinstance(details, dict):
            continue
        compatibility_reason = details.get("reason", "manual_check_required")
        canonical_reason = details.get("canonical_reason", compatibility_reason)
        attempts = details.get("attempts", 0)
        lines.append(f"- `{field}`: `{canonical_reason}` after {attempts} attempt(s)")
        action_target = details.get("action_target")
        if action_target:
            lines.append(f"  - action target: `{action_target}`")
        if compatibility_reason != canonical_reason:
            lines.append(f"  - compatibility reason: `{compatibility_reason}`")
        extractors = details.get("attempted_extractors") or []
        if isinstance(extractors, list) and extractors:
            lines.append(f"  - attempted extractors: {', '.join(f'`{extractor}`' for extractor in extractors)}")
        capability = details.get("capability")
        if isinstance(capability, dict):
            capability_parts = _capability_report_parts(capability)
            if capability_parts:
                lines.append(f"  - capability: {'; '.join(capability_parts)}")
        source_urls = details.get("source_urls") or []
        if isinstance(source_urls, list) and source_urls:
            lines.append(f"  - sources: {', '.join(str(url) for url in source_urls[:5])}")
        note = details.get("note")
        if note:
            lines.append(f"  - note: {note}")
    lines.append("- Note: missing reasons describe the current crawl and extractors; they do not prove the official site lacks the field.")
    lines.append("")


def _capability_report_parts(capability: dict[str, object]) -> list[str]:
    parts: list[str] = []
    categories = _code_values(capability.get("discovery_categories"))
    if categories:
        parts.append(f"categories {categories}")
    gates = _code_values(capability.get("context_gates"))
    if gates:
        parts.append(f"context gates {gates}")
    extractors = _code_values(capability.get("deterministic_extractors"))
    if extractors:
        parts.append(f"extractors {extractors}")
    llm_claims = _code_values(capability.get("llm_claim_paths"))
    if llm_claims:
        parts.append(f"LLM claims {llm_claims}")
    return parts


def _code_values(values: object) -> str:
    if not isinstance(values, list):
        return ""
    clean_values = [str(value) for value in values if value]
    return ", ".join(f"`{value}`" for value in clean_values)


def _field(lines: list[str], label: str, value: FieldValue, data: AdmissionsData | None = None) -> None:
    lines.append(f"- {label}: {value.value} (`{value.status}`, confidence `{value.confidence}`, parse `{value.parse_status}`)")
    _parsed(lines, value, indent="  ")
    if data is not None:
        for item in _evidence_for(data, value.evidence):
            page = f", page {item.page_number}" if item.page_number else ""
            lines.append(f"  - evidence: {item.source_url}{page} — {item.snippet}")


def _requirements(lines: list[str], title: str, records: list[RequirementRecord], data: AdmissionsData | None = None) -> None:
    lines.append(f"### {title}")
    if not records:
        lines.append("- unknown")
    for record in records:
        lines.append(f"- {record.label}: {record.value.value} (`{record.value.status}`, confidence `{record.value.confidence}`, parse `{record.value.parse_status}`)")
        _parsed(lines, record.value, indent="  ")
        if data is not None:
            for item in _evidence_for(data, record.value.evidence):
                page = f", page {item.page_number}" if item.page_number else ""
                lines.append(f"  - evidence: {item.source_url}{page} — {item.snippet}")
    lines.append("")


def _evidence_for(data: AdmissionsData, evidence_paths: list[str]):
    wanted = set(evidence_paths)
    return [item for item in data.evidence if item.claim_path in wanted]


def _parsed(lines: list[str], value: FieldValue, *, indent: str) -> None:
    if value.parsed not in (None, [], {}):
        rendered = json.dumps(value.parsed, ensure_ascii=False, sort_keys=True)
        lines.append(f"{indent}- parsed: `{rendered}`")
    elif value.raw_text and value.parse_status != "parsed":
        lines.append(f"{indent}- raw candidate only: {value.raw_text}")


def _format_counts(counts: dict[object, object]) -> str:
    return ", ".join(f"`{key}`: {value}" for key, value in counts.items())


def _format_dimensions(dimensions: object) -> str:
    if not isinstance(dimensions, dict):
        return "`none`"
    parts: list[str] = []
    for key, values in dimensions.items():
        if isinstance(values, list):
            rendered_values = ", ".join(str(value) for value in values)
        else:
            rendered_values = str(values)
        parts.append(f"`{key}`={rendered_values}")
    return "; ".join(parts) if parts else "`none`"
