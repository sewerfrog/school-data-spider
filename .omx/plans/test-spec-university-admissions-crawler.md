# Test Spec — University Admissions Crawler Broad MVP

## Test Strategy

This test spec validates the evidence-first MVP described in `.omx/plans/prd-university-admissions-crawler.md` and `.omx/specs/deep-interview-university-admissions-crawler.md`. Tests must be deterministic and must not require paid APIs, live network, or browser installation by default.

## Test Pyramid

### Unit tests

- URL normalization and deduplication.
- Domain allowlist / controlled subdomain policy.
- Positive/negative keyword scoring.
- Page classification into all required categories plus `irrelevant`.
- Schema construction and serialization.
- Evidence validation for non-unknown claims.
- Warning generation for missing evidence, stale pages, conflicts, non-official sources, ambiguous applicant groups, and manual-check fields.
- Report rendering sections and admissions-verdict exclusion.

### Integration tests

- Fixture mini-site discovery with max depth/pages enforced.
- Fixture fetcher -> classifier -> extractor -> normalizer pipeline.
- PDF extractor interface with mocked/page-indexed fixture output.
- Optional LLM provider mock that returns both supported and unsupported claims; unsupported claims must be rejected/downgraded.
- Fetch adapter-contract test proving fixture/static fetcher and crawl4ai stub/implementation satisfy the same `FetchResult` / source-evidence protocol.
- Incremental/diff test proving changed source hashes or field values are recorded when previous output exists, and first-run absence of prior data is represented explicitly.
- Failure recovery test proving timeout, bad status, parse failure, and PDF extraction failure become warnings/retriable events rather than whole-crawl aborts.
- Optional dependency behavior test proving core tests pass without browser installs, paid credentials, hosted APIs, or optional provider extras.

### CLI smoke tests

- Fixture command writes `result.json` and `report.md`.
- Output JSON includes run metadata, sources, evidence, confidence, warnings, and admissions/programme structures.
- Markdown report includes facts, warnings/manual-check, and evidence appendix.

### Optional live smoke tests

Only run with explicit opt-in flags/environment. Use low caps such as `max_pages=20`, `max_depth=2`, and no paid providers unless explicitly configured.

## Fixtures

Create `tests/fixtures/mini_university_site/` with pages representing:

- homepage
- undergraduate admissions
- international requirements
- application deadlines
- accepted qualifications
- programme list
- programme prerequisites
- fees
- scholarships
- visa/student pass
- housing
- contact
- irrelevant news/events/alumni/donate/staff/jobs/blog pages
- stale academic-year page
- conflicting deadline/requirement pages
- PDF-like mocked source with page-numbered evidence

## Acceptance Matrix

| Requirement | Test evidence |
|---|---|
| CLI outputs JSON + Markdown | `test_cli_smoke.py` |
| Bounded crawling | `test_discovery.py` max_pages/max_depth cases |
| Domain policy | `test_filters.py` |
| Required page categories | `test_classifier.py` |
| Non-unknown claims have evidence | `test_schema_evidence.py`, integration smoke |
| Unknown/manual-check instead of fabrication | `test_normalizer.py` |
| Stale/conflict warnings | `test_normalizer.py` |
| PDF source/page refs | mocked PDF extractor test |
| Fetch adapter contract | adapter contract test for fixture/static fetcher and crawl4ai stub/implementation |
| Incremental diff/source hash behavior | diff test with prior output fixture and first-run no-prior-data case |
| Failure recovery warnings | timeout/bad status/parse/PDF failure fixture tests |
| Optional dependencies guarded | test/default config proving browser/paid API/provider extras are skipped unless opt-in |
| Report evidence appendix | `test_report.py` |
| No UI/backend/admissions verdict | report/CLI/package surface tests |

## Quality Gates

Before implementation is considered complete:

1. Full deterministic offline test suite passes locally; live/network/browser/provider tests are skipped by default unless explicitly opted in.
2. Fixture CLI smoke produces valid output files.
3. Generated JSON passes schema/evidence validation.
4. Markdown report contains an evidence appendix and manual-check section.
5. Optional live/network paths are documented as skipped unless explicitly enabled.
