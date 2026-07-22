# University Admissions Crawler

Evidence-first MVP for extracting undergraduate admissions information from official university websites. The current implementation is an LLM-assisted Python CLI/library for live university homepages with deterministic validation for every fact that enters the result.

## What it does now

- Starts from fixture roots, live university homepages, or batch-configured seed URLs.
- For non-fixture URLs, live HTTP crawling, LLM-assisted source planning and
  structured extraction fallback, default scan limits, fetch timeout, and
  allowed-domain inference are applied by default; `--auto` and
  `--enable-live-network` remain compatibility flags.
- Discovers bounded official links with `max_pages` / `max_depth` limits.
- Uses a vendored Public Suffix List snapshot for official-domain boundaries,
  including ICANN and PRIVATE rules such as `co.uk`, `edu.au`, wildcard rules,
  exceptions, and hosted suffixes like `github.io`.
- Classifies admissions-related pages into undergraduate admissions, international requirements, deadlines, accepted qualifications, programme lists/prerequisites, fees, scholarships, visa, housing, contact, and irrelevant pages.
- Extracts only claims that can be tied to source evidence snippets.
- Emits `unknown` / `needs_manual_check` warnings rather than fabricating unsupported fields.
- Preserves official source URLs, including discovered official subdomains, in source/evidence/report output.
- Records discovered page categories in JSON and Markdown.
- Handles PDF-like fixture sources and optional real PDF parsing through a page-indexed extractor protocol.
- In browser mode, obvious PDF URLs and Playwright `Download is starting` PDF navigations fall back to HTTP byte download so the source is recorded as `SourceType.PDF`.
- Handles public JSON/API sources as first-class evidence sources.
- Preserves HTML table text for deterministic extraction from table-heavy admissions pages.
- Parses programme-catalog tables with mapped/reordered columns, known metadata
  columns, grouped rows that inherit table context, and nearby faculty/school
  section context. Inherited values remain conservative and carry their own
  field-level evidence instead of borrowing the programme-name evidence.
- Filters obvious static assets and low-value privacy/GDPR/cookie/terms-like
  documents before follow/fetch decisions while preserving admissions
  prospectus, requirements, fee, and programme PDFs.
- Strips common navigation/header/footer/cookie noise before extraction and records core-field coverage diagnostics.
- Records optional classification-assist diagnostics and a summary when guarded
  classification assist is enabled; zero-trigger runs remain visible, and
  candidates are not applied to facts.
- Records source-level extraction diagnostics plus field-level
  `missing_reasons` for missing core fields. Mixed extractor failures now
  prefer `attempted_no_match` over context-gate skips, but these diagnostics
  still describe current crawl/extractor outcomes and are not official absence
  evidence.
- Detects obvious WAF/challenge/noindex/access-denied sources and records them
  as `blocked_or_challenge` diagnostics. These sources remain reviewable but
  are not treated as usable admissions text for fact extraction.
- Supports guarded LLM source navigation by default for live scans when a
  provider is available. Candidate URLs and queries are validated, reported
  under diagnostics, and accepted URL candidates can enter the bounded crawl
  frontier; they never become admissions facts without fetched official-source
  evidence.
- Adds a lightweight cleaned-candidate layer for key fields: `raw_text`, `parsed`, and `parse_status`.
- Parses common English test scores, fee amounts, and application dates when the raw text is specific enough; otherwise the raw candidate remains visible for manual review.
- Keeps raw fee-table/reference candidates when an official undergraduate fee
  page exposes only table labels rather than amounts; these remain
  `raw_needs_manual_review` and are not structured fee amounts. A fixture-backed
  NTU-style amount-row case verifies that explicit `S$` values parse as
  structured `SGD` amounts when the source actually contains them.
- Filters undergraduate core extraction away from common pollution pages such as postgraduate/graduate pages, hall/accommodation pages, search pages, current-students pages, privacy/contact forms, and generic marketing pages unless they have strong undergraduate admissions context.
- Records discovery relevance diagnostics under `run.config`, including
  per-source discovery score, relevance signals, and strategy name.
