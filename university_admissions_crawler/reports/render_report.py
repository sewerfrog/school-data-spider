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
    _source_strategy(lines, data)

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


def _source_strategy(lines: list[str], data: AdmissionsData) -> None:
    summary = data.run.config.get("source_strategy_summary")
    if not isinstance(summary, dict) or not summary:
        return
    lines.append("## Source Strategy")
    lines.append("")
    for label, count in summary.items():
        lines.append(f"- `{label}`: {count}")
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
