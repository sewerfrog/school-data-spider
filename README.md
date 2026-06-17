# University Admissions Crawler

Evidence-first MVP for extracting undergraduate admissions information from official university websites. The current implementation is a deterministic Python CLI/library that can run end-to-end on local fixtures and produce structured JSON plus a Markdown evidence report.

## What it does now

- Starts from fixture roots, guarded live URLs, or batch-configured seed URLs.
- Discovers bounded official links with `max_pages` / `max_depth` limits.
- Classifies admissions-related pages into undergraduate admissions, international requirements, deadlines, accepted qualifications, programme lists/prerequisites, fees, scholarships, visa, housing, contact, and irrelevant pages.
- Extracts only claims that can be tied to source evidence snippets.
- Emits `unknown` / `needs_manual_check` warnings rather than fabricating unsupported fields.
- Preserves official source URLs, including discovered official subdomains, in source/evidence/report output.
- Records discovered page categories in JSON and Markdown.
- Handles PDF-like fixture sources and optional real PDF parsing through a page-indexed extractor protocol.
- In browser mode, obvious PDF URLs and Playwright `Download is starting` PDF navigations fall back to HTTP byte download so the source is recorded as `SourceType.PDF`.
- Handles public JSON/API sources as first-class evidence sources.
- Preserves HTML table text for deterministic extraction from table-heavy admissions pages.
- Filters obvious static assets and low-value privacy/GDPR/cookie/terms-like
  documents before follow/fetch decisions while preserving admissions
  prospectus, requirements, fee, and programme PDFs.
- Strips common navigation/header/footer/cookie noise before extraction and records core-field coverage diagnostics.
- Records optional classification-assist diagnostics and a summary when guarded
  mock classification assist is enabled; zero-trigger runs remain visible, and
  candidates are not applied to facts.
- Records source-level extraction diagnostics plus field-level
  `missing_reasons` for missing core fields; these describe current
  crawl/extractor outcomes and are not official absence evidence.
- Adds a lightweight cleaned-candidate layer for key fields: `raw_text`, `parsed`, and `parse_status`.
- Parses common English test scores, fee amounts, and application dates when the raw text is specific enough; otherwise the raw candidate remains visible for manual review.
- Keeps raw fee-table/reference candidates when an official undergraduate fee
  page exposes only table labels rather than amounts; these remain
  `raw_needs_manual_review` and are not structured fee amounts.
- Filters undergraduate core extraction away from common pollution pages such as postgraduate/graduate pages, hall/accommodation pages, search pages, current-students pages, privacy/contact forms, and generic marketing pages unless they have strong undergraduate admissions context.
- Records discovery relevance diagnostics under `run.config`, including per-source discovery score, relevance signals, and strategy name.
- Supports reviewable keyword plans for discovery diagnostics through `--keyword-query`; by default these plans do not change crawl ordering.
- Provides an opt-in deterministic `bm25-like` relevance strategy for keyword-assisted discovery ranking. It must be explicitly selected and requires a keyword query.
- Supports guarded mock LLM keyword-plan generation and classification-assist diagnostics for plumbing tests only; hosted LLM providers remain disabled.
- Guards optional live/browser/PDF/LLM/crawl4ai/ScrapeGraphAI capabilities behind interfaces; they are not required for core tests.
- Writes `result.json` and `report.md`.

## Current implementation decision

The first implementation uses Python stdlib `dataclasses` plus explicit validators for runtime records, evidence links, warnings, and tests. Pydantic is intentionally not a core dependency in this MVP; if the project later adopts Pydantic, schema code, tests, `pyproject.toml`, and this README must be updated together.

Optional capabilities are represented as dependency groups / guarded execution modes:

- `browser`: Playwright browser-backed live crawling support
- `pdf`: optional pypdf parsing support for live PDF sources
- `llm`: guarded mock keyword-plan plumbing, mock classification-assist diagnostics, and future hosted LLM provider surface
- `crawl4ai`: future crawl4ai adapter surface, currently warning-only stub
- `scrapegraph`: future ScrapeGraphAI adapter support

Core deterministic tests pass without browser installation, paid credentials, hosted APIs, or live network access.
Recent internal cleanup split shared output writing, fetch result types,
source/content-type helpers, JSON helpers, and optional warning-only stubs into
small modules while keeping legacy import paths compatible.

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