- Uses a built-in `admissions_programme_profile` relevance strategy by default,
  so undergraduate admissions, requirements, dates, fees, English requirements,
  documents, contacts, and programme catalogue pages are prioritized without a
  user keyword query.
- Keeps deterministic `--keyword-query` and `bm25-like` as legacy debug
  surfaces; they are no longer the recommended route for ordinary scans.
- Supports guarded mock and OpenAI LLM classification-assist diagnostics,
  source navigation, and captured programme-catalog row category/mode hints;
  Anthropic and Gemini remain reserved and fail closed. LLM keyword-plan
  generation has been removed from the user-facing workflow.
- Guards optional live/browser/PDF/LLM/crawl4ai/ScrapeGraphAI capabilities behind interfaces; they are not required for core tests.
- Writes legacy `result.json`, `report.md`, root `programme_catalog.csv` when
  programme rows exist, and a cleaning-oriented `structured/` output layer.

## Current implementation decision

The first implementation uses Python stdlib `dataclasses` plus explicit validators for runtime records, evidence links, warnings, and tests. Pydantic is intentionally not a core dependency in this MVP; if the project later adopts Pydantic, schema code, tests, `pyproject.toml`, and this README must be updated together.

Optional capabilities are represented as dependency groups / guarded execution modes:

- `browser`: Playwright browser-backed live crawling support
- `pdf`: optional pypdf parsing support for live PDF sources
- `llm`: guarded mock/OpenAI classification-assist diagnostics, source-navigation frontier hints, and captured programme-catalog row hints
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

- `/tmp/uac-smoke/result.json` — legacy full internal snapshot with facts,
  sources, evidence, warnings, diagnostics, and diff metadata.
- `/tmp/uac-smoke/report.md` — human-readable fact/warning/source/evidence report.
- `/tmp/uac-smoke/structured/` — cleaning-oriented JSON/JSONL/CSV tables for
  downstream joins.

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

Recommended live scan from a university homepage:

```bash
python -m university_admissions_crawler.cli https://www.example.edu/ \
  --output-dir outputs/example-homepage
```

For live URLs, the CLI enables HTTP crawling and LLM-assisted source navigation
and structured extraction fallback by default, infers the allowed official
domain from the input URL, uses the built-in `admissions_programme_profile`
relevance strategy, and applies live defaults of `max_pages=80`, `max_depth=4`,
`timeout_seconds=60`, and a four-page targeted programme-detail reserve inside
the same `max_pages` budget. The first pass parses captured catalogs; the second
pass fetches only detail URLs that uniquely match catalog rows still missing a
faculty/school and pass the catalog-family trust gate. Use
`--programme-detail-reserve 0` to disable this second pass; fixture scans default
to zero. Small page caps limit the effective reserve to at most one quarter of
`max_pages`. Provider selection defaults to `--llm-provider auto`:
it uses OpenAI when `OPENAI_API_KEY` is present, otherwise records
`llm_runtime.provider = none` and continues with deterministic crawling. Use
`--no-llm` or `--deterministic-only` to disable LLM-assisted live crawling. Use
`--enable-browser` only when a site needs JavaScript rendering; it keeps
HTTP-first fetching and uses Playwright as a fallback for high-value rendered
pages.

Official-source trust uses the vendored Public Suffix List in
`university_admissions_crawler/resources/public_suffix_list.dat`. The seed host
is always allowed; sibling official subdomains are allowed only when they share
the same PSL-backed registrable domain and `allow_official_subdomains` remains
enabled. PSL failures fail closed rather than falling back to a naive last-two-
labels domain guess.

