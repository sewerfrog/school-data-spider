"""Merge multiple admissions scan results into one batch result."""

from __future__ import annotations

from university_admissions_crawler.extractor.schema import AdmissionsData, EvidenceItem, FieldValue, RequirementRecord


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
