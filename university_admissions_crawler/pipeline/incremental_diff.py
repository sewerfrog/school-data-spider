"""Incremental diff diagnostics for repeated scans."""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Callable
from typing import Any

from university_admissions_crawler.extractor.normalizer import add_warning
from university_admissions_crawler.extractor.schema import AdmissionsData, WarningCode, WarningRecord


_CATALOG_SEMANTIC_FIELDS = (
    "name",
    "degree_or_award",
    "faculty_or_school",
    "category",
    "mode",
    "duration_or_units",
    "admissions_choice_name",
    "specialisations_or_majors",
)
_MAX_FIELD_CHANGE_WARNINGS = 20
_REQUIREMENT_COLLECTIONS = (
    (
        "admissions.international_requirements",
        ("admissions", "international_requirements"),
        "/admissions/international_requirements",
    ),
    (
        "admissions.accepted_qualifications",
        ("admissions", "accepted_qualifications"),
        "/admissions/accepted_qualifications",
    ),
    (
        "admissions.application_periods",
        ("admissions", "application_periods"),
        "/admissions/application_periods",
    ),
    (
        "admissions.required_documents",
        ("admissions", "required_documents"),
        "/admissions/required_documents",
    ),
    (
        "admissions.english_requirements",
        ("admissions", "english_requirements"),
        "/admissions/english_requirements",
    ),
    (
        "admissions.standardized_tests",
        ("admissions", "standardized_tests"),
        "/admissions/standardized_tests",
    ),
    (
        "admissions.selection_tests_or_interviews",
        ("admissions", "selection_tests_or_interviews"),
        "/admissions/selection_tests_or_interviews",
    ),
    ("fees", ("fees",), "/fees"),
    ("scholarships", ("scholarships",), "/scholarships"),
    ("visa", ("visa",), "/visa"),
    ("housing", ("housing",), "/housing"),
    ("contacts", ("contacts",), "/contacts"),
)