For a smaller smoke run, add `--smoke`; it caps the run at `max_pages<=20` and `max_depth<=2` even if larger values are supplied. In batch mode, a university config's own `max_pages` or `max_depth` still overrides the CLI smoke cap for that university. `--enable-scrapegraph` remains a guarded future surface and fails closed. `--llm-provider mock` remains the deterministic test provider, `--llm-provider openai` uses the OpenAI Responses API, and `--llm-provider openai-chat` uses an OpenAI-compatible `/v1/chat/completions` endpoint. Both hosted providers are available for source planning, classification assist, programme-catalog hints, and structured extraction fallback. `--keyword-query` is deterministic debug input and no longer enables LLM keyword-plan generation. Anthropic and Gemini provider names remain reserved and fail closed.

To compare with a previous run:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --previous-result /tmp/uac-smoke/result.json \
  --output-dir /tmp/uac-smoke-next
```

`run.config.diff` keeps the legacy `changed_sources` source-hash list and
index-based `changed_fields` list, and also records order-independent impact
ledgers for unique source URL additions/removals, authoritative
`programme_catalog` semantic changes, and compatibility `programmes` changes.
Catalog field changes are separated into gained, lost, and changed values. The
Markdown report renders the counts and a bounded source URL sample under
`Incremental Impact`; complete lists remain in `result.json`.

`run.config.diff.field_warning_policy` records the `stable-semantic-v3` warning
policy. Raw legacy paths remain available in `changed_fields`, but paths under
`/programmes/<index>/...` and the tracked admissions, fee, scholarship, visa,
housing, and contact collections no longer generate one warning per shifted
list position. `run.config.diff.structured_collections` contains 12
order-independent `RequirementRecord` ledgers. A real semantic change emits one
aggregate `incremental_change` warning at the affected collection path; stable
non-list paths retain their original path-specific warnings, capped at 20. The
policy records retained unstable paths, suppressed index warnings, truncation,
semantic warning fields, and emitted field-warning counts, and the Markdown
report exposes the summary. `source_mix_only_change` also requires every
structured collection to be stable. This intentionally changes warning
cardinality without removing the legacy diff fields. If no prior result is
supplied, the output includes an explicit `needs_manual_check` warning for the
missing baseline and marks the ledgers as unavailable.

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

Current working-tree validation after the batch-validation slice:

```bash
.venv314/bin/python -m pytest -q
```

The latest local pytest run passed `390` tests.

The focused target group for the structured-output compatibility slice is:

```bash
.venv314/bin/python -m pytest -q tests/test_structured_output.py tests/test_programme_catalog_output.py tests/test_report_cli.py
```

The latest target-group run passed `53` tests.

## Evidence and safety policy

- Every non-unknown `FieldValue` must reference an evidence item with the exact claim path.
- Evidence items must point to real claim paths.
- Conflicting official values are preserved and downgraded with conflict warnings.
- Stale academic-year sources are warning-producing.
- Non-official supporting sources and ambiguous applicant-group requirements are warning-producing.
- Unsupported LLM candidate claims are rejected unless claim path, source text, evidence snippet, and candidate value all line up.
- Keyword-plan debug input is deterministic and not LLM-generated. It is
  recorded only when supplied and can only affect discovery ordering when an
  explicit relevance strategy uses it.
- LLM source-plan output is never promoted into admissions facts. It is
  schema-validated, URL-validated, recorded as diagnostics, and accepted source
  URL candidates may be used only as bounded crawl frontier hints.
- Fetch/bad-status/parse/PDF failures produce warnings and the scan continues when other usable sources remain.

## Non-goals

- No Web UI or admin backend in v1.
- No automated admissions verdict or recommendation.
- No unbounded crawl.
- No unsupported factual inference.
- No required paid API credentials or hosted-provider calls in core tests.
- No LLM keyword-plan generation.
- No required hosted LLM calls in core tests or default runs; OpenAI is an
  opt-in guarded provider for source navigation, classification assist, and
  captured programme-catalog row hints only.

## Live crawling status

Live crawling is the default for non-fixture HTTP(S) URLs. Start from the
official university homepage whenever possible:

```bash
python -m university_admissions_crawler.cli https://www.nus.edu.sg/ \
  --output-dir outputs/nus-homepage
