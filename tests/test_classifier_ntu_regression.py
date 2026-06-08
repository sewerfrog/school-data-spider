import json
from pathlib import Path

from university_admissions_crawler.classifier.page_classifier import classify_page
from university_admissions_crawler.extractor.schema import PageCategory


def test_ntu_admissions_pages_are_not_rejected_by_navigation_noise():
    root = Path("outputs/batch/ntu/sources")
    if not root.exists():
        return
    by_url = {}
    for meta in root.glob("*.json"):
        payload = json.loads(meta.read_text(encoding="utf-8"))
        by_url[payload["source_url"]] = (payload, meta.with_suffix(".txt").read_text(encoding="utf-8", errors="replace"))

    checks = {
        "https://www.ntu.edu.sg/admissions/undergraduate/admission-guide/international-qualifications": PageCategory.INTERNATIONAL_REQUIREMENTS,
        "https://www.ntu.edu.sg/admissions/undergraduate/financial-matters/tuition-fees": PageCategory.FEES,
        "https://www.ntu.edu.sg/admissions/undergraduate/scholarships": PageCategory.SCHOLARSHIPS,
    }
    for url, expected in checks.items():
        if url not in by_url:
            continue
        meta, text = by_url[url]
        assert classify_page(url, meta.get("title"), text).category == expected
