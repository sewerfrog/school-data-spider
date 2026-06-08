"""Simple deterministic evidence/source persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path

from university_admissions_crawler.extractor.schema import AdmissionsData, SourceRecord


def write_source_record(output_dir: str | Path, source: SourceRecord, content: str) -> Path:
    """Persist source metadata and captured content under a hash-named file."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    stem = (source.content_hash or "unhashed")[:16]
    content_path = root / f"{stem}.txt"
    meta_path = root / f"{stem}.json"
    content_path.write_text(content, encoding="utf-8")
    meta_path.write_text(json.dumps(source.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return content_path


def load_previous_result(path: str | Path | None) -> dict | None:
    if path is None:
        return None
    target = Path(path)
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def source_hashes(data: AdmissionsData | dict) -> dict[str, str | None]:
    if isinstance(data, AdmissionsData):
        return {source.source_url: source.content_hash for source in data.sources}
    return {source.get("source_url"): source.get("content_hash") for source in data.get("sources", [])}
