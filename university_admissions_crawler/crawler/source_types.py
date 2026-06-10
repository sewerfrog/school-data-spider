"""Source type and content-type helpers for fetched content."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from university_admissions_crawler.extractor.schema import SourceType


def source_type_for_url_or_content(url: str, content_type: str) -> SourceType:
    lower_content = content_type.lower()
    if lower_content == "application/pdf" or looks_like_pdf_url(url):
        return SourceType.PDF
    if lower_content in {"text/html", "application/xhtml+xml"}:
        return SourceType.HTML
    if lower_content in {"application/json", "application/ld+json"} or urlparse(url).path.lower().endswith(".json"):
        return SourceType.JSON
    return SourceType.OTHER


def looks_like_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def source_type_for_fixture_path(path: Path) -> SourceType:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return SourceType.PDF
    if suffix == ".json":
        return SourceType.JSON
    if suffix in {".html", ".htm"}:
        return SourceType.HTML
    return SourceType.OTHER


def content_type_for_source_type(source_type: SourceType) -> str:
    if source_type == SourceType.PDF:
        return "application/pdf"
    if source_type == SourceType.JSON:
        return "application/json"
    if source_type == SourceType.HTML:
        return "text/html"
    return "application/octet-stream"
