"""Helpers for writing scan output artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from university_admissions_crawler.extractor.schema import AdmissionsData
from university_admissions_crawler.reports.programme_catalog_csv import write_programme_catalog_csv
from university_admissions_crawler.reports.render_report import render_markdown_report


def write_result_files(data: AdmissionsData, output_dir: str | Path) -> tuple[Path, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / "result.json"
    report_path = out_dir / "report.md"
    result_path.write_text(json.dumps(data.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(render_markdown_report(data), encoding="utf-8")
    write_programme_catalog_csv(data, out_dir)
    return result_path, report_path
