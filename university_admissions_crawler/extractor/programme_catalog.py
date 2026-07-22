"""Conservative programme catalog extraction.

This parser owns high-cardinality programme table rows separately from the
legacy admissions-summary ``extract_programmes`` regex path.
"""

from __future__ import annotations

from collections.abc import Sequence
import re
from dataclasses import dataclass, replace
from urllib.parse import unquote, urljoin, urlparse

from university_admissions_crawler.crawler.filters import canonicalize_url
from university_admissions_crawler.crawler.html_text import HTMLContentBlock
from university_admissions_crawler.crawler.programme_sources import classify_programme_source_role
from university_admissions_crawler.crawler.public_suffix import registrable_domain
from university_admissions_crawler.evidence.provenance import evidence_from_source
from university_admissions_crawler.extractor.institution_profiles import (
    InstitutionProfile,
    extract_profile_programme_name,
    faculty_label_conflicts,
    institution_profile_for_source,
    programme_name_conflicts,
    profile_faculty_from_source_title,
    profile_faculty_from_structured_label,
    profile_programme_category,
)
from university_admissions_crawler.extractor.llm_provider import ProgrammeCatalogAssistProvider, generate_programme_catalog_classification_hint
from university_admissions_crawler.extractor.schema import Confidence, EvidenceItem, ProgrammeCatalogRecord, SourceRecord, WarningCode, WarningRecord
from university_admissions_crawler.extractor.structured import PARSED, RAW_NEEDS_REVIEW


_INHERITABLE_TABLE_CONTEXT_ROLES = frozenset({"award", "category", "faculty"})
_INHERITED_ROLE_TO_RECORD_FIELD = {
    "award": "degree_or_award",
    "category": "category",
    "faculty": "faculty_or_school",
}


@dataclass(frozen=True)
class _TableContextValue:
    value: str
    source_text: str


@dataclass(frozen=True)
class _CatalogCandidate:
    text: str
    table_headers: tuple[str, ...] = ()
    table_cells: tuple[str, ...] = ()
    inherited_context_fields: tuple[str, ...] = ()
    inherited_context_evidence: tuple[tuple[str, _TableContextValue], ...] = ()
    context_provider_fields: tuple[str, ...] = ()
    section_context_fields: tuple[str, ...] = ()
    section_context_evidence: tuple[tuple[str, _TableContextValue], ...] = ()
    section_context_provider_fields: tuple[str, ...] = ()
    block_kind: str | None = None
    section_path: tuple[str, ...] = ()
    parser_branch: str = "legacy_text_fallback"
    block_flags: tuple[str, ...] = ()
    heading_level: int | None = None
    link_texts: tuple[str, ...] = ()
    link_hrefs: tuple[str, ...] = ()
    table_scope_rejection_reason: str | None = None

    @property
    def shape(self) -> str:
        if self.parser_branch == "non_catalog_table_header":
            return "non_catalog_table_header"
        if self.parser_branch == "non_catalog_table_row":
            return "non_catalog_table_row"
        if self.parser_branch == "table_header":
            return "table_header"
        if self.inherited_context_fields:
            return "grouped_table_row"
        if self.context_provider_fields:
            return "group_context_row"
        if self.section_context_provider_fields:
            return "section_context_row"
        if self.table_headers and _is_partial_table_header(list(self.table_headers)):
            return "partial_header_table"
        if self.table_headers:
            return "header_mapped_table"
        if self.section_context_fields:
            return "section_context_candidate"
        if self.block_kind == "table_row" or self.table_cells:
            return "table_row"
        if self.block_kind:
            return f"{self.block_kind}_candidate"
        if "|" in self.text:
            return "table_row"
        return "text"


@dataclass(frozen=True)
class _EntityGateResult:
    structural_anchor: str | None
    rejection_reason: str | None
    name_quality_passed: bool
    institution_consistent: bool


def extract_programme_catalog(
    text: str,
    source: SourceRecord,
    *,
    start_index: int = 0,
    base_path: str = "/programme_catalog",
    assist_provider: ProgrammeCatalogAssistProvider | None = None,
    candidate_diagnostics: list[dict[str, object]] | None = None,
    content_blocks: Sequence[HTMLContentBlock] | None = None,
) -> list[tuple[ProgrammeCatalogRecord, list[EvidenceItem]]]:
    """Extract evidence-backed programme catalog rows from structured text.

    The parser requires catalogue source context, a structural anchor, name
    quality, and institution consistency before emitting an evidence-backed
    row. Ambiguous candidates remain in diagnostics rather than accepted facts.
    """

    if not _looks_like_programme_catalog_source(text, source):
        return []

    rows: list[tuple[ProgrammeCatalogRecord, list[EvidenceItem]]] = []
    seen: dict[tuple[str, str, str, str], int] = {}
    institution_profile = institution_profile_for_source(source.source_url, is_official=source.is_official)
    faculty_hint = _faculty_hint(source, institution_profile)
    source_role = classify_programme_source_role(
        source.source_url,
        source.title,
        text,
        content_blocks or (),
    ).role
    candidates = (
        _block_candidates(content_blocks, institution_profile=institution_profile)
        if content_blocks
        else _candidate_lines(text, institution_profile=institution_profile)
    )
    if source_role == "programme_detail":
        candidates = _with_detail_source_title_candidate(candidates, source)
    for candidate in candidates:
        if candidate.parser_branch == "table_header":
            _record_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=candidate.text,
                decision="context",
                reason="table_header_captured",
                parser_stage="table_header",
                candidate_shape=candidate.shape,
                block_kind=candidate.block_kind,
                section_path=candidate.section_path,
                parser_branch=candidate.parser_branch,
                source_role=source_role,
            )
            continue
        pre_gate_reason = _candidate_pre_gate_rejection(candidate, source_role=source_role)
        if pre_gate_reason:
            _record_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=candidate.text,
                decision="rejected",
                reason=pre_gate_reason,
                parser_stage="entity_gate",
                candidate_shape=candidate.shape,
                block_kind=candidate.block_kind,
                section_path=candidate.section_path,
                parser_branch=candidate.parser_branch,
                block_flags=candidate.block_flags,
                source_role=source_role,
                name_quality_passed=False,
            )
            continue
        candidate_faculty_hint = faculty_hint
        if candidate.section_context_evidence:
            candidate_faculty_hint = candidate.section_context_evidence[0][1].value
        parsed = _parse_candidate(
            candidate.text,
            faculty_hint=candidate_faculty_hint,
            institution_profile=institution_profile,
            allow_unknown_category=assist_provider is not None,
            table_headers=candidate.table_headers,
            table_cells=candidate.table_cells,
            inherited_context_fields=candidate.inherited_context_fields,
            allow_pipe_table_fallback=candidate.parser_branch == "legacy_text_fallback",
            parser_branch=candidate.parser_branch,
        )
        if parsed is None:
            is_table_context_row = bool(candidate.context_provider_fields)
            is_section_context_row = bool(candidate.section_context_provider_fields)
            _record_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=candidate.text,
                decision="context" if is_table_context_row or is_section_context_row else "rejected",
                reason=(
                    "group_context_captured"
                    if is_table_context_row
                    else "section_context_captured"
                    if is_section_context_row
                    else _candidate_rejection_reason(
                        candidate.text,
                        parser_branch=candidate.parser_branch,
                        block_flags=candidate.block_flags,
                    )
                ),
                parser_stage=(
                    "table_context"
                    if is_table_context_row
                    else "section_context"
                    if is_section_context_row
                    else "parse_candidate"
                ),
                candidate_shape=candidate.shape,
                context_fields=candidate.context_provider_fields or candidate.section_context_provider_fields,
                section_context_fields=candidate.section_context_fields,
                block_kind=candidate.block_kind,
                section_path=candidate.section_path,
                parser_branch=candidate.parser_branch,
                block_flags=candidate.block_flags,
                source_role=source_role,
            )
            continue
        claim_path = f"{base_path}/{start_index + len(rows)}/name"
        snippet = _snippet(candidate.text)
        if assist_provider is not None:
            _apply_programme_catalog_hint(parsed=parsed, candidate=candidate.text, source=source, provider=assist_provider)
        if parsed.get("_requires_category_hint") and parsed.get("category") == "unknown":
            _record_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=candidate.text,
                decision="rejected",
                reason="category_hint_required",
                parser_stage="llm_hint_gate",
                name=_string_or_none(parsed.get("name")),
                category=_string_or_none(parsed.get("category")),
                candidate_shape=_string_or_none(parsed.get("_candidate_shape")) or candidate.shape,
                inherited_context_fields=candidate.inherited_context_fields,
                section_context_fields=candidate.section_context_fields,
                block_kind=candidate.block_kind,
                section_path=candidate.section_path,
                parser_branch=candidate.parser_branch,
                block_flags=candidate.block_flags,
                source_role=source_role,
            )
            continue
        gate = _programme_entity_gate(
            parsed=parsed,
            candidate=candidate,
            source=source,
            source_role=source_role,
            institution_profile=institution_profile,
        )
        if gate.rejection_reason:
            _record_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=candidate.text,
                decision="rejected",
                reason=gate.rejection_reason,
                parser_stage="entity_gate",
                name=_string_or_none(parsed.get("name")),
                category=_string_or_none(parsed.get("category")),
                candidate_shape=_string_or_none(parsed.get("_candidate_shape")) or candidate.shape,
                inherited_context_fields=candidate.inherited_context_fields,
                section_context_fields=candidate.section_context_fields,
                block_kind=candidate.block_kind,
                section_path=candidate.section_path,
                parser_branch=candidate.parser_branch,
                block_flags=candidate.block_flags,
                source_role=source_role,
                structural_anchor=gate.structural_anchor,
                name_quality_passed=gate.name_quality_passed,
                institution_consistent=gate.institution_consistent,
            )
            continue
        parsed["_structural_anchor"] = gate.structural_anchor
        parsed["_source_role"] = source_role
        parsed["_name_quality_passed"] = gate.name_quality_passed
        parsed["_institution_consistent"] = gate.institution_consistent
        faculty_or_school = _string_or_none(parsed.get("faculty_or_school") or faculty_hint)
        if candidate.section_context_fields:
            parsed["_section_context_fields"] = list(candidate.section_context_fields)
        degree_or_award = _string_or_none(parsed.get("degree_or_award"))
        if not _is_confident_row(parsed):
            _record_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=candidate.text,
                decision="rejected",
                reason="entity_gate_incomplete",
                parser_stage="entity_gate",
                name=_string_or_none(parsed.get("name")),
                category=_string_or_none(parsed.get("category")),
                candidate_shape=_string_or_none(parsed.get("_candidate_shape")) or candidate.shape,
                inherited_context_fields=candidate.inherited_context_fields,
                section_context_fields=candidate.section_context_fields,
                block_kind=candidate.block_kind,
                section_path=candidate.section_path,
                parser_branch=candidate.parser_branch,
                block_flags=candidate.block_flags,
                source_role=source_role,
                structural_anchor=gate.structural_anchor,
                name_quality_passed=gate.name_quality_passed,
                institution_consistent=gate.institution_consistent,
            )
            continue
        parse_status = PARSED
        key = _normalised_programme_key(parsed["name"], degree_or_award, faculty_or_school, source.source_url)
        duplicate_index = seen.get(key, 0)
        seen[key] = duplicate_index + 1
        warnings = _quality_warnings(
            parsed=parsed,
            claim_path=claim_path,
            source_url=source.source_url,
            parse_status=parse_status,
            faculty_or_school=faculty_or_school,
            degree_or_award=degree_or_award,
            duplicate_index=duplicate_index,
        )
        confidence = Confidence.HIGH if parse_status == PARSED else Confidence.MEDIUM
        row = ProgrammeCatalogRecord(
            name=parsed["name"],
            faculty_or_school=faculty_or_school,
            degree_or_award=degree_or_award,
            category=parsed["category"],
            mode=parsed.get("mode"),
            duration_or_units=parsed.get("duration_or_units"),
            admissions_choice_name=parsed.get("admissions_choice_name"),
            specialisations_or_majors=parsed.get("specialisations_or_majors", []),
            source_url=source.source_url,
            evidence_snippet=snippet,
            evidence_confidence=confidence,
            evidence_path=claim_path,
            parse_status=parse_status,
            warnings=warnings,
        )
        evidence = [evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=confidence)]
        field_evidence_paths: dict[str, str] = {}
        field_context_evidence = dict(candidate.section_context_evidence)
        field_context_evidence.update(candidate.inherited_context_evidence)
        for role, context_value in sorted(field_context_evidence.items()):
            record_field = _INHERITED_ROLE_TO_RECORD_FIELD[role]
            field_claim_path = f"{base_path}/{start_index + len(rows)}/{record_field}"
            field_evidence_paths[record_field] = field_claim_path
            evidence.append(
                evidence_from_source(
                    claim_path=field_claim_path,
                    source=source,
                    snippet=_snippet(context_value.source_text),
                    confidence=Confidence.MEDIUM,
                )
            )
        if (
            faculty_hint
            and faculty_or_school == faculty_hint
            and "faculty_or_school" not in field_evidence_paths
            and source.title
        ):
            faculty_claim_path = f"{base_path}/{start_index + len(rows)}/faculty_or_school"
            field_evidence_paths["faculty_or_school"] = faculty_claim_path
            evidence.append(
                evidence_from_source(
                    claim_path=faculty_claim_path,
                    source=source,
                    snippet=_snippet(source.title),
                    confidence=Confidence.MEDIUM,
                )
            )
        rows.append((row, evidence))
        primary_source_urls = _candidate_primary_source_urls(candidate, source=source, name=row.name)
        _record_candidate_diagnostic(
            candidate_diagnostics,
            source=source,
            candidate=candidate.text,
            decision="accepted",
            reason="accepted_parsed" if parse_status == PARSED else "accepted_manual_review",
            parser_stage="emit_row",
            claim_path=claim_path,
            name=row.name,
            category=row.category,
            parse_status=parse_status,
            candidate_shape=_string_or_none(parsed.get("_candidate_shape")) or candidate.shape,
            inherited_context_fields=candidate.inherited_context_fields,
            section_context_fields=candidate.section_context_fields,
            ignored_metadata_headers=_string_tuple(parsed.get("_ignored_metadata_headers")),
            field_evidence_paths=field_evidence_paths,
            primary_source_urls=primary_source_urls,
            block_kind=candidate.block_kind,
            section_path=candidate.section_path,
            parser_branch=candidate.parser_branch,
            block_flags=candidate.block_flags,
            source_role=source_role,
            structural_anchor=gate.structural_anchor,
            name_quality_passed=gate.name_quality_passed,
            institution_consistent=gate.institution_consistent,
        )
    return rows


