"""Lightweight deterministic parsing for cleaned admissions candidates."""

from __future__ import annotations

import re
import html as html_lib
from typing import Any


PARSED = "parsed"
RAW_NEEDS_REVIEW = "raw_needs_manual_review"
UNPARSED = "unparsed"


def parse_english_tests(raw_text: str) -> tuple[list[dict[str, Any]], str]:
    """Extract structured English test scores from a short requirement snippet."""

    cleaned = _clean(raw_text)
    if not cleaned:
        return [], UNPARSED
    if _has_exemption_rule(cleaned):
        return [{"rule_type": "exemption_or_waiver", "raw_text": cleaned}], PARSED

    out: list[dict[str, Any]] = []
    for test_name, pattern in (
        ("IELTS", r"\bIELTS\b"),
        ("TOEFL iBT", r"\bTOEFL(?:\s+iBT)?\b"),
        ("PTE Academic", r"\bPTE\s+Academic\b|\bPTE\b"),
        ("HKDSE English", r"\bHKDSE\s+English\b|\bHK\s*DSE\s+English\b"),
        ("Cambridge English", r"\bCambridge\b|\bC1\s+Advanced\b|\bC2\s+Proficiency\b|\bCAE\b"),
        ("SAT", r"\bSAT\b"),
        ("ACT", r"\bACT\b"),
        ("MUET", r"\bMUET\b"),
    ):
        for match in re.finditer(pattern, cleaned, flags=re.IGNORECASE):
            window = _clause_around(cleaned, match.start(), match.end())
            parsed = _parse_english_window(test_name, window)
            if parsed is None and len(window) < len(match.group(0)) + 12:
                window = _window_around(cleaned, match.start(), match.end(), before=80, after=120)
                parsed = _parse_english_window(test_name, window)
            if parsed:
                out.append(parsed)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in out:
        key = (
            item.get("test_name"),
            item.get("overall_score"),
            tuple(sorted((item.get("component_scores") or {}).items())),
            item.get("raw_text"),
        )
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped, PARSED if deduped else RAW_NEEDS_REVIEW


def has_english_score_or_rule(raw_text: str) -> bool:
    parsed, status = parse_english_tests(raw_text)
    return status == PARSED and bool(parsed)


def parse_money_candidates(raw_text: str) -> tuple[list[dict[str, Any]], str]:
    """Extract currency/amount rows from fee text while preserving row context."""

    cleaned = _clean(raw_text)
    if not cleaned:
        return [], UNPARSED
    money_pattern = re.compile(
        r"(?P<currency>HKD|HK\$|S\$|SGD|USD|US\$|\$)\s*(?P<amount>[0-9][0-9,]*(?:\.[0-9]+)?)",
        flags=re.IGNORECASE,
    )
    items: list[dict[str, Any]] = []
    for match in money_pattern.finditer(cleaned):
        row = _fee_context(cleaned, match.start(), match.end())
        item = {
            "currency": _normalise_currency(match.group("currency"), row),
            "amount": int(match.group("amount").replace(",", "").split(".", 1)[0]),
            "student_group": _student_group(row),
            "academic_year": _academic_year(row),
            "cohort": _cohort(row),
            "billing_period": _billing_period(row),
            "fee_type": _fee_type(row),
            "raw_text": row,
        }
        items.append(item)
    return items, PARSED if items else RAW_NEEDS_REVIEW


def parse_application_dates(raw_text: str) -> tuple[dict[str, Any], str]:
    """Parse common admissions date snippets into open/deadline fields."""

    cleaned = _clean(raw_text)
    if not cleaned:
        return {}, UNPARSED
    date = r"[0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}(?:,\s*[0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)?"
    parsed: dict[str, Any] = {"raw_text": cleaned}
    range_match = re.search(rf"({date})\s*(?:-|to|until|through|–)\s*({date})", cleaned, flags=re.IGNORECASE)
    if range_match:
        parsed["open_date"] = _clean(range_match.group(1))
        parsed["deadline"] = _clean(range_match.group(2))
    else:
        deadline_match = re.search(rf"({date})", cleaned, flags=re.IGNORECASE)
        if deadline_match:
            if re.search(r"\b(?:start|open|from)\b", cleaned, flags=re.IGNORECASE):
                parsed["open_date"] = _clean(deadline_match.group(1))
            else:
                parsed["deadline"] = _clean(deadline_match.group(1))
    round_match = re.search(r"\b(first[- ]round|main round|early round|regular round|rolling)\b", cleaned, flags=re.IGNORECASE)
    if round_match:
        parsed["round"] = _clean(round_match.group(1))
    group_match = re.search(r"\b(JUPAS|Non-JUPAS|International|Mainland|Senior Year|Local|Non-local)\b", cleaned, flags=re.IGNORECASE)
    if group_match:
        parsed["applicant_group"] = _clean(group_match.group(1))
    intake_match = re.search(r"\b(?:Sept(?:ember)?|Jan(?:uary)?|Aug(?:ust)?)\s+[0-9]{4}\s+Entry\b", cleaned, flags=re.IGNORECASE)
    if intake_match:
        parsed["intake"] = _clean(intake_match.group(0))
    return parsed, PARSED if any(key in parsed for key in ("open_date", "deadline")) else RAW_NEEDS_REVIEW