After editable install, the console script is also available as
`university-admissions-crawler`; the examples below use `python -m
university_admissions_crawler.cli` so they also work before script wrappers are
on `PATH`.

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

For extracted key fields, `result.json` now keeps both the original candidate and the cleaned parse status:

```json
{
  "value": "English language requirements: IELTS 6.5 overall; TOEFL 90 minimum",
  "raw_text": "English language requirements: IELTS 6.5 overall; TOEFL 90 minimum",
  "parsed": [
    {"test_name": "IELTS", "overall_score": 6.5, "component_scores": {}},
    {"test_name": "TOEFL iBT", "overall_score": 90, "component_scores": {}}
  ],
  "parse_status": "parsed"
}
```

If a field cannot be safely parsed, it is left as a raw candidate with `parse_status` such as `unparsed` or `raw_needs_manual_review`; it should not be treated as a cleaned business field.

For a smaller smoke run, add `--smoke`; it caps the run at `max_pages<=20` and `max_depth<=2` even if larger values are supplied. In batch mode, a university config's own `max_pages` or `max_depth` still overrides the CLI smoke cap for that university. `--enable-scrapegraph` remains a guarded future surface and fails closed. `--enable-llm` is guarded as well: only `--llm-provider mock` is currently accepted. With `--keyword-query`, it can generate a reviewable keyword plan; with `--enable-classification-assist`, it records low-confidence classification diagnostics. Hosted providers remain rejected.

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
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
.venv314/bin/python -m compileall -q university_admissions_crawler tests
```

If `pytest` is not installed in the active environment, install the `dev` extra
before running the deterministic suite.

Saved-source regression fixtures live under `tests/fixtures/saved_sources/`.
The `outputs/` directory is for generated run output and should not be required
by deterministic tests.

Current feature-branch validation after the diagnostics, source-filtering, and
NTU fee saved-source updates:

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider
python -m compileall -q university_admissions_crawler tests
```

The latest local pytest run passed `112` tests.

The focused target group used during the diagnostics/source-filtering work is:

```bash
env PYTHONDONTWRITEBYTECODE=1 .venv314/bin/python -m pytest -q -p no:cacheprovider tests/test_filters.py tests/test_discovery.py tests/test_pipeline.py tests/test_report_cli.py
```

The latest target-group run passed `57` tests.

## Evidence and safety policy

- Every non-unknown `FieldValue` must reference an evidence item with the exact claim path.
- Evidence items must point to real claim paths.
- Conflicting official values are preserved and downgraded with conflict warnings.
- Stale academic-year sources are warning-producing.
- Non-official supporting sources and ambiguous applicant-group requirements are warning-producing.
- Unsupported LLM candidate claims are rejected unless claim path, source text, evidence snippet, and candidate value all line up.
- LLM keyword-plan output is never promoted into admissions facts. It is validated into a `KeywordPlan`, recorded as run diagnostics, and can only affect discovery ordering when an explicit relevance strategy uses it.
- Fetch/bad-status/parse/PDF failures produce warnings and the scan continues when other usable sources remain.

## Non-goals

- No Web UI or admin backend in v1.
- No automated admissions verdict or recommendation.
- No unbounded crawl.
- No unsupported factual inference.
- No required paid API credentials or hosted-provider calls in core tests.
- No hosted LLM keyword-plan generation in the current implementation.

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
- `missing_reasons` — per-missing-field diagnostic reasons derived from the
  current crawl and extractor attempts. They do not prove the official site
  lacks the field.
- `source_strategy` — per-source labels such as `html_page`, `pdf_document`,
  `json_api`, `application_portal`, `blocked_or_challenge`, or `irrelevant`.
  Each entry also records `discovery_score`, `discovery_signals`, and
  `relevance_strategy`.
- `source_strategy_summary` — counts by strategy label.
- `extraction_diagnostics` and `extraction_diagnostics_summary` — source-level
  extractor attempts, skips, matches, and reason counts. These diagnostics do
  not write admissions facts.
- `relevance_strategy` — the discovery scoring strategy used for the scan.
- `keyword_plan` — present only when a user or mock LLM keyword plan was
  supplied.
- `llm_keyword_plan` — present only when guarded mock LLM keyword-plan
  generation was used; records provider, schema, fallback status, elapsed time,
  warnings, and error details.
- `classification_assist` and `classification_assist_summary` — present only
  when guarded mock classification assist is enabled; suggestions are
  diagnostics-only and remain unapplied.

