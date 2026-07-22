"""Programme catalog extraction from public JSON/API sources."""

from __future__ import annotations

import json
import re
from typing import Any

from university_admissions_crawler.evidence.provenance import evidence_from_source
from university_admissions_crawler.extractor.schema import Confidence, EvidenceItem, ProgrammeCatalogRecord, SourceRecord, WarningCode, WarningRecord
from university_admissions_crawler.extractor.structured import PARSED


def extract_programme_catalog_api(
    text: str,
    source: SourceRecord,
    *,
    start_index: int = 0,
    base_path: str = "/programme_catalog",
    candidate_diagnostics: list[dict[str, object]] | None = None,
) -> list[tuple[ProgrammeCatalogRecord, list[EvidenceItem]]]:
    """Extract high-cardinality programme catalog rows from public JSON."""

    payload = _json_payload(text)
    if payload is None:
        return []

    rows: list[tuple[ProgrammeCatalogRecord, list[EvidenceItem]]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in _candidate_objects(payload):
        snippet = _snippet(item)
        parsed = _parse_catalog_object(item)
        if parsed is None:
            candidate_name = _clean_name(_first_value(item, _NAME_KEYS))
            _record_api_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=snippet,
                decision="rejected",
                reason=_api_candidate_rejection_reason(item),
                name=candidate_name,
            )
            continue
        if parsed.get("category") == "unknown":
            _record_api_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=snippet,
                decision="rejected",
                reason="ambiguous_api_programme_entity",
                name=_string_or_none(parsed.get("name")),
            )
            continue
        key = _row_key(parsed, source.source_url)
        if key in seen:
            _record_api_candidate_diagnostic(
                candidate_diagnostics,
                source=source,
                candidate=snippet,
                decision="rejected",
                reason="duplicate_api_programme_object",
                name=_string_or_none(parsed.get("name")),
            )
            continue
        seen.add(key)
        claim_path = f"{base_path}/{start_index + len(rows)}/name"
        parse_status = PARSED
        confidence = Confidence.HIGH
        warnings = _quality_warnings(parsed=parsed, claim_path=claim_path, source_url=source.source_url, parse_status=parse_status)
        row = ProgrammeCatalogRecord(
            name=str(parsed["name"]),
            faculty_or_school=_string_or_none(parsed.get("faculty_or_school")),
            degree_or_award=_string_or_none(parsed.get("degree_or_award")),
            category=str(parsed.get("category") or "unknown"),
            mode=_string_or_none(parsed.get("mode")),
            duration_or_units=_string_or_none(parsed.get("duration_or_units")),
            admissions_choice_name=_string_or_none(parsed.get("admissions_choice_name")),
            specialisations_or_majors=_string_list(parsed.get("specialisations_or_majors")),
            source_url=source.source_url,
            evidence_snippet=snippet,
            evidence_confidence=confidence,
            evidence_path=claim_path,
            parse_status=parse_status,
            warnings=warnings,
        )
        evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=confidence)
        rows.append((row, [evidence]))
        _record_api_candidate_diagnostic(
            candidate_diagnostics,
            source=source,
            candidate=snippet,
            decision="accepted",
            reason="accepted_parsed",
            name=row.name,
            category=row.category,
            claim_path=claim_path,
        )
    return rows


def _record_api_candidate_diagnostic(
    diagnostics: list[dict[str, object]] | None,
    *,
    source: SourceRecord,
    candidate: str,
    decision: str,
    reason: str,
    name: str | None = None,
    category: str | None = None,
    claim_path: str | None = None,
) -> None:
    if diagnostics is None:
        return
    item: dict[str, object] = {
        "source_url": source.source_url,
        "source_title": source.title,
        "candidate_text": candidate,
        "decision": decision,
        "reason": reason,
        "parser_stage": "api_entity_gate",
        "candidate_shape": "json_object",
        "block_kind": "json_object",
        "parser_branch": "json_object",
        "source_role": "canonical_catalog",
        "structural_anchor": "api_programme_name_field",
        "name_quality_passed": decision == "accepted",
        "institution_consistent": True,
    }
    if name:
        item["name"] = name
    if claim_path:
        item["claim_path"] = claim_path
    if decision == "accepted":
        if category:
            item["category"] = category
        item["parse_status"] = PARSED
    diagnostics.append(item)