def _parse_english_window(test_name: str, raw_window: str) -> dict[str, Any] | None:
    window = _clean(raw_window)
    if not _score_context(window):
        return None
    overall = _overall_score(test_name, window)
    components = _component_scores(window)
    if overall is None and not components:
        return None
    return {
        "test_name": test_name,
        "overall_score": overall,
        "component_scores": components,
        "raw_text": window,
        "confidence": "medium",
    }


def _overall_score(test_name: str, window: str) -> float | int | str | None:
    number = r"([0-9]{1,4}(?:\.[0-9])?)"
    first_token = re.escape(test_name.split()[0])
    qualifier = r"(?:overall\s+band\s+of|overall\s+score\s+of|overall\s+of|overall|minimum\s+of\s+overall|minimum\s+overall\s+score\s+of|minimum\s+overall\s+of|minimum\s+overall|minimum\s+of\s+composite\s+score\s+of|minimum\s+composite\s+score\s+of|composite\s+score\s+of|minimum\s+of|at\s+least|minimum)"
    before_patterns = [
        rf"{qualifier}\s+{number}\s*(?:in|for)?\s*(?:the\s+)?{first_token}\b",
        rf"{qualifier}\s+{number}\b[^;|]{{0,100}}?{first_token}\b",
        rf"(?:at\s+least|minimum(?:\s+of)?)\s+{number}\s+(?:overall|score)",
    ]
    after_patterns = [
        rf"{first_token}\b[^.;|]{{0,120}}?{qualifier}\s*{number}",
        rf"{first_token}\b\s*{number}\s*(?:overall|minimum|score|band)?",
        rf"{first_token}\b\s*\([^)]*?(?:overall|minimum(?:\s+of)?|at\s+least|composite\s+score\s+of)\s*{number}",
    ]
    for pattern in before_patterns + after_patterns:
        match = re.search(pattern, window, flags=re.IGNORECASE)
        if match:
            return _number(match.group(1))
    return None


def _component_scores(window: str) -> dict[str, float | int | str]:
    components: dict[str, float | int | str] = {}
    for component in ("writing", "speaking", "reading", "listening", "verbal"):
        match = re.search(rf"\b{component}\s*(?:score\s*)?(?:of\s*)?([0-9]{{1,4}}(?:\.[0-9])?|[A-E][0-9]?)\b", window, flags=re.IGNORECASE)
        if match:
            components[component] = _number(match.group(1))
    subtest_match = re.search(r"\b(?:no\s+)?(?:subtest|component)\s+(?:below|less\s+than|under|at\s+least)\s*([0-9]{1,4}(?:\.[0-9])?)", window, flags=re.IGNORECASE)
    if subtest_match:
        components["minimum_component"] = _number(subtest_match.group(1))
    return components


def _score_context(value: str) -> bool:
    lower = value.lower()
    if any(token in lower for token in ("at least", "minimum", "overall", "score", "band", "writing", "speaking", "reading", "listening", "verbal")):
        return bool(re.search(r"[0-9]", value))
    return bool(re.search(r"\b[A-E][0-9]?\b", value)) and "grade" in lower


def _has_exemption_rule(value: str) -> bool:
    lower = value.lower()
    return any(token in lower for token in ("exempt", "exemption", "waiver", "waived")) and any(
        token in lower for token in ("english", "ielts", "toefl", "pte", "medium of instruction")
    )


