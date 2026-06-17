"""Small deterministic extractor for fixture/offline MVP."""

from __future__ import annotations

import re

from university_admissions_crawler.evidence.provenance import evidence_from_source
from university_admissions_crawler.extractor.schema import ClaimStatus, Confidence, EvidenceItem, FieldValue, RequirementRecord, SourceRecord, SourceType
from university_admissions_crawler.extractor.structured import (
    PARSED,
    RAW_NEEDS_REVIEW,
    parse_application_dates,
    parse_english_tests,
    parse_money_candidates,
)


def extract_deadline(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    date = r"[0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}(?:,\s*[0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)?"
    patterns = (
        rf"((?:application period|application window)[:\s|]+({date})\s*(?:-|to|until|through|–)\s*({date}))",
        rf"((?:apply from|applications? open)[:\s]+({date})\s*(?:-|to|until|through|–)\s*({date}))",
        rf"((?:apply by|deadline|closing date(?:\s+on)?|application deadline)[:\s]+({date}))",
    )
    match = None
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            break
    if not match:
        return None, []
    snippet = _clean_sentence(match.group(1))
    dates = [part for part in match.groups()[1:] if part]
    value = " to ".join(_clean_sentence(part) for part in dates) if len(dates) > 1 else _clean_sentence(dates[0])
    parsed, parse_status = parse_application_dates(snippet)
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.HIGH)
    return (
        RequirementRecord(
            label="application deadline",
            value=FieldValue(value=value, raw_text=snippet, parsed=parsed, parse_status=parse_status, status=ClaimStatus.KNOWN, confidence=Confidence.HIGH, evidence=[claim_path]),
        ),
        [evidence],
    )


def extract_english_requirement(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    lower = text.lower()
    if not re.search(r"\b(?:english language requirements?|english proficiency|english language proficiency|ielts|toefl|pte academic|hkdse english|hk dse english|cambridge c1|cambridge c2|c1 advanced|c2 proficiency)\b", lower):
        return None, []
    snippet = _english_snippet(text)
    if not snippet or len(snippet) > 900:
        return None, []
    parsed, parse_status = parse_english_tests(snippet)
    if parse_status != PARSED:
        return None, []
    if _looks_like_hard_false_english_requirement(snippet):
        return None, []
    value = _clean_sentence(_english_value_from_parsed(snippet, parsed))
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=value, confidence=Confidence.MEDIUM)
    return (
        RequirementRecord(
            label="english language requirement",
            value=FieldValue(value=value, raw_text=value, parsed=parsed, parse_status=parse_status, status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[claim_path]),
        ),
        [evidence],
    )


def extract_accepted_qualification(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    match = re.search(r"((?:Accepted qualifications?|Qualifications? accepted)[^.]*\.)", text, re.IGNORECASE)
    if not match:
        match = re.search(r"((?:A-level|IB Diploma|International Baccalaureate)[^.]*accepted[^.]*\.)", text, re.IGNORECASE)
    if not match:
        return None, []
    snippet = match.group(1).strip()
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM)
    return (
        RequirementRecord(
            label="accepted qualification",
            value=FieldValue(value=_clean_sentence(snippet), status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[claim_path]),
        ),
        [evidence],
    )


def extract_programme(text: str, source: SourceRecord, claim_path: str) -> tuple[str | None, list[EvidenceItem]]:
    programmes = extract_programmes(text, source, claim_path.rsplit("/", 1)[0].rsplit("/", 1)[0] or "/programmes")
    if not programmes:
        return None, []
    programme, evidence = programmes[0]
    evidence[0].claim_path = claim_path
    programme.name.evidence = [claim_path]
    programme.evidence = [claim_path]
    return str(programme.name.value), evidence


def extract_programmes(text: str, source: SourceRecord, base_path: str, start_index: int = 0) -> list[tuple["ProgrammeRecord", list[EvidenceItem]]]:
    from university_admissions_crawler.extractor.schema import ProgrammeRecord

    out: list[tuple[ProgrammeRecord, list[EvidenceItem]]] = []
    pattern = re.compile(
        r"\b((?:Bachelor|BSc|BA|BEng|LLB|MBBS|BBA|BAcc)\s+(?:of|in)?\s*[A-Z][A-Za-z&/(),\- ]{2,90}?)(?=\s+(?:requires?|needs?|must)\b|[.;\n]|$)",
        re.IGNORECASE,
    )
    seen: set[str] = set()
    for match in pattern.finditer(text):
        name = _clean_programme_name(match.group(1))
        if not name or len(name.split()) < 2:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        index = start_index + len(out)
        claim_path = f"{base_path}/{index}/name"
        snippet = _clean_sentence(match.group(0))
        evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM)
        programme = ProgrammeRecord(
            name=FieldValue(value=name, status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[claim_path]),
            source_url=source.source_url,
            evidence=[claim_path],
        )
        out.append((programme, [evidence]))
    return out


