#!/usr/bin/env python3
"""Download the official Public Suffix List into the vendored resources."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from urllib.request import urlopen


OFFICIAL_PUBLIC_SUFFIX_LIST_URL = "https://publicsuffix.org/list/public_suffix_list.dat"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "university_admissions_crawler" / "resources" / "public_suffix_list.dat"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=OFFICIAL_PUBLIC_SUFFIX_LIST_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = _download(args.url)
    _validate_public_suffix_list(data, source_url=args.url)
    _atomic_write(args.output, data)
    version, commit = _metadata(data)
    print(f"updated {args.output}")
    if version:
        print(f"version: {version}")
    if commit:
        print(f"commit: {commit}")
    return 0


def _download(url: str) -> str:
    with urlopen(url, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset)


def _validate_public_suffix_list(data: str, *, source_url: str) -> None:
    if source_url != OFFICIAL_PUBLIC_SUFFIX_LIST_URL:
        raise SystemExit(f"refusing non-official PSL source: {source_url}")
    required = (
        "Mozilla Public License, v. 2.0",
        "===BEGIN ICANN DOMAINS===",
        "===BEGIN PRIVATE DOMAINS===",
        "===END PRIVATE DOMAINS===",
    )
    missing = [marker for marker in required if marker not in data]
    if missing:
        raise SystemExit(f"downloaded data does not look like the official PSL; missing: {', '.join(missing)}")


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _metadata(data: str) -> tuple[str | None, str | None]:
    version = None
    commit = None
    for line in data.splitlines():
        if line.startswith("// VERSION:"):
            version = line.removeprefix("// VERSION:").strip()
        elif line.startswith("// COMMIT:"):
            commit = line.removeprefix("// COMMIT:").strip()
        if version and commit:
            break
    return version, commit


if __name__ == "__main__":
    raise SystemExit(main())
