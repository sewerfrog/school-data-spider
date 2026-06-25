"""Rule-based page classification for the offline MVP."""

from __future__ import annotations

from dataclasses import dataclass, field

from university_admissions_crawler.crawler.admissions_context import has_english_requirement_context, has_undergraduate_admissions_context
from university_admissions_crawler.extractor.schema import PageCategory


@dataclass(slots=True)
class Classification:
    category: PageCategory
    score: int
    signals: list[str] = field(default_factory=list)


LOW_CONFIDENCE_SCORE_THRESHOLD = 1


KEYWORDS: dict[PageCategory, tuple[str, ...]] = {
    PageCategory.UNDERGRADUATE_ADMISSIONS: ("undergraduate admissions", "admissions", "apply", "how to apply"),
    PageCategory.INTERNATIONAL_REQUIREMENTS: ("international requirements", "international applicants", "international", "requirements"),
    PageCategory.APPLICATION_DEADLINES: ("deadline", "deadlines", "apply by", "application period", "closing date"),
    PageCategory.ACCEPTED_QUALIFICATIONS: ("accepted qualification", "accepted qualifications", "qualification", "a-level", "ib diploma"),
    PageCategory.PROGRAMME_LIST: (
        "programmes",
        "programs",
        "degrees",
        "degree",
        "undergraduate programmes",
        "undergraduate education",
        "degree programmes",
        "degree programs",
        "majors",
        "minors",
        "bulletin",
        "catalogue",
        "catalog",
    ),
    PageCategory.PROGRAMME_PREREQUISITES: ("prerequisite", "prerequisites", "required for", "requires mathematics", "mathematics required"),
    PageCategory.FEES: ("tuition", "fees", "fee"),
    PageCategory.SCHOLARSHIPS: ("scholarship", "scholarships", "financial aid"),
    PageCategory.VISA: ("visa", "student pass", "immigration"),
    PageCategory.HOUSING: ("housing", "accommodation", "residence"),
    PageCategory.CONTACT: ("contact", "email", "phone", "admissions office"),
}

NEGATIVE = ("alumni", "news", "donate", "giving", "staff", "jobs", "blog")

STRONG_ADMISSIONS_SIGNALS = (
    "/admissions/",
    "/admission/",
    "undergraduate admissions",
    "admissions office",
    "admission guide",
    "international qualifications",
    "international requirements",
    "tuition fees",
    "scholarships",
    "student pass",
    "undergraduate housing",
    "undergraduate programmes",
    "undergraduate education",
)

STRONG_IRRELEVANT_PATHS = (
    "/news/",
    "/alumni/",
    "/giving/",
    "/donate",
    "/jobs",
    "/careers",
    "/staff/",
    "/blog/",
)


def classify_page(url: str, title: str | None, text: str) -> Classification:
    haystack = f"{url} {title or ''} {text}".lower()
    url_lower = url.lower()
    title_lower = (title or "").lower()
    negative_hits = [kw for kw in NEGATIVE if kw in haystack]
    if _is_strongly_irrelevant(url_lower, title_lower, haystack, negative_hits):
        return Classification(PageCategory.IRRELEVANT, -len(negative_hits), negative_hits)
    if _is_contextually_irrelevant(url, title, text):
        return Classification(PageCategory.IRRELEVANT, 0, ["non-admissions-context"])

    best = Classification(PageCategory.IRRELEVANT, 0, [])
    for category, words in KEYWORDS.items():
        signals = [word for word in words if word in haystack]
        score = len(signals)
        if title and any(word in title.lower() for word in words):
            score += 2
        if any(word.replace(" ", "-") in url.lower() or word.replace(" ", "_") in url.lower() for word in words):
            score += 1
        if category == PageCategory.INTERNATIONAL_REQUIREMENTS and "english" in haystack and has_english_requirement_context(url, title, text):
            score += 1
            signals.append("english")
        if category == PageCategory.APPLICATION_DEADLINES and any(token in haystack for token in ("2026", "2027", "2028")):
            score += 1
            signals.append("year")
        if category == PageCategory.PROGRAMME_PREREQUISITES and "pdf" in url.lower():
            score += 1
            signals.append("pdf")
        if score > best.score:
            best = Classification(category, score, signals)
    return best


def is_low_confidence_classification(classification: Classification, threshold: int = LOW_CONFIDENCE_SCORE_THRESHOLD) -> bool:
    """Return whether a rule classification is weak enough for assistive diagnostics."""

    return 0 <= classification.score <= threshold


def _is_contextually_irrelevant(url: str, title: str | None, text: str) -> bool:
    lower = f"{url} {title or ''}".lower()
    if any(token in lower for token in ("/current-students", "/education", "/research", "/gs/", "/graduate", "/postgraduate", "/sao/", "/student-affairs", "/hall-admission", "/accommodation", "/search-results", "/contact-us/form")):
        return not has_undergraduate_admissions_context(url, title, text)
    return False


def _is_strongly_irrelevant(url: str, title: str, haystack: str, negative_hits: list[str]) -> bool:
    if not negative_hits:
        return False
    if any(signal in url or signal in title for signal in STRONG_ADMISSIONS_SIGNALS):
        return False
    if any(path in url for path in STRONG_IRRELEVANT_PATHS):
        return True
    if "news" in title and not any(signal in title for signal in ("admission", "undergraduate", "scholarship")):
        return True
    if any(strong in haystack for strong in ("undergraduate admissions", "admissions office")):
        return False
    return len(negative_hits) >= 3
