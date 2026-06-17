"""URL canonicalization, domain policy, and link scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlencode, urldefrag, urljoin, urlparse

from university_admissions_crawler.crawler.admissions_context import NON_ADMISSIONS_PATH_HINTS, UNDERGRAD_ADMISSIONS_PATH_HINTS
from university_admissions_crawler.config import (
    NEGATIVE_KEYWORDS,
    POSITIVE_KEYWORDS,
    TRACKING_QUERY_NAMES,
    TRACKING_QUERY_PREFIXES,
)


STATIC_RESOURCE_SUFFIXES: tuple[str, ...] = (
    ".css",
    ".js",
    ".mjs",
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".avif",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".map",
)

LOW_VALUE_DOCUMENT_TERMS: tuple[str, ...] = (
    "privacy",
    "gdpr",
    "cookie",
    "cookies",
    "terms",
    "data protection",
    "personal information collection",
)


@dataclass(slots=True)
class DomainPolicy:
    """Bounded official-domain policy.

    The MVP allows same host by default.  It may also allow controlled official
    subdomains under the same registrable-domain approximation when configured;
    this is deterministic and intentionally conservative.
    """

    seed_url: str
    allowed_hosts: set[str] | None = None
    allowed_domains: set[str] | None = None
    allow_official_subdomains: bool = True
    seed_host: str = field(init=False)
    seed_domain: str = field(init=False)

    def __post_init__(self) -> None:
        seed_host = normalize_host(urlparse(self.seed_url).netloc)
        self.seed_host = seed_host
        self.seed_domain = registrable_domain(seed_host)
        self.allowed_hosts = {normalize_host(h) for h in (self.allowed_hosts or {seed_host}) if h}
        self.allowed_domains = {normalize_host(d) for d in (self.allowed_domains or set()) if d}

    def is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https", "file"}:
            return False
        if parsed.scheme == "file":
            return "file" in self.allowed_hosts
        host = normalize_host(parsed.netloc)
        if not host:
            return False
        if host in self.allowed_hosts:
            return True
        domain = registrable_domain(host)
        if host in self.allowed_domains or domain in self.allowed_domains:
            return True
        if self.allow_official_subdomains and domain == self.seed_domain:
            return True
        return False


def canonicalize_url(url: str, base_url: str | None = None) -> str:
    """Normalize URLs for dedupe without erasing meaningful paths."""

    if base_url:
        url = urljoin(base_url, url)
    url = urldefrag(url)[0]
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    if scheme == "file":
        return parsed._replace(scheme=scheme, params="", query="", fragment="").geturl()

    netloc = normalize_host(parsed.netloc)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = _canonical_query(parsed.query)
    return parsed._replace(scheme=scheme, netloc=netloc, path=path, params="", query=query, fragment="").geturl()


def normalize_host(host: str) -> str:
    host = host.lower().strip()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if ":" in host:
        hostname, _, port = host.partition(":")
        if port in {"80", "443"}:
            return hostname
    return host


def registrable_domain(host: str) -> str:
    """Small offline approximation sufficient for deterministic policy tests."""

    parts = [p for p in normalize_host(host).split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    # Handle common academic country-code domains such as example.edu.sg.
    if len(parts[-1]) == 2 and parts[-2] in {"ac", "edu", "com", "org", "net", "gov"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def is_static_resource_url(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    return path.endswith(STATIC_RESOURCE_SUFFIXES)


def is_low_value_source_url(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    if is_static_resource_url(url):
        return True
    if is_pdf_url(url) and any(term in path for term in LOW_VALUE_DOCUMENT_TERMS):
        return True
    return False


def score_url(url: str, title: str | None = None, text: str | None = None) -> int:
    haystack = " ".join(v for v in [url, title or "", text or ""] if v).lower()
    score = sum(2 for kw in POSITIVE_KEYWORDS if kw in haystack)
    score -= sum(3 for kw in NEGATIVE_KEYWORDS if kw in haystack)
    path = urlparse(url).path.lower()
    if any(token in path for token in NON_ADMISSIONS_PATH_HINTS) and not any(token in path for token in UNDERGRAD_ADMISSIONS_PATH_HINTS):
        score -= 12
    if any(token in path for token in ("/admission", "/undergraduate", "/apply", "/programme", "/program", "/fee", "/scholarship", "/international", "/requirement", "/contact")):
        score += 6
    if any(token in path for token in ("/news", "/alumni", "/giving", "/donate", "/staff", "/jobs", "/career", "/privacy", "/cookie")):
        score -= 8
    if is_pdf_url(url) and any(kw in haystack for kw in ("admission", "programme", "requirement", "prospectus")):
        score += 4
    if urlparse(url).path.lower().endswith(".json") or "/api/" in path:
        score += 3
    if is_low_value_source_url(url):
        score -= 100
    return score


def should_follow_url(url: str, policy: DomainPolicy) -> bool:
    if not policy.is_allowed(url):
        return False
    if is_low_value_source_url(url):
        return False
    return score_url(url) >= -2


def _canonical_query(query: str) -> str:
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lower = key.lower()
        if lower in TRACKING_QUERY_NAMES or any(lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        kept.append((key, value))
    return urlencode(sorted(kept))
