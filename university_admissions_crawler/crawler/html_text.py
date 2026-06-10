"""HTML-to-text helpers for fetcher source normalization."""

from __future__ import annotations

import html as html_lib
import re


def _html_to_text(html: str) -> str:
    text = _main_content_fragment(html)
    text = _remove_html_noise(text)
    text = _tables_to_text(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _strip_tags(value: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", value))


def _main_content_fragment(html: str) -> str:
    for pattern in (
        r"<main\b[^>]*>(.*?)</main>",
        r"<article\b[^>]*>(.*?)</article>",
        r"<(?:div|section)\b[^>]*(?:role|id|class)\s*=\s*[\"'][^\"']*(?:main|content|page-content|body-content)[^\"']*[\"'][^>]*>(.*?)</(?:div|section)>",
    ):
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            fragment = match.group(1)
            if len(_strip_tags(fragment).strip()) >= 80:
                return fragment
    return html


def _remove_html_noise(html: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    for tag in ("script", "style", "noscript", "svg", "canvas", "iframe", "nav", "header", "footer", "aside"):
        text = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    noisy_attr = (
        "breadcrumb|cookie|consent|banner|global|nav|menu|mega|header|footer|"
        "sidebar|social|share|skip|search|modal|popup|toolbar|utility"
    )
    pattern = rf"<(?P<tag>div|section|form|ul|ol)\b[^>]*(?:class|id|role|aria-label)\s*=\s*[\"'][^\"']*(?:{noisy_attr})[^\"']*[\"'][^>]*>.*?</(?P=tag)>"
    previous = None
    while previous != text:
        previous = text
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE | re.DOTALL)
    return text


def _tables_to_text(html: str) -> str:
    def replace_table(match: re.Match) -> str:
        rows: list[str] = []
        for row_match in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", match.group(1), flags=re.IGNORECASE | re.DOTALL):
            cells = [
                re.sub(r"\s+", " ", _strip_tags(cell_match.group(1))).strip()
                for cell_match in re.finditer(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_match.group(1), flags=re.IGNORECASE | re.DOTALL)
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(" | ".join(cells))
        return " . ".join(rows)

    return re.sub(r"<table\b[^>]*>(.*?)</table>", replace_table, html, flags=re.IGNORECASE | re.DOTALL)
