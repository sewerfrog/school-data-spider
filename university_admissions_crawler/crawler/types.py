"""Shared fetch result types for crawler adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from university_admissions_crawler.extractor.schema import SourceRecord, WarningCode, WarningRecord


@dataclass(slots=True)
class NetworkResponseRecord:
    url: str
    method: str = "GET"
    status: int | None = None
    content_type: str = ""
    response_size_bytes: int | None = None
    request_query_params: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)
    body_text: str | None = None
    body_sha256: str | None = None
    body_truncated: bool = False


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    title: str | None
    content_type: str
    retrieved_at: str
    engine: str
    text: str = ""
    markdown: str | None = None
    links: list[str] = field(default_factory=list)
    network_response_urls: list[str] = field(default_factory=list)
    network_responses: list[NetworkResponseRecord] = field(default_factory=list)
    source: SourceRecord | None = None
    warnings: list[WarningRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400 and not any(w.code == WarningCode.FETCH_FAILED for w in self.warnings)


class Fetcher(Protocol):
    engine: str

    def fetch(self, url: str) -> FetchResult:
        ...
