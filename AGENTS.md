# Repository Guidelines

## Project Structure & Module Organization

This repository contains a dependency-light Python 3.11 package for evidence-first university admissions crawling and extraction.

- `university_admissions_crawler/` is the source package.
- `crawler/` handles bounded discovery, filters, sitemap parsing, and fetching.
- `classifier/`, `extractor/`, `evidence/`, `pipeline/`, and `reports/` contain page classification, structured extraction, provenance validation, orchestration, and Markdown report rendering.
- `tests/` contains pytest tests plus deterministic fixture sites under `tests/fixtures/mini_university_site/`.
- `outputs/` stores generated sample results such as `result.json`, reports, CSVs, and source indexes.

## Build, Test, and Development Commands

- `python3 -m pytest -q` runs the full deterministic test suite.
- `python3 -m compileall university_admissions_crawler tests` checks import-time syntax errors.
- `python3 -m university_admissions_crawler.cli tests/fixtures/mini_university_site --fixture --output-dir /tmp/uac-smoke --max-pages 20 --max-depth 3` runs an end-to-end fixture smoke scan.
- `python3 -m university_admissions_crawler.cli ... --smoke` caps a scan for quick validation.

Install dev tooling with `python3 -m pip install -e '.[dev]'` when `pytest` is not already available.

## Coding Style & Naming Conventions

Use standard Python style with 4-space indentation, descriptive snake_case names for functions and modules, and PascalCase for classes and dataclasses. Keep core code deterministic and dependency-free unless an optional extra is explicitly being implemented. Prefer explicit validators and clear data structures over implicit inference. Do not fabricate admissions facts; unsupported values should become `unknown` or `needs_manual_check` warnings.

## Testing Guidelines

Tests use pytest and live under `tests/test_*.py`. Add focused tests near the behavior being changed, and prefer fixture-backed cases over live network calls. Core tests must pass without browser installs, paid credentials, hosted APIs, or external network access. For extractor or evidence changes, assert both the value and the source/evidence claim path.

## Commit & Pull Request Guidelines

This checkout has no local git history to infer prior style. Follow the repository instruction convention: commit messages should explain why the change exists, then include useful git trailers such as `Constraint:`, `Rejected:`, `Confidence:`, `Scope-risk:`, `Tested:`, and `Not-tested:`. Pull requests should include a short purpose statement, changed areas, verification commands, known gaps, and sample output paths when reports or JSON artifacts change.

## Security & Configuration Tips

Optional provider flags such as `--enable-llm`, `--enable-browser`, and `--enable-scrapegraph` are guarded surfaces. Keep credentials out of fixtures, tests, generated outputs, and commit messages.