The report also marks parsed versus raw-only values. For example, parsed fee
rows appear with structured `currency`, `amount`, `student_group`,
`academic_year`/`cohort`, `billing_period`, `fee_type`, and `raw_text` when
those parts can be inferred. When present, keyword plans, mock LLM keyword
diagnostics, classification assist, extraction diagnostics, and missing reasons
are shown in diagnostic sections before facts; they are not admissions facts.

## Keyword-assisted discovery

Keyword-assisted discovery is opt-in and evidence-safe. It changes discovery
diagnostics, and can change crawl ordering only when a non-default relevance
strategy is explicitly selected. It does not write admissions facts.

To record a reviewable keyword plan without changing discovery ranking:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --keyword-query "undergraduate admissions IELTS fees" \
  --output-dir /tmp/uac-keyword-plan
```

The run keeps `rule_based` discovery scoring and writes
`run.config.keyword_plan`.

To opt in to deterministic keyword-assisted ranking:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --keyword-query "fees tuition international" \
  --relevance-strategy bm25-like \
  --output-dir /tmp/uac-bm25-like
```

`bm25-like` is a lightweight token/url-hint overlap scorer layered on top of
the existing rule-based score. It is not a full BM25 implementation. It remains
bounded by `max_pages`, `max_depth`, allowed hosts/domains, and the follow
threshold.

Guarded mock LLM keyword-plan generation can be used to test the plumbing
without a hosted model:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --keyword-query "undergraduate admissions IELTS fees" \
  --enable-llm \
  --llm-provider mock \
  --output-dir /tmp/uac-mock-llm-keywords
```

Only `mock` is currently supported. Requests for hosted providers such as
`openai`, `anthropic`, or `gemini` fail closed. The mock provider returns a
schema-validated `KeywordPlan` and records `run.config.llm_keyword_plan`; it is
not evidence extraction and does not call a network API.

Guarded mock classification assist can also be enabled for low-confidence page
classifications:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --enable-llm \
  --llm-provider mock \
  --enable-classification-assist \
  --output-dir /tmp/uac-mock-classification-assist
```

This writes `classification_assist` and `classification_assist_summary` under
`run.config` when the mock assist path is enabled. Even when no low-confidence
page triggers assist, the summary records a zero-trigger state. Assist
candidates are never applied to `PageCategory`, extractor routing, or facts.

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

When browser mode discovers a PDF URL, the browser fetcher now downloads the
PDF through the HTTP fetcher instead of trying to render it as a page. This
allows the source to be saved as `pdf` and counted as `pdf_document`. Use
`--enable-pdf` plus the `pdf` extra when you want the PDF text parsed with
`pypdf`; otherwise non-fixture PDF sources return an optional-dependency
warning and do not contribute parsed PDF evidence.

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

Batch configs may also opt in to keyword-assisted discovery per university:

```json
{
  "id": "example-u",
  "name": "Example University",
  "seed_urls": ["https://example.edu/"],
  "allowed_domains": ["example.edu"],
  "mode": "live-http",
  "max_pages": 20,
  "max_depth": 2,
  "keyword_query": "undergraduate admissions fees international",
  "relevance_strategy": "bm25-like"
}
```

Both fields are optional. If omitted, batch scans keep the default
`rule_based` strategy. If `relevance_strategy` is `bm25-like`, `keyword_query`
is required.

The current extractors are conservative and still rule-based. For real sites,
`overall confidence` reflects evidence/conflict status for extracted claims; it
does not mean all admissions fields were found. Use `run.config.coverage` and
the report's "Core Field Coverage" / "Missing Reasons" sections to see which
fields remain missing and where the current crawl/extractor chain stopped.

## Current real-site caveat

The saved outputs under `outputs/batch-classifier-fixed/hku`,
`outputs/batch-classifier-fixed/ntu`, `outputs/batch/hku`,
`outputs/batch/hku-cleaned`, `outputs/batch/ntu`, `outputs/batch/polyu`, and
`outputs/nus-live-programmes/` are historical generated outputs. Current
feature-branch diagnostic samples such as `outputs/hku-live-step6*` and
`outputs/ntu-current-diagnostics/` are also generated run artifacts, not test
fixtures. They are useful as references, but deterministic tests now use copied
fixtures under `tests/fixtures/saved_sources/`. Generated `result.json` /
`report.md` files will not reflect later code behavior until those schools are
rerun.