```

Advanced live controls remain available when you need tighter boundaries:

```bash
python -m university_admissions_crawler.cli https://www.example.edu/ \
  --output-dir outputs/example-auto \
  --max-pages 40 \
  --max-depth 3 \
  --allowed-host cdn.example.edu \
  --allowed-domain example.edu \
  --timeout-seconds 45
```

`--auto` and `--enable-live-network` are still accepted for compatibility, but
they are no longer required for ordinary one-URL live scans.

JavaScript-rendered pages can use the optional Playwright browser fetcher:

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
python -m university_admissions_crawler.cli https://www.nus.edu.sg/ \
  --enable-browser \
  --output-dir outputs/nus-browser-test \
  --browser-wait-until domcontentloaded \
  --timeout-seconds 45 \
  --max-pages 80 \
  --max-depth 4
```

All modes write the same output shape:

- `result.json`
- `report.md`
- `programme_catalog.csv` when `AdmissionsData.programme_catalog` is non-empty
- `structured/manifest.json`
- `structured/institution.json`
- `structured/facts.jsonl`
- `structured/sources.jsonl`
- `structured/evidence.jsonl`
- `structured/missing_fields.jsonl`
- `structured/warnings.jsonl`
- `structured/diagnostics.json`
- `structured/records/programme_catalog.jsonl`
- `structured/records/programme_catalog.csv`
- `structured/records/international_requirements.jsonl`
- `structured/records/application_periods.jsonl`
- `structured/records/fees.jsonl`
- `structured/records/english_requirements.jsonl`
- `structured/records/accepted_qualifications.jsonl`
- `structured/records/required_documents.jsonl`
- `structured/records/standardized_tests.jsonl`
- `structured/records/selection_tests_or_interviews.jsonl`
- `structured/records/scholarships.jsonl`
- `structured/records/visa.jsonl`
- `structured/records/housing.jsonl`
- `structured/records/contacts.jsonl`
- `structured/records/programmes_legacy.jsonl`
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
- `programme_catalog_summary` and `programme_catalog_candidate_diagnostics` —
  aggregate and row-level HTML candidate decisions, rejection reasons, table
  shapes, section/group context, and manual-review counts. They are audit data,
  not proof that a catalog is complete.
- `programme_catalog_field_evidence` — optional field-to-claim-path mappings for
  programme values inherited from table or section context.
- `relevance_strategy` — the discovery scoring strategy used for the scan.
- `keyword_plan` — present only when deterministic `--keyword-query` debug
  input was supplied.
- `classification_assist` and `classification_assist_summary` — present only
  when guarded classification assist is enabled; suggestions are
  diagnostics-only and remain unapplied.
- `llm_source_plan` — present only when guarded source planning is enabled. It
  records trigger state, provider/schema/fallback status,
  candidate queries, accepted/rejected candidate URLs, applied candidate URLs,
  budget-skipped candidate URLs, warnings, and the diagnostic boundary. Accepted
  candidates are crawl frontier hints, not admissions facts.

The report also marks parsed versus raw-only values. For example, parsed fee
rows appear with structured `currency`, `amount`, `student_group`,
`academic_year`/`cohort`, `billing_period`, `fee_type`, and `raw_text` when
those parts can be inferred. When present, keyword plans, classification
assist, source planning, extraction diagnostics, and missing reasons are shown
in diagnostic sections before facts; they are not admissions facts.