def apply_incremental_diff(data: AdmissionsData, previous_result: dict[str, Any] | None) -> None:
    current_result = data.to_dict()
    if previous_result is None:
        data.warnings.append(WarningRecord(WarningCode.NEEDS_MANUAL_CHECK, "No prior result supplied; incremental diff baseline is unavailable.", field="/run/diff"))
        data.run.config["diff"] = {
            "baseline": "none",
            "changed_sources": [],
            "changed_fields": [],
            "field_warning_policy": _unavailable_field_warning_policy(),
            "source_mix": _unavailable_collection_diff(len(data.sources)),
            "programme_catalog": _unavailable_collection_diff(len(data.programme_catalog)),
            "legacy_programmes": _unavailable_collection_diff(len(data.programmes)),
            "structured_collections": _unavailable_structured_collection_diffs(current_result),
            "assessment": {
                "source_mix_changed": None,
                "authoritative_catalog_stable": None,
                "authoritative_catalog_gain": None,
                "authoritative_catalog_regression": None,
                "legacy_programmes_stable": None,
                "structured_collections_stable": None,
                "source_mix_only_change": None,
            },
        }
        return

    previous_hashes = {
        source.get("source_url"): source.get("content_hash")
        for source in _dict_items(previous_result.get("sources"))
        if isinstance(source.get("source_url"), str)
    }
    changed_sources: list[str] = []
    for source in data.sources:
        old_hash = previous_hashes.get(source.source_url)
        if old_hash is not None and old_hash != source.content_hash:
            changed_sources.append(source.source_url)
    current_fields = _field_snapshot(current_result)
    previous_fields = _field_snapshot(previous_result)
    changed_fields = sorted(path for path, value in current_fields.items() if path in previous_fields and previous_fields[path] != value)
    source_mix = _source_mix_diff(current_result.get("sources"), previous_result.get("sources"))
    programme_catalog = _programme_catalog_diff(
        current_result.get("programme_catalog"),
        previous_result.get("programme_catalog"),
    )
    legacy_programmes = _legacy_programmes_diff(
        current_result.get("programmes"),
        previous_result.get("programmes"),
    )
    structured_collections = _structured_collection_diffs(current_result, previous_result)
    field_warning_policy, stable_warning_paths = _field_warning_policy(
        changed_fields,
        legacy_programmes,
        structured_collections,
    )
    structured_collections_stable = all(
        bool(collection["stable"])
        for collection in structured_collections.values()
    )
    authoritative_gain = bool(
        programme_catalog["added_count"]
        or programme_catalog["gained_field_count"]
    )
    authoritative_regression = bool(
        programme_catalog["removed_count"]
        or programme_catalog["lost_field_count"]
    )
    data.run.config["diff"] = {
        "baseline": "provided",
        "changed_sources": sorted(changed_sources),
        "changed_fields": changed_fields,
        "field_warning_policy": field_warning_policy,
        "source_mix": source_mix,
        "programme_catalog": programme_catalog,
        "legacy_programmes": legacy_programmes,
        "structured_collections": structured_collections,
        "assessment": {
            "source_mix_changed": not source_mix["stable"],
            "authoritative_catalog_stable": programme_catalog["stable"],
            "authoritative_catalog_gain": authoritative_gain,
            "authoritative_catalog_regression": authoritative_regression,
            "legacy_programmes_stable": legacy_programmes["stable"],
            "structured_collections_stable": structured_collections_stable,
            "source_mix_only_change": bool(
                not source_mix["stable"]
                and programme_catalog["stable"]
                and legacy_programmes["stable"]
                and structured_collections_stable
            ),
        },
    }
    for url in changed_sources:
        add_warning(data, WarningRecord(WarningCode.INCREMENTAL_CHANGE, "Source content hash changed since previous result.", field=url, source_urls=[url]))
    for path in stable_warning_paths:
        add_warning(data, WarningRecord(WarningCode.INCREMENTAL_CHANGE, "Extracted field value changed since previous result.", field=path))
    if field_warning_policy["legacy_semantic_warning_emitted"]:
        add_warning(
            data,
            WarningRecord(
                WarningCode.INCREMENTAL_CHANGE,
                "Compatibility programme collection changed since previous result: "
                f"{legacy_programmes['added_count']} added, "
                f"{legacy_programmes['removed_count']} removed, "
                f"{legacy_programmes['changed_row_count']} changed rows.",
                field="/programmes",
            ),
        )
    structured_by_field = {
        str(collection["field"]): collection
        for collection in structured_collections.values()
    }
    for field in field_warning_policy["structured_semantic_warning_fields"]:
        collection = structured_by_field[str(field)]
        add_warning(
            data,
            WarningRecord(
                WarningCode.INCREMENTAL_CHANGE,
                "Structured collection changed since previous result: "
                f"{collection['added_count']} added, "
                f"{collection['removed_count']} removed, "
                f"{collection['changed_row_count']} changed rows.",
                field=str(field),
            ),
        )


def _field_warning_policy(
    changed_fields: list[str],
    legacy_programmes: dict[str, object],
    structured_collections: dict[str, dict[str, object]],
) -> tuple[dict[str, object], list[str]]:
    legacy_index_paths = [path for path in changed_fields if _is_legacy_programme_index_path(path)]
    structured_index_paths = [
        path
        for path in changed_fields
        if _structured_collection_field_for_index_path(path) is not None
    ]
    stable_paths = [
        path
        for path in changed_fields
        if not _is_legacy_programme_index_path(path)
        and _structured_collection_field_for_index_path(path) is None
    ]
    stable_warning_paths = stable_paths[:_MAX_FIELD_CHANGE_WARNINGS]
    semantic_warning_emitted = not bool(legacy_programmes["stable"])
    structured_semantic_warning_fields = [
        str(collection["field"])
        for collection in structured_collections.values()
        if not collection["stable"]
    ]
    policy: dict[str, object] = {
        "strategy": "stable-semantic-v3",
        "raw_changed_field_count": len(changed_fields),
        "stable_path_count": len(stable_paths),
        "stable_path_warning_count": len(stable_warning_paths),
        "stable_path_warning_truncated_count": len(stable_paths) - len(stable_warning_paths),
        "legacy_index_path_count": len(legacy_index_paths),
        "legacy_index_warnings_suppressed": len(legacy_index_paths),
        "legacy_semantic_warning_emitted": semantic_warning_emitted,
        "structured_index_path_count": len(structured_index_paths),
        "structured_index_warnings_suppressed": len(structured_index_paths),
        "structured_semantic_warning_count": len(structured_semantic_warning_fields),
        "structured_semantic_warning_fields": structured_semantic_warning_fields,
        "emitted_warning_count": (
            len(stable_warning_paths)
            + int(semantic_warning_emitted)
            + len(structured_semantic_warning_fields)
        ),
    }
    return policy, stable_warning_paths


