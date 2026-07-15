"""Public Suffix List-backed domain boundary helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from ipaddress import ip_address


PUBLIC_SUFFIX_LIST_RESOURCE = "resources/public_suffix_list.dat"


@dataclass(frozen=True, slots=True)
class PublicSuffixList:
    exact_rules: frozenset[str]
    wildcard_rules: frozenset[str]
    exception_rules: frozenset[str]
    version: str | None = None
    commit: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.exact_rules or self.wildcard_rules or self.exception_rules)


def public_suffix(host: str) -> str | None:
    """Return the public suffix for a host using the vendored PSL."""

    domain = _canonical_domain(host)
    if not domain:
        return None
    labels = tuple(domain.split("."))
    rules = _public_suffix_list()
    if not rules.available:
        return None
    suffix_labels = _matching_suffix_labels(labels, rules)
    return ".".join(suffix_labels) if suffix_labels else None


def registrable_domain(host: str) -> str | None:
    """Return the eTLD+1 registrable domain for a host, or None for public suffixes."""

    domain = _canonical_domain(host)
    if not domain:
        return None
    suffix = public_suffix(domain)
    if not suffix:
        return None
    labels = tuple(domain.split("."))
    suffix_label_count = len(suffix.split("."))
    if len(labels) <= suffix_label_count:
        return None
    return ".".join(labels[-(suffix_label_count + 1) :])


def public_suffix_list_metadata() -> dict[str, object]:
    rules = _public_suffix_list()
    return {
        "available": rules.available,
        "version": rules.version,
        "commit": rules.commit,
        "exact_rule_count": len(rules.exact_rules),
        "wildcard_rule_count": len(rules.wildcard_rules),
        "exception_rule_count": len(rules.exception_rules),
    }


@lru_cache(maxsize=1)
def _public_suffix_list() -> PublicSuffixList:
    try:
        text = files("university_admissions_crawler").joinpath(PUBLIC_SUFFIX_LIST_RESOURCE).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return PublicSuffixList(frozenset(), frozenset(), frozenset())
    return _parse_public_suffix_list(text)


def _parse_public_suffix_list(text: str) -> PublicSuffixList:
    exact_rules: set[str] = set()
    wildcard_rules: set[str] = set()
    exception_rules: set[str] = set()
    version: str | None = None
    commit: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("//"):
            if line.startswith("// VERSION:"):
                version = line.removeprefix("// VERSION:").strip()
            elif line.startswith("// COMMIT:"):
                commit = line.removeprefix("// COMMIT:").strip()
            continue
        if line.startswith("!"):
            rule = _canonical_rule(line[1:])
            if rule:
                exception_rules.add(rule)
            continue
        if line.startswith("*."):
            rule = _canonical_rule(line[2:])
            if rule:
                wildcard_rules.add(rule)
            continue
        rule = _canonical_rule(line)
        if rule:
            exact_rules.add(rule)
    return PublicSuffixList(
        exact_rules=frozenset(exact_rules),
        wildcard_rules=frozenset(wildcard_rules),
        exception_rules=frozenset(exception_rules),
        version=version,
        commit=commit,
    )


def _matching_suffix_labels(labels: tuple[str, ...], rules: PublicSuffixList) -> tuple[str, ...]:
    for index in range(len(labels)):
        candidate = ".".join(labels[index:])
        if candidate in rules.exception_rules:
            return labels[index + 1 :]

    matches: list[tuple[str, ...]] = []
    for index in range(len(labels)):
        candidate = ".".join(labels[index:])
        if candidate in rules.exact_rules:
            matches.append(labels[index:])
        if index < len(labels) - 1:
            wildcard_tail = ".".join(labels[index + 1 :])
            if wildcard_tail in rules.wildcard_rules:
                matches.append(labels[index:])

    if matches:
        return max(matches, key=len)
    return labels[-1:]


def _canonical_rule(value: str) -> str:
    return _canonical_domain(value)


def _canonical_domain(value: str) -> str:
    host = _strip_host_port(value).lower().strip(".")
    if not host:
        return ""
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        return ""

    labels: list[str] = []
    for label in host.split("."):
        if not label:
            return ""
        try:
            labels.append(label.encode("idna").decode("ascii").lower())
        except UnicodeError:
            return ""
    return ".".join(labels)


def _strip_host_port(value: str) -> str:
    host = value.strip()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            return host[1:end]
    if host.count(":") == 1:
        name, port = host.rsplit(":", 1)
        if port.isdigit():
            return name
    return host
