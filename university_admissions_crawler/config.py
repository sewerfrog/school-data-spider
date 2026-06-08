"""Runtime configuration for bounded admissions scans.

The defaults intentionally describe a safe MVP crawl, not a production-scale
harvester.  Live network/browser/LLM modes must be explicitly enabled by a
caller and still reuse these caps.
"""

from __future__ import annotations

from dataclasses import dataclass, field


POSITIVE_KEYWORDS: tuple[str, ...] = (
    "admission",
    "admissions",
    "apply",
    "application",
    "application period",
    "deadline",
    "closing date",
    "undergraduate",
    "international",
    "international applicant",
    "requirement",
    "requirements",
    "english",
    "ielts",
    "toefl",
    "pte",
    "qualification",
    "qualifications",
    "programme",
    "programmes",
    "program",
    "programs",
    "degree",
    "prerequisite",
    "tuition",
    "fees",
    "financial",
    "scholarship",
    "scholarships",
    "visa",
    "student pass",
    "housing",
    "accommodation",
    "contact",
    "office",
    "prospectus",
    "pdf",
    "api",
)


NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "alumni",
    "news",
    "event",
    "events",
    "donate",
    "giving",
    "media",
    "staff",
    "jobs",
    "careers",
    "blog",
    "press",
    "privacy",
    "terms",
    "cookie",
    "cookies",
    "sitemap",
)


TRACKING_QUERY_PREFIXES: tuple[str, ...] = ("utm_",)
TRACKING_QUERY_NAMES: tuple[str, ...] = (
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
)


@dataclass(slots=True)
class CrawlConfig:
    """User-facing crawl limits and policy switches."""

    max_depth: int = 3
    max_pages: int = 100
    timeout_seconds: float = 15.0
    max_pdf_pages: int = 10
    allowed_hosts: set[str] = field(default_factory=set)
    allowed_domains: set[str] = field(default_factory=set)
    allow_official_subdomains: bool = True
    positive_keywords: tuple[str, ...] = POSITIVE_KEYWORDS
    negative_keywords: tuple[str, ...] = NEGATIVE_KEYWORDS
    retries: int = 1
    enable_live_network: bool = False
    enable_llm: bool = False


def smoke_config() -> CrawlConfig:
    """Small deterministic config for smoke tests and cautious demos."""

    return CrawlConfig(max_depth=2, max_pages=20, timeout_seconds=10.0, max_pdf_pages=5)