def _looks_like_programme_catalog_source(text: str, source: SourceRecord) -> bool:
    haystack = f"{source.source_url} {source.title or ''} {text}".lower()
    url_title = f"{source.source_url} {source.title or ''}".lower()
    if _looks_like_admissions_longform_source(url_title):
        return False
    if not any(token in haystack for token in ("undergraduate", "bachelor", "bsc", "bba", "beng", "programme", "program", "degree", "major")):
        return False
    if any(token in haystack for token in ("graduate programmes", "postgraduate", "master of", "phd", "executive education")):
        return "undergraduate" in haystack
    return any(token in haystack for token in ("programme", "program", "degree", "major", "undergraduate education", "undergraduate programmes"))


def _looks_like_admissions_longform_source(url_title: str) -> bool:
    if any(token in url_title for token in ("programme", "program", "course", "catalog", "jupas", "study/ug")):
        return False
    return any(
        token in url_title
        for token in (
            "admission-guide",
            "international qualifications",
            "tuition",
            "fees",
            "scholarship",
            "financial",
            "contact-us",
        )
    )


def _candidate_pre_gate_rejection(candidate: _CatalogCandidate, *, source_role: str) -> str | None:
    if candidate.table_scope_rejection_reason:
        return candidate.table_scope_rejection_reason
    if "css_like" in candidate.block_flags:
        return "css_or_template_text"
    container_reason = _non_catalog_container_reason(candidate.section_path)
    if container_reason:
        return container_reason
    if source_role == "curriculum_or_old_cohort":
        return "course_or_curriculum_row"
    if _looks_like_course_table_candidate(candidate.text):
        return "course_or_curriculum_row"
    if candidate.context_provider_fields or candidate.section_context_provider_fields:
        return None
    if candidate.parser_branch == "paragraph_sentence":
        if _contains_degree_keyword(candidate.text):
            if _looks_like_sentence_like_candidate(candidate.text):
                return "sentence_like_name"
            return "unanchored_degree_mention"
        if _looks_like_sentence_like_candidate(candidate.text):
            return "sentence_like_name"
    return None


def _non_catalog_container_reason(section_path: tuple[str, ...]) -> str | None:
    for section in section_path:
        lower = _clean(section).lower()
        if re.match(r"^(?:related|similar|recommended)\s+(?:degree\s+)?programmes?\b", lower):
            return "related_programme_container"
        if re.match(
            r"^(?:course|courses|curriculum|module|modules|pre-?requisites?|bde|icc|academic units?|programme structure|program structure)\b",
            lower,
        ):
            return "course_or_curriculum_row"
        if re.match(
            r"^(?:academic integrity|brochure|contact|faq|frequently asked questions|how to apply|requirements?|student stories|career)\b",
            lower,
        ):
            return "non_catalog_container"
    return None


def _programme_entity_gate(
    *,
    parsed: dict[str, object],
    candidate: _CatalogCandidate,
    source: SourceRecord,
    source_role: str,
    institution_profile: InstitutionProfile | None,
) -> _EntityGateResult:
    name = _string_or_none(parsed.get("name")) or ""
    structural_anchor = _candidate_structural_anchor(
        candidate,
        name=name,
        source=source,
        source_role=source_role,
        institution_profile=institution_profile,
    )
    name_rejection = _programme_name_quality_rejection(name, candidate=candidate, structural_anchor=structural_anchor)
    institution_consistent = _candidate_institution_consistent(
        candidate,
        source=source,
        name=name,
        institution_profile=institution_profile,
        faculty_label=_string_or_none(parsed.get("faculty_or_school")),
    )
    if name_rejection:
        return _EntityGateResult(structural_anchor, name_rejection, False, institution_consistent)
    if source_role in {"curriculum_or_old_cohort", "unrelated"}:
        return _EntityGateResult(structural_anchor, "non_catalog_source_role", True, institution_consistent)
    if source_role == "programme_detail" and not _detail_name_matches_source(name, source):
        return _EntityGateResult(structural_anchor, "detail_name_mismatch", True, institution_consistent)
    if structural_anchor is None:
        return _EntityGateResult(None, "unanchored_degree_mention", True, institution_consistent)
    if not institution_consistent:
        return _EntityGateResult(structural_anchor, "institution_context_mismatch", True, False)
    return _EntityGateResult(structural_anchor, None, True, True)