def _api_candidate_rejection_reason(item: dict[str, Any]) -> str:
    text = _object_text(item)
    lower = text.lower()
    name = _clean_name(_first_value(item, _NAME_KEYS)) or ""
    if any(token in lower for token in ("@media", "stylesheet", "display:", "font-family")):
        return "css_or_template_text"
    if re.search(r"\b(?:course code|course title|curriculum|pre-?requisite|total\s+(?:no\.\s+of\s+)?aus?)\b", lower):
        return "course_or_curriculum_row"
    if _looks_like_filter_or_navigation(item, name):
        return "api_filter_or_navigation_object"
    if name and _looks_like_catalog_name(name):
        return "ambiguous_api_programme_entity"
    return "invalid_api_programme_object"


def programme_catalog_api_diagnostics(text: str, *, accepted_row_count: int) -> dict[str, object]:
    """Summarize API catalog extraction without creating admissions facts."""

    body_profile = catalog_api_body_profile(text)
    payload = _json_payload(text)
    if payload is None:
        return {
            "candidate_object_count": 0,
            "accepted_row_count": accepted_row_count,
            "rejected_row_count": 0,
            "api_total_count": None,
            "api_pagination_complete": False,
            "api_pagination_incomplete": False,
            **body_profile,
        }

    candidate_object_count = sum(1 for _item in _candidate_objects(payload))
    total_count = _find_total_count(payload)
    pagination_complete = total_count is not None and accepted_row_count >= total_count
    pagination_incomplete = total_count is not None and accepted_row_count < total_count
    return {
        "candidate_object_count": candidate_object_count,
        "accepted_row_count": accepted_row_count,
        "rejected_row_count": max(0, candidate_object_count - accepted_row_count),
        "api_total_count": total_count,
        "api_pagination_complete": pagination_complete,
        "api_pagination_incomplete": pagination_incomplete,
        **body_profile,
    }


def catalog_api_body_profile(text: str) -> dict[str, object]:
    """Classify whether a JSON response body looks like a programme catalog.

    This is a candidate/source diagnostic only.  It does not create admissions
    facts; row creation still goes through ``extract_programme_catalog_api``.
    """

    payload = _json_payload(text)
    if payload is None:
        return {
            "api_body_likely_catalog": False,
            "api_body_signals": [],
            "api_body_candidate_object_count": 0,
            "api_body_parseable_row_count": 0,
            "api_body_filter_keys": [],
            "api_body_sample_keys": [],
            "api_body_rejection_reason": "invalid_json",
        }

    candidate_objects = list(_candidate_objects(payload))
    parseable_row_count = sum(1 for item in candidate_objects if _parse_catalog_object(item) is not None)
    total_count = _find_total_count(payload)
    filter_keys = _filter_metadata_keys(payload)
    sample_keys = _sample_keys(payload)
    signals: list[str] = []
    if candidate_objects:
        signals.append("programme_like_object_keys")
    if parseable_row_count:
        signals.append("parseable_programme_rows")
    if total_count is not None:
        signals.append("pagination_total_count")
    if filter_keys:
        signals.append("catalog_filter_metadata")
    if _has_catalog_vocabulary(payload):
        signals.append("catalog_vocabulary")

    likely = bool(parseable_row_count) or bool(filter_keys and "catalog_vocabulary" in signals) or bool(
        candidate_objects and total_count is not None and "catalog_vocabulary" in signals
    )
    rejection_reason = None if likely else "body_not_catalog_like"
    return {
        "api_body_likely_catalog": likely,
        "api_body_signals": signals,
        "api_body_candidate_object_count": len(candidate_objects),
        "api_body_parseable_row_count": parseable_row_count,
        "api_body_filter_keys": filter_keys,
        "api_body_sample_keys": sample_keys,
        "api_body_rejection_reason": rejection_reason,
    }