def _is_legacy_programme_index_path(path: str) -> bool:
    parts = path.strip("/").split("/")
    return len(parts) >= 3 and parts[0] == "programmes" and parts[1].isdigit()


def _structured_collection_field_for_index_path(path: str) -> str | None:
    parts = path.strip("/").split("/")
    for _name, collection_parts, field in _REQUIREMENT_COLLECTIONS:
        collection_length = len(collection_parts)
        if (
            tuple(parts[:collection_length]) == collection_parts
            and len(parts) > collection_length
            and parts[collection_length].isdigit()
        ):
            return field
    return None


def _source_mix_diff(current_sources: object, previous_sources: object) -> dict[str, object]:
    current_records = _dict_items(current_sources)
    previous_records = _dict_items(previous_sources)
    current_urls = _source_urls(current_sources)
    previous_urls = _source_urls(previous_sources)
    added_urls = sorted(current_urls - previous_urls)
    removed_urls = sorted(previous_urls - current_urls)
    return {
        "baseline_available": True,
        "baseline_record_count": len(previous_records),
        "current_record_count": len(current_records),
        "baseline_count": len(previous_urls),
        "current_count": len(current_urls),
        "retained_count": len(current_urls & previous_urls),
        "added_count": len(added_urls),
        "removed_count": len(removed_urls),
        "symmetric_difference_count": len(added_urls) + len(removed_urls),
        "added_urls": added_urls,
        "removed_urls": removed_urls,
        "stable": not added_urls and not removed_urls,
    }


def _programme_catalog_diff(current_rows: object, previous_rows: object) -> dict[str, object]:
    current = _dict_items(current_rows)
    previous = _dict_items(previous_rows)
    duplicate_names = _duplicate_identities(current, previous, _catalog_name_identity)
    current_index = _semantic_index(
        current,
        identity=lambda row: _catalog_identity(row, duplicate_names),
        semantic=_catalog_semantic_row,
    )
    previous_index = _semantic_index(
        previous,
        identity=lambda row: _catalog_identity(row, duplicate_names),
        semantic=_catalog_semantic_row,
    )
    return _semantic_diff(current_index, previous_index)


def _legacy_programmes_diff(current_rows: object, previous_rows: object) -> dict[str, object]:
    current = _dict_items(current_rows)
    previous = _dict_items(previous_rows)
    duplicate_names = _duplicate_identities(current, previous, _legacy_name_identity)
    current_index = _semantic_index(
        current,
        identity=lambda row: _legacy_identity(row, duplicate_names),
        semantic=_legacy_semantic_row,
    )
    previous_index = _semantic_index(
        previous,
        identity=lambda row: _legacy_identity(row, duplicate_names),
        semantic=_legacy_semantic_row,
    )
    return _semantic_diff(current_index, previous_index)


def _structured_collection_diffs(
    current_result: dict[str, Any],
    previous_result: dict[str, Any],
) -> dict[str, dict[str, object]]:
    diffs: dict[str, dict[str, object]] = {}
    for name, path, field in _REQUIREMENT_COLLECTIONS:
        collection_diff = _requirement_collection_diff(
            _nested_value(current_result, path),
            _nested_value(previous_result, path),
        )
        diffs[name] = {"field": field, **collection_diff}
    return diffs


def _requirement_collection_diff(current_rows: object, previous_rows: object) -> dict[str, object]:
    current = _dict_items(current_rows)
    previous = _dict_items(previous_rows)
    duplicate_labels = _duplicate_identities(current, previous, _requirement_label_identity)
    current_index = _semantic_index(
        current,
        identity=lambda row: _requirement_identity(row, duplicate_labels),
        semantic=_requirement_semantic_row,
    )
    previous_index = _semantic_index(
        previous,
        identity=lambda row: _requirement_identity(row, duplicate_labels),
        semantic=_requirement_semantic_row,
    )
    return _semantic_diff(current_index, previous_index)