`structured/` is the preferred downstream-cleaning entry point. It keeps
`result.json` as the legacy/debug snapshot and exports joinable `source_id`,
`evidence_id`, and `record_id` values. `structured/facts.jsonl` currently
contains programme catalog, all 12 tracked requirement collections, and legacy
programme rows. `structured/sources.jsonl` also carries normalized source
host/path helper fields, and programme rows carry
`normalized_programme_name_key` for initial cross-school cleaning and dedupe.
Programme JSONL rows expose optional field-level evidence refs, while
`structured/diagnostics.json` preserves the candidate ledger and field-evidence
mapping when present. It also exposes a compact top-level
`programme_catalog_completeness` object with status, canonical capture,
candidate/section conservation, failure stages/reasons, and the recommended
next action. Its `row_yield` block preserves raw accepted counts/ratios and
adds claim-path/structural-anchor quality-adjusted counts, exclusion reasons,
and raw/effective low-yield flags. The full summary remains under
`diagnostics.programme_catalog_summary`. Whenever `run.config.diff` exists,
including an explicit `baseline=none` result, its lossless payload is also
exported as `diagnostics.diff`; older objects without diff metadata omit that
optional key.
The cleaning CSV columns remain unchanged.
The current schema version is `structured-output-v1`; this branch treats the
structured layer as additive and keeps legacy outputs intact. Downstream
cleaning should branch on `schema_version`, prefer `structured/facts.jsonl` or
record-specific JSONL over `result.json`, and treat diagnostics as diagnostics,
not admissions facts.

## Relevance and Legacy Keyword Debug

Discovery now uses the built-in `admissions_programme_profile` strategy by
default. This profile favors official undergraduate admissions and programme
catalogue sources, including requirements, dates, tuition/fees, English or
international requirements, required documents, contacts, degrees, majors,
bulletins, catalogues, and undergraduate programme pages. It also keeps negative
signals for low-value or off-target pages such as news, alumni, giving, jobs,
staff, privacy/cookie pages, summer/pre-university material, postgraduate-only
pages, and executive/continuing education.

The profile is still bounded by `max_pages`, `max_depth`, and allowed
host/domain policy. It only affects source discovery priority and diagnostics;
it does not write admissions facts.

The following options are legacy diagnostics for developers comparing discovery
behavior. They are not part of the recommended homepage-first path.

`--keyword-query` remains available only as deterministic debug input. To record
a reviewable keyword plan without switching away from the default profile:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --keyword-query "undergraduate admissions IELTS fees" \
  --output-dir /tmp/uac-keyword-plan
```

The run keeps `admissions_programme_profile` discovery scoring and writes
`run.config.keyword_plan`.

To opt in to the legacy deterministic keyword-assisted ranking path:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --keyword-query "fees tuition international" \
  --relevance-strategy bm25-like \
  --output-dir /tmp/uac-bm25-like
```

`bm25-like` is a lightweight token/url-hint overlap scorer layered on top of
the legacy rule-based score. It is not a full BM25 implementation, is never the
default, and remains bounded by `max_pages`, `max_depth`, allowed hosts/domains,
and the follow threshold.

LLM keyword-plan generation is no longer supported. `--keyword-query` remains a
deterministic debug input for explicit keyword-plan diagnostics and the legacy
`bm25-like` path.

LLM-assisted source navigation is enabled by default for live scans when a
provider is available. Use `mock` for deterministic offline tests:

```bash
python -m university_admissions_crawler.cli https://www.example.edu/ \
  --enable-llm \
  --llm-provider mock \
  --enable-source-planning \
  --output-dir outputs/example-source-navigation
```

The provider can only suggest source candidates. Candidate URLs must pass
deterministic domain/source-value validation before they can enter the bounded
crawl frontier, and extracted facts still require captured official-source
evidence.

For a real OpenAI-backed live run, provide credentials through environment
variables; keys are never read from fixture files or written to outputs. For
team/local development, copy the tracked template to an ignored local `.env`
file:

```bash
cp .env.example .env
```

Edit `.env` locally:

```bash
OPENAI_API_KEY=your-real-key
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=
OPENAI_CHAT_COMPLETIONS_PATH=/v1/chat/completions
OPENAI_CHAT_RESPONSE_FORMAT=json_schema
OPENAI_REASONING_EFFORT=
OPENAI_USER_AGENT=
UAC_LLM_PROVIDER=
```

