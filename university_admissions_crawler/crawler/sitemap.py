"""Small sitemap parser used by future live/static discovery paths."""

from __future__ import annotations

import re
from html import unescape

from university_admissions_crawler.crawler.filters import canonicalize_url


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
