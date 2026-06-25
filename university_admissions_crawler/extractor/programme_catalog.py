"""Conservative programme catalog extraction.

This parser owns high-cardinality programme table rows separately from the
legacy admissions-summary ``extract_programmes`` regex path.
"""

from __future__ import annotations

import re

from university_admissions_crawler.evidence.provenance import evidence_from_source
from university_admissions_crawler.extractor.llm_provider import ProgrammeCatalogAssistProvider, generate_programme_catalog_classification_hint
from university_admissions_crawler.extractor.schema import Confidence, EvidenceItem, ProgrammeCatalogRecord, SourceRecord, WarningCode, WarningRecord
from university_admissions_crawler.extractor.structured import PARSED, RAW_NEEDS_REVIEW


def extract_programme_catalog(
    text: str,
    source: SourceRecord,
    *,
    start_index: int = 0,
    base_path: str = "/programme_catalog",
    assist_provider: ProgrammeCatalogAssistProvider | None = None,
) -> list[tuple[ProgrammeCatalogRecord, list[EvidenceItem]]]:
    """Extract evidence-backed programme catalog rows from structured text.

    The first implementation is intentionally conservative: it requires source
    context that looks like an undergraduate programme/catalog page and only
    emits rows with a source URL, snippet, and claim path.  Ambiguous but useful
    rows are retained with ``raw_needs_manual_review`` and a row-level warning.
    """

    if not _looks_like_programme_catalog_source(text, source):
        return []

    rows: list[tuple[ProgrammeCatalogRecord, list[EvidenceItem]]] = []
    seen: dict[tuple[str, str, str, str], int] = {}
    faculty_hint = _faculty_hint(text, source)
    for candidate in _candidate_lines(text):
        parsed = _parse_candidate(candidate, faculty_hint=faculty_hint, allow_unknown_category=assist_provider is not None)
        if parsed is None:
            continue
        claim_path = f"{base_path}/{start_index + len(rows)}/name"
        snippet = _snippet(candidate)
        if assist_provider is not None:
            _apply_programme_catalog_hint(parsed=parsed, candidate=candidate, source=source, provider=assist_provider)
        if parsed.get("_requires_category_hint") and parsed.get("category") == "unknown":
            continue
        faculty_or_school = _string_or_none(parsed.get("faculty_or_school") or faculty_hint)
        degree_or_award = _string_or_none(parsed.get("degree_or_award"))
        parse_status = PARSED if _is_confident_row(parsed) else RAW_NEEDS_REVIEW
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
        evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=confidence)
        rows.append((row, [evidence]))
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


def _candidate_lines(text: str) -> list[str]:
    normalised = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    normalised = re.sub(r"</(?:li|tr|p|h[1-6]|div|section)>", "\n", normalised, flags=re.IGNORECASE)
    normalised = re.sub(r"<[^>]+>", " ", normalised)
    out: list[str] = []
    for line in re.split(r"[\n\r]+", normalised):
        cleaned = _clean(line)
        if not cleaned:
            continue
        if "|" in cleaned:
            cells = [_clean(part) for part in cleaned.split("|") if _clean(part)]
            if len(cells) >= 2 and _is_table_header(cells):
                continue
            if cells:
                out.append(" | ".join(cells))
                continue
        for sentence in re.split(r"(?<=[.;])\s+", cleaned):
            sentence = _clean(sentence)
            if sentence:
                out.append(sentence)
    return out


def _parse_candidate(line: str, *, faculty_hint: str | None, allow_unknown_category: bool = False) -> dict[str, object] | None:
    specialisations = _specialisations(line)
    labelled = _parse_labelled_catalog_candidate(line)
    if labelled:
        if not labelled.get("faculty_or_school"):
            labelled["faculty_or_school"] = faculty_hint
        if specialisations and not labelled.get("specialisations_or_majors"):
            labelled["specialisations_or_majors"] = specialisations
        return labelled

    cells = [_clean(part) for part in line.split("|")] if "|" in line else []
    if len(cells) >= 2:
        parsed = _parse_table_candidate(cells)
        if parsed:
            if not parsed.get("faculty_or_school"):
                parsed["faculty_or_school"] = faculty_hint
            if specialisations and not parsed.get("specialisations_or_majors"):
                parsed["specialisations_or_majors"] = specialisations
            return parsed

    name = _extract_name(line)
    if not name:
        return None
    category = _category_for_name(name, line)
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
        "_category_inferred": True,
        "_requires_category_hint": category == "unknown",
    }
    return parsed


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