def extract_prerequisite(text: str, source: SourceRecord, claim_path: str, page_number: int | None = None) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    match = re.search(r"(Mathematics required[^.]*\.)", text, re.IGNORECASE)
    if match:
        snippet = match.group(1)
    else:
        match = re.search(r"(requires Mathematics[^.]*\.)", text, re.IGNORECASE)
        if not match:
            return None, []
        snippet = match.group(1)
    evidence = evidence_from_source(
        claim_path=claim_path,
        source=source,
        snippet=snippet,
        confidence=Confidence.MEDIUM,
        page_number=page_number if page_number is not None else source.page_number,
    )
    return (
        RequirementRecord(
            label="mathematics prerequisite",
            value=FieldValue(value="Mathematics required", status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[claim_path]),
        ),
        [evidence],
    )


def extract_fee(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    match = re.search(
        r"((?:(?:Tuition|Fees?|International undergraduate|Domestic undergraduate|Singapore citizen|Permanent resident)[^.\n|]*?(?:USD|SGD|S\$|\$|per year|per annum|annual|semester)[^.\n]*\.?)|(?:(?:USD|SGD|S\$|\$)\s?[0-9][0-9,]*(?:\s*(?:per year|per annum|annual|semester))?))",
        text,
        re.IGNORECASE,
    )
    snippet = match.group(1).strip() if match else _fee_table_reference_snippet(text, source)
    if not snippet:
        return None, []
    parsed, parse_status = parse_money_candidates(snippet)
    if match and parse_status == RAW_NEEDS_REVIEW and _fee_snippet_requires_number(snippet):
        snippet = _fee_table_reference_snippet(text, source)
        if not snippet:
            return None, []
        parsed, parse_status = parse_money_candidates(snippet)
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM)
    return _requirement("tuition/fees", _clean_sentence(snippet), claim_path, parsed=parsed, parse_status=parse_status), [evidence]


def extract_scholarship(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    match = re.search(r"((?:Scholarships?|Financial aid)[^.]*\.)", text, re.IGNORECASE)
    if not match:
        return None, []
    snippet = match.group(1).strip()
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM)
    return _requirement("scholarship", _clean_sentence(snippet), claim_path), [evidence]


def extract_visa(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    match = re.search(r"((?:Visa|Student pass|Immigration)[^.]*\.)", text, re.IGNORECASE)
    if not match:
        return None, []
    snippet = match.group(1).strip()
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM)
    return _requirement("visa/student pass", _clean_sentence(snippet), claim_path), [evidence]


def extract_housing(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    match = re.search(r"((?:Housing|Accommodation|Residence)[^.]*\.)", text, re.IGNORECASE)
    if not match:
        return None, []
    snippet = match.group(1).strip()
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM)
    return _requirement("housing/accommodation", _clean_sentence(snippet), claim_path), [evidence]


def extract_contact(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    if _looks_like_non_admissions_contact(source.source_url, source.title, text):
        return None, []
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    phone_match = re.search(r"(?:phone|tel)[:\s]+([+()0-9][+()0-9\-\s]{5,})", text, re.IGNORECASE)
    if not email_match and not phone_match:
        return None, []
    snippet = _sentence_with(text, email_match.group(0) if email_match else phone_match.group(1)) or (email_match.group(0) if email_match else phone_match.group(0))
    value = email_match.group(0) if email_match else phone_match.group(1).strip()
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM)
    return _requirement("admissions contact", value, claim_path), [evidence]


def extract_required_document(text: str, source: SourceRecord, claim_path: str) -> tuple[RequirementRecord | None, list[EvidenceItem]]:
    match = re.search(r"((?:Required documents?|Documents required)[^.]*\.)", text, re.IGNORECASE)
    if not match:
        return None, []
    snippet = match.group(1).strip()
    evidence = evidence_from_source(claim_path=claim_path, source=source, snippet=snippet, confidence=Confidence.MEDIUM)
    return _requirement("required documents", _clean_sentence(snippet), claim_path), [evidence]


