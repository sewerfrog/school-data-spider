"""University scan config loading for batch runs."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class UniversityConfig:
    id: str
    name: str
    seed_urls: list[str]
    allowed_domains: set[str] = field(default_factory=set)
    allowed_hosts: set[str] = field(default_factory=set)
    max_pages: int | None = None
    max_depth: int | None = None
    mode: str = "live-http"


def load_university_configs(path: str | Path) -> list[UniversityConfig]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "universities" in payload:
        items = payload["universities"]
    elif isinstance(payload, list):
        items = payload
    else:
        items = [payload]
    return [_parse_config(item) for item in items]


def _parse_config(item: dict[str, Any]) -> UniversityConfig:
    seed_urls = item.get("seed_urls") or item.get("seeds") or ([item["seed_url"]] if item.get("seed_url") else [])
    if not seed_urls:
        raise ValueError(f"University config {item.get('id') or item.get('name') or '<unknown>'} has no seed_urls.")
    name = item.get("name") or item.get("id")
    if not name:
        raise ValueError("University config needs name or id.")
    return UniversityConfig(
        id=item.get("id") or _slugify(name),
        name=name,
        seed_urls=list(seed_urls),
        allowed_domains=set(item.get("allowed_domains", [])),
        allowed_hosts=set(item.get("allowed_hosts", [])),
        max_pages=item.get("max_pages"),
        max_depth=item.get("max_depth"),
        mode=item.get("mode", "live-http"),
    )


def _slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "university"
