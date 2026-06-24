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
    _llm_keyword_plan(lines, data)
    _classification_assist(lines, data)
    _source_strategy(lines, data)
    _source_planning(lines, data)
    _extraction_diagnostics(lines, data)
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


def _llm_keyword_plan(lines: list[str], data: AdmissionsData) -> None:
    diagnostics = data.run.config.get("llm_keyword_plan")
    if not isinstance(diagnostics, dict):
        return
    lines.append("## LLM Keyword Plan Diagnostics")
    lines.append("")
    lines.append(f"- Provider: `{diagnostics.get('provider', 'unknown')}`")
    lines.append(f"- Fallback: {diagnostics.get('fallback', False)}")
    lines.append(f"- Elapsed ms: {diagnostics.get('elapsed_ms', 0)}")
    warnings = diagnostics.get("warnings") or []
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
    _source_plan_candidates(lines, "Accepted candidate URLs", diagnostics.get("accepted_candidate_urls") or [])
    _source_plan_candidates(lines, "Rejected candidate URLs", diagnostics.get("rejected_candidate_urls") or [])
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
        if reason:
            line += f": {reason}"
        lines.append(line)
    if len(items) > 10:
        lines.append(f"  - Omitted candidates: {len(items) - 10}")


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


def _missing_reasons(lines: list[str], data: AdmissionsData) -> None:
    missing_reasons = data.run.config.get("missing_reasons")
    if not isinstance(missing_reasons, dict) or not missing_reasons:
        return
    lines.append("## Missing Reasons")
    lines.append("")
    for field, details in missing_reasons.items():
        if not isinstance(details, dict):
            continue
        reason = details.get("reason", "manual_check_required")
        attempts = details.get("attempts", 0)
        lines.append(f"- `{field}`: `{reason}` after {attempts} attempt(s)")
        extractors = details.get("attempted_extractors") or []
        if isinstance(extractors, list) and extractors:
            lines.append(f"  - attempted extractors: {', '.join(f'`{extractor}`' for extractor in extractors)}")
        source_urls = details.get("source_urls") or []
        if isinstance(source_urls, list) and source_urls:
            lines.append(f"  - sources: {', '.join(str(url) for url in source_urls[:5])}")
        note = details.get("note")
        if note:
            lines.append(f"  - note: {note}")
    lines.append("- Note: missing reasons describe the current crawl and extractors; they do not prove the official site lacks the field.")
    lines.append("")


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
