"""JSON content helpers used by fetch adapters."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin


def json_to_text(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def extract_json_links(text: str, base_url: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    links: list[str] = []
    for value in walk_json_values(payload):
        if isinstance(value, str) and looks_like_link(value):
            links.append(urljoin(base_url, value))
    return dedupe_preserve_order(links)


def walk_json_values(value: Any):
    if isinstance(value, dict):
        for subvalue in value.values():
            yield from walk_json_values(subvalue)
        return
    if isinstance(value, list):
        for subvalue in value:
            yield from walk_json_values(subvalue)
        return
    yield value


def looks_like_link(value: str) -> bool:
    stripped = value.strip()
    if stripped.startswith(("http://", "https://", "/")):
        return True
    return bool(re.search(r"\.(?:html?|pdf|json)(?:[?#].*)?$", stripped, flags=re.IGNORECASE))


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


_json_to_text = json_to_text
_extract_json_links = extract_json_links
_walk_json_values = walk_json_values
_looks_like_link = looks_like_link
_dedupe_preserve_order = dedupe_preserve_order
