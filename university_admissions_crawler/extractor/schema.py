"""Schema and validation models for evidence-first admissions extraction.

The first implementation intentionally uses stdlib dataclasses plus explicit
validators so the deterministic core has no runtime dependency on optional
provider/browser packages.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, fields as dataclass_fields, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable


class SourceType(StrEnum):
    HTML = "html"
    PDF = "pdf"
    JSON = "json"
    OTHER = "other"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ClaimStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NEEDS_MANUAL_CHECK = "needs_manual_check"


class PageCategory(StrEnum):
    UNDERGRADUATE_ADMISSIONS = "undergraduate_admissions"
    INTERNATIONAL_REQUIREMENTS = "international_requirements"
    APPLICATION_DEADLINES = "application_deadlines"
    ACCEPTED_QUALIFICATIONS = "accepted_qualifications"
    PROGRAMME_LIST = "programme_list"
    PROGRAMME_PREREQUISITES = "programme_prerequisites"
    FEES = "fees"
    SCHOLARSHIPS = "scholarships"
    VISA = "visa"
    HOUSING = "housing"
    CONTACT = "contact"
    IRRELEVANT = "irrelevant"


class WarningCode(StrEnum):
    STALE_PAGE = "stale_page"
    CONFLICT = "conflict"
    MISSING_EVIDENCE = "missing_evidence"
    NEEDS_MANUAL_CHECK = "needs_manual_check"
    NON_OFFICIAL_SOURCE = "non_official_source"
    AMBIGUOUS_APPLICANT_GROUP = "ambiguous_applicant_group"
    FETCH_FAILED = "fetch_failed"
    PARSE_FAILED = "parse_failed"
    PDF_UNAVAILABLE = "pdf_unavailable"
    PDF_PARSE_FAILED = "pdf_parse_failed"
    OPTIONAL_DEPENDENCY_MISSING = "optional_dependency_missing"
    LLM_UNSUPPORTED_CLAIM = "llm_unsupported_claim"
    INCREMENTAL_CHANGE = "incremental_change"


UNKNOWN = ClaimStatus.UNKNOWN
NEEDS_MANUAL_CHECK = ClaimStatus.NEEDS_MANUAL_CHECK


@dataclass(slots=True)
class WarningRecord:
    code: WarningCode
    message: str
    field: str | None = None
    source_urls: list[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class SourceRecord:
    source_url: str
    source_type: SourceType = SourceType.HTML
    title: str | None = None
    retrieved_at: str = dc_field(default_factory=lambda: datetime.now(UTC).isoformat())
    academic_year: str | None = None
    page_number: int | None = None
    content_hash: str | None = None
    engine: str | None = None
    is_official: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class EvidenceItem:
    claim_path: str
    source_url: str
    snippet: str
    source_type: SourceType = SourceType.HTML
    title: str | None = None
    retrieved_at: str = dc_field(default_factory=lambda: datetime.now(UTC).isoformat())
    academic_year: str | None = None
    page_number: int | None = None
    confidence: Confidence = Confidence.MEDIUM
    warnings: list[WarningRecord] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class FieldValue:
    """A scalar/list/dict claim with explicit evidence linkage."""

    value: Any = UNKNOWN
    raw_text: str | None = None
    parsed: Any = None
    parse_status: str = "unparsed"
    evidence: list[str] = dc_field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    status: ClaimStatus = ClaimStatus.UNKNOWN
    warnings: list[WarningRecord] = dc_field(default_factory=list)

    @classmethod
    def unknown(cls, message: str | None = None, field_path: str | None = None) -> "FieldValue":
        warnings: list[WarningRecord] = []
        if message:
            warnings.append(
                WarningRecord(
                    WarningCode.NEEDS_MANUAL_CHECK,
                    message,
                    field=field_path,
                )
            )
        return cls(value=str(UNKNOWN), status=ClaimStatus.UNKNOWN, warnings=warnings)

    @classmethod
    def manual_check(cls, message: str, field_path: str | None = None, value: Any = NEEDS_MANUAL_CHECK) -> "FieldValue":
        return cls(
            value=value,
            status=ClaimStatus.NEEDS_MANUAL_CHECK,
            warnings=[WarningRecord(WarningCode.NEEDS_MANUAL_CHECK, message, field=field_path)],
        )

    @property
    def is_unknownish(self) -> bool:
        return self.status in {ClaimStatus.UNKNOWN, ClaimStatus.NEEDS_MANUAL_CHECK} or self.value is None or self.value == str(UNKNOWN) or self.value == str(NEEDS_MANUAL_CHECK)

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class Institution:
    name: FieldValue = dc_field(default_factory=FieldValue)
    homepage_url: str = ""
    country_or_region: FieldValue = dc_field(default_factory=FieldValue)

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class RunMetadata:
    input_url: str
    retrieved_at: str = dc_field(default_factory=lambda: datetime.now(UTC).isoformat())
    crawler_version: str | None = None
    config: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class RequirementRecord:
    label: str
    value: FieldValue
    applicant_group: FieldValue = dc_field(default_factory=FieldValue)
    qualification: FieldValue = dc_field(default_factory=FieldValue)
    requires_applicant_group: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class ProgrammeRecord:
    name: FieldValue
    degree: FieldValue = dc_field(default_factory=FieldValue)
    faculty_or_school: FieldValue = dc_field(default_factory=FieldValue)
    source_url: str | None = None
    prerequisites: list[RequirementRecord] = dc_field(default_factory=list)
    evidence: list[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class AdmissionsRecord:
    undergraduate_application_entry: FieldValue = dc_field(default_factory=FieldValue)
    international_requirements: list[RequirementRecord] = dc_field(default_factory=list)
    accepted_qualifications: list[RequirementRecord] = dc_field(default_factory=list)
    application_periods: list[RequirementRecord] = dc_field(default_factory=list)
    required_documents: list[RequirementRecord] = dc_field(default_factory=list)
    english_requirements: list[RequirementRecord] = dc_field(default_factory=list)
    standardized_tests: list[RequirementRecord] = dc_field(default_factory=list)
    selection_tests_or_interviews: list[RequirementRecord] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class AdmissionsData:
    institution: Institution
    run: RunMetadata
    sources: list[SourceRecord] = dc_field(default_factory=list)
    admissions: AdmissionsRecord = dc_field(default_factory=AdmissionsRecord)
    programmes: list[ProgrammeRecord] = dc_field(default_factory=list)
    fees: list[RequirementRecord] = dc_field(default_factory=list)
    scholarships: list[RequirementRecord] = dc_field(default_factory=list)
    visa: list[RequirementRecord] = dc_field(default_factory=list)
    housing: list[RequirementRecord] = dc_field(default_factory=list)
    contacts: list[RequirementRecord] = dc_field(default_factory=list)
    discovered_categories: list["PageClassificationRecord"] = dc_field(default_factory=list)
    evidence: list[EvidenceItem] = dc_field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    warnings: list[WarningRecord] = dc_field(default_factory=list)

    def evidence_paths(self) -> set[str]:
        return {item.claim_path for item in self.evidence}

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


@dataclass(slots=True)
class PageClassificationRecord:
    source_url: str
    category: PageCategory
    score: int
    signals: list[str] = dc_field(default_factory=list)
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _to_jsonable(self)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return str(value)
    if is_dataclass(value):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in dataclass_fields(value)}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def resolve_claim_path(data: "AdmissionsData", claim_path: str) -> Any:
    """Resolve a JSON-pointer-like claim path against the dataclass model.

    The path must point to an actual object/field location, not merely share a
    prefix with an evidence item. This guards evidence appendix entries from
    drifting away from the serialized claim they support.
    """

    current: Any = data
    for raw_part in claim_path.strip("/").split("/"):
        if raw_part == "":
            continue
        if isinstance(current, list):
            try:
                current = current[int(raw_part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(claim_path) from exc
            continue
        if is_dataclass(current):
            if not hasattr(current, raw_part):
                raise KeyError(claim_path)
            current = getattr(current, raw_part)
            continue
        raise KeyError(claim_path)
    return current


def collect_nested_field_warnings(data: "AdmissionsData") -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for _, claim in iter_field_values(data):
        warnings.extend(claim.warnings)
    return warnings


def validate_evidence_links(data: AdmissionsData) -> list[WarningRecord]:
    """Return warnings for non-unknown nested claims that lack evidence.

    Validation is warning-producing rather than exception-throwing so the
    pipeline can emit a report with manual-check items instead of crashing.
    """

    warnings = list(data.warnings)
    evidence_paths = data.evidence_paths()

    for item in data.evidence:
        try:
            resolve_claim_path(data, item.claim_path)
        except KeyError:
            warnings.append(
                WarningRecord(
                    WarningCode.MISSING_EVIDENCE,
                    "Evidence item points to a claim path that does not exist.",
                    field=item.claim_path,
                    source_urls=[item.source_url],
                )
            )

    for path, claim in iter_field_values(data):
        if claim.is_unknownish:
            continue
        if claim.evidence and any(ref in evidence_paths and ref == path for ref in claim.evidence):
            continue
        warnings.append(
            WarningRecord(
                WarningCode.MISSING_EVIDENCE,
                "Non-unknown claim has no matching evidence reference.",
                field=path,
            )
        )

    return warnings


def iter_field_values(value: Any, prefix: str = "") -> Iterable[tuple[str, FieldValue]]:
    if isinstance(value, FieldValue):
        yield prefix or "/", value
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_field_values(item, f"{prefix}/{index}")
        return
    if is_dataclass(value):
        for f in dataclass_fields(value):
            actual = getattr(value, f.name)
            yield from iter_field_values(actual, f"{prefix}/{f.name}")
        return


def attach_validation_warnings(data: AdmissionsData) -> AdmissionsData:
    """Apply the central normalization/warning policy.

    Kept here as a compatibility entry point for callers and tests.  The policy
    owner lives in ``extractor.normalizer`` so extractor, pipeline, and report
    code do not grow their own duplicate warning semantics.
    """

    from university_admissions_crawler.extractor.normalizer import normalize_admissions_data

    return normalize_admissions_data(data)