def _candidate_structural_anchor(
    candidate: _CatalogCandidate,
    *,
    name: str,
    source: SourceRecord,
    source_role: str,
    institution_profile: InstitutionProfile | None,
) -> str | None:
    if candidate.parser_branch == "detail_source_title":
        if source_role == "programme_detail" and _detail_name_matches_source(name, source):
            return "detail_source_identity"
        return None
    if candidate.parser_branch == "table_row" and candidate.table_headers:
        if "name" in {_table_header_role(header) for header in candidate.table_headers}:
            return "programme_table_cell"
    if candidate.parser_branch == "table_row" and candidate.table_cells:
        return "programme_table_row"
    if candidate.parser_branch == "heading_candidate":
        if candidate.heading_level == 1 and source_role == "programme_detail" and _detail_name_matches_source(name, source):
            return "detail_h1"
        if candidate.heading_level and candidate.heading_level >= 2 and _candidate_title_matches_name(
            candidate.text,
            name,
            institution_profile=institution_profile,
        ):
            return "faculty_degree_heading"
        return None
    if candidate.parser_branch in {"list_candidate", "card_candidate"}:
        if any(_normalise_programme_identity(link_text) == _normalise_programme_identity(name) for link_text in candidate.link_texts):
            return "programme_primary_link"
        if _candidate_title_matches_name(candidate.text, name, institution_profile=institution_profile):
            return "programme_card_title" if candidate.parser_branch == "card_candidate" else "programme_list_title"
        return None
    if candidate.parser_branch == "legacy_text_fallback":
        if candidate.table_cells or "|" in candidate.text:
            return "legacy_table_row"
        if source_role == "programme_detail" and _detail_name_matches_source(name, source):
            return "detail_source_identity"
        if _candidate_title_matches_name(candidate.text, name, institution_profile=institution_profile):
            return "catalog_text_line"
    return None


def _candidate_title_matches_name(
    candidate_text: str,
    name: str,
    *,
    institution_profile: InstitutionProfile | None,
) -> bool:
    extracted = _extract_name(candidate_text, institution_profile=institution_profile)
    return bool(extracted and _normalise_programme_identity(extracted) == _normalise_programme_identity(name))


def _programme_name_quality_rejection(
    name: str,
    *,
    candidate: _CatalogCandidate,
    structural_anchor: str | None,
) -> str | None:
    cleaned = _clean(name)
    if not cleaned:
        return "missing_programme_name"
    lower = cleaned.lower()
    if any(token in lower for token in ("@media", "stylesheet", "display:", "font-family", "{", "}")):
        return "css_or_template_text"
    if re.match(r"^[A-Z]{2,5}\d{3,5}\b", cleaned) or re.search(r"\b(?:total\s+(?:no\.\s+of\s+)?aus?|pre-?requisite|course code)\b", lower):
        return "course_or_curriculum_row"
    if len(cleaned) > 240:
        return "programme_name_too_long"
    if len(cleaned) > 160 and structural_anchor not in {
        "programme_table_cell",
        "detail_h1",
        "detail_source_identity",
        "faculty_degree_heading",
    }:
        return "programme_name_too_long"
    if len(cleaned.split()) > 28 and not _strong_catalog_title_allows_length(
        cleaned,
        candidate=candidate,
        structural_anchor=structural_anchor,
    ):
        return "sentence_like_name"
    if _looks_like_sentence_like_candidate(cleaned) and not _strong_catalog_title_allows_length(
        cleaned,
        candidate=candidate,
        structural_anchor=structural_anchor,
    ):
        return "sentence_like_name"
    if candidate.parser_branch == "paragraph_sentence":
        return "unanchored_degree_mention"
    return None


def _candidate_institution_consistent(
    candidate: _CatalogCandidate,
    *,
    source: SourceRecord,
    name: str,
    institution_profile: InstitutionProfile | None,
    faculty_label: str | None,
) -> bool:
    if programme_name_conflicts(institution_profile, name) or faculty_label_conflicts(institution_profile, faculty_label):
        return False
    matching_hrefs = [
        href
        for text, href in zip(candidate.link_texts, candidate.link_hrefs)
        if _normalise_programme_identity(text) == _normalise_programme_identity(name)
    ]
    if not matching_hrefs:
        return True
    source_host = (urlparse(source.source_url).hostname or "").lower()
    source_domain = registrable_domain(source_host)
    for href in matching_hrefs:
        target_host = (urlparse(urljoin(source.source_url, href)).hostname or "").lower()
        target_domain = registrable_domain(target_host)
        if source_domain and target_domain:
            if source_domain != target_domain:
                return False
        elif source_host != target_host:
            return False
    return True


def _candidate_primary_source_urls(
    candidate: _CatalogCandidate,
    *,
    source: SourceRecord,
    name: str,
) -> tuple[str, ...]:
    target_identity = _normalise_programme_identity(name)
    urls = (
        canonicalize_url(href, source.source_url)
        for text, href in zip(candidate.link_texts, candidate.link_hrefs)
        if href and _normalise_programme_identity(text) == target_identity
    )
    return tuple(dict.fromkeys(urls))


def _detail_name_matches_source(name: str, source: SourceRecord) -> bool:
    target = _normalise_programme_identity(name)
    if not target:
        return False
    title = _normalise_programme_identity((source.title or "").split("|", 1)[0])
    if title and title == target:
        return True
    slug = unquote(urlparse(source.source_url).path.rstrip("/").rsplit("/", 1)[-1])
    return bool(slug and _normalise_programme_identity(slug) == target)


def _with_detail_source_title_candidate(
    candidates: list[_CatalogCandidate],
    source: SourceRecord,
) -> list[_CatalogCandidate]:
    primary_title = _clean((source.title or "").split("|", 1)[0])
    if not primary_title or not _contains_degree_keyword(primary_title):
        return candidates
    title_identity = _normalise_programme_identity(primary_title)
    if any(
        candidate.parser_branch == "heading_candidate"
        and candidate.heading_level == 1
        and (
            _normalise_programme_identity(candidate.text) == title_identity
            or _normalise_programme_identity(candidate.text).startswith(f"{title_identity} ")
        )
        for candidate in candidates
    ):
        return candidates
    return [
        _CatalogCandidate(
            text=primary_title,
            block_kind="source_title",
            parser_branch="detail_source_title",
        ),
        *candidates,
    ]


