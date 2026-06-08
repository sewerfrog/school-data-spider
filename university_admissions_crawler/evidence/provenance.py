"""Evidence/provenance helpers."""

from __future__ import annotations

from hashlib import sha256

from university_admissions_crawler.extractor.schema import Confidence, EvidenceItem, SourceRecord, SourceType


def content_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return sha256(content).hexdigest()


def evidence_from_source(
    *,
    claim_path: str,
    source: SourceRecord,
    snippet: str,
    confidence: Confidence = Confidence.MEDIUM,
    page_number: int | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        claim_path=claim_path,
        source_url=source.source_url,
        source_type=source.source_type,
        title=source.title,
        retrieved_at=source.retrieved_at,
        academic_year=source.academic_year,
        page_number=page_number if page_number is not None else source.page_number,
        snippet=snippet,
        confidence=confidence,
    )


def source_from_text(
    *,
    source_url: str,
    text: str,
    source_type: SourceType = SourceType.HTML,
    title: str | None = None,
    retrieved_at: str | None = None,
    engine: str | None = None,
    is_official: bool = True,
) -> SourceRecord:
    source = SourceRecord(source_url=source_url, source_type=source_type, title=title, engine=engine, is_official=is_official)
    if retrieved_at is not None:
        source.retrieved_at = retrieved_at
    source.content_hash = content_hash(text)
    return source