Load it into the current shell before running the crawler:

```bash
set -a
source .env
set +a
```

Verify that the variables are present without printing the key:

```bash
python -c 'import os; print("OPENAI_API_KEY set:", bool(os.environ.get("OPENAI_API_KEY"))); print("OPENAI_MODEL:", os.environ.get("OPENAI_MODEL"))'
```

Then run the default LLM-assisted live crawler:

```bash
python -m university_admissions_crawler.cli https://www.example.edu/ \
  --output-dir outputs/example-openai-auto
```

`.env` is ignored by git; `.env.example` is the only credential-related file
that should be committed, and it must not contain real keys. The CLI does not
auto-load `.env`; it reads provider variables from the process environment.

Provider modes:

- `openai` uses the OpenAI Responses API at `/v1/responses`.
- `openai-chat` uses an OpenAI-compatible chat completions endpoint. Set
  `UAC_LLM_PROVIDER=openai-chat` or pass `--llm-provider openai-chat`, set
  `OPENAI_BASE_URL` to the relay base URL, and keep
  `OPENAI_CHAT_COMPLETIONS_PATH=/v1/chat/completions` unless the relay uses a
  different path.
- `OPENAI_CHAT_RESPONSE_FORMAT` defaults to `json_schema`. Set it to
  `json_object` or `none` only when a relay or relay WAF rejects the larger
  schema-constrained `response_format` request body. Disabling schema
  constraint lowers model-side guarantees, but the crawler still strictly
  parses JSON and runs the existing payload validators before any result write.
- `OPENAI_REASONING_EFFORT` is optional. When set, the chat-completions provider
  sends it as `reasoning_effort`; leave it unset if the relay rejects that
  parameter.
- `OPENAI_USER_AGENT` is optional and only affects OpenAI-compatible relay
  requests. Set it when a relay WAF blocks Python's default `urllib` client
  signature.

OpenAI-compatible relays vary in JSON schema support. The chat-completions
provider requests schema-constrained JSON via `response_format` by default,
then still strictly parses JSON and runs the existing payload validators.
Provider output never writes admissions facts directly.

Guarded classification assist can also be enabled for low-confidence page
classifications. The same flag enables bounded programme-catalog category/mode
hints for ambiguous captured candidate rows:

```bash
python -m university_admissions_crawler.cli tests/fixtures/mini_university_site \
  --fixture \
  --enable-llm \
  --llm-provider mock \
  --enable-classification-assist \
  --output-dir /tmp/uac-mock-classification-assist
```

This writes `classification_assist` and `classification_assist_summary` under
`run.config` when assist is enabled. Even when no low-confidence page triggers
assist, the summary records a zero-trigger state. Page-classification assist
candidates are never applied to `PageCategory`, extractor routing, or facts.
Programme-catalog hints can only classify already captured candidate rows; they
cannot create programme names or admissions facts.

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

API safe capture, pagination, and filter enumeration reject off-domain final
redirects by default. If a university-owned API legitimately redirects to a CDN
or another host, add the exact host with `--allowed-host`; use
`--allowed-domain` only when the full domain is institution-controlled. Rejected
API redirects are shown in the Markdown report with the captured final URL and a
configuration suggestion.

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
- `outputs/batch/<university-id>/structured/`
- `outputs/batch/<university-id>/sources/`

Batch runs also write cross-university cleaning tables:

- `outputs/batch/structured/manifest.json`
- `outputs/batch/structured/all_programme_catalog.jsonl`
- `outputs/batch/structured/all_missing_fields.jsonl`
- `outputs/batch/structured/all_sources.jsonl`
- `outputs/batch/structured/all_international_requirements.jsonl`
- `outputs/batch/structured/all_application_periods.jsonl`
- `outputs/batch/structured/all_fees.jsonl`
- `outputs/batch/structured/all_english_requirements.jsonl`
- `outputs/batch/structured/all_accepted_qualifications.jsonl`
- `outputs/batch/structured/all_required_documents.jsonl`
- `outputs/batch/structured/all_standardized_tests.jsonl`
- `outputs/batch/structured/all_selection_tests_or_interviews.jsonl`
- `outputs/batch/structured/all_scholarships.jsonl`
- `outputs/batch/structured/all_visa.jsonl`
- `outputs/batch/structured/all_housing.jsonl`
- `outputs/batch/structured/all_contacts.jsonl`