def _normalise_programme_identity(value: str) -> str:
    value = unquote(value).lower()
    value = re.sub(r"\b(?:hons?|honours?)\b", "", value)
    value = re.sub(r"\b(?:ntu singapore|programme|program)\b$", "", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _contains_degree_keyword(value: str) -> bool:
    return bool(re.search(r"\b(?:bachelor|bsc|bba|beng|llb|mbbs|degree|major|minor|programme|program)\b", value, flags=re.IGNORECASE))


def _looks_like_sentence_like_candidate(value: str) -> bool:
    cleaned = _clean(value)
    lower = cleaned.lower()
    sentence_markers = (
        " applicants ",
        " careers ",
        " graduates ",
        " please ",
        " students ",
        " the programme ",
        " this programme ",
        " your ",
        " requires ",
        " develops ",
        " provides ",
    )
    padded = f" {lower} "
    return len(cleaned.split()) >= 14 or any(marker in padded for marker in sentence_markers) or cleaned.endswith((".", "!", "?"))


def _strong_catalog_title_allows_length(
    name: str,
    *,
    candidate: _CatalogCandidate,
    structural_anchor: str | None,
) -> bool:
    if structural_anchor not in {
        "programme_primary_link",
        "programme_card_title",
        "programme_list_title",
        "detail_source_identity",
    }:
        return False
    if _normalise_programme_identity(candidate.text) != _normalise_programme_identity(name):
        return False
    lower = f" {name.lower()} "
    prose_markers = (
        " applicants ",
        " careers ",
        " graduates ",
        " please ",
        " students ",
        " the programme ",
        " this programme ",
        " your ",
        " requires ",
        " develops ",
        " provides ",
    )
    return not any(marker in lower for marker in prose_markers) and not name.endswith((".", "!", "?"))


def _block_candidates(
    blocks: Sequence[HTMLContentBlock],
    *,
    institution_profile: InstitutionProfile | None,
) -> list[_CatalogCandidate]:
    out: list[_CatalogCandidate] = []
    active_table_headers: tuple[str, ...] = ()
    active_table_context: dict[str, _TableContextValue] = {}
    active_table_scope_rejection_reason: str | None = None
    consumed_metadata_blocks: set[int] = set()
    section_context_suspended = False

    for index, block in enumerate(blocks):
        cleaned = _clean(block.text)
        if not cleaned:
            continue
        if block.kind == "table_row":
            section_context_suspended = True
            cells = [_clean(cell) for cell in block.cells]
            table_scope_rejection_reason = _non_catalog_table_scope_reason(cells)
            if table_scope_rejection_reason:
                active_table_headers = ()
                active_table_context = {}
                active_table_scope_rejection_reason = table_scope_rejection_reason
                out.append(
                    _CatalogCandidate(
                        text=" | ".join(cells),
                        table_cells=tuple(cells),
                        block_kind=block.kind,
                        section_path=block.section_path,
                        parser_branch="non_catalog_table_header",
                        block_flags=block.flags,
                        link_texts=tuple(link.text for link in block.links),
                        link_hrefs=tuple(link.href for link in block.links),
                        table_scope_rejection_reason=table_scope_rejection_reason,
                    )
                )
                continue
            if len(cells) >= 2 and (_is_table_header(cells) or _is_partial_table_header(cells)):
                active_table_headers = tuple(cells)
                active_table_context = {}
                active_table_scope_rejection_reason = None
                out.append(
                    _CatalogCandidate(
                        text=" | ".join(cells),
                        table_cells=tuple(cells),
                        block_kind=block.kind,
                        section_path=block.section_path,
                        parser_branch="table_header",
                        block_flags=block.flags,
                        link_texts=tuple(link.text for link in block.links),
                        link_hrefs=tuple(link.href for link in block.links),
                    )
                )
                continue
            if cells:
                candidate = _table_candidate(cells, active_table_headers, active_table_context)
                out.append(
                    replace(
                        candidate,
                        block_kind=block.kind,
                        section_path=block.section_path,
                        block_flags=block.flags,
                        link_texts=tuple(link.text for link in block.links),
                        link_hrefs=tuple(link.href for link in block.links),
                        table_scope_rejection_reason=active_table_scope_rejection_reason,
                        parser_branch=(
                            "non_catalog_table_row"
                            if active_table_scope_rejection_reason
                            else "table_row"
                        ),
                    )
                )
            continue

        active_table_headers = ()
        active_table_context = {}
        active_table_scope_rejection_reason = None
        if block.kind == "heading":
            section_context_suspended = False
        if index in consumed_metadata_blocks:
            continue

        section_context = (
            None
            if section_context_suspended
            else _section_context_from_path(block.section_path, institution_profile=institution_profile)
        )
        path_section_context = section_context
        inline_faculty = _section_faculty_context(
            cleaned,
            institution_profile=institution_profile,
            allow_profile_aliases=block.kind in {"heading", "card"},
        )
        if inline_faculty:
            section_context = _TableContextValue(value=inline_faculty, source_text=cleaned)
            if not _extract_name(cleaned, institution_profile=institution_profile):
                if block.kind == "heading" or path_section_context is None or path_section_context.value != inline_faculty:
                    out.append(
                        _CatalogCandidate(
                            text=cleaned,
                            section_context_provider_fields=("faculty",),
                            block_kind=block.kind,
                            section_path=block.section_path,
                            parser_branch="section_context",
                            block_flags=block.flags,
                            heading_level=block.heading_level,
                            link_texts=tuple(link.text for link in block.links),
                            link_hrefs=tuple(link.href for link in block.links),
                        )
                    )
                continue

        section_context_fields = ("faculty",) if section_context else ()
        section_context_evidence = (("faculty", section_context),) if section_context else ()
        if block.kind in {"heading", "list_item", "card"}:
            candidate_text = cleaned
            if block.kind in {"heading", "card"} and index + 1 < len(blocks):
                following = blocks[index + 1]
                if (
                    following.kind == "paragraph"
                    and following.section_path == block.section_path
                    and _is_title_metadata_paragraph(following.text)
                ):
                    candidate_text = f"{candidate_text} {_clean(following.text)}"
                    consumed_metadata_blocks.add(index + 1)
            out.append(
                _CatalogCandidate(
                    text=candidate_text,
                    section_context_fields=section_context_fields,
                    section_context_evidence=section_context_evidence,
                    block_kind=block.kind,
                    section_path=block.section_path,
                    parser_branch={
                        "heading": "heading_candidate",
                        "list_item": "list_candidate",
                        "card": "card_candidate",
                    }[block.kind],
                    block_flags=block.flags,
                    heading_level=block.heading_level,
                    link_texts=tuple(link.text for link in block.links),
                    link_hrefs=tuple(link.href for link in block.links),
                )
            )
            continue
        if block.kind == "paragraph":
            for sentence in re.split(r"(?<=[.;])\s+|[\n\r]+", cleaned):
                sentence = _clean(sentence)
                if sentence:
                    out.append(
                        _CatalogCandidate(
                            text=sentence,
                            section_context_fields=section_context_fields,
                            section_context_evidence=section_context_evidence,
                            block_kind=block.kind,
                            section_path=block.section_path,
                            parser_branch="paragraph_sentence",
                            block_flags=block.flags,
                            link_texts=tuple(link.text for link in block.links),
                            link_hrefs=tuple(link.href for link in block.links),
                        )
                    )
    return out


def _section_context_from_path(
    section_path: tuple[str, ...],
    *,
    institution_profile: InstitutionProfile | None,
) -> _TableContextValue | None:
    context: _TableContextValue | None = None
    for heading in section_path:
        cleaned = _clean(heading)
        if _is_section_context_boundary(cleaned):
            context = None
            continue
        faculty = _section_faculty_context(
            cleaned,
            institution_profile=institution_profile,
            allow_profile_aliases=True,
        )
        if faculty:
            context = _TableContextValue(value=faculty, source_text=cleaned)
    return context


def _is_title_metadata_paragraph(text: str) -> bool:
    return bool(re.match(r"^(?:majors?|specialisations?|specializations?)\s*:", _clean(text), flags=re.IGNORECASE))


def _candidate_lines(text: str, *, institution_profile: InstitutionProfile | None) -> list[_CatalogCandidate]:
    normalised = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    normalised = re.sub(r"</(?:li|tr|p|h[1-6]|div|section)>", "\n", normalised, flags=re.IGNORECASE)
    normalised = re.sub(r"<[^>]+>", " ", normalised)
    out: list[_CatalogCandidate] = []
    active_table_headers: tuple[str, ...] = ()
    active_table_context: dict[str, _TableContextValue] = {}
    active_table_scope_rejection_reason: str | None = None
    active_section_context: _TableContextValue | None = None
    for line in re.split(r"[\n\r]+", normalised):
        cleaned = _clean(line)
        if not cleaned:
            continue
        if "|" in cleaned:
            active_section_context = None
            table_candidates = _flattened_table_candidate_lines(
                cleaned,
                institution_profile=institution_profile,
            )
            if table_candidates:
                out.extend(table_candidates)
                active_table_headers = ()
                active_table_context = {}
                active_table_scope_rejection_reason = None
                continue
            cells = _table_cells(cleaned)
            table_scope_rejection_reason = _non_catalog_table_scope_reason(cells)
            if table_scope_rejection_reason:
                active_table_headers = ()
                active_table_context = {}
                active_table_scope_rejection_reason = table_scope_rejection_reason
                out.append(
                    _CatalogCandidate(
                        cleaned,
                        table_cells=tuple(cells),
                        parser_branch="non_catalog_table_header",
                        table_scope_rejection_reason=table_scope_rejection_reason,
                    )
                )
                continue
            if len(cells) >= 2 and (_is_table_header(cells) or _is_partial_table_header(cells)):
                active_table_headers = tuple(cells)
                active_table_context = {}
                active_table_scope_rejection_reason = None
                continue
            if cells and active_table_scope_rejection_reason:
                out.append(
                    _CatalogCandidate(
                        cleaned,
                        table_cells=tuple(cells),
                        parser_branch="non_catalog_table_row",
                        table_scope_rejection_reason=active_table_scope_rejection_reason,
                    )
                )
                continue
            if cells and (
                active_table_headers
                or _looks_like_table_candidate_cells(cells, institution_profile=institution_profile)
            ):
                out.append(_table_candidate(cells, active_table_headers, active_table_context))
                continue
        active_table_headers = ()
        active_table_context = {}
        active_table_scope_rejection_reason = None
        section_faculty = _section_faculty_context(
            cleaned,
            institution_profile=institution_profile,
            allow_profile_aliases=False,
        )
        if section_faculty:
            active_section_context = _TableContextValue(value=section_faculty, source_text=cleaned)
            if not _extract_name(cleaned, institution_profile=institution_profile):
                out.append(
                    _CatalogCandidate(
                        cleaned,
                        section_context_provider_fields=("faculty",),
                    )
                )
                continue
        if _is_section_context_boundary(cleaned):
            active_section_context = None
        for sentence in re.split(r"(?<=[.;])\s+", cleaned):
            sentence = _clean(sentence)
            if sentence:
                section_context_evidence = (("faculty", active_section_context),) if active_section_context else ()
                out.append(
                    _CatalogCandidate(
                        sentence,
                        section_context_fields=("faculty",) if active_section_context else (),
                        section_context_evidence=section_context_evidence,
                    )
                )
    return out


def _flattened_table_candidate_lines(
    line: str,
    *,
    institution_profile: InstitutionProfile | None,
) -> list[_CatalogCandidate]:
    """Recover rows from tables flattened into one browser/OCR text line."""

    explicit_rows = [_clean(part) for part in re.split(r"\s+[.;]\s+", line) if _clean(part)]
    candidates: list[_CatalogCandidate] = []
    if len(explicit_rows) > 1:
        active_headers: tuple[str, ...] = ()
        active_context: dict[str, _TableContextValue] = {}
        active_table_scope_rejection_reason: str | None = None
        for row in explicit_rows:
            cells = _table_cells(row)
            if len(cells) < 2:
                continue
            table_scope_rejection_reason = _non_catalog_table_scope_reason(cells)
            if table_scope_rejection_reason:
                active_headers = ()
                active_context = {}
                active_table_scope_rejection_reason = table_scope_rejection_reason
                candidates.append(
                    _CatalogCandidate(
                        row,
                        table_cells=tuple(cells),
                        parser_branch="non_catalog_table_header",
                        table_scope_rejection_reason=table_scope_rejection_reason,
                    )
                )
                continue
            if _is_table_header(cells) or _is_partial_table_header(cells):
                active_headers = tuple(cells)
                active_context = {}
                active_table_scope_rejection_reason = None
                continue
            if active_table_scope_rejection_reason:
                candidates.append(
                    _CatalogCandidate(
                        row,
                        table_cells=tuple(cells),
                        parser_branch="non_catalog_table_row",
                        table_scope_rejection_reason=active_table_scope_rejection_reason,
                    )
                )
                continue
            candidate = _table_candidate(cells, active_headers, active_context)
            if candidate.table_headers or _looks_like_table_candidate_cells(
                cells,
                institution_profile=institution_profile,
            ):
                candidates.append(candidate)
    if candidates:
        return candidates

    cells = _table_cells(line)
    header_width = _flattened_header_width(cells)
    if not header_width:
        return []
    headers = tuple(cells[:header_width])
    out: list[_CatalogCandidate] = []
    context: dict[str, _TableContextValue] = {}
    for index in range(header_width, len(cells), header_width):
        row_cells = cells[index : index + header_width]
        if len(row_cells) == header_width:
            out.append(_table_candidate(row_cells, headers, context))
    return out


def _flattened_header_width(cells: list[str]) -> int:
    width = 0
    for cell in cells:
        if _table_header_role(cell) is None:
            break
        width += 1
    if width >= 2 and _is_table_header(cells[:width]):
        return width
    return 0


def _table_cells(line: str) -> list[str]:
    return [_clean(part) for part in line.split("|")]


def _table_candidate(cells: list[str], headers: tuple[str, ...], context: dict[str, _TableContextValue]) -> _CatalogCandidate:
    text = " | ".join(cells)
    if not headers:
        return _CatalogCandidate(text, table_cells=tuple(cells))

    aligned = _align_grouped_table_cells(cells, headers, context)
    if aligned is None:
        return _CatalogCandidate(text, table_cells=tuple(cells))

    name_index = next((index for index, header in enumerate(headers) if _table_header_role(header) == "name"), None)
    has_explicit_name = name_index is not None and bool(aligned[name_index])
    resolved = list(aligned)
    inherited_fields: set[str] = set()
    inherited_context_evidence: dict[str, _TableContextValue] = {}
    provider_fields: set[str] = set()
    for index, header in enumerate(headers):
        role = _table_header_role(header)
        if role not in _INHERITABLE_TABLE_CONTEXT_ROLES:
            continue
        value = aligned[index]
        if value:
            context[role] = _TableContextValue(value=value, source_text=text)
            if not has_explicit_name:
                provider_fields.add(role)
        elif has_explicit_name and role in context:
            resolved[index] = context[role].value
            inherited_fields.add(role)
            inherited_context_evidence[role] = context[role]

    return _CatalogCandidate(
        text=text,
        table_headers=headers,
        table_cells=tuple(resolved),
        inherited_context_fields=tuple(sorted(inherited_fields)),
        inherited_context_evidence=tuple(sorted(inherited_context_evidence.items())),
        context_provider_fields=tuple(sorted(provider_fields)),
    )


def _align_grouped_table_cells(cells: list[str], headers: tuple[str, ...], context: dict[str, _TableContextValue]) -> list[str] | None:
    if len(cells) == len(headers):
        return list(cells)
    if len(cells) >= len(headers):
        return None

    missing_count = len(headers) - len(cells)
    missing_roles = [_table_header_role(header) for header in headers[:missing_count]]
    if not all(role in _INHERITABLE_TABLE_CONTEXT_ROLES and role in context for role in missing_roles):
        return None
    return [""] * missing_count + list(cells)


def _looks_like_table_candidate_cells(
    cells: list[str],
    *,
    institution_profile: InstitutionProfile | None,
) -> bool:
    if len(cells) < 2:
        return False
    if any(len(cell) > 200 for cell in cells):
        return False
    if _looks_like_course_table_candidate(" | ".join(cells)):
        return False
    if _is_table_header(cells):
        return False
    if _looks_like_programme_name_cell(cells[0], institution_profile=institution_profile) and _looks_like_award(cells[1]):
        return True
    return any(
        _category_for_name(cell, " | ".join(cells), institution_profile=institution_profile)
        for cell in cells
    )


def _parse_candidate(
    line: str,
    *,
    faculty_hint: str | None,
    institution_profile: InstitutionProfile | None,
    allow_unknown_category: bool = False,
    table_headers: tuple[str, ...] = (),
    table_cells: tuple[str, ...] = (),
    inherited_context_fields: tuple[str, ...] = (),
    allow_pipe_table_fallback: bool = True,
    parser_branch: str = "legacy_text_fallback",
) -> dict[str, object] | None:
    if _looks_like_course_table_candidate(line):
        return None
    if _looks_like_second_major_explainer(line):
        return None
    if _looks_like_admissions_explainer(line):
        return None
    if parser_branch == "paragraph_sentence" and not _is_strict_paragraph_candidate(
        line,
        institution_profile=institution_profile,
    ):
        return None
    specialisations = _specialisations(line)
    labelled = _parse_labelled_catalog_candidate(line)
    if labelled:
        if not labelled.get("faculty_or_school"):
            labelled["faculty_or_school"] = faculty_hint
        if specialisations and not labelled.get("specialisations_or_majors"):
            labelled["specialisations_or_majors"] = specialisations
        return labelled

    cells = list(table_cells)
    if not cells and allow_pipe_table_fallback and "|" in line:
        cells = [_clean(part) for part in line.split("|")]
    if len(cells) >= 2:
        parsed = _parse_table_candidate(
            cells,
            table_headers=table_headers,
            institution_profile=institution_profile,
        )
        if parsed:
            if inherited_context_fields:
                parsed["_context_inherited"] = True
                parsed["_inherited_context_fields"] = list(inherited_context_fields)
                parsed["_candidate_shape"] = "grouped_table_row"
            if not parsed.get("faculty_or_school"):
                parsed["faculty_or_school"] = faculty_hint
            if specialisations and not parsed.get("specialisations_or_majors"):
                parsed["specialisations_or_majors"] = specialisations
            return parsed
        if _looks_like_unbounded_programme_card_cells(cells):
            return None
        if table_headers:
            return None

    name = _extract_name(line, institution_profile=institution_profile)
    if not name:
        return None
    if _looks_like_longform_prose_candidate(line):
        return None
    category = _category_for_name(name, line, institution_profile=institution_profile)
    if category is None:
        if not allow_unknown_category:
            return None
        category = "unknown"
    parsed = {
        "name": name,
        "faculty_or_school": faculty_hint,
        "degree_or_award": _degree_for_name(name, line, category),
        "category": category,
        "mode": _mode(line),
        "duration_or_units": _duration(line),
        "admissions_choice_name": _admissions_choice(line, name),
        "specialisations_or_majors": specialisations,
        "_category_inferred": not _category_has_direct_text_evidence(category, line),
        "_requires_category_hint": category == "unknown",
    }
    return parsed


def _record_candidate_diagnostic(
    diagnostics: list[dict[str, object]] | None,
    *,
    source: SourceRecord,
    candidate: str,
    decision: str,
    reason: str,
    parser_stage: str,
    claim_path: str | None = None,
    name: str | None = None,
    category: str | None = None,
    parse_status: str | None = None,
    candidate_shape: str | None = None,
    inherited_context_fields: tuple[str, ...] = (),
    context_fields: tuple[str, ...] = (),
    ignored_metadata_headers: tuple[str, ...] = (),
    field_evidence_paths: dict[str, str] | None = None,
    primary_source_urls: tuple[str, ...] = (),
    section_context_fields: tuple[str, ...] = (),
    block_kind: str | None = None,
    section_path: tuple[str, ...] = (),
    parser_branch: str | None = None,
    block_flags: tuple[str, ...] = (),
    source_role: str | None = None,
    structural_anchor: str | None = None,
    name_quality_passed: bool | None = None,
    institution_consistent: bool | None = None,
) -> None:
    if diagnostics is None:
        return
    institution_profile = institution_profile_for_source(source.source_url, is_official=source.is_official)
    item: dict[str, object] = {
        "source_url": source.source_url,
        "source_title": source.title,
        "institution_profile": institution_profile.key if institution_profile else "generic",
        "candidate_text": _snippet(candidate),
        "decision": decision,
        "reason": reason,
        "parser_stage": parser_stage,
    }
    if claim_path:
        item["claim_path"] = claim_path
    if name:
        item["name"] = name
    if category:
        item["category"] = category
    if parse_status:
        item["parse_status"] = parse_status
    if candidate_shape:
        item["candidate_shape"] = candidate_shape
    if inherited_context_fields:
        item["inherited_context_fields"] = list(inherited_context_fields)
    if section_context_fields:
        item["section_context_fields"] = list(section_context_fields)
    if context_fields:
        item["context_fields"] = list(context_fields)
    if ignored_metadata_headers:
        item["ignored_metadata_headers"] = list(ignored_metadata_headers)
    if field_evidence_paths:
        item["field_evidence_paths"] = dict(sorted(field_evidence_paths.items()))
    if primary_source_urls:
        item["primary_source_urls"] = list(primary_source_urls)
    item["block_kind"] = block_kind or "legacy_text"
    if section_path:
        item["section_path"] = list(section_path)
    if parser_branch:
        item["parser_branch"] = parser_branch
    if block_flags:
        item["block_flags"] = list(block_flags)
    if source_role:
        item["source_role"] = source_role
    if structural_anchor:
        item["structural_anchor"] = structural_anchor
    if name_quality_passed is not None:
        item["name_quality_passed"] = name_quality_passed
    if institution_consistent is not None:
        item["institution_consistent"] = institution_consistent
    diagnostics.append(item)


def _candidate_rejection_reason(
    line: str,
    *,
    parser_branch: str = "legacy_text_fallback",
    block_flags: tuple[str, ...] = (),
) -> str:
    if "css_like" in block_flags:
        return "css_or_template_text"
    if _looks_like_course_table_candidate(line):
        return "course_or_curriculum_row"
    if _looks_like_second_major_explainer(line):
        return "second_major_explainer"
    if _looks_like_admissions_explainer(line):
        return "admissions_explainer"
    if _looks_like_longform_prose_candidate(line):
        return "longform_prose"
    if parser_branch == "paragraph_sentence" and _contains_degree_keyword(line):
        return "sentence_like_name" if _looks_like_sentence_like_candidate(line) else "unanchored_degree_mention"
    if parser_branch == "paragraph_sentence" and _looks_like_sentence_like_candidate(line):
        return "sentence_like_name"
    if parser_branch == "legacy_text_fallback" and _looks_like_unbounded_programme_card_cells(_table_cells(line)):
        return "unbounded_programme_card"
    if "|" in line and parser_branch == "legacy_text_fallback":
        return "unknown_table_shape"
    if _extract_name(line):
        return "missing_catalog_shape"
    return "no_programme_name"


def _apply_programme_catalog_hint(
    *,
    parsed: dict[str, object],
    candidate: str,
    source: SourceRecord,
    provider: ProgrammeCatalogAssistProvider,
) -> None:
    if not _needs_programme_catalog_hint(parsed):
        return
    result = generate_programme_catalog_classification_hint(
        candidate_text=candidate,
        source_url=source.source_url,
        title=source.title,
        provider=provider,
    )
    hint = result.hint
    parsed["_llm_category_hint"] = result.diagnostics
    if hint is None:
        return
    if (not parsed.get("category") or parsed.get("category") == "unknown") and hint.category != "unknown":
        parsed["category"] = hint.category
        parsed["_category_inferred"] = True
    if not parsed.get("mode") and hint.mode != "unknown":
        parsed["mode"] = hint.mode


def _needs_programme_catalog_hint(parsed: dict[str, object]) -> bool:
    return parsed.get("category") in {None, "unknown"} or not parsed.get("mode")


def _parse_table_candidate(
    cells: list[str],
    *,
    table_headers: tuple[str, ...] = (),
    institution_profile: InstitutionProfile | None,
) -> dict[str, object] | None:
    if table_headers:
        return _parse_header_mapped_table_candidate(
            cells,
            table_headers,
            institution_profile=institution_profile,
        )

    listed = _parse_award_listing_candidate(cells[0])
    if listed:
        remaining = cells[1:]
        listed["mode"] = listed.get("mode") or _mode_from_values(remaining)
        listed["duration_or_units"] = listed.get("duration_or_units") or _duration_from_values(remaining)
        return listed

    if _looks_like_unbounded_programme_card_cells(cells):
        return None

    named_award = _parse_named_award_table_candidate(cells, institution_profile=institution_profile)
    if named_award:
        return named_award

    name = next(
        (
            cell
            for cell in cells
            if _category_for_name(cell, cell, institution_profile=institution_profile)
        ),
        "",
    )
    if not name:
        return None
    category = _category_for_name(name, " | ".join(cells), institution_profile=institution_profile)
    if category is None:
        return None
    remaining = [cell for cell in cells if cell != name]
    faculty_or_school = _faculty_from_values(remaining, institution_profile=institution_profile)
    non_faculty_remaining = [cell for cell in remaining if cell != faculty_or_school]
    degree_or_award = _first_matching(non_faculty_remaining, _looks_like_award) or _degree_for_name(
        name,
        " | ".join(cells),
        category,
    )
    return {
        "name": name,
        "faculty_or_school": faculty_or_school,
        "degree_or_award": degree_or_award,
        "category": category,
        "mode": _mode_from_values(remaining),
        "duration_or_units": _duration_from_values(remaining),
        "admissions_choice_name": _first_matching(non_faculty_remaining, _looks_like_admissions_choice),
        "specialisations_or_majors": [],
        "_category_inferred": not _category_has_direct_text_evidence(category, degree_or_award or name),
    }


def _parse_header_mapped_table_candidate(
    cells: list[str],
    headers: tuple[str, ...],
    *,
    institution_profile: InstitutionProfile | None,
) -> dict[str, object] | None:
    if not headers or len(cells) != len(headers) or not _is_table_header(list(headers)):
        return None

    values_by_role: dict[str, list[str]] = {}
    for header, value in zip(headers, cells):
        role = _table_header_role(header)
        if role:
            values_by_role.setdefault(role, []).append(value)

    name_values = values_by_role.get("name", [])
    if len(name_values) != 1:
        return None
    name = _clean_name(name_values[0])
    if not _looks_like_programme_name_cell(name, institution_profile=institution_profile):
        return None

    context = " | ".join(cells)
    award = _first_matching(values_by_role.get("award", []), _looks_like_award)
    explicit_category = _category_from_table_values(values_by_role.get("category", []))
    category = explicit_category or _category_for_name(name, context, institution_profile=institution_profile)
    if category is None:
        return None

    degree_or_award = award
    if not degree_or_award and _looks_like_award(name):
        degree_or_award = _degree_for_name(name, context, category)
    if not degree_or_award and explicit_category is None:
        return None

    faculty_values = values_by_role.get("faculty", [])
    faculty_or_school = _faculty_from_values(
        faculty_values,
        institution_profile=institution_profile,
        explicit_field=True,
    )
    specialisations = _catalog_list_values(values_by_role.get("specialisations", []))
    ignored_metadata_headers = sorted(
        {
            header
            for header, value in zip(headers, cells)
            if _table_header_role(header) == "metadata" and value
        }
    )
    return {
        "name": name,
        "faculty_or_school": faculty_or_school,
        "degree_or_award": degree_or_award,
        "category": category,
        "mode": _mode_from_values(values_by_role.get("mode", [])),
        "duration_or_units": _duration_from_values(values_by_role.get("duration", [])),
        "admissions_choice_name": _first_catalog_value(values_by_role.get("admissions_choice", [])),
        "specialisations_or_majors": specialisations,
        "_category_inferred": explicit_category is None
        and not _category_has_direct_text_evidence(category, degree_or_award or name),
        "_candidate_shape": "header_mapped_table",
        "_ignored_metadata_headers": ignored_metadata_headers,
    }


def _category_from_table_values(values: list[str]) -> str | None:
    for value in values:
        lower = value.lower().strip()
        if "dual degree" in lower or "double degree" in lower:
            return "dual_degree"
        if re.search(r"\bmajor\b", lower):
            return "major"
        if re.search(r"\bminor\b", lower):
            return "minor"
        if "special programme" in lower or "special program" in lower:
            return "special_programme"
        if "degree" in lower or "programme" in lower or "program" in lower:
            return "degree_programme"
    return None


def _catalog_list_values(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        for part in re.split(r"\s*[;,]\s*", value):
            cleaned = _clean_name(part)
            if cleaned and cleaned.lower() not in {"none", "n/a", "not applicable"} and cleaned not in out:
                out.append(cleaned)
    return out


def _first_catalog_value(values: list[str]) -> str | None:
    for value in values:
        cleaned = _clean(value)
        if cleaned and cleaned.lower() not in {"none", "n/a", "not applicable", "unknown"}:
            return cleaned
    return None


def _parse_named_award_table_candidate(
    cells: list[str],
    *,
    institution_profile: InstitutionProfile | None,
) -> dict[str, object] | None:
    if len(cells) < 2:
        return None
    name = _clean_name(cells[0])
    degree_or_award = _clean(cells[1])
    if not _looks_like_programme_name_cell(name, institution_profile=institution_profile) or not _looks_like_award(degree_or_award):
        return None
    context = " | ".join(cells)
    category = _category_for_name(
        name,
        context,
        institution_profile=institution_profile,
    ) or _category_for_name(
        degree_or_award,
        context,
        institution_profile=institution_profile,
    )
    if category is None:
        return None
    remaining = cells[2:]
    faculty_or_school = _faculty_from_values(remaining, institution_profile=institution_profile)
    non_faculty_remaining = [cell for cell in remaining if cell != faculty_or_school]
    return {
        "name": name,
        "faculty_or_school": faculty_or_school,
        "degree_or_award": degree_or_award,
        "category": category,
        "mode": _mode_from_values(remaining),
        "duration_or_units": _duration_from_values(remaining),
        "admissions_choice_name": _first_matching(non_faculty_remaining, _looks_like_admissions_choice),
        "specialisations_or_majors": [],
        "_category_inferred": not _category_has_direct_text_evidence(category, degree_or_award),
    }


def _parse_labelled_catalog_candidate(line: str) -> dict[str, object] | None:
    match = re.search(
        r"\b(?P<name>Bachelor\s+(?:of|in)\s+[A-Z][A-Za-z&/(),'+\- ]{2,120})\s+"
        r"CODE\s+(?P<code>[A-Z0-9-]+)\s+"
        r"FACULTY\s+(?P<faculty>.+?)\s+"
        r"STUDY\s+PERIOD\s+(?P<duration>.+?)\s+"
        r"TYPE\s+(?P<programme_type>.+)$",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    name = _clean_name(match.group("name"))
    return {
        "name": name,
        "faculty_or_school": _clean(match.group("faculty")),
        "degree_or_award": name,
        "category": _category_from_programme_type(match.group("programme_type")),
        "mode": _mode(line),
        "duration_or_units": _clean(match.group("duration")),
        "admissions_choice_name": _clean(match.group("code")),
        "specialisations_or_majors": [],
        "_category_inferred": False,
    }


def _parse_award_listing_candidate(line: str) -> dict[str, object] | None:
    match = re.search(
        r"^(?P<name>.+?)\s+-\s+(?P<short_award>B(?:A|Sc|Eng|BA|BAA|BAF|BAI|FA|SW|Des|Ed)[A-Za-z() ]*(?:\s+Scheme)?)\s+-\s+"
        r"(?P<award>Bachelor(?:'s)?\s+(?:of\s+)?[A-Za-z() ]+(?:\s+Scheme)?)\s+"
        r"(?P<code>[A-Z]{2}\d{4}|[0-9]{5}(?:-[A-Z]+)?)?$",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    raw_name = _clean(match.group("name"))
    specialisations = _parenthetical_specialisations(raw_name)
    name = _clean(re.sub(r"\s*\([^)]*/[^)]*\)", "", raw_name))
    award = _clean(match.group("award"))
    code = match.group("code")
    return {
        "name": name,
        "degree_or_award": award,
        "category": "degree_programme",
        "mode": _mode(line),
        "duration_or_units": _duration(line),
        "admissions_choice_name": _clean(code) if code else None,
        "specialisations_or_majors": specialisations,
        "_category_inferred": False,
    }


def _category_from_programme_type(value: str) -> str:
    lower = value.lower()
    if "double degree" in lower or "dual degree" in lower:
        return "dual_degree"
    if "degree" in lower or "programme" in lower or "program" in lower:
        return "degree_programme"
    return "unknown"


def _extract_name(
    line: str,
    *,
    institution_profile: InstitutionProfile | None = None,
) -> str | None:
    patterns = (
        r"\b(Bachelor\s+of\s+[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b(Bachelor\s+in\s+[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b(BSc\s*\(Hons\)\s+Major:\s*[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b(BBA\s+Major:\s*[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b(Scholars Programme)(?=\s|$|[.;,])",
    )
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            return _clean_name(match.group(1))
    return extract_profile_programme_name(institution_profile, line)


def _category_for_name(
    name: str,
    context: str,
    *,
    institution_profile: InstitutionProfile | None = None,
) -> str | None:
    lower = f"{name} {context}".lower()
    if "major:" in lower or "primary major" in lower:
        return "major"
    if "minor:" in lower:
        return "minor"
    if "special programme" in lower:
        return "special_programme"
    if "bachelor" in lower or re.search(r"\b(?:bsc|ba|beng|bba|llb|mbbs)\b", lower):
        return "degree_programme"
    return profile_programme_category(institution_profile, name)


def _category_has_direct_text_evidence(category: str, *values: str) -> bool:
    text = " ".join(values).lower()
    if category == "dual_degree":
        return bool(re.search(r"\b(?:double|dual)\s+degree\b", text))
    if category == "major":
        return bool(re.search(r"\b(?:primary\s+)?major\b", text))
    if category == "minor":
        return bool(re.search(r"\bminor\b", text))
    if category == "special_programme":
        return bool(re.search(r"\bspecial\s+program(?:me)?\b", text))
    if category == "degree_programme":
        degree_signals = re.findall(r"\b(?:bachelor(?:'s)?|bsc|ba|beng|bba|llb|mbbs)\b", text)
        return len(degree_signals) == 1
    return False


def _degree_for_name(name: str, context: str, category: str) -> str | None:
    if category == "degree_programme":
        return name
    if category == "major":
        award_match = re.search(r"\b(Bachelor\s+of\s+[A-Z][A-Za-z&/(),'\- ]{2,100})", context)
        if award_match:
            return _clean_name(award_match.group(1))
        if "bba" in name.lower():
            return "Major within Bachelor of Business Administration (Honours)"
        if "bsc" in name.lower():
            return "Bachelor of Science (Honours)"
    return None


def _faculty_hint(source: SourceRecord, institution_profile: InstitutionProfile | None) -> str | None:
    profile_label = profile_faculty_from_source_title(
        institution_profile,
        title=source.title,
    )
    if profile_label:
        return profile_label
    for segment in re.split(r"\s*\|\s*", source.title or ""):
        cleaned = _clean(segment)
        lower = cleaned.lower()
        if not cleaned or any(token in lower for token in ("admission", "bachelor", "degree", "programme", "program")):
            continue
        if _looks_like_faculty_or_school(cleaned):
            return cleaned
    return None


def _section_faculty_context(
    line: str,
    *,
    institution_profile: InstitutionProfile | None,
    allow_profile_aliases: bool,
) -> str | None:
    match = re.match(
        r"^(?:The\s+)?((?:School|Faculty|College|Academy|Institute|Department)\s+of\s+"
        r"[A-Z][A-Za-z&,'()\- ]{2,100}?)(?=\s+(?:offers?|provides?|lists?|has|undergraduate|degree|programmes?|programs?)\b|[.:;]|$)",
        line,
    )
    if match:
        return _clean(match.group(1))
    if allow_profile_aliases:
        profile_label = profile_faculty_from_structured_label(institution_profile, line)
        if profile_label:
            return profile_label
        if faculty_label_conflicts(institution_profile, line):
            return _clean(line)
    return None


def _is_section_context_boundary(line: str) -> bool:
    return bool(
        re.match(
            r"^(?:about|admissions?|application|contact|course|curriculum|entry requirements?|fees?|"
            r"how to apply|modules?|postgraduate|related programmes?|related programs?|requirements?|"
            r"scholarships?|tuition)\b",
            line,
            flags=re.IGNORECASE,
        )
    )


def _is_confident_row(parsed: dict[str, object]) -> bool:
    return bool(
        parsed.get("name")
        and parsed.get("category") != "unknown"
        and parsed.get("_structural_anchor")
        and parsed.get("_source_role") not in {None, "curriculum_or_old_cohort", "unrelated"}
        and parsed.get("_name_quality_passed") is True
        and parsed.get("_institution_consistent") is True
    )


def _quality_warnings(
    *,
    parsed: dict[str, object],
    claim_path: str,
    source_url: str,
    parse_status: str,
    faculty_or_school: str | None,
    degree_or_award: str | None,
    duplicate_index: int,
) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    if duplicate_index:
        warnings.append(
            _row_warning(
                "duplicate_name",
                "Duplicate programme normalized key retained for manual review.",
                claim_path,
                source_url,
            )
        )
    if not degree_or_award:
        warnings.append(
            _row_warning(
                "ambiguous_degree",
                "Programme row does not expose a stable degree or award.",
                claim_path,
                source_url,
            )
        )
    if not faculty_or_school:
        warnings.append(
            _row_warning(
                "missing_faculty",
                "Programme row does not expose a faculty or school.",
                claim_path,
                source_url,
            )
        )
    if parsed.get("_category_inferred"):
        warnings.append(
            _row_warning(
                "category_inferred",
                "Programme category was inferred from row text rather than an explicit catalogue type.",
                claim_path,
                source_url,
            )
        )
    inherited_context_fields = parsed.get("_inherited_context_fields")
    if isinstance(inherited_context_fields, list) and inherited_context_fields:
        warnings.append(
            _row_warning(
                "grouped_context_inherited",
                "Programme row inherited grouped table context for " + ", ".join(str(item) for item in inherited_context_fields) + ".",
                claim_path,
                source_url,
            )
        )
    section_context_fields = parsed.get("_section_context_fields")
    if isinstance(section_context_fields, list) and section_context_fields:
        warnings.append(
            _row_warning(
                "section_context_inherited",
                "Programme row inherited nearby section context for " + ", ".join(str(item) for item in section_context_fields) + ".",
                claim_path,
                source_url,
            )
        )
    if parse_status == RAW_NEEDS_REVIEW:
        warnings.append(
            _row_warning(
                "raw_needs_manual_review",
                "Programme catalog row could not be fully normalised; review category/award context.",
                claim_path,
                source_url,
            )
        )
    return warnings


def _row_warning(label: str, message: str, claim_path: str, source_url: str) -> WarningRecord:
    return WarningRecord(
        WarningCode.NEEDS_MANUAL_CHECK,
        f"{label}: {message}",
        field=claim_path,
        source_urls=[source_url],
    )


def _normalised_programme_key(name: object, degree_or_award: str | None, faculty_or_school: str | None, source_url: str) -> tuple[str, str, str, str]:
    return (
        _normalised_key_part(name),
        _normalised_key_part(degree_or_award),
        _normalised_key_part(faculty_or_school),
        _normalised_key_part(source_url),
    )


def _normalised_key_part(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _snippet(line: str) -> str:
    return _clean(line)[:700]


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" \t\r\n-|")


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+(?:CODE|FACULTY|STUDY\s+PERIOD|TYPE)\b.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+(?:Specialisations?|Majors)\b.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+(?:requires?|needs?|must|is offered|are offered|leads to|programmes are)\b.*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+(?:full-time|part-time|four-year|three-year|160 units?|at least).*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+within\b.*$", "", name, flags=re.IGNORECASE)
    return _clean(name).rstrip(".;:,")


def _is_table_header(cells: list[str]) -> bool:
    roles = [_table_header_role(cell) for cell in cells]
    role_set = {role for role in roles if role}
    if "name" not in role_set:
        return False
    if not role_set.intersection({"award", "category", "mode", "duration", "faculty", "specialisations", "admissions_choice"}):
        return False
    return all(role is not None for role in roles) and not any(_category_for_name(cell, cell) for cell in cells)


def _non_catalog_table_scope_reason(cells: list[str]) -> str | None:
    normalized = [re.sub(r"[^a-z0-9]+", " ", cell.lower()).strip() for cell in cells]
    if len(normalized) < 3:
        return None
    is_minor_or_second_major = normalized[0] in {
        "minor",
        "minor programme",
        "minor program",
        "second major",
    }
    has_offering_unit = any(value.startswith("school offering") for value in normalized[1:])
    has_eligibility_column = any(
        value.startswith("offered to students") or value.startswith("eligible students")
        for value in normalized[1:]
    )
    if is_minor_or_second_major and has_offering_unit and has_eligibility_column:
        return "minor_or_second_major_eligibility_table"
    return None


def _is_partial_table_header(cells: list[str]) -> bool:
    roles = [_table_header_role(cell) for cell in cells]
    role_set = {role for role in roles if role}
    if "name" not in role_set or all(role is not None for role in roles):
        return False
    if not role_set.intersection({"award", "category", "mode", "duration", "faculty", "specialisations", "admissions_choice"}):
        return False
    return not any(_category_for_name(cell, cell) for cell in cells)


def _table_header_role(value: str) -> str | None:
    lower = re.sub(r"[^a-z]+", " ", value.lower()).strip()
    aliases = {
        "name": {
            "programme",
            "program",
            "programme name",
            "program name",
            "programme title",
            "program title",
            "programme of study",
            "program of study",
            "study programme",
            "study program",
        },
        "award": {
            "award",
            "degree",
            "degree title",
            "degree award",
            "degree awarded",
            "award title",
            "award qualification",
            "qualification",
            "qualification awarded",
        },
        "category": {
            "category",
            "programme category",
            "program category",
            "programme type",
            "program type",
            "type",
        },
        "mode": {"attendance", "attendance mode", "mode", "mode of study", "study mode"},
        "duration": {"duration", "duration of study", "length", "normal duration", "study period", "years"},
        "faculty": {"academic unit", "college", "department", "faculty", "faculty school", "offered by", "school"},
        "specialisations": {
            "major",
            "majors",
            "majors tracks",
            "specialisation",
            "specialisations",
            "specialization",
            "specializations",
            "track",
            "tracks",
        },
        "admissions_choice": {
            "admission choice",
            "admissions choice",
            "application choice",
            "application code",
            "choice",
            "jupas code",
            "pathway",
            "programme code",
            "program code",
        },
        "metadata": {
            "academic year",
            "campus",
            "details",
            "intake",
            "location",
            "more information",
            "programme details",
            "program details",
            "start date",
            "website",
        },
    }
    for role, names in aliases.items():
        if lower in names:
            return role
    if lower.endswith(" programme") or lower.endswith(" program"):
        return "name"
    return None


def _looks_like_programme_name_cell(
    value: str,
    *,
    institution_profile: InstitutionProfile | None = None,
) -> bool:
    cleaned = _clean(value)
    if len(cleaned) < 3 or len(cleaned) > 160:
        return False
    lower = cleaned.lower()
    if lower in {"programme", "program", "degree", "degree title", "award", "all", "filter"}:
        return False
    if any(token in lower for token in ("programme level", "programme type", "select a", "view all", "read more")):
        return False
    if _looks_like_longform_prose_candidate(cleaned):
        return False
    return bool(
        _category_for_name(cleaned, cleaned, institution_profile=institution_profile)
        or re.search(
            r"\b(?:accountancy|architecture|arts?|business|computing|communication|design|economics|education|engineering|humanities|law|medicine|psychology|science|sociology)\b",
            lower,
        )
        or re.match(r"^[A-Z][A-Za-z&/(),'+\- ]+$", cleaned)
    )


def _looks_like_faculty_or_school(value: str) -> bool:
    return bool(re.search(r"\b(?:faculty|school|college|academy|institute|department|centre|center)\b", value, flags=re.IGNORECASE))


def _faculty_from_values(
    values: list[str],
    *,
    institution_profile: InstitutionProfile | None,
    explicit_field: bool = False,
) -> str | None:
    for value in values:
        profile_label = profile_faculty_from_structured_label(institution_profile, value)
        if profile_label:
            return profile_label
        if _looks_like_faculty_or_school(value):
            return value
        if explicit_field and _clean(value):
            return _clean(value)
    return None


def _looks_like_longform_prose_candidate(line: str) -> bool:
    if "|" in line:
        return False
    lower = line.lower()
    if len(line) > 700:
        return True
    prose_markers = re.findall(
        r"\b(?:applicants?|curriculum|students?|graduates?|courses?|requirements?|admissions?|designed|provides?|offers?|learn|career)\b",
        lower,
    )
    return len(line) > 320 and len(prose_markers) >= 3


def _is_strict_paragraph_candidate(
    line: str,
    *,
    institution_profile: InstitutionProfile | None,
) -> bool:
    if not _extract_name(line, institution_profile=institution_profile):
        return False
    if extract_profile_programme_name(institution_profile, line):
        return True
    if re.match(
        r"^(?:Bachelor\b|BSc\b|BBA\b|BEng\b|Scholars Programme\b)",
        line,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(
        re.match(
            r"^(?:The\s+)?(?:School|Faculty|College|Academy|Institute|Department)\b.{0,120}\b"
            r"(?:offers?|provides?|lists?)\b.{0,160}\b(?:Bachelor|BSc|BBA|BEng|LLB|MBBS)\b",
            line,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_second_major_explainer(line: str) -> bool:
    if "|" in line:
        return False
    lower = line.lower()
    if not any(token in lower for token in ("second major", "second-major", "double major", "additional major")):
        return False
    explainer_markers = (
        "may",
        "can",
        "choose",
        "option",
        "available",
        "alongside",
        "in addition",
        "not a degree",
        "not an admission",
        "after admission",
        "students",
    )
    return any(marker in lower for marker in explainer_markers)


def _looks_like_admissions_explainer(line: str) -> bool:
    if "|" in line:
        return False
    return bool(
        re.search(
            r"\b(?:applicants?|students?)\b.{0,80}\b(?:apply|must|need|should|submit|are required)\b",
            line,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_course_table_candidate(line: str) -> bool:
    lower = line.lower()
    if "programme | degree" in lower or "program | degree" in lower:
        return False
    strong_table_headers = (
        "course code",
        "course title",
        "major pe courses",
        "pre-req",
        "pre req",
        "pre-requisite",
        "prerequisite",
        "open to",
    )
    header_hits = sum(1 for token in strong_table_headers if token in lower)
    if "major pe courses" in lower:
        return True
    if "course code" in lower and ("course title" in lower or "open to" in lower):
        return True
    if "open to" in lower and ("course" in lower or " au " in f" {lower} " or "pre-req" in lower):
        return True
    if header_hits >= 3:
        return True
    has_course_code = bool(re.search(r"\b[A-Z]{2,4}\d{4}[A-Z]?\b", line))
    if has_course_code and ("open to" in lower or " au " in f" {lower} " or "pre-req" in lower or "course title" in lower):
        return True
    return False


def _first_matching(values: list[str], predicate) -> str | None:
    for value in values:
        if predicate(value):
            return value
    return None


def _looks_like_award(value: str) -> bool:
    return bool(re.search(r"\b(?:Bachelor|BSc|BA|BEng|BBA|LLB|MBBS|Honours|Hons)\b", value, flags=re.IGNORECASE))


def _looks_like_unbounded_programme_card_cells(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False
    for value in cells[1:]:
        cleaned = _clean(value)
        if not _looks_like_award(cleaned):
            continue
        starts_with_award = bool(
            re.match(
                r"^(?:Bachelor(?:'s)?|BSc|BA|BEng|BBA|LLB|MBBS)\b",
                cleaned,
                flags=re.IGNORECASE,
            )
        )
        if not starts_with_award or _looks_like_sentence_like_candidate(cleaned):
            return True
    return False


def _looks_like_admissions_choice(value: str) -> bool:
    lower = value.lower()
    return any(token in lower for token in ("engineering", "business administration", "humanities", "common computer", "nus college"))


def _mode(value: str) -> str | None:
    lower = value.lower()
    if "full-time" in lower or "full time" in lower:
        return "full-time"
    if "part-time" in lower or "part time" in lower:
        return "part-time"
    return None


def _mode_from_values(values: list[str]) -> str | None:
    for value in values:
        mode = _mode(value)
        if mode:
            return mode
    return None


def _duration(value: str) -> str | None:
    match = re.search(r"((?:three|four|five|six|[0-9]+)[- ]year[^.;|]*|(?:at least\s+)?[0-9]{2,3}\s+units?[^.;|]*)", value, flags=re.IGNORECASE)
    if not match:
        return None
    return _clean(re.split(r",\s*(?:full-time|part-time)|\s+(?:full-time|part-time)\b", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0])


def _duration_from_values(values: list[str]) -> str | None:
    for value in values:
        duration = _duration(value)
        if duration:
            return duration
    return None


def _admissions_choice(line: str, name: str) -> str | None:
    match = re.search(r"(?:admissions? choice|choice|pathway)[:\s]+([A-Z][A-Za-z&/(),'\- ]{2,80})", line, flags=re.IGNORECASE)
    if match:
        return _clean_name(match.group(1))
    if "business administration" in name.lower():
        return "Business Administration"
    if "computing in computer science" in name.lower():
        return "Common Computer Science Programmes"
    if "engineering" in name.lower():
        return "Engineering"
    if "nus college" in name.lower():
        return "NUS College"
    return None


def _specialisations(line: str) -> list[str]:
    match = re.search(r"(?:including|majors? including|majors?[:\s]+|specialisations?[:\s]+)([A-Z][^.]+)", line, flags=re.IGNORECASE)
    if not match:
        return _parenthetical_specialisations(line)
    values = []
    for part in re.split(r",|;", match.group(1)):
        cleaned = re.sub(r"^\s*and\s+", "", _clean_name(part), flags=re.IGNORECASE)
        if cleaned and len(cleaned) > 2:
            values.append(cleaned)
    return values


def _parenthetical_specialisations(value: str) -> list[str]:
    match = re.search(r"\(([^)]*/[^)]*)\)", value)
    if not match:
        return []
    out: list[str] = []
    for part in match.group(1).split("/"):
        cleaned = _clean_name(part)
        if cleaned and len(cleaned) > 2:
            out.append(cleaned)
    return out
