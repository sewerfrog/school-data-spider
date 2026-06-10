import json
from pathlib import Path

from university_admissions_crawler.classifier.page_classifier import classify_page
from university_admissions_crawler.extractor.schema import PageCategory


def test_ntu_admissions_pages_are_not_rejected_by_navigation_noise():
    root = Path("tests/fixtures/saved_sources/ntu")
    by_url = {}
    for meta in (
        root / "347ce27695edcec6.json",
        root / "980551993bc03f86.json",
        root / "5dc9515c773773a2.json",
    ):
        payload = json.loads(meta.read_text(encoding="utf-8"))
        by_url[payload["source_url"]] = (payload, meta.with_suffix(".txt").read_text(encoding="utf-8", errors="replace"))

    checks = {
        "https://www.ntu.edu.sg/admissions/undergraduate/admission-guide/international-qualifications": PageCategory.INTERNATIONAL_REQUIREMENTS,
        "https://www.ntu.edu.sg/admissions/undergraduate/financial-matters/tuition-fees": PageCategory.FEES,
        "https://www.ntu.edu.sg/admissions/undergraduate/scholarships": PageCategory.SCHOLARSHIPS,
    }
    for url, expected in checks.items():
        meta, text = by_url[url]
        assert classify_page(url, meta.get("title"), text).category == expected
