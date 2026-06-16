"""Admission-context URL and text gates used before field extraction."""

from __future__ import annotations

from urllib.parse import urlparse


UNDERGRAD_ADMISSIONS_PATH_HINTS = (
    "/admission",
    "/admissions",
    "/study/ug",
    "/undergraduate",
    "/ug/",
    "/apply",
    "/jupas",
    "/non-jupas",
    "/requirements",
    "/qualifications",
    "/fees-and-scholarships",
)

EXPLICIT_UNDERGRAD_PATH_HINTS = (
    "/study/ug",
    "/undergraduate",
    "/undergraduate-education",
    "/ug/",
    "/jupas",
    "/non-jupas",
)

NON_ADMISSIONS_PATH_HINTS = (
    "/current-students",
    "/education",
    "/research",
    "/gs/",
    "/graduate",
    "/graduates",
    "/postgraduate",
    "/postgraduates",
    "/sao/",
    "/student-affairs",
    "/hall-admission",
    "/accommodation",
    "/residential-life",
    "/life-at-ntu/accommodation",
    "/search-results",
    "/privacy",
    "/human-resources",
    "/finance-office",
    "/contact-us/form",
    "/alumni",
    "/news",
    "/giving",
    "/jobs",
    "/careers",
)

ENGLISH_REQUIREMENT_TEXT_HINTS = (
    "english language requirement",
    "english language requirements",
    "english proficiency",
    "english language proficiency",
    "minimum english",
    "ielts",
    "toefl",
    "pte academic",
    "hk dse english",
    "hkdse english",
    "cambridge c1",
    "cambridge c2",
    "c1 advanced",
    "c2 proficiency",
)

ENGLISH_FALSE_POSITIVE_HINTS = (
    "english language centre",
    "english and applied linguistics",
    "quick links",
    "current students",
    "summer programme website",
    "institute for higher education research",
)


def has_undergraduate_admissions_context(url: str, title: str | None, text: str = "") -> bool:
    lower_url = url.lower()
    title_lower = (title or "").lower()
    text_head = text[:1200].lower()
    path = urlparse(url).path.lower()
    has_explicit_undergrad_path = any(hint in path for hint in EXPLICIT_UNDERGRAD_PATH_HINTS)
    if any(hint in path for hint in NON_ADMISSIONS_PATH_HINTS) and not has_explicit_undergrad_path:
        return False
    if has_explicit_undergrad_path:
        return True
    if any(hint in path for hint in ("/admission", "/admissions", "/apply", "/requirements", "/qualifications", "/fees-and-scholarships")):
        if any(token in f"{title_lower} {text_head}" for token in ("undergraduate", "jupas", "non-jupas", "bachelor", "freshmen", "freshman")):
            return True
    if "undergraduate admissions" in title_lower or "undergraduate admissions" in text_head:
        return True
    if "admissions" in lower_url and "undergraduate" in f"{title_lower} {text_head}":
        return True
    return False


def has_undergraduate_fee_context(url: str, title: str | None, text: str) -> bool:
    if not has_undergraduate_admissions_context(url, title, text):
        return False
    path = urlparse(url).path.lower()
    title_lower = (title or "").lower()
    url_title_path = f"{url} {title_lower} {path}"
    if any(token in url_title_path for token in ("hall fee", "hall fees", "phd fellowship", "graduate tuition", "postgraduate", "residential life", "/graduate", "/postgraduate", "/current-students", "/sao/", "/hall-admission")):
        return False
    haystack = f"{url} {title_lower} {text[:1800]}".lower()
    return any(token in haystack for token in ("tuition", "application fee", "fees", "fee"))


def has_undergraduate_scholarship_context(url: str, title: str | None, text: str) -> bool:
    if not has_undergraduate_admissions_context(url, title, text):
        return False
    haystack = f"{url} {title or ''} {text[:1800]}".lower()
    if any(token in haystack for token in ("phd fellowship", "graduate school", "postgraduate", "research postgraduate")):
        return False
    return "scholarship" in haystack or "financial aid" in haystack


def has_admissions_contact_context(url: str, title: str | None, text: str) -> bool:
    if not has_undergraduate_admissions_context(url, title, text):
        return False
    haystack = f"{url} {title or ''} {text[:1600]}".lower()
    if any(token in haystack for token in ("privacy", "personal information collection statement", "data access and correction", "/contact-us/form")):
        return False
    return any(token in haystack for token in ("admissions office", "admission matters", "admissions matters", "contact us", "enquiry", "enquiries"))


def has_english_requirement_context(url: str, title: str | None, text: str) -> bool:
    if not has_undergraduate_admissions_context(url, title, text):
        return False
    haystack = f"{url} {title or ''} {text[:2500]}".lower()
    if any(hint in haystack for hint in ENGLISH_FALSE_POSITIVE_HINTS):
        return False
    return any(hint in haystack for hint in ENGLISH_REQUIREMENT_TEXT_HINTS)
