"""Guarded LLM structured extraction fallback for missing admissions facts."""

from __future__ import annotations

from collections import Counter

from university_admissions_crawler.crawler.discovery import DiscoveryConfig
from university_admissions_crawler.crawler.filters import DomainPolicy
from university_admissions_crawler.evidence.provenance import evidence_from_source
from university_admissions_crawler.evidence.validator import validate_llm_candidate_fact
from university_admissions_crawler.extractor.llm_provider import (
    LLMStructuredCandidateFact,
    LLMStructuredExtractionSource,
    STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
    STRUCTURED_EXTRACTION_OUTPUT_SCHEMA,
    StructuredExtractionProvider,
    structured_extraction_result_from_payload,
)
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    ClaimStatus,
    Confidence,
    FieldValue,
    PageCategory,
    ProgrammeCatalogRecord,
    RequirementRecord,
    SourceRecord,
)
from university_admissions_crawler.pipeline.diagnostics import llm_structured_validation_summary, refresh_run_diagnostics


def attach_llm_structured_extraction_diagnostics(
    data: AdmissionsData,
    captured_source_texts: dict[str, str],
    provider: StructuredExtractionProvider,
    discovery_config: DiscoveryConfig,
) -> None:
    diagnostic = data.run.config.get("llm_structured_extraction")
    if not isinstance(diagnostic, dict):
        diagnostic = {}
    trigger_reasons = _llm_structured_trigger_reasons(data)
    diagnostic.update(
        {
            "enabled": True,
            "provider": getattr(provider, "name", type(provider).__name__),
            "triggered": bool(trigger_reasons),
            "trigger_reasons": trigger_reasons,
            "applied_to_facts": False,
            "note": "LLM structured extraction fallback writes only validated candidates into missing fields; rejected or skipped candidates remain diagnostics.",
        }
    )
    if not trigger_reasons:
        diagnostic.update(
            {
                "candidate_count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "results": [],
                "source_urls_used": [],
            }
        )
        data.run.config["llm_structured_extraction"] = diagnostic
        return

    source_records = {source.source_url: source for source in data.sources}
    policy = DomainPolicy(
        seed_url=data.run.input_url,
        allowed_hosts=set(discovery_config.allowed_hosts),
        allowed_domains=set(discovery_config.allowed_domains),
        allow_official_subdomains=discovery_config.allow_official_subdomains,
    )
    validation_results: list[dict[str, object]] = []
    source_urls_used: list[str] = []
    warnings: list[str] = []
    existing_targets = _llm_structured_existing_targets(data)
    for source in _llm_structured_candidate_sources(data, captured_source_texts):
        source_urls_used.append(source.source_url)
        try:
            payload = provider.extract_structured_candidate_payload(
                source,
                STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
                STRUCTURED_EXTRACTION_OUTPUT_SCHEMA,
            )
            result = structured_extraction_result_from_payload(payload)
        except Exception as exc:
            validation_results.append(
                {
                    "accepted": False,
                    "candidate": None,
                    "reject_reason": "malformed_candidate",
                    "source_url": source.source_url,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "validation_status": "rejected",
                    "applied_to_facts": False,
                }
            )
            continue
        warnings.extend(result.warnings)
        for candidate in result.candidate_facts:
            validation = validate_llm_candidate_fact(
                candidate,
                captured_sources=captured_source_texts,
                source_records=source_records,
                domain_policy=policy,
            )
            validation_result = validation.to_dict()
            if validation.accepted and validation.candidate is not None:
                validation_result.update(
                    _apply_llm_structured_candidate(
                        data,
                        validation.candidate,
                        source_records=source_records,
                        existing_targets=existing_targets,
                    )
                )
            else:
                validation_result["validation_status"] = "rejected"
                validation_result["applied_to_facts"] = False
            validation_results.append(validation_result)

    summary = llm_structured_validation_summary(validation_results)
    applied_count = sum(1 for result in validation_results if result.get("applied_to_facts") is True)
    write_status_counts = Counter(str(result.get("write_status", "not_applicable")) for result in validation_results)
    diagnostic.update(summary)
    diagnostic["results"] = validation_results
    diagnostic["source_urls_used"] = source_urls_used
    diagnostic["warnings"] = warnings
    diagnostic["applied_to_facts"] = applied_count > 0
    diagnostic["applied_count"] = applied_count
    diagnostic["write_status_counts"] = dict(sorted(write_status_counts.items()))
    diagnostic["note"] = "LLM structured extraction fallback writes only validated candidates into missing fields; rejected or skipped candidates remain diagnostics."
    data.run.config["llm_structured_extraction"] = diagnostic
    if applied_count:
        refresh_run_diagnostics(data)
        data.run.config["llm_structured_extraction"] = diagnostic


