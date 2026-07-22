"""Captured-source text, classification, and source-strategy context."""

from __future__ import annotations

import re
from dataclasses import dataclass

from university_admissions_crawler.classifier.page_classifier import Classification, classify_page, is_low_confidence_classification
from university_admissions_crawler.crawler.discovery import DiscoveredPage, DiscoveryConfig
from university_admissions_crawler.crawler.fetcher import FetchResult
from university_admissions_crawler.crawler.html_text import HTMLContentBlock
from university_admissions_crawler.crawler.programme_sources import classify_programme_source_role
from university_admissions_crawler.crawler.relevance import relevance_diagnostics
from university_admissions_crawler.extractor.llm_provider import ClassificationAssistProvider, generate_classification_assist_diagnostic
from university_admissions_crawler.extractor.pdf_extractor import PDFExtractor, PDFPageText
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    PageCategory,
    PageClassificationRecord,
    SourceRecord,
    SourceType,
    WarningCode,
    WarningRecord,
)
from university_admissions_crawler.pipeline.diagnostics import source_strategy_for


@dataclass(slots=True)
class SourceTextContext:
    discovery_text: str
    extraction_text: str
    pdf_pages: list[PDFPageText]
    content_blocks: tuple[HTMLContentBlock, ...]


@dataclass(slots=True)
class CapturedSourceContext:
    final_url: str
    title: str | None
    source: SourceRecord
    discovery_text: str
    extraction_text: str
    pdf_pages: list[PDFPageText]
    content_blocks: tuple[HTMLContentBlock, ...]
    classification: Classification
    source_strategy: str
    source_role: str
    source_family: str


def source_text_context(data: AdmissionsData, result: FetchResult, pdf_extractor: PDFExtractor) -> SourceTextContext:
    discovery_text = result.markdown or result.text
    if result.source is None or result.source.source_type != SourceType.PDF:
        return SourceTextContext(
            discovery_text=discovery_text,
            extraction_text=discovery_text,
            pdf_pages=[],
            content_blocks=result.content_blocks,
        )

    try:
        pdf_result = pdf_extractor.extract(result.source, result.text)
    except Exception as exc:
        data.warnings.append(
            WarningRecord(
                WarningCode.PDF_PARSE_FAILED,
                f"PDF extractor raised {type(exc).__name__}: {exc}",
                field=result.source.source_url,
                source_urls=[result.source.source_url],
            )
        )
        return SourceTextContext(discovery_text=discovery_text, extraction_text="", pdf_pages=[], content_blocks=())

    data.warnings.extend(pdf_result.warnings)
    return SourceTextContext(
        discovery_text=discovery_text,
        extraction_text=pdf_result.text if pdf_result.pages else "",
        pdf_pages=pdf_result.pages,
        content_blocks=(),
    )


def build_captured_source_context(
    data: AdmissionsData,
    page: DiscoveredPage,
    discovery_config: DiscoveryConfig,
    pdf_extractor: PDFExtractor,
    classification_assist_provider: ClassificationAssistProvider | None,
) -> CapturedSourceContext:
    result = page.result
    if result.source is None:
        raise ValueError("Cannot build a captured source context without a source record.")
    text_context = source_text_context(data, result, pdf_extractor)
    classification = classify_page(result.final_url, result.title, text_context.extraction_text)
    if classification_assist_provider is not None and is_low_confidence_classification(classification):
        data.run.config.setdefault("classification_assist", []).append(
            generate_classification_assist_diagnostic(
                url=result.final_url,
                title=result.title,
                text=text_context.extraction_text,
                rule_category=classification.category,
                rule_score=classification.score,
                provider=classification_assist_provider,
            )
        )

    discovery_diagnostics = relevance_diagnostics(
        discovery_config.relevance_strategy,
        result.final_url,
        result.title,
        text_context.discovery_text,
        score=page.score,
    )
    data.discovered_categories.append(
        PageClassificationRecord(
            source_url=result.final_url,
            category=classification.category,
            score=classification.score,
            signals=classification.signals,
            title=result.title,
        )
    )
    strategy = source_strategy_for(result.source.source_type, result.final_url, result.title, text_context.extraction_text, classification.category)
    source_role = classify_programme_source_role(
        result.final_url,
        result.title,
        text_context.extraction_text,
        text_context.content_blocks,
    )
    source_strategy_entry: dict[str, object] = {
        "url": result.final_url,
        "source_type": str(result.source.source_type),
        "category": str(classification.category),
        "strategy": strategy,
        "discovery_score": discovery_diagnostics.score,
        "discovery_signals": list(discovery_diagnostics.signals),
        "relevance_strategy": discovery_diagnostics.strategy,
        "source_role": source_role.role,
        "source_role_signals": list(source_role.signals),
        "source_family": source_role.source_family,
    }
    if result.url != result.final_url:
        source_strategy_entry["requested_url"] = result.url
    catalog_source_status = catalog_source_status_for(classification.category, text_context.extraction_text)
    if catalog_source_status:
        source_strategy_entry["catalog_source_status"] = catalog_source_status
    data.run.config.setdefault("source_strategy", []).append(source_strategy_entry)
    return CapturedSourceContext(
        final_url=result.final_url,
        title=result.title,
        source=result.source,
        discovery_text=text_context.discovery_text,
        extraction_text=text_context.extraction_text,
        pdf_pages=text_context.pdf_pages,
        content_blocks=text_context.content_blocks,
        classification=classification,
        source_strategy=strategy,
        source_role=source_role.role,
        source_family=source_role.source_family,
    )


def catalog_source_status_for(category: object, text: str) -> str | None:
    if category not in {PageCategory.PROGRAMME_LIST, PageCategory.PROGRAMME_PREREQUISITES}:
        return None
    if looks_like_dynamic_catalog_shell(text):
        return "dynamic_shell_no_rows"
    return None


def looks_like_dynamic_catalog_shell(text: str) -> bool:
    lower = " ".join(text.lower().split())
    if not lower:
        return False
    has_filter_shell = (
        ("programme level" in lower and "programme type" in lower)
        or sum(1 for token in ("programme level", "programme type", "study mode", "full-time", "part-time", "filter", "all") if token in lower) >= 4
    )
    if not has_filter_shell:
        return False
    if not any(token in lower for token in ("undergraduate", "programme", "program", "degree")):
        return False
    has_row_signal = bool(
        re.search(r"\bprogramme\s*\|\s*(?:degree|award|title)\b", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:Bachelor\s+of|Bachelor\s+in|BSc|BA|BEng|BBA|LLB|MBBS)\b.{0,80}\b(?:degree|honours|hons|faculty|school)\b", text, flags=re.IGNORECASE)
    )
    return not has_row_signal