def _parse_table_candidate(cells: list[str]) -> dict[str, object] | None:
    listed = _parse_award_listing_candidate(cells[0])
    if listed:
        remaining = cells[1:]
        listed["mode"] = listed.get("mode") or _mode_from_values(remaining)
        listed["duration_or_units"] = listed.get("duration_or_units") or _duration_from_values(remaining)
        return listed

    name = next((cell for cell in cells if _category_for_name(cell, cell)), "")
    if not name:
        return None
    category = _category_for_name(name, " | ".join(cells))
    if category is None:
        return None
    remaining = [cell for cell in cells if cell != name]
    return {
        "name": name,
        "degree_or_award": _first_matching(remaining, _looks_like_award) or _degree_for_name(name, " | ".join(cells), category),
        "category": category,
        "mode": _mode_from_values(remaining),
        "duration_or_units": _duration_from_values(remaining),
        "admissions_choice_name": _first_matching(remaining, _looks_like_admissions_choice),
        "specialisations_or_majors": [],
        "_category_inferred": False,
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


def _extract_name(line: str) -> str | None:
    patterns = (
        r"\b(Bachelor\s+of\s+[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b(Bachelor\s+in\s+[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b(BSc\s*\(Hons\)\s+Major:\s*[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b(BBA\s+Major:\s*[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b((?:CHS|FASS)\s+(?:Primary\s+)?Major:\s*[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b(Scholars Programme)(?=\s|$|[.;,])",
        r"\b((?:NUS\s+College|Special Programme in Science(?:\s+\(SPS\))?|Engineering Scholars Programme(?:\s+\(E-Scholars\))?))(?=\s|$|[.;,])",
    )
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            return _clean_name(match.group(1))
    return None


def _category_for_name(name: str, context: str) -> str | None:
    lower = f"{name} {context}".lower()
    if "major:" in lower or "primary major" in lower:
        return "major"
    if "minor:" in lower:
        return "minor"
    if "special programme" in lower or "nus college" in lower or "e-scholars" in lower:
        return "special_programme"
    if "bachelor" in lower or re.search(r"\b(?:bsc|ba|beng|bba|llb|mbbs)\b", lower):
        return "degree_programme"
    return None


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


def _faculty_hint(text: str, source: SourceRecord) -> str | None:
    haystack = f"{source.title or ''} {source.source_url} {text[:500]}".lower()
    known = (
        ("NUS Business School", ("business school", "school-of-business")),
        ("School of Computing", ("school of computing", "school-of-computing")),
        ("College of Design and Engineering", ("college of design and engineering", "design and engineering", "college-of-design-and-engineering")),
        ("College of Humanities and Sciences", ("college of humanities and sciences", "chs.nus.edu.sg")),
        ("Faculty of Science", ("faculty of science", "faculty-of-science")),
    )
    for label, needles in known:
        if any(needle in haystack for needle in needles):
            return label
    return None


def _is_confident_row(parsed: dict[str, object]) -> bool:
    return bool(parsed.get("name") and parsed.get("category") != "unknown" and parsed.get("degree_or_award"))


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
    joined = " ".join(cells).lower()
    return "programme" in joined and "degree" in joined and not any(_category_for_name(cell, cell) for cell in cells)


def _first_matching(values: list[str], predicate) -> str | None:
    for value in values:
        if predicate(value):
            return value
    return None


def _looks_like_award(value: str) -> bool:
    return bool(re.search(r"\b(?:Bachelor|BSc|BA|BEng|BBA|LLB|MBBS|Honours|Hons)\b", value, flags=re.IGNORECASE))


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
