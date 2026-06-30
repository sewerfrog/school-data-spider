"""Small sitemap helpers used by live/static discovery paths."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin, urlparse

from university_admissions_crawler.crawler.filters import canonicalize_url

SITEMAP_PROBE_PATHS: tuple[str, ...] = (
    "/sitemap.xml",
    "/sitemap_index.xml",
)

COMMON_OFFICIAL_PATH_PROBES: tuple[str, ...] = (
    "/admissions",
    "/undergraduate",
    "/undergraduate-admissions",
    "/undergraduate-programmes",
    "/programmes",
    "/degree-programmes",
    "/study/undergraduate",
    "/catalogue",
    "/catalog",
    "/bulletin",
)


def parse_sitemap_urls(xml_text: str, base_url: str | None = None) -> list[str]:
    """Extract canonical URLs from a sitemap XML string.

    This intentionally avoids a heavy XML dependency surface; malformed
    sitemap content simply yields the loc values the regex can prove.
    """

    urls: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"<loc>\s*(.*?)\s*</loc>", xml_text, flags=re.IGNORECASE | re.DOTALL):
        url = canonicalize_url(unescape(match.group(1).strip()), base_url)
        if url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def sitemap_probe_urls(seed_url: str) -> list[str]:
    """Return the small public sitemap probe set for an HTTP(S) seed URL."""

    return _origin_joined_urls(seed_url, SITEMAP_PROBE_PATHS)


def common_official_path_probe_urls(seed_url: str) -> list[str]:
    """Return deterministic official-path probes for admissions/programme discovery."""

    return _origin_joined_urls(seed_url, COMMON_OFFICIAL_PATH_PROBES)


def looks_like_sitemap_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return "sitemap" in path and path.endswith(".xml")


def _origin_joined_urls(seed_url: str, paths: tuple[str, ...]) -> list[str]:
    parsed = urlparse(seed_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    origin = f"{parsed.scheme.lower()}://{parsed.netloc}/"
    return [canonicalize_url(urljoin(origin, path.lstrip("/"))) for path in paths]