def _semantic_diff(
    current: dict[str, dict[str, object]],
    previous: dict[str, dict[str, object]],
) -> dict[str, object]:
    current_keys = set(current)
    previous_keys = set(previous)
    added = [_identity_summary(identity, current[identity]) for identity in sorted(current_keys - previous_keys)]
    removed = [_identity_summary(identity, previous[identity]) for identity in sorted(previous_keys - current_keys)]
    field_changes: list[dict[str, object]] = []
    gained_field_count = 0
    lost_field_count = 0
    changed_field_count = 0
    for identity in sorted(current_keys & previous_keys):
        gained: dict[str, object] = {}
        lost: dict[str, object] = {}
        changed: dict[str, dict[str, object]] = {}
        current_row = current[identity]
        previous_row = previous[identity]
        for field_name in sorted(set(current_row) | set(previous_row)):
            before = previous_row.get(field_name)
            after = current_row.get(field_name)
            if before == after:
                continue
            if _is_missing(before) and not _is_missing(after):
                gained[field_name] = after
            elif not _is_missing(before) and _is_missing(after):
                lost[field_name] = before
            else:
                changed[field_name] = {"before": before, "after": after}
        if not gained and not lost and not changed:
            continue
        gained_field_count += len(gained)
        lost_field_count += len(lost)
        changed_field_count += len(changed)
        field_changes.append(
            {
                "identity": identity,
                "name": current_row.get("name") or previous_row.get("name"),
                "gained": gained,
                "lost": lost,
                "changed": changed,
            }
        )
    stable = not added and not removed and not field_changes
    return {
        "baseline_available": True,
        "baseline_count": len(previous),
        "current_count": len(current),
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_row_count": len(field_changes),
        "gained_field_count": gained_field_count,
        "lost_field_count": lost_field_count,
        "changed_field_count": changed_field_count,
        "added": added,
        "removed": removed,
        "field_changes": field_changes,
        "stable": stable,
    }


def _semantic_index(
    rows: list[dict[str, Any]],
    *,
    identity: Callable[[dict[str, Any]], str],
    semantic: Callable[[dict[str, Any]], dict[str, object]],
) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    occurrences: Counter[str] = Counter()
    prepared = sorted(
        ((identity(row), semantic(row)) for row in rows),
        key=lambda item: (item[0], repr(item[1])),
    )
    for base_identity, semantic_row in prepared:
        occurrences[base_identity] += 1
        occurrence = occurrences[base_identity]
        stable_identity = base_identity if occurrence == 1 else f"{base_identity} #{occurrence}"
        indexed[stable_identity] = semantic_row
    return indexed


def _catalog_identity(row: dict[str, Any], duplicate_names: set[str]) -> str:
    name = _catalog_name_identity(row) or "unnamed"
    if name not in duplicate_names:
        return name
    award = _normalise_identity(row.get("degree_or_award")) or "unknown"
    category = _normalise_identity(row.get("category")) or "unknown"
    return f"{name} | award={award} | category={category}"


def _legacy_identity(row: dict[str, Any], duplicate_names: set[str]) -> str:
    name = _legacy_name_identity(row) or "unnamed"
    if name not in duplicate_names:
        return name
    source_url = _clean_scalar(row.get("source_url")) or "unknown"
    return f"{name} | source={source_url}"


def _requirement_identity(row: dict[str, Any], duplicate_labels: set[str]) -> str:
    label = _requirement_label_identity(row) or "unnamed"
    if label not in duplicate_labels:
        return label
    value = _normalise_identity(_field_value(row.get("value"))) or "unknown"
    applicant_group = _normalise_identity(_field_value(row.get("applicant_group"))) or "unknown"
    qualification = _normalise_identity(_field_value(row.get("qualification"))) or "unknown"
    return (
        f"{label} | value={value} | applicant_group={applicant_group} | "
        f"qualification={qualification}"
    )


def _catalog_semantic_row(row: dict[str, Any]) -> dict[str, object]:
    semantic: dict[str, object] = {}
    for field_name in _CATALOG_SEMANTIC_FIELDS:
        value = row.get(field_name)
        if field_name == "specialisations_or_majors":
            semantic[field_name] = (
                sorted(_clean_scalar(item) for item in value if _clean_scalar(item))
                if isinstance(value, list)
                else []
            )
        else:
            semantic[field_name] = _clean_scalar(value)
    return semantic