These `all_*.jsonl` files are concatenations of the already generated
per-university structured JSONL files. They do not refetch, dedupe, infer, or
rewrite admissions facts. The batch manifest records the structured schema,
input university directory count, row count per table, and file map. Missing
requirement files from older per-university outputs contribute zero rows rather
than failing the batch merge. Its `input_coverage` entry for every table records
expected, present, missing, nonempty, and empty input-file counts plus the
corresponding input directory names. A present empty file and a missing file are
therefore distinguishable; neither state by itself proves that the university's
official site lacks that admissions information. The manifest also reports
`input_validation` per table and an `input_validation_summary`. This audit checks
that each JSONL row is an object with the current `schema_version`, that its
`university_id` matches the input directory, and that record tables use the
expected `record_type`. Invalid rows remain in the concatenated output and its
row count, but affected files and reason counts are explicit in the manifest.
Missing files are coverage gaps, not invalid rows. Malformed JSON still fails the
merge when it occurs in a file being concatenated, instead of being classified
as a row-validation issue.

The same validation also checks the minimum table shape: source rows require
`run_id`, `source_id`, and `source_url`; missing-field rows require `run_id`,
`field_key`, `status`, and `source_urls`; record rows require `run_id`,
`record_id`, `value`, `source_refs`, and `evidence_refs`. Empty reference lists
are valid. Each reference that is present must contain a string identifier that
resolves to the same university's readable `sources.jsonl` or `evidence.jsonl`.
`reference_index_coverage` distinguishes missing, unreadable, and readable index
files and reports unusable identifier rows. An unreadable auxiliary evidence
index is audited without dropping record rows; malformed JSON in a file that is
itself being concatenated still fails the merge.

Identifier auditing treats IDs as unique within each university. Duplicate
`source_id` and `evidence_id` values are excluded from the resolvable index and
reported separately; references to them are `ambiguous_*_ref`, not resolved.
`evidence_validation` checks each readable evidence row's minimum identity and
its `source_id` link to the same university's source index. Record IDs are
checked across programme catalog and all 12 requirement tables, so both
same-table duplicates and cross-table collisions are visible in
`input_validation`. These checks remain diagnostic: duplicate rows are not
removed or reordered.

The top-level `batch_validation` object reduces those detailed audits to one
deterministic verdict. `valid` means the exported structured artifacts passed
the current integrity checks; `incomplete` means only expected input or
reference-index files are missing, or no university inputs were supplied;
`invalid` means rows are invalid, a reference index is unreadable, identifiers
are malformed or ambiguous, or evidence-to-source links fail validation.
`invalid` takes precedence over `incomplete`. The object includes stable reason
codes and aggregate metrics, but remains non-blocking: it does not change CLI
exit codes or remove rows. It also does not claim that crawling or admissions
data is complete. File-gap metrics describe separate audit surfaces, so one
physical index file can contribute to both an aggregate-input gap and a
reference-index gap.

Batch configs normally only need a homepage seed and optional domain/limit
controls:

```json
{
  "id": "example-u",
  "name": "Example University",
  "seed_urls": ["https://example.edu/"],
  "allowed_hosts": ["cdn.example.edu"],
  "allowed_domains": ["example.edu"],
  "mode": "live-http",
  "max_pages": 80,
  "max_depth": 4
}
```

Batch configs may still opt in to the legacy keyword-assisted discovery path per
university for debugging:

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
`admissions_programme_profile` strategy. If `relevance_strategy` is
`bm25-like`, `keyword_query` is required.

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
