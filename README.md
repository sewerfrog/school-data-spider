# University Admissions Crawler

Evidence-first MVP for extracting undergraduate admissions information from official university websites. The current implementation is a deterministic Python CLI/library that can run end-to-end on local fixtures and produce structured JSON plus a Markdown evidence report.

## What it does now

- Starts from a seed homepage in `--fixture` mode.
- Discovers bounded official links with `max_pages` / `max_depth` limits.
- Classifies admissions-related pages into undergraduate admissions, international requirements, deadlines, accepted qualifications, programme lists/prerequisites, fees, scholarships, visa, housing, contact, and irrelevant pages.
- Extracts only claims that can be tied to source evidence snippets.
- Emits `unknown` / `needs_manual_check` warnings rather than fabricating unsupported fields.
- Preserves official source URLs, including discovered official subdomains, in source/evidence/report output.
- Records discovered page categories in JSON and Markdown.
- Handles PDF-like fixture sources and optional real PDF parsing through a page-indexed extractor protocol.
- Handles public JSON/API sources as first-class evidence sources.
- Preserves HTML table text for deterministic extraction from table-heavy admissions pages.
- Strips common navigation/header/footer/cookie noise before extraction and records core-field coverage diagnostics.
- Guards optional live/browser/PDF/LLM/ScrapeGraphAI capabilities behind interfaces; they are not required for core tests.
- Writes `result.json` and `report.md`.

## Current implementation decision

The first implementation uses Python stdlib `dataclasses` plus explicit validators for runtime records, evidence links, warnings, and tests. Pydantic is intentionally not a core dependency in this MVP; if the project later adopts Pydantic, schema code, tests, `pyproject.toml`, and this README must be updated together.

Optional capabilities are represented as dependency groups / guarded execution modes:

- `browser`: Playwright browser-backed live crawling support
- `pdf`: optional pypdf parsing support for live PDF sources
- `llm`: future LLM provider support
- `scrapegraph`: future ScrapeGraphAI adapter support

Core deterministic tests pass without browser installation, paid credentials, hosted APIs, or live network access.

## Install / run

Use Python 3.11 or newer. On this workstation, Python 3.14 is available at
`/opt/homebrew/bin/python3.14`.

Recommended setup:

```bash
/opt/homebrew/bin/python3.14 -m venv .venv314
source .venv314/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'
```

From the repository root:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --output-dir /tmp/uac-smoke \
  --max-pages 30 \
  --max-depth 3
```

Outputs:

- `/tmp/uac-smoke/result.json` — structured data, sources, evidence, warnings, and diff metadata.
- `/tmp/uac-smoke/report.md` — human-readable fact/warning/source/evidence report.

For a smaller smoke run, add `--smoke`; it caps the run at `max_pages<=20` and `max_depth<=2` even if larger values are supplied. Optional provider flags such as `--enable-llm` and `--enable-scrapegraph` exist as explicit guarded surfaces and fail closed in this dependency-free MVP.

To compare with a previous run:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --previous-result /tmp/uac-smoke/result.json \
  --output-dir /tmp/uac-smoke-next
```

`run.config.diff` records changed source hashes and changed field values when a prior result is supplied. If no prior result is supplied, the output includes an explicit `needs_manual_check` warning for the missing baseline.

## Testing

Install `.[dev]` and run:

```bash
python -m pytest -q
python -m compileall -q university_admissions_crawler tests
```

If `pytest` is not installed in the active environment, the deterministic suite
can still be checked with a small stdlib direct runner, but `pytest` is the
intended test command.

## Evidence and safety policy

- Every non-unknown `FieldValue` must reference an evidence item with the exact claim path.
- Evidence items must point to real claim paths.
- Conflicting official values are preserved and downgraded with conflict warnings.
- Stale academic-year sources are warning-producing.
- Non-official supporting sources and ambiguous applicant-group requirements are warning-producing.
- Unsupported LLM candidate claims are rejected unless claim path, source text, evidence snippet, and candidate value all line up.
- Fetch/bad-status/parse/PDF failures produce warnings and the scan continues when other usable sources remain.

## Non-goals

- No Web UI or admin backend in v1.
- No automated admissions verdict or recommendation.
- No unbounded crawl.
- No unsupported factual inference.
- No required paid API credentials or hosted-provider calls in core tests.

## Live crawling status

Live crawling is guarded and opt-in. Static pages can use the stdlib HTTP
fetcher:

```bash
python -m university_admissions_crawler.cli https://www.nus.edu.sg/oam/undergraduate-programmes \
  --enable-live-network \
  --output-dir outputs/nus-live-test \
  --allowed-domain nus.edu.sg \
  --max-pages 30 \
  --max-depth 2
```

For a new university where you only have one admissions URL, use `--auto`.
It enables live HTTP mode and infers the allowed official domain from the URL:

```bash
python -m university_admissions_crawler.cli https://www.example.edu/admissions \
  --auto \
  --output-dir outputs/example-auto \
  --max-pages 40 \
  --max-depth 2
```

JavaScript-rendered pages can use the optional Playwright browser fetcher:

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
python -m university_admissions_crawler.cli https://www.nus.edu.sg/oam/undergraduate-programmes \
  --enable-browser \
  --output-dir outputs/nus-browser-test \
  --allowed-domain nus.edu.sg \
  --browser-wait-until domcontentloaded \
  --timeout-seconds 45 \
  --max-pages 30 \
  --max-depth 2
```

All modes write the same output shape:

- `result.json`
- `report.md`
- `sources/*.json`
- `sources/*.txt`

`result.json` also includes diagnostics under `run.config`:

- `coverage` — found/missing core undergraduate fields.
- `source_strategy` — per-source labels such as `html_page`, `pdf_document`,
  `json_api`, `application_portal`, `blocked_or_challenge`, or `irrelevant`.
- `source_strategy_summary` — counts by strategy label.

Some university sites use WAF/anti-bot protection. When that happens, the
captured source may be a challenge page rather than the admissions content; the
report and source files should be reviewed before trusting extracted fields.
Browser mode also requires the local Playwright package and Chromium browser;
without them the scan records `optional_dependency_missing`.

Live PDF parsing is optional:

```bash
python -m pip install -e '.[pdf]'
python -m university_admissions_crawler.cli https://www.example.edu/admissions/prospectus.pdf \
  --enable-live-network \
  --enable-pdf \
  --output-dir outputs/example-pdf-test \
  --allowed-domain example.edu \
  --max-pages 1 \
  --max-depth 0
```

Public JSON/API sources are detected through `application/json`, `.json` URLs,
and browser network responses. JSON values are preserved as source text, and
common public API fields such as `programmeName`, `applicationDeadline`,
`tuitionFee`, and `requiredDocuments` are promoted into the normal evidence
schema when they can be tied to a JSON snippet.

Batch scans can be driven by a JSON config:

```bash
python -m university_admissions_crawler.cli \
  --config configs/universities.example.json \
  --output-dir outputs/batch \
  --browser-wait-until domcontentloaded \
  --timeout-seconds 45 \
  --enable-pdf
```

Each configured university writes to its own folder:

- `outputs/batch/<university-id>/result.json`
- `outputs/batch/<university-id>/report.md`
- `outputs/batch/<university-id>/sources/`

The current extractors are conservative and still rule-based. For real sites,
`overall confidence` reflects evidence/conflict status for extracted claims; it
does not mean all admissions fields were found. Use `run.config.coverage` and
the report's "Core Field Coverage" section to see which fields remain missing.