def _legacy_semantic_row(row: dict[str, Any]) -> dict[str, object]:
    prerequisites: list[dict[str, object]] = []
    for item in _dict_items(row.get("prerequisites")):
        prerequisites.append(
            {
                "label": _clean_scalar(item.get("label")),
                "value": _field_value(item.get("value")),
            }
        )
    return {
        "name": _field_value(row.get("name")),
        "degree": _field_value(row.get("degree")),
        "faculty_or_school": _field_value(row.get("faculty_or_school")),
        "source_url": _clean_scalar(row.get("source_url")),
        "prerequisites": sorted(prerequisites, key=repr),
    }


def _requirement_semantic_row(row: dict[str, Any]) -> dict[str, object]:
    return {
        "label": _clean_scalar(row.get("label")),
        "value": _field_value(row.get("value")),
        "applicant_group": _field_value(row.get("applicant_group")),
        "qualification": _field_value(row.get("qualification")),
        "requires_applicant_group": bool(row.get("requires_applicant_group")),
    }


def _identity_summary(identity: str, row: dict[str, object]) -> dict[str, object]:
    return {
        "identity": identity,
        "name": row.get("name") or row.get("label"),
    }


def _duplicate_identities(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    identity: Callable[[dict[str, Any]], str],
) -> set[str]:
    duplicate_keys: set[str] = set()
    for rows in (current, previous):
        counts = Counter(identity(row) for row in rows)
        duplicate_keys.update(key for key, count in counts.items() if key and count > 1)
    return duplicate_keys


def _catalog_name_identity(row: dict[str, Any]) -> str:
    return _normalise_identity(row.get("name"))


def _legacy_name_identity(row: dict[str, Any]) -> str:
    return _normalise_identity(_field_value(row.get("name")))


def _requirement_label_identity(row: dict[str, Any]) -> str:
    return _normalise_identity(row.get("label"))


def _normalise_identity(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    tokens: list[str] = []
    current: list[str] = []
    for char in normalized:
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return " ".join(tokens)


def _field_value(value: object) -> object:
    if not isinstance(value, dict):
        return _clean_scalar(value)
    raw_value = value.get("value")
    if value.get("status") == "unknown" or raw_value == "unknown":
        return None
    return _clean_scalar(raw_value)


def _clean_scalar(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = " ".join(value.split())
        return cleaned or None
    return value


def _is_missing(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _source_urls(sources: object) -> set[str]:
    return {
        str(source["source_url"])
        for source in _dict_items(sources)
        if isinstance(source.get("source_url"), str) and source["source_url"]
    }


def _dict_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _nested_value(value: object, path: tuple[str, ...]) -> object:
    current = value
    for part in path:
        if not isinstance(current, dict):
            return []
        current = current.get(part)
    return current


def _unavailable_collection_diff(current_count: int) -> dict[str, object]:
    return {
        "baseline_available": False,
        "baseline_count": None,
        "current_count": current_count,
        "stable": None,
    }


def _unavailable_structured_collection_diffs(
    current_result: dict[str, Any],
) -> dict[str, dict[str, object]]:
    return {
        name: {
            "field": field,
            **_unavailable_collection_diff(
                len(_dict_items(_nested_value(current_result, path)))
            ),
        }
        for name, path, field in _REQUIREMENT_COLLECTIONS
    }


def _unavailable_field_warning_policy() -> dict[str, object]:
    return {
        "strategy": "stable-semantic-v3",
        "raw_changed_field_count": 0,
        "stable_path_count": 0,
        "stable_path_warning_count": 0,
        "stable_path_warning_truncated_count": 0,
        "legacy_index_path_count": 0,
        "legacy_index_warnings_suppressed": 0,
        "legacy_semantic_warning_emitted": False,
        "structured_index_path_count": 0,
        "structured_index_warnings_suppressed": 0,
        "structured_semantic_warning_count": 0,
        "structured_semantic_warning_fields": [],
        "emitted_warning_count": 0,
    }


def _field_snapshot(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        if set(value.keys()) >= {"value", "status", "confidence"}:
            out[prefix] = value.get("value")
            return out
        for key, subvalue in value.items():
            if key in {"sources", "evidence", "warnings", "run"}:
                continue
            out.update(_field_snapshot(subvalue, f"{prefix}/{key}"))
    elif isinstance(value, list):
        for index, subvalue in enumerate(value):
            out.update(_field_snapshot(subvalue, f"{prefix}/{index}"))
    return out