def _json_payload(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _candidate_objects(value: Any):
    if isinstance(value, dict):
        if _has_programme_name_key(value):
            yield value
        for subvalue in value.values():
            yield from _candidate_objects(subvalue)
    elif isinstance(value, list):
        for subvalue in value:
            yield from _candidate_objects(subvalue)


def _parse_catalog_object(item: dict[str, Any]) -> dict[str, object] | None:
    name = _clean_name(_first_value(item, _NAME_KEYS))
    if not name or not _looks_like_catalog_name(name):
        return None
    context = _object_text(item)
    if not _has_catalog_signal(name, context):
        return None
    if _looks_like_filter_or_navigation(item, name):
        return None

    degree_or_award = _clean_text(_first_value(item, _DEGREE_KEYS)) or _degree_from_name(name)
    faculty_or_school = _clean_text(_first_value(item, _FACULTY_KEYS))
    category = _category_for_item(item, name=name, degree_or_award=degree_or_award)
    return {
        "name": name,
        "faculty_or_school": faculty_or_school,
        "degree_or_award": degree_or_award,
        "category": category,
        "mode": _mode(_first_value(item, _MODE_KEYS) or context),
        "duration_or_units": _clean_text(_first_value(item, _DURATION_KEYS)),
        "admissions_choice_name": _clean_text(_first_value(item, _ADMISSIONS_CHOICE_KEYS)),
        "specialisations_or_majors": _specialisations(item),
    }


def _has_programme_name_key(item: dict[str, Any]) -> bool:
    normalized = {_normalize_key(key) for key in item}
    return any(_normalize_key(key) in normalized for key in _NAME_KEYS)


def _first_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    normalized = {_normalize_key(key): value for key, value in item.items()}
    for key in keys:
        value = normalized.get(_normalize_key(key))
        if value not in (None, "", []):
            return value
    return None


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _clean_text(value: Any | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip(" \t\r\n-|")
    return cleaned or None


def _clean_name(value: Any | None) -> str | None:
    cleaned = _clean_text(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"\s+(?:requires?|needs?|must|is offered|are offered|leads to)\b.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.rstrip(".;:,")


def _looks_like_catalog_name(name: str) -> bool:
    if len(name) < 3 or len(name) > 160:
        return False
    lower = name.lower()
    if lower in {"all", "any", "undergraduate", "programme", "program", "degree", "filter", "search"}:
        return False
    if any(token in lower for token in ("select ", "view all", "read more", "find out", "apply now")):
        return False
    if len(re.findall(r"[.;:]", name)) > 3:
        return False
    return True


def _has_catalog_signal(name: str, context: str) -> bool:
    haystack = f"{name} {context}".lower()
    return bool(
        re.search(r"\b(?:undergraduate|bachelor|bsc|ba|beng|bba|llb|mbbs|degree|major|minor|programme|program|course)\b", haystack)
    )


def _looks_like_filter_or_navigation(item: dict[str, Any], name: str) -> bool:
    context = _object_text(item).lower()
    lower_name = name.lower()
    if lower_name in {"full-time", "part-time", "undergraduate", "postgraduate", "degree programme"}:
        return True
    return any(token in context for token in ("filteroption", "filter option", "navigation", "breadcrumb", "facet"))


def _object_text(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def _degree_from_name(name: str) -> str | None:
    if re.search(r"\b(?:Bachelor|BSc|BA|BEng|BBA|LLB|MBBS)\b", name, flags=re.IGNORECASE):
        return name
    return None


def _category_for_item(item: dict[str, Any], *, name: str, degree_or_award: str | None) -> str:
    context = " ".join(str(value) for value in item.values() if isinstance(value, (str, int, float)))
    lower = f"{name} {degree_or_award or ''} {context}".lower()
    if "minor" in lower:
        return "minor"
    if "major" in lower and "bachelor" not in lower:
        return "major"
    if "double degree" in lower or "dual degree" in lower:
        return "dual_degree"
    if "special programme" in lower:
        return "special_programme"
    if re.search(r"\b(?:bachelor|bsc|ba|beng|bba|llb|mbbs|degree)\b", lower):
        return "degree_programme"
    if "programme" in lower or "program" in lower:
        return "special_programme"
    return "unknown"


def _mode(value: Any | None) -> str | None:
    text = str(value or "").lower()
    if "full-time" in text or "full time" in text:
        return "full-time"
    if "part-time" in text or "part time" in text:
        return "part-time"
    return None


def _specialisations(item: dict[str, Any]) -> list[str]:
    value = _first_value(item, ("specialisations", "specializations", "majors", "specialisationsOrMajors", "specializationsOrMajors"))
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for part in value:
        cleaned = _clean_name(part)
        if cleaned and len(cleaned) > 2:
            out.append(cleaned)
    return out


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _snippet(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))[:700]


def _row_key(parsed: dict[str, object], source_url: str) -> tuple[str, str, str]:
    return (
        str(parsed.get("name", "")).casefold(),
        str(parsed.get("degree_or_award", "")).casefold(),
        source_url.casefold(),
    )


def _quality_warnings(*, parsed: dict[str, object], claim_path: str, source_url: str, parse_status: str) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    if not parsed.get("degree_or_award"):
        warnings.append(_row_warning("ambiguous_degree", "API programme row does not expose a stable degree or award.", claim_path, source_url))
    if not parsed.get("faculty_or_school"):
        warnings.append(_row_warning("missing_faculty", "API programme row does not expose a faculty or school.", claim_path, source_url))
    return warnings


def _row_warning(label: str, message: str, claim_path: str, source_url: str) -> WarningRecord:
    return WarningRecord(
        WarningCode.NEEDS_MANUAL_CHECK,
        f"{label}: {message}",
        field=claim_path,
        source_urls=[source_url],
    )


def _find_total_count(value: Any) -> int | None:
    if isinstance(value, dict):
        for key, subvalue in value.items():
            if _normalize_key(key) in {"total", "count", "totalcount", "recordstotal"} and isinstance(subvalue, int):
                return subvalue
        for subvalue in value.values():
            found = _find_total_count(subvalue)
            if found is not None:
                return found
    if isinstance(value, list):
        for subvalue in value:
            found = _find_total_count(subvalue)
            if found is not None:
                return found
    return None


def _filter_metadata_keys(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any, *, in_filter_container: bool = False) -> None:
        if isinstance(item, dict):
            for key, subvalue in item.items():
                normalised = _normalize_key(key)
                if normalised in {"filters", "facets", "filteroptions", "filtermetadata", "searchfilters"}:
                    visit(subvalue, in_filter_container=True)
                    continue
                if in_filter_container and normalised in _FILTER_METADATA_KEYS and isinstance(subvalue, (list, tuple, dict)):
                    found.add(key)
                visit(subvalue, in_filter_container=in_filter_container)
        elif isinstance(item, list):
            for subvalue in item:
                visit(subvalue, in_filter_container=in_filter_container)

    visit(value)
    return sorted(found, key=str.casefold)


def _sample_keys(value: Any, *, limit: int = 20) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def visit(item: Any) -> None:
        if len(found) >= limit:
            return
        if isinstance(item, dict):
            for key, subvalue in item.items():
                if key not in seen:
                    seen.add(key)
                    found.append(str(key))
                    if len(found) >= limit:
                        return
                visit(subvalue)
                if len(found) >= limit:
                    return
        elif isinstance(item, list):
            for subvalue in item:
                visit(subvalue)
                if len(found) >= limit:
                    return

    visit(value)
    return found


def _has_catalog_vocabulary(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False)[:12000].lower()
    return bool(
        re.search(
            r"\b(?:undergraduate|bachelor|bsc|ba|beng|bba|llb|mbbs|degree|programme|program|major|minor|faculty|school)\b",
            text,
        )
    )


_NAME_KEYS = (
    "name",
    "title",
    "programme",
    "program",
    "programmeName",
    "programName",
    "courseTitle",
    "degreeTitle",
)
_DEGREE_KEYS = ("degree", "award", "qualification", "degreeTitle", "awardName", "degree_or_award")
_FACULTY_KEYS = ("faculty", "school", "college", "department", "schoolName", "facultyOrSchool", "faculty_or_school")
_MODE_KEYS = ("mode", "studyMode", "attendance", "fullTimePartTime")
_DURATION_KEYS = ("duration", "studyPeriod", "durationOrUnits", "units", "credits")
_ADMISSIONS_CHOICE_KEYS = ("choice", "admissionChoice", "admissionsChoice", "jupasCode", "applicationCode", "code")
_FILTER_METADATA_KEYS = {
    "level",
    "programmetype",
    "studytype",
    "studymode",
    "mode",
    "faculty",
    "school",
    "college",
    "department",
    "degree",
    "award",
    "category",
}