def _apply_llm_structured_candidate(
    data: AdmissionsData,
    candidate: LLMStructuredCandidateFact,
    *,
    source_records: dict[str, SourceRecord],
    existing_targets: dict[str, bool],
) -> dict[str, object]:
    source = source_records.get(candidate.source_url)
    if source is None:
        return _llm_write_result(write_status="source_record_missing", applied=False)
    if existing_targets.get(candidate.claim_path):
        return _llm_write_result(write_status="existing_value", applied=False)

    if candidate.claim_path == "admissions.application_entry":
        if not data.admissions.undergraduate_application_entry.is_unknownish:
            return _llm_write_result(write_status="existing_value", applied=False)
        evidence_path = "/admissions/undergraduate_application_entry"
        data.admissions.undergraduate_application_entry = _llm_field_value(candidate, evidence_path)
        data.evidence.append(_llm_evidence(candidate, source, evidence_path))
        _mark_llm_structured_target_existing(existing_targets, candidate.claim_path)
        return _llm_write_result(write_status="applied", applied=True, evidence_path=evidence_path)

    requirement_target = _llm_requirement_target(data, candidate.claim_path)
    if requirement_target is not None:
        dest, label, claim_prefix = requirement_target
        if _has_requirement_value(dest, candidate.value):
            return _llm_write_result(write_status="duplicate_value", applied=False)
        evidence_path = f"{claim_prefix}/{len(dest)}/value"
        dest.append(
            RequirementRecord(
                label=label,
                value=_llm_field_value(candidate, evidence_path),
            )
        )
        data.evidence.append(_llm_evidence(candidate, source, evidence_path))
        _mark_llm_structured_target_existing(existing_targets, candidate.claim_path)
        return _llm_write_result(write_status="applied", applied=True, evidence_path=evidence_path)

    if candidate.claim_path == "programme_catalog[].name":
        if _has_programme_catalog_name(data.programme_catalog, candidate.value):
            return _llm_write_result(write_status="duplicate_value", applied=False)
        evidence_path = f"/programme_catalog/{len(data.programme_catalog)}/name"
        data.programme_catalog.append(
            ProgrammeCatalogRecord(
                name=candidate.value,
                source_url=candidate.source_url,
                evidence_snippet=candidate.evidence_snippet,
                evidence_path=evidence_path,
                evidence_confidence=_llm_confidence(candidate.confidence),
                parse_status="llm_fallback_validated",
            )
        )
        data.evidence.append(_llm_evidence(candidate, source, evidence_path))
        return _llm_write_result(write_status="applied", applied=True, evidence_path=evidence_path)

    return _llm_write_result(write_status="unsupported_claim_path_for_write", applied=False)


def _llm_write_result(*, write_status: str, applied: bool, evidence_path: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "extractor": "llm_fallback_validated",
        "validation_status": "accepted",
        "write_status": write_status,
        "applied_to_facts": applied,
    }
    if evidence_path is not None:
        result["evidence_path"] = evidence_path
    return result


def _llm_structured_existing_targets(data: AdmissionsData) -> dict[str, bool]:
    period_exists = _has_known_requirement_records(data.admissions.application_periods)
    return {
        "admissions.application_period": period_exists,
        "admissions.application_deadline": period_exists,
        "admissions.application_entry": not data.admissions.undergraduate_application_entry.is_unknownish,
        "admissions.requirements.academic": _has_known_requirement_records(data.admissions.accepted_qualifications),
        "admissions.requirements.english": _has_known_requirement_records(data.admissions.english_requirements),
        "admissions.required_documents": _has_known_requirement_records(data.admissions.required_documents),
        "admissions.fees": _has_known_requirement_records(data.fees),
        "admissions.scholarships": _has_known_requirement_records(data.scholarships),
        "admissions.contact": _has_known_requirement_records(data.contacts),
    }


def _mark_llm_structured_target_existing(existing_targets: dict[str, bool], claim_path: str) -> None:
    existing_targets[claim_path] = True
    if claim_path in {"admissions.application_period", "admissions.application_deadline"}:
        existing_targets["admissions.application_period"] = True
        existing_targets["admissions.application_deadline"] = True


