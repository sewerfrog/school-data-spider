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

DISALLOWED_SOURCE_PLAN_HOST_TERMS: tuple[str, ...] = (
    "facebook.",
    "instagram.",
    "linkedin.",
    "twitter.",
    "x.com",
    "youtube.",
    "youtu.be",
    "tiktok.",
    "reddit.",
    "quora.",
    "medium.",
)

DISALLOWED_SOURCE_PLAN_PATH_TERMS: tuple[str, ...] = (
    "/redirect",
    "/redir",
    "/outbound",
    "/external",
    "/tracking",
    "/track",
)

CHALLENGE_URL_TERMS: tuple[str, ...] = (
    "_incapsula_resource",
    "captcha",
    "access-denied",
    "access_denied",
)

CHALLENGE_TEXT_TERMS: tuple[str, ...] = (
    "captcha",
    "cloudflare",
    "access denied",
    "verify you are human",
    "enable javascript",
    "bot detection",
    "incapsula incident id",
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


def looks_like_blocked_or_challenge_source(url: str, title: str | None = None, text: str = "") -> bool:
    """Return whether a fetched page is clearly a bot/WAF challenge."""

    url_title = f"{url} {title or ''}".lower()
    text_head = text[:4000].lower()
    if any(term in url_title for term in CHALLENGE_URL_TERMS):
        return True
    if any(term in text_head for term in CHALLENGE_TEXT_TERMS):
        return True
    if _has_noindex_nofollow(text_head):
        return True
    if "request unsuccessful" in text_head and any(term in text_head for term in ("incident id", "_incapsula_resource")):
        return True
    if _looks_like_short_script_challenge(text_head):
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


def validate_source_plan_candidate_url(url: str, policy: DomainPolicy) -> tuple[bool, str]:
    """Validate a model-suggested URL before it can become a crawl candidate."""

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False, "non_https"
    if not policy.is_allowed(url):
        return False, "outside_allowed_domain"
    host = normalize_host(parsed.netloc)
    if any(term in host for term in DISALLOWED_SOURCE_PLAN_HOST_TERMS):
        return False, "social_or_forum_url"
    path = unquote(parsed.path).lower()
    if any(term in path for term in DISALLOWED_SOURCE_PLAN_PATH_TERMS):
        return False, "tracking_or_redirect_url"
    query_names = {key.lower() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_names & set(TRACKING_QUERY_NAMES) or any(any(key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES) for key in query_names):
        return False, "tracking_or_redirect_url"
    if is_low_value_source_url(url):
        return False, "low_value_source_url"
    return True, "accepted"


def _has_noindex_nofollow(text_lower: str) -> bool:
    return "noindex" in text_lower and "nofollow" in text_lower and ("robots" in text_lower or "<meta" in text_lower)


def _looks_like_short_script_challenge(text_lower: str) -> bool:
    if len(text_lower) > 2500:
        return False
    has_challenge_markup = "<iframe" in text_lower or "<script" in text_lower
    has_challenge_signal = "_incapsula_resource" in text_lower or "challenge" in text_lower or "captcha" in text_lower
    return has_challenge_markup and has_challenge_signal


def _canonical_query(query: str) -> str:
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lower = key.lower()
        if lower in TRACKING_QUERY_NAMES or any(lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        kept.append((key, value))
    return urlencode(sorted(kept))