def _sentence_with(text: str, needle: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if needle.lower() in sentence.lower():
            return sentence.strip()
    return None


def _english_snippet(text: str) -> str | None:
    safe_text = r"(?:[0-9]\.[0-9]|[^.\n])"
    patterns = (
        rf"(?:English language requirements?|English proficiency|English language proficiency){safe_text}{{0,260}}(?:IELTS|TOEFL|PTE|HKDSE|HK DSE|Cambridge|minimum|required|requirement|qualification|exempt|waiver){safe_text}{{0,260}}\.?",
        rf"(?:IELTS|TOEFL|PTE Academic|HKDSE English|HK DSE English|C1 Advanced|C2 Proficiency|Cambridge C1|Cambridge C2){safe_text}{{0,220}}(?:[0-9]{{1,3}}(?:\.[0-9])?|minimum|required|requirement|qualification|exempt|waiver){safe_text}{{0,220}}\.?",
    )
    scored_snippets: list[tuple[int, int, str]] = []
    for test_match in re.finditer(r"\b(?:IELTS|TOEFL(?:\s+iBT)?|PTE\s+Academic|SAT|ACT|MUET|C1\s+Advanced|C2\s+Proficiency|Cambridge English Advanced|CAE)\b", text, flags=re.IGNORECASE):
        snippet = _clean_sentence(text[max(0, test_match.start() - 260) : min(len(text), test_match.end() + 620)])
        parsed, parse_status = parse_english_tests(snippet)
        if parse_status == PARSED and parsed:
            scored_snippets.append((len(parsed), len(snippet), snippet))
    if scored_snippets:
        return sorted(scored_snippets, key=lambda item: (-item[0], item[1]))[0][2]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_sentence(match.group(0))
    return None


def _looks_like_false_english_requirement(snippet: str) -> bool:
    lower = snippet.lower()
    if _looks_like_hard_false_english_requirement(snippet):
        return True
    if lower.count(" bachelor ") >= 2 or lower.count(" programme ") >= 5:
        return True
    return False


def _looks_like_hard_false_english_requirement(snippet: str) -> bool:
    lower = snippet.lower()
    return any(token in lower for token in ("english language centre", "english and applied linguistics", "quick links", "current students", "summer programme website"))


def _english_value_from_parsed(snippet: str, parsed) -> str:
    raw_parts = [_clean_sentence(str(item.get("raw_text", ""))) for item in parsed if isinstance(item, dict) and item.get("raw_text")]
    raw_parts = [part for part in raw_parts if part]
    if raw_parts:
        return "; ".join(dict.fromkeys(raw_parts))
    return snippet


def _requirement(label: str, value: str, claim_path: str, *, parsed=None, parse_status: str = "unparsed") -> RequirementRecord:
    return RequirementRecord(
        label=label,
        value=FieldValue(value=value, raw_text=value, parsed=parsed, parse_status=parse_status, status=ClaimStatus.KNOWN, confidence=Confidence.MEDIUM, evidence=[claim_path]),
    )


def _fee_snippet_requires_number(snippet: str) -> bool:
    lower = snippet.lower()
    return any(token in lower for token in ("tuition", "fee", "fees", "application fee")) and not re.search(r"(?:HKD|HK\$|S\$|SGD|USD|US\$|\$)\s*[0-9]", snippet, flags=re.IGNORECASE)


def _fee_table_reference_snippet(text: str, source: SourceRecord) -> str | None:
    source_hint = f"{source.source_url} {source.title or ''}".lower()
    if any(token in source_hint for token in ("/graduate", "/postgraduate", "postgraduate", "graduate tuition", "/hall-admission", "/sao/", "residential life")):
        return None
    if "/admissions/undergraduate/" not in source.source_url.lower() and "undergraduate" not in text[:2500].lower():
        return None

    cleaned = _clean_sentence(text)
    anchors = []
    semester_match = re.search(r"Tuition Fees For Semester 1 and 2(?:\s+Accepted programme offer in [0-9]{4})?", cleaned, flags=re.IGNORECASE)
    ay_match = re.search(r"Tuition fees payable for AY[0-9]{4}\s*[-–]\s*[0-9]{2,4}", cleaned, flags=re.IGNORECASE)
    part_time_match = re.search(r"Tuition Fees payable per academic unit[^.]{0,180}", cleaned, flags=re.IGNORECASE)
    for match in (semester_match, ay_match, part_time_match):
        if match:
            anchors.append(_clean_sentence(match.group(0)))
    if not anchors:
        return None
    return ". ".join(dict.fromkeys(anchors))


def _looks_like_non_admissions_contact(url: str, title: str | None, text: str) -> bool:
    lower = f"{url} {title or ''} {text[:1000]}".lower()
    if "/contact-us/form" in lower or "privacy" in lower or "personal information collection statement" in lower:
        return True
    return False


def _clean_sentence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_programme_name(value: str) -> str:
    value = _clean_sentence(value)
    value = re.sub(r"\s+(?:requires?|needs?|must)\b.*$", "", value, flags=re.IGNORECASE)
    value = value.strip(" .;,|")
    replacements = {
        "Bsc": "BSc",
        "Ba ": "BA ",
        "Beng": "BEng",
        "Llb": "LLB",
        "Mbbs": "MBBS",
        "Bba": "BBA",
        "Bacc": "BAcc",
    }
    for old, new in replacements.items():
        if value.startswith(old):
            value = new + value[len(old) :]
    return value