def _fee_context(text: str, start: int, end: int) -> str:
    before = max(
        text.rfind(".", 0, start),
        text.rfind("|", 0, start),
        text.rfind(" Left Column ", 0, start),
        text.rfind(" Middle Column ", 0, start),
        text.rfind(" Right Column ", 0, start),
    )
    after_candidates = [
        pos for pos in (
            text.find(".", end),
            text.find("|", end),
            text.find(" Left Column ", end),
            text.find(" Middle Column ", end),
            text.find(" Right Column ", end),
        )
        if pos != -1
    ]
    after = min(after_candidates) if after_candidates else min(len(text), end + 220)
    row = text[before + 1 : after].strip()
    if len(row) > 360:
        row = text[max(0, start - 120) : min(len(text), end + 220)].strip()
    return _clean(row)


def _normalise_currency(currency: str, context: str) -> str:
    upper = currency.upper()
    if upper in {"HKD", "HK$"}:
        return "HKD"
    if upper in {"SGD", "S$"}:
        return "SGD"
    if upper in {"USD", "US$"}:
        return "USD"
    if upper == "$":
        lower = context.lower()
        if "hong kong" in lower or "hkd" in lower or "hk$" in lower:
            return "HKD"
        if "singapore" in lower or "sgd" in lower or "s$" in lower:
            return "SGD"
        return "unknown"
    return upper


def _student_group(context: str) -> str | None:
    lower = context.lower()
    if "non-local" in lower or "international" in lower:
        if "stem" in lower and "non-stem" not in lower:
            return "non-local STEM"
        if "non-stem" in lower:
            return "non-local non-STEM"
        return "non-local"
    if "local" in lower or "singapore citizen" in lower:
        return "local"
    if "permanent resident" in lower:
        return "permanent resident"
    return None


def _academic_year(context: str) -> str | None:
    match = re.search(r"\b(?:AY|academic year)\s*([0-9]{4}\s*[/\\-]\s*[0-9]{2,4})\b", context, flags=re.IGNORECASE)
    return re.sub(r"\s+", "", match.group(1)).replace("-", "/") if match else None


def _cohort(context: str) -> str | None:
    match = re.search(r"\(([0-9]{4}\s*-\s*[0-9]{2,4}\s+cohort)\)", context, flags=re.IGNORECASE)
    return _clean(match.group(1)) if match else None


def _billing_period(context: str) -> str | None:
    lower = context.lower()
    if "per academic year" in lower:
        return "per academic year"
    if "per annum" in lower:
        return "per annum"
    if "per year" in lower or "annual" in lower:
        return "per year"
    if "semester" in lower:
        return "per semester"
    return None


def _fee_type(context: str) -> str:
    lower = context.lower()
    if "application fee" in lower:
        return "application_fee"
    if "tuition" in lower:
        return "tuition"
    if "miscellaneous" in lower:
        return "miscellaneous_fee"
    return "fee"


def _window_around(text: str, start: int, end: int, *, before: int, after: int) -> str:
    left = max(0, start - before)
    right = min(len(text), end + after)
    return text[left:right]


def _clause_around(text: str, start: int, end: int) -> str:
    lower = text.lower()
    left_candidates = [0]
    right_candidates = [len(text)]
    for delimiter in (" or ", ";", "[back to top]"):
        pos = lower.rfind(delimiter, 0, start)
        if pos != -1:
            left_candidates.append(pos + len(delimiter))
        pos = lower.find(delimiter, end)
        if pos != -1:
            right_candidates.append(pos)
    for pos in _sentence_period_positions(text):
        if pos < start:
            left_candidates.append(pos + 1)
        elif pos >= end:
            right_candidates.append(pos)
    left = max(left_candidates)
    right = min(right_candidates)
    return text[left:right]


def _sentence_period_positions(text: str):
    for match in re.finditer(r"\.", text):
        pos = match.start()
        prev_char = text[pos - 1] if pos > 0 else ""
        next_char = text[pos + 1] if pos + 1 < len(text) else ""
        if prev_char.isdigit() and next_char.isdigit():
            continue
        yield pos


def _number(value: str) -> float | int | str:
    cleaned = value.strip()
    if re.fullmatch(r"[0-9]+", cleaned):
        return int(cleaned)
    if re.fullmatch(r"[0-9]+\.[0-9]+", cleaned):
        return float(cleaned)
    return cleaned


def _clean(value: str) -> str:
    value = html_lib.unescape(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip(" ;,.")
