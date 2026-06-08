"""PDF extraction protocol and deterministic fixture implementation."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from university_admissions_crawler.extractor.schema import SourceRecord, WarningCode, WarningRecord


@dataclass(slots=True)
class PDFPageText:
    page_number: int
    text: str


@dataclass(slots=True)
class PDFExtractionResult:
    pages: list[PDFPageText]
    warnings: list[WarningRecord]

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)


class PDFExtractor(Protocol):
    def extract(self, source: SourceRecord, raw_text: str, max_pages: int = 10) -> PDFExtractionResult:
        ...


class FixturePDFExtractor:
    """Parse text fixtures that mimic PDFs with explicit page markers.

    The project deliberately does not add a runtime PDF dependency yet.  Real
    PDF support can implement the same protocol behind the optional ``pdf``
    extra without changing the pipeline/evidence contract.
    """

    def extract(self, source: SourceRecord, raw_text: str, max_pages: int = 10) -> PDFExtractionResult:
        if not raw_text.strip():
            return PDFExtractionResult(
                pages=[],
                warnings=[WarningRecord(WarningCode.PDF_PARSE_FAILED, "PDF fixture text is empty.", field=source.source_url, source_urls=[source.source_url])],
            )
        pages: list[PDFPageText] = []
        current_page = 1
        current_lines: list[str] = []
        for line in raw_text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("PDF PAGE "):
                if current_lines:
                    pages.append(PDFPageText(current_page, "\n".join(current_lines).strip()))
                    current_lines = []
                maybe = stripped.rsplit(" ", 1)[-1]
                current_page = int(maybe) if maybe.isdigit() else current_page
                continue
            if stripped.startswith("---PAGE ") and stripped.endswith("---"):
                if current_lines:
                    pages.append(PDFPageText(current_page, "\n".join(current_lines).strip()))
                    current_lines = []
                maybe = stripped.removeprefix("---PAGE ").removesuffix("---").strip()
                current_page = int(maybe) if maybe.isdigit() else current_page + 1
                continue
            current_lines.append(line)
        if current_lines:
            pages.append(PDFPageText(current_page, "\n".join(current_lines).strip()))
        warnings: list[WarningRecord] = []
        if len(pages) > max_pages:
            warnings.append(
                WarningRecord(
                    WarningCode.PDF_UNAVAILABLE,
                    f"PDF fixture truncated from {len(pages)} to max_pdf_pages={max_pages}.",
                    field=source.source_url,
                    source_urls=[source.source_url],
                )
            )
            pages = pages[:max_pages]
        return PDFExtractionResult(pages=pages, warnings=warnings)


class MissingPDFExtractor:
    """Runtime guard for real PDFs when no optional parser is installed."""

    def extract(self, source: SourceRecord, raw_text: str, max_pages: int = 10) -> PDFExtractionResult:
        return PDFExtractionResult(
            pages=[],
            warnings=[
                WarningRecord(
                    WarningCode.OPTIONAL_DEPENDENCY_MISSING,
                    "PDF parsing support is optional and not installed/enabled for this run.",
                    field=source.source_url,
                    source_urls=[source.source_url],
                )
            ],
        )


class PypdfPDFExtractor:
    """Optional real PDF parser using pypdf when installed.

    Fetchers pass bytes through ``raw_text`` as latin-1 compatible text in this
    dependency-light MVP. If a caller already decoded a text-like PDF fixture,
    this extractor will fail closed with a parser warning instead of guessing.
    """

    def extract(self, source: SourceRecord, raw_text: str, max_pages: int = 10) -> PDFExtractionResult:
        try:
            from pypdf import PdfReader
        except Exception as exc:
            return PDFExtractionResult(
                pages=[],
                warnings=[
                    WarningRecord(
                        WarningCode.OPTIONAL_DEPENDENCY_MISSING,
                        f"pypdf support is optional and not available: {type(exc).__name__}: {exc}",
                        field=source.source_url,
                        source_urls=[source.source_url],
                    )
                ],
            )
        try:
            raw = raw_text.encode("latin-1")
            reader = PdfReader(BytesIO(raw))
            pages: list[PDFPageText] = []
            for index, page in enumerate(reader.pages[:max_pages], start=1):
                pages.append(PDFPageText(index, (page.extract_text() or "").strip()))
        except Exception as exc:
            return PDFExtractionResult(
                pages=[],
                warnings=[
                    WarningRecord(
                        WarningCode.PDF_PARSE_FAILED,
                        f"pypdf parser failed: {type(exc).__name__}: {exc}",
                        field=source.source_url,
                        source_urls=[source.source_url],
                    )
                ],
            )
        warnings: list[WarningRecord] = []
        if len(reader.pages) > max_pages:
            warnings.append(
                WarningRecord(
                    WarningCode.PDF_UNAVAILABLE,
                    f"PDF truncated from {len(reader.pages)} to max_pdf_pages={max_pages}.",
                    field=source.source_url,
                    source_urls=[source.source_url],
                )
            )
        return PDFExtractionResult(pages=pages, warnings=warnings)
