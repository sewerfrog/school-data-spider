"""Programme source roles used by discovery and extraction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
from urllib.parse import unquote, urlparse

from university_admissions_crawler.crawler.html_text import HTMLContentBlock
from university_admissions_crawler.crawler.public_suffix import registrable_domain


PROGRAMME_SOURCE_ROLES: tuple[str, ...] = (
    "canonical_catalog",
    "faculty_catalog",
    "programme_detail",
    "minor_or_second_major_catalog",
    "curriculum_or_old_cohort",
    "unrelated",
)

PROGRAMME_SOURCE_ROLE_PRIORITY: dict[str, int] = {
    "canonical_catalog": 0,
    "faculty_catalog": 1,
    "programme_detail": 2,
    "minor_or_second_major_catalog": 3,
    "curriculum_or_old_cohort": 4,
    "unrelated": 2,
}

BOUNDED_FRONTIER_SOURCE_ROLES = frozenset(
    {
        "programme_detail",
        "minor_or_second_major_catalog",
        "curriculum_or_old_cohort",
    }
)

_CATALOG_LEAF_PATHS = frozenset(
    {
        "programmes",
        "programs",
        "undergraduate-programmes",
        "undergraduate-programs",
        "degree-programmes",
        "degree-programs",
        "majors",
        "catalogue",
        "catalog",
    }
)
_CATALOG_INDEX_LEAF_PATHS = frozenset({"undergraduate", "undergraduate-education", "ug"})
_COMPOUND_PROGRAMME_DETAIL_PATH_HINTS = (
    "double-major",
    "double-degree",
    "dual-degree",
    "joint-degree",
    "combined-degree",
)
_PROGRAMME_TITLE_RE = re.compile(
    r"^(?:Bachelor\b|B(?:Sc|A|Eng|BA|BAA|FA|Ed|Med|Mus|Comm|SocSci|Comp)\b|LLB\b|MBBS\b)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProgrammeSourceRoleDecision:
    role: str
    priority: int
    source_family: str
    signals: tuple[str, ...] = ()


def classify_programme_source_role(
    url: str,
    title: str | None = None,
    text: str = "",
    blocks: Sequence[HTMLContentBlock] = (),
) -> ProgrammeSourceRoleDecision:
    """Classify one source without treating every programme-like URL as a catalog."""

    parsed = urlparse(url)
    path = unquote(parsed.path).lower().rstrip("/") or "/"
    title_text = " ".join((title or "").lower().split())
    identity = f"{path} {title_text}"
    signals: list[str] = []

    if _is_old_cohort(identity):
        signals.append("old_cohort_path_or_title")
        return _decision("curriculum_or_old_cohort", url, signals)
    if any(token in identity for token in ("curriculum", "course-content", "course structure", "study-plan", "study plan")):
        signals.append("curriculum_path_or_title")
        return _decision("curriculum_or_old_cohort", url, signals)
    if any(
        token in identity
        for token in (
            "minorprogrammes",
            "minor-programmes",
            "minor-programme",
            "minor-in-",
            "second-major",
            "second major",
            "second-major-programmes",
        )
    ):
        signals.append("minor_or_second_major_path_or_title")
        return _decision("minor_or_second_major_catalog", url, signals)
    if _is_programme_detail(path, title_text):
        signals.append("programme_detail_path_or_title")
        return _decision("programme_detail", url, signals)

    if _is_ntu_canonical_catalog(url):
        signals.append("institution_profile:ntu_degree_catalog")
        return _decision("canonical_catalog", url, signals)

    path_segments = [segment for segment in path.split("/") if segment]
    catalog_leaf = path_segments[-1] if path_segments else ""
    has_catalog_leaf = catalog_leaf in _CATALOG_LEAF_PATHS
    has_catalog_path = any(segment in _CATALOG_LEAF_PATHS for segment in path_segments)
    has_catalog_index_path = has_catalog_path and catalog_leaf in _CATALOG_INDEX_LEAF_PATHS
    has_catalog_structure = _has_programme_catalog_structure(text, blocks)
    broad_catalog_identity = any(
        token in identity
        for token in (
            "degree-programmes",
            "degree-programs",
            "degree programmes",
            "degree programs",
            "programme-catalog",
            "program-catalog",
            "programme catalogue",
            "program catalog",
            "programmes.json",
            "programs.json",
        )
    )
    if has_catalog_structure:
        signals.append("programme_catalog_structure")
    if broad_catalog_identity:
        signals.append("broad_catalog_identity")

    if broad_catalog_identity and (has_catalog_structure or has_catalog_leaf):
        return _decision("canonical_catalog", url, signals)
    if has_catalog_leaf and len(path_segments) == 1:
        signals.append("root_catalog_path")
        return _decision("canonical_catalog", url, signals)
    if (
        has_catalog_leaf
        or has_catalog_index_path
        or (has_catalog_structure and _has_programme_identity(identity, text))
        or _has_programme_listing_text(identity, text)
    ):
        signals.append("faculty_catalog_path_or_structure")
        return _decision("faculty_catalog", url, signals)
    return _decision("unrelated", url, signals)


def institution_profile_programme_urls(seed_url: str) -> tuple[str, ...]:
    """Return bounded, domain-scoped canonical catalog hints for known institutions."""

    parsed = urlparse(seed_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ()
    host = (parsed.hostname or "").lower().rstrip(".")
    if registrable_domain(host) != "ntu.edu.sg":
        return ()
    return (f"{parsed.scheme.lower()}://{parsed.netloc}/education/degree-programmes",)


def programme_source_family(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or parsed.netloc or "unknown").lower()
    segments = [segment for segment in parsed.path.lower().split("/") if segment]
    if not segments:
        return host
    if len(segments) == 1:
        return f"{host}/{segments[0]}"
    return f"{host}/{segments[0]}/{segments[1]}"


def is_catalog_backed_programme_detail_source(source_url: str, catalog_urls: Sequence[str]) -> bool:
    """Return whether a detail source shares a family or path ancestry with a captured catalog."""

    source_family = programme_source_family(source_url)
    source = urlparse(source_url)
    source_host = (source.hostname or source.netloc).lower().rstrip(".")
    source_path = unquote(source.path).lower().rstrip("/")
    for catalog_url in catalog_urls:
        if programme_source_family(catalog_url) == source_family:
            return True
        catalog = urlparse(catalog_url)
        catalog_host = (catalog.hostname or catalog.netloc).lower().rstrip(".")
        catalog_path = unquote(catalog.path).lower().rstrip("/")
        if (
            source_host == catalog_host
            and catalog_path
            and source_path.startswith(f"{catalog_path}/")
        ):
            return True
    return False


def _decision(role: str, url: str, signals: list[str]) -> ProgrammeSourceRoleDecision:
    return ProgrammeSourceRoleDecision(
        role=role,
        priority=PROGRAMME_SOURCE_ROLE_PRIORITY[role],
        source_family=programme_source_family(url),
        signals=tuple(dict.fromkeys(signals)),
    )


def _is_old_cohort(identity: str) -> bool:
    return any(token in identity for token in ("earlier-cohort", "earlier cohort", "old-cohort", "old cohort"))


def _is_programme_detail(path: str, title: str) -> bool:
    if is_explicit_programme_detail_source(path, title):
        return True
    segments = [segment for segment in path.split("/") if segment]
    for marker in (
        "undergraduate-programme",
        "undergraduate-programmes",
        "undergraduate-program",
        "undergraduate-programs",
        "degree-programme",
        "degree-programmes",
        "degree-program",
        "degree-programs",
    ):
        if marker in segments and segments.index(marker) < len(segments) - 1:
            return True
    return False


def is_explicit_programme_detail_source(url_or_path: str, title: str | None = None) -> bool:
    """Return whether URL/title identifies a programme itself, not any descendant page."""

    path = unquote(urlparse(url_or_path).path or url_or_path).lower().rstrip("/")
    if "/detail/" in path or path.endswith("/detail"):
        return True
    primary_title = (title or "").split("|", 1)[0].strip()
    return bool(_PROGRAMME_TITLE_RE.match(primary_title))


def is_compound_programme_detail_source(url_or_path: str, title: str | None = None) -> bool:
    """Return whether an explicit detail URL identifies a compound degree or major."""

    if not is_explicit_programme_detail_source(url_or_path, title):
        return False
    path = unquote(urlparse(url_or_path).path or url_or_path).lower()
    return any(hint in path for hint in _COMPOUND_PROGRAMME_DETAIL_PATH_HINTS)


def _has_programme_catalog_structure(text: str, blocks: Sequence[HTMLContentBlock]) -> bool:
    for block in blocks:
        if block.kind != "table_row" or len(block.cells) < 2:
            continue
        roles = {_catalog_header_role(cell) for cell in block.cells}
        if "name" in roles and roles.intersection({"award", "category"}):
            return True
    for line in re.split(r"[\n\r]+", text):
        if "|" not in line:
            continue
        roles = {_catalog_header_role(cell) for cell in line.split("|")}
        if "name" in roles and roles.intersection({"award", "category"}):
            return True
    return False


def _catalog_header_role(value: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    if normalized in {
        "programme",
        "program",
        "programme name",
        "program name",
        "programme of study",
        "program of study",
        "course",
        "major",
    }:
        return "name"
    if normalized in {"degree", "degree title", "degree awarded", "award", "qualification"}:
        return "award"
    if normalized in {"type", "programme type", "program type", "category", "level"}:
        return "category"
    return None


def _has_programme_identity(identity: str, text: str) -> bool:
    sample = f"{identity} {text[:4000].lower()}"
    return any(token in sample for token in ("undergraduate", "bachelor", "programme", "program", "degree", "major"))


def _has_programme_listing_text(identity: str, text: str) -> bool:
    sample = f"{identity} {text[:12000].lower()}"
    if not any(token in sample for token in ("undergraduate programmes", "undergraduate programs", "degree programmes", "degree programs")):
        return False
    return len(re.findall(r"\b(?:bachelor|bsc|ba|beng|bba|llb|mbbs)\b", sample, flags=re.IGNORECASE)) >= 2


def _is_ntu_canonical_catalog(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = unquote(parsed.path).lower().rstrip("/")
    return registrable_domain(host) == "ntu.edu.sg" and path == "/education/degree-programmes"