def _llm_requirement_target(data: AdmissionsData, claim_path: str) -> tuple[list[RequirementRecord], str, str] | None:
    if claim_path == "admissions.application_period":
        return data.admissions.application_periods, "application period", "/admissions/application_periods"
    if claim_path == "admissions.application_deadline":
        return data.admissions.application_periods, "application deadline", "/admissions/application_periods"
    if claim_path == "admissions.requirements.academic":
        return data.admissions.accepted_qualifications, "academic requirement", "/admissions/accepted_qualifications"
    if claim_path == "admissions.requirements.english":
        return data.admissions.english_requirements, "english language requirement", "/admissions/english_requirements"
    if claim_path == "admissions.required_documents":
        return data.admissions.required_documents, "required documents", "/admissions/required_documents"
    if claim_path == "admissions.fees":
        return data.fees, "tuition/fees", "/fees"
    if claim_path == "admissions.scholarships":
        return data.scholarships, "scholarship", "/scholarships"
    if claim_path == "admissions.contact":
        return data.contacts, "contact", "/contacts"
    return None


def _llm_field_value(candidate: LLMStructuredCandidateFact, evidence_path: str) -> FieldValue:
    return FieldValue(
        value=candidate.value,
        raw_text=candidate.evidence_snippet,
        parse_status="llm_fallback_validated",
        evidence=[evidence_path],
        confidence=_llm_confidence(candidate.confidence),
        status=ClaimStatus.KNOWN,
    )


def _llm_evidence(candidate: LLMStructuredCandidateFact, source: SourceRecord, evidence_path: str):
    return evidence_from_source(
        claim_path=evidence_path,
        source=source,
        snippet=candidate.evidence_snippet,
        confidence=_llm_confidence(candidate.confidence),
    )


def _llm_confidence(score: float) -> Confidence:
    if score >= 0.9:
        return Confidence.HIGH
    if score >= 0.65:
        return Confidence.MEDIUM
    return Confidence.LOW


def _has_known_requirement_records(records: list[RequirementRecord]) -> bool:
    return any(not record.value.is_unknownish for record in records)


def _has_requirement_value(records: list[RequirementRecord], value: str) -> bool:
    normalized = value.strip().casefold()
    return any(str(record.value.value).strip().casefold() == normalized for record in records)


def _has_programme_catalog_name(records: list[ProgrammeCatalogRecord], value: str) -> bool:
    normalized = value.strip().casefold()
    return any(record.name.strip().casefold() == normalized for record in records)


def _llm_structured_trigger_reasons(data: AdmissionsData) -> list[str]:
    reasons: list[str] = []
    coverage = data.run.config.get("coverage")
    if isinstance(coverage, dict) and coverage.get("missing"):
        reasons.append("core_field_missing")
    extraction_summary = data.run.config.get("extraction_diagnostics_summary")
    if isinstance(extraction_summary, dict):
        status_counts = extraction_summary.get("status_counts")
        if isinstance(status_counts, dict) and int(status_counts.get("no_match", 0) or 0) > 0:
            reasons.append("extractor_attempted_no_match")
    programme_summary = data.run.config.get("programme_catalog_summary")
    if isinstance(programme_summary, dict) and programme_summary.get("probable_incomplete_catalog"):
        reasons.append("programme_catalog_probable_incomplete")
    return reasons


def _llm_structured_candidate_sources(data: AdmissionsData, captured_source_texts: dict[str, str], limit: int = 5) -> list[LLMStructuredExtractionSource]:
    source_strategy = data.run.config.get("source_strategy")
    strategy_by_url: dict[str, dict[str, object]] = {}
    if isinstance(source_strategy, list):
        for item in source_strategy:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                strategy_by_url[str(item["url"])] = item
    scored: list[tuple[int, LLMStructuredExtractionSource]] = []
    for source in data.sources:
        text = captured_source_texts.get(source.source_url, "")
        if not text.strip():
            continue
        strategy = strategy_by_url.get(source.source_url, {})
        if strategy.get("strategy") in {"blocked_or_challenge", "application_portal", "irrelevant"}:
            continue
        category = str(strategy.get("category", ""))
        score = int(strategy.get("discovery_score", 0) or 0)
        if category in {str(PageCategory.UNDERGRADUATE_ADMISSIONS), str(PageCategory.PROGRAMME_LIST), str(PageCategory.PROGRAMME_PREREQUISITES)}:
            score += 20
        elif category in {str(PageCategory.FEES), str(PageCategory.SCHOLARSHIPS), str(PageCategory.INTERNATIONAL_REQUIREMENTS), str(PageCategory.APPLICATION_DEADLINES)}:
            score += 12
        scored.append(
            (
                score,
                LLMStructuredExtractionSource(
                    source_url=source.source_url,
                    title=source.title,
                    text=text[:6000],
                    source_type=str(source.source_type),
                ),
            )
        )
    return [source for _score, source in sorted(scored, key=lambda item: (-item[0], item[1].source_url))[:limit]]
