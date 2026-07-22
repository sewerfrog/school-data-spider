"""Domain-scoped institution rules for programme catalog extraction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

from university_admissions_crawler.crawler.public_suffix import registrable_domain


@dataclass(frozen=True, slots=True)
class FacultyAlias:
    canonical: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InstitutionProfile:
    key: str
    domains: frozenset[str]
    faculty_aliases: tuple[FacultyAlias, ...]
    programme_name_patterns: tuple[str, ...] = ()
    special_programme_names: frozenset[str] = frozenset()


NUS_PROFILE = InstitutionProfile(
    key="nus",
    domains=frozenset({"nus.edu.sg"}),
    faculty_aliases=(
        FacultyAlias("NUS Business School", ("NUS Business School", "School of Business")),
        FacultyAlias("College of Humanities and Sciences", ("College of Humanities and Sciences", "CHS")),
        FacultyAlias("Faculty of Arts and Social Sciences", ("Faculty of Arts and Social Sciences", "FASS")),
        FacultyAlias("NUS College", ("NUS College",)),
        FacultyAlias("School of Computing", ("School of Computing",)),
        FacultyAlias("College of Design and Engineering", ("College of Design and Engineering", "CDE")),
        FacultyAlias("Faculty of Science", ("Faculty of Science",)),
    ),
    programme_name_patterns=(
        r"\b((?:CHS|FASS)\s+(?:Primary\s+)?Major:\s*[A-Z][A-Za-z&/(),'\- ]{2,100})",
        r"\b((?:NUS\s+College|Special Programme in Science(?:\s+\(SPS\))?|Engineering Scholars Programme(?:\s+\(E-Scholars\))?))(?=\s|$|[.;,])",
    ),
    special_programme_names=frozenset(
        {
            "nus college",
            "special programme in science",
            "special programme in science sps",
            "engineering scholars programme",
            "engineering scholars programme e scholars",
        }
    ),
)


NTU_PROFILE = InstitutionProfile(
    key="ntu",
    domains=frozenset({"ntu.edu.sg"}),
    faculty_aliases=(
        FacultyAlias("Nanyang Business School", ("Nanyang Business School", "NBS")),
        FacultyAlias("College of Computing and Data Science", ("College of Computing and Data Science", "CCDS")),
        FacultyAlias(
            "College of Humanities, Arts and Social Sciences",
            ("College of Humanities, Arts and Social Sciences", "CoHASS"),
        ),
        FacultyAlias("School of Art, Design and Media", ("School of Art, Design and Media", "ADM")),
        FacultyAlias("School of Humanities", ("School of Humanities", "SoH")),
        FacultyAlias("School of Social Sciences", ("School of Social Sciences", "SSS")),
        FacultyAlias(
            "Wee Kim Wee School of Communication and Information",
            ("Wee Kim Wee School of Communication and Information", "WKWSCI"),
        ),
    ),
)


INSTITUTION_PROFILES = (NUS_PROFILE, NTU_PROFILE)


def institution_profile_for_source(source_url: str, *, is_official: bool) -> InstitutionProfile | None:
    """Select a profile only for an official source on a configured domain."""

    if not is_official:
        return None
    host = (urlparse(source_url).hostname or "").lower()
    domain = registrable_domain(host)
    if not domain:
        return None
    return next((profile for profile in INSTITUTION_PROFILES if domain in profile.domains), None)


def extract_profile_programme_name(profile: InstitutionProfile | None, value: str) -> str | None:
    if profile is None:
        return None
    for pattern in profile.programme_name_patterns:
        match = re.search(pattern, value)
        if match:
            return _clean_name(match.group(1))
    return None


def profile_programme_category(profile: InstitutionProfile | None, name: str) -> str | None:
    if profile is None:
        return None
    normalized = _normalize(name)
    if normalized in profile.special_programme_names:
        return "special_programme"
    return None


def profile_faculty_from_source_title(
    profile: InstitutionProfile | None,
    *,
    title: str | None,
) -> str | None:
    if profile is None:
        return None
    return _faculty_alias_match(profile, title or "", allow_embedded=True)


def profile_faculty_from_structured_label(profile: InstitutionProfile | None, value: str) -> str | None:
    """Resolve aliases only when the caller has established structured context."""

    if profile is None:
        return None
    return _faculty_alias_match(profile, value, allow_embedded=False)


def faculty_label_conflicts(profile: InstitutionProfile | None, label: str | None) -> bool:
    if profile is None or not label:
        return False
    if _faculty_alias_match(profile, label, allow_embedded=False):
        return False
    return any(
        _faculty_alias_match(other, label, allow_embedded=False)
        for other in INSTITUTION_PROFILES
        if other.key != profile.key
    )


def programme_name_conflicts(profile: InstitutionProfile | None, name: str) -> bool:
    if profile is None:
        return False
    if extract_profile_programme_name(profile, name):
        return False
    return any(
        extract_profile_programme_name(other, name)
        for other in INSTITUTION_PROFILES
        if other.key != profile.key
    )


def _faculty_alias_match(profile: InstitutionProfile, value: str, *, allow_embedded: bool) -> str | None:
    normalized_value = _normalize(value)
    if not normalized_value:
        return None
    for faculty in profile.faculty_aliases:
        for alias in faculty.aliases:
            normalized_alias = _normalize(alias)
            if normalized_value == normalized_alias:
                return faculty.canonical
            if allow_embedded and re.search(rf"(?:^|\s){re.escape(normalized_alias)}(?:\s|$)", normalized_value):
                return faculty.canonical
    return None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _clean_name(value: str) -> str:
    value = re.sub(r"\s+(?:full-time|part-time|four-year|three-year|160 units?|at least).*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+within\b.*$", "", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" \t\r\n-|.;:,")
