# Consensus Plan Draft — University Admissions Crawler Broad MVP

## Inputs and Evidence

- Requirements source: `.omx/specs/deep-interview-university-admissions-crawler.md`
- The repo is effectively empty; implementation will create a Python package scaffold.
- Spec lines 17-31 define the core product: one homepage URL in, discover/extract undergraduate admissions information, JSON + Markdown evidence report out.
- Spec lines 45-62 define required page categories, extraction fields, evidence-first normalization, and optional LLM/ScrapeGraphAI boundaries.
- Spec lines 64-71 define non-goals: no UI/backend, no admissions verdict, no unbounded crawl, no unsupported inference, no non-official primary evidence.
- Spec lines 73-90 authorize implementation choices but reserve paid credentials, large-scale crawling, persistent service/UI, and admissions recommendations for user confirmation.
- Spec lines 92-102 define hard constraints: evidence over coverage, `unknown`/`needs_manual_check`, `retrieved_at`/`academic_year`, PDF source typing/page refs, bounded crawl, official source preference, warnings.
- Spec lines 131-158 propose responsibility boundaries for crawler, classifier, extractor, evidence, pipeline, reports, and tests.
- Spec lines 160-170 propose default crawl limits/keyword filters.
- Spec lines 172-249 define schema concepts.
- Spec lines 251-259 define quality-control requirements.
- Spec lines 262-276 define acceptance criteria.
- Official docs checked during deep-interview: Crawl4AI supports asynchronous crawling, browser/run config, Markdown generation, CSS/XPath extraction, LLM extraction, and dynamic-page crawling; ScrapeGraphAI v2 exposes hosted API services such as scrape/extract/search/crawl/monitor/history and requires API-key style usage for hosted services.

## Requirements Summary

Build a broad but bounded MVP Python CLI/library for university undergraduate admissions information extraction. The MVP should start with one official university homepage URL, discover official admissions/programme/requirements pages, classify pages into admissions-related categories, extract structured data, attach source evidence to every non-unknown claim, and render JSON plus Markdown reports. The first implementation should prioritize source-traceable correctness over complete field fill-rate.

## RALPLAN-DR Summary

### Principles

1. Evidence before extraction coverage: every non-unknown claim must carry source provenance.
2. Bounded crawling before clever crawling: crawl scope is explicit, configurable, and testable.
3. Modular adapters over hard dependencies: crawler, extraction, PDF, LLM, and ScrapeGraphAI integration stay behind interfaces.
4. Offline-verifiable core before live-network confidence: tests must pass without paid APIs or unstable external sites.
5. Human review is a product feature: low confidence, stale, conflicting, and missing data must surface as warnings/manual-check items.

### Decision Drivers

1. **Safety/accuracy for high-stakes admissions data** — avoid hallucinated requirements and preserve official evidence.
2. **Deliverable breadth within MVP boundaries** — broad field coverage without UI/backend or admissions verdicts.
3. **Implementation resilience** — heterogeneous university sites, PDFs, subdomains, JavaScript, and conflicting pages require staged, testable components.

### Viable Options

#### Option A — Local evidence-first pipeline with capability-based fetch engines (favored)

Pros:
- Best matches bounded crawl + evidence storage requirements.
- Keeps tests offline by separating fetcher/extractor interfaces from fixtures.
- Avoids paid-hosted API as mandatory dependency.
- Allows optional LLM/ScrapeGraphAI adapters later without changing schema/report contract.

Cons:
- More local architecture work: URL scoring, classification, schema, evidence store, reporting.
- Rule/heuristic extraction will be imperfect on diverse sites until iterated.
- Browser dependencies may need careful installation if crawl4ai is selected.

#### Option B — Hosted/LLM-first extraction using ScrapeGraphAI as primary path

Pros:
- Faster to prototype structured extraction on some pages.
- Hosted crawl/extract APIs may reduce local browser/crawler complexity.
- Good candidate for comparison or optional extractor adapter.

Cons:
- Hosted API key/cost/availability conflicts with offline-verifiable MVP and requires explicit user confirmation for credentials.
- LLM-first extraction raises hallucination and provenance risks unless heavily constrained.
- Harder to guarantee evidence attachment and deterministic tests.

#### Option C — Minimal no-new-dependency scraper with requests/stdlib + fixtures first

Pros:
- Very lightweight and deterministic.
- Fast scaffold and tests.
- Good for schema/report/evidence contract validation.

Cons:
- Weak for dynamic pages, sitemap variants, PDFs, and realistic crawling breadth.
- Would under-deliver the selected broad MVP ambition.
- Likely requires rework when adding crawl4ai/browser/PDF capabilities.

### Favored Direction

Adopt Option A with an explicit capability-based engine policy: create an evidence-first modular Python pipeline using a single fetch/capture protocol. Fixture/static fetchers are the deterministic default for tests and ordinary static pages; crawl4ai is the preferred live/dynamic engine when live mode or JavaScript-heavy pages require it; ScrapeGraphAI remains an optional adapter/spike, not a required v1 path. All engines must emit the same source/evidence contract.

## ADR

### Decision

Implement the MVP as a modular Python CLI/library centered on an evidence-first local pipeline: discovery -> fetch/content capture -> classification -> extraction -> normalization/evidence validation -> JSON + Markdown reporting. Use one fetch/capture protocol with capability-based engines: fixture/static fetchers for deterministic tests and ordinary static pages, crawl4ai for explicitly enabled live/dynamic crawling, and optional ScrapeGraphAI/LLM providers behind adapters. All engines must preserve identical source/evidence contracts.

### Drivers

- Admissions information is high-impact and must be traceable to official sources.
- The user selected broad MVP coverage but evidence precision as the top success criterion.
- The repository is empty, so the plan can define clean module boundaries from the start.
- User authorized autonomous choices for structure, crawl limits, dependencies, LLM strategy, and tests.

### Alternatives considered

- ScrapeGraphAI/hosted LLM as primary pipeline: rejected for v1 default because hosted credentials/cost and LLM nondeterminism conflict with offline tests and evidence-first correctness.
- Minimal requests-only scraper: rejected as the main strategy because it is too weak for broad MVP requirements such as dynamic pages, PDFs, controlled subdomains, and realistic content extraction.

### Why chosen

The chosen architecture gives the strongest path to a broad but safe MVP: evidence contracts and tests remain deterministic, while live crawling/PDF/LLM capabilities can be added without invalidating the schema and report contracts.

### Consequences

- More initial scaffolding than a single script.
- The first implementation should stage features to avoid false confidence: schema/evidence/report contracts first, then discovery/classification, then real fetch/PDF/LLM adapters.
- Some fields will intentionally remain `unknown`/`needs_manual_check` until evidence quality is sufficient.

### Follow-ups

- After planning, implement via `$ultragoal` or Team + Ultragoal, not directly in the planning workflow.
- If real hosted LLM/ScrapeGraphAI credentials are needed, request explicit user confirmation at execution time.

## Proposed File Plan

Create this Python package layout unless implementation discovers a better equivalent:

```text
pyproject.toml
README.md
university_admissions_crawler/
  __init__.py
  cli.py
  config.py
  crawler/
    __init__.py
    discovery.py
    fetcher.py
    filters.py
    sitemap.py
  classifier/
    __init__.py
    page_classifier.py
  extractor/
    __init__.py
    schema.py
    html_extractor.py
    pdf_extractor.py
    llm_provider.py
    normalizer.py
  evidence/
    __init__.py
    provenance.py
    store.py
  pipeline/
    __init__.py
    run_university_scan.py
  reports/
    __init__.py
    render_report.py
tests/
  fixtures/
    mini_university_site/
    sample_pages/
  test_filters.py
  test_discovery.py
  test_classifier.py
  test_schema_evidence.py
  test_normalizer.py
  test_report.py
  test_cli_smoke.py
```

## Implementation Plan

### Phase 0 — Project scaffold and dependency policy

Files:
- `pyproject.toml`
- `README.md`
- package `__init__.py` files

Actions:
1. Create a minimal Python package with a CLI entry point such as `university-admissions-crawler`.
2. Add formatting/test tooling only if needed and justified. Use `pytest` for tests.
3. Use one validation system consistently across runtime records, evidence, normalization, and tests: prefer Pydantic models if the implementation adopts the dependency; otherwise choose dataclasses plus explicit validators, but do not keep both as equal runtime paths after implementation begins.
4. Package optional capabilities as extras or documented optional groups: browser crawling/crawl4ai, PDF parsing, LLM providers, and ScrapeGraphAI. Core tests must pass without optional credentials, hosted APIs, or browser installation.
5. Document that real network crawling and paid LLM/ScrapeGraphAI calls are optional execution modes; tests must not require credentials.

Acceptance checks:
- `python -m university_admissions_crawler.cli --help` or configured console script prints usage.
- `pytest` discovers tests.

### Phase 1 — Core schema, evidence model, and warning semantics

Files:
- `university_admissions_crawler/extractor/schema.py`
- `university_admissions_crawler/evidence/provenance.py`
- `university_admissions_crawler/extractor/normalizer.py`
- `tests/test_schema_evidence.py`
- `tests/test_normalizer.py`

Actions:
1. Define normalized data structures for institution, run metadata, source records, admissions fields, applicant groups, qualifications, required documents, English/standardized tests, interview/test/portfolio requirements, programmes, prerequisites, fee/scholarship/visa/housing/contact records, evidence items, confidence, and warnings.
2. Require every non-unknown nested claim or array item to be linkable to one or more evidence items by field path/claim id; otherwise mark it `needs_manual_check` or emit a `missing_evidence` warning according to the chosen validator behavior. This applies especially to `programmes[]`, `requirements[]`, `programme_prerequisites[]`, fee/scholarship/visa/housing/contact records, and PDF page-level claims.
3. Keep all conflicting official sources and downgrade confidence rather than deleting or overwriting the losing source.
4. Define constants/enums for page categories, source types, confidence levels, and warning codes.
5. Implement validation that flags missing evidence, stale/conflicting evidence, and manual-check fields. Keep `normalizer.py` as the single policy owner for warnings/conflicts/manual-check behavior so extractors and reports do not duplicate policy.
6. Ensure race/skin-color/parents-race fields are not modeled as normal eligibility variables; if detected in source text later, only allow warning-tagged evidence records.

Acceptance checks:
- Unit tests prove non-unknown claims without evidence produce `missing_evidence` warnings or validation failures according to chosen design.
- Unit tests prove unknown/manual-check fields are allowed without fabricated evidence.
- Unit tests cover stale/conflict warning records.

### Phase 2 — URL filtering, domain policy, sitemap/homepage discovery

Files:
- `university_admissions_crawler/config.py`
- `university_admissions_crawler/crawler/filters.py`
- `university_admissions_crawler/crawler/sitemap.py`
- `university_admissions_crawler/crawler/discovery.py`
- `tests/test_filters.py`
- `tests/test_discovery.py`

Actions:
1. Define crawl config defaults: broad mode `max_depth=3`, `max_pages=100`, smoke mode `max_pages=20`, explicit timeout, max PDF pages, allowed domains, positive/negative keywords.
2. Implement URL normalization/canonicalization: remove fragments, normalize trailing slashes, lowercase host, sort/drop tracking query params, classify PDF URLs.
3. Implement domain policy: allow same registrable domain and controlled official subdomains linked from allowed pages; reject untrusted external domains unless explicitly whitelisted.
4. Implement link scoring using positive keywords from spec lines 164-170 and negative keywords for news/events/alumni/donate/media/staff/jobs/blog/etc.
5. Implement sitemap and homepage link discovery as deterministic functions over fetched content, with depth/page caps enforced.
6. Add bounded recovery behavior: timeouts, bad status codes, parse failures, and PDF extraction failures become source-level warnings/retriable events and do not abort the entire crawl unless they affect the seed URL and no usable sources remain. Default to at most 1 retry per failed URL in MVP mode, then continue with warnings.

Acceptance checks:
- Tests prove max depth/pages stop traversal.
- Tests prove negative pages are deprioritized/rejected.
- Tests prove official subdomain expansion requires discovery from an official allowed page or explicit config.
- Tests prove URL canonicalization deduplicates obvious duplicates.
- Tests prove timeouts/bad status/parse/PDF failures are recorded as warnings and traversal continues within caps.

### Phase 3 — Fetch/content abstraction and raw evidence store

Files:
- `university_admissions_crawler/crawler/fetcher.py`
- `university_admissions_crawler/evidence/store.py`
- `tests/fixtures/...`
- `tests/test_cli_smoke.py` partial

Actions:
1. Define a `FetchResult` / `Fetcher` protocol: URL in; normalized source record out with original URL, final URL, status, title, content type, retrieved_at, engine name, raw text/html/markdown where available, content hash, discovered link set, and warnings/errors.
2. Implement fixture/file fetcher for tests and ordinary deterministic fixture paths.
3. Implement capability-based engine selection: fixture/static fetcher for deterministic tests and ordinary static content; crawl4ai adapter for explicitly enabled live/dynamic crawling or JavaScript-heavy pages; ScrapeGraphAI only as an optional adapter/spike if selected later. All engines must satisfy the same fetch contract.
4. Persist raw/markdown/source metadata under an output directory, with content hash and retrieval metadata.
5. Keep crawl4ai-specific code isolated so tests can run without browser installation if necessary.
6. Persist prior run metadata/source hashes when an output directory already contains a previous result, and produce a field/source-level diff or an explicit MVP warning if no prior result exists.

Acceptance checks:
- Fixture fetcher drives discovery/classification tests without network.
- Evidence store writes deterministic source records and content hashes.
- Live fetch mode is optional and skipped when dependencies/network are unavailable.
- Adapter-contract tests prove fixture/static fetcher and crawl4ai adapter stub/implementation satisfy the same fetch protocol.
- Incremental/diff tests prove changed source hashes or field values are recorded when a previous result is present.

### Phase 4 — Page classification

Files:
- `university_admissions_crawler/classifier/page_classifier.py`
- `tests/test_classifier.py`

Actions:
1. Implement rule-based category scoring from URL path, title, headings, anchor text, and snippets.
2. Support categories from spec lines 45-57.
3. Return category, score, matched signals, and `irrelevant` fallback.
4. Avoid primary reliance on LLM classification; optional LLM provider can enrich but not be required for tests.

Acceptance checks:
- Fixture pages classify into undergraduate admissions, international requirements, application deadlines, accepted qualifications, programme list, programme prerequisites, fees, scholarships, visa, housing, contact, and irrelevant.
- News/events/alumni/staff pages classify as irrelevant even if they mention admissions in incidental text unless strong official admissions signals exist.

### Phase 5 — HTML/Markdown extraction and normalization

Files:
- `university_admissions_crawler/extractor/html_extractor.py`
- `university_admissions_crawler/extractor/llm_provider.py`
- `university_admissions_crawler/extractor/normalizer.py`
- `tests/test_normalizer.py`

Actions:
1. Implement deterministic extraction heuristics for page title, headings, tables/lists, deadlines, links, contacts, programme names, and requirement-like sections.
2. Attach snippets to claim paths for every extracted field.
3. Implement `unknown`/`needs_manual_check` when evidence is weak, ambiguous, or conflicting.
4. Add optional LLM provider interface that accepts bounded source text + schema and returns candidate claims with evidence references; mock provider only for tests.
5. Use bounded chunking/section selection for long pages: prioritize headings/tables/sections with admissions/programme/requirements signals, preserve source offsets/snippets, and avoid sending unbounded page text to any provider.
6. Post-validate all LLM candidates against evidence snippets already captured from the source before accepting them. Unsupported or weakly supported LLM claims become `needs_manual_check` or are rejected with warnings.

Acceptance checks:
- Extracted sample fields include evidence item references.
- Unsupported LLM/mock claims without source snippets are rejected or downgraded to warning/manual-check.
- Conflicting fixture pages preserve both sources and add conflict warnings.

### Phase 6 — PDF extraction path

Files:
- `university_admissions_crawler/extractor/pdf_extractor.py`
- `tests/test_normalizer.py` or `tests/test_pdf_extractor.py`

Actions:
1. Define PDF extractor protocol returning page-indexed text snippets and source metadata.
2. Implement the first version as an optional dependency-gated local parser if a lightweight PDF library is chosen during execution; otherwise provide a protocol-backed mock/fixture extractor and clear runtime warning for unsupported PDFs.
3. Missing PDF support or PDF parse failure must warn and continue, not crash the scan.
4. Mark PDF evidence with `source_type="pdf"` and page numbers when available.
5. Bound PDF processing by `max_pdf_pages`.

Acceptance checks:
- Fixture or mocked PDF extraction yields page-numbered evidence records.
- If PDF library is absent, CLI/report warns rather than crashes.

### Phase 7 — Pipeline orchestration and CLI

Files:
- `university_admissions_crawler/pipeline/run_university_scan.py`
- `university_admissions_crawler/cli.py`
- `tests/test_cli_smoke.py`

Actions:
1. Implement pipeline: load config -> discover URLs -> fetch/capture content -> classify pages -> extract candidates -> normalize/validate -> write JSON/report.
2. CLI options: input URL, output dir, max pages, max depth, allowed domains, smoke mode, fixture mode, enable-live-network, optional LLM/provider flags.
3. Default to safe bounded config. Require explicit flags for live network if implementation chooses that safety gate.
4. Return nonzero only for operational failures; data incompleteness should be warnings/manual-check in output.

Acceptance checks:
- CLI fixture smoke test creates JSON and Markdown outputs.
- Output contains run metadata, sources, evidence, warnings, and report path.
- CLI respects max_pages/max_depth in fixture traversal.

### Phase 8 — Markdown report rendering

Files:
- `university_admissions_crawler/reports/render_report.py`
- `tests/test_report.py`

Actions:
1. Render a report with sections: summary, sources, discovered categories, admissions requirements, programmes/prerequisites, fees/scholarships/visa/housing/contact, warnings/manual-check, evidence appendix.
2. Clearly separate facts from engineering inference and unknown/manual-check fields.
3. Include source URLs, titles, retrieved_at, snippets, PDF page refs, and confidence.

Acceptance checks:
- Snapshot/string tests verify report includes evidence appendix and warnings.
- Report does not contain admissions verdict language.

### Phase 9 — NUS sample plan / fixture and documentation

Files:
- `README.md`
- `tests/fixtures/mini_university_site/...`
- optional `examples/nus_run_plan.md`

Actions:
1. Document how the system should run for NUS: start at homepage, discover admissions, international qualifications, undergraduate programmes, programme prerequisites, deadlines, fees/scholarships/visa/housing/contact when official and within limits.
2. Provide a deterministic mini-site fixture emulating these page types for tests.
3. If live NUS smoke is added, mark it optional and non-blocking unless the user explicitly permits live network verification.

Acceptance checks:
- README includes install/run commands, fixture smoke command, output file descriptions, and limitations.
- Fixture smoke demonstrates the required page categories and evidence behavior.

## Testable Acceptance Criteria

1. `pytest` passes for schema/evidence, URL filtering/dedup, discovery caps, classification, extraction normalization, PDF interface behavior, report rendering, and CLI fixture smoke.
2. CLI fixture smoke writes both `result.json` and `report.md` to an output directory.
3. Every non-unknown extracted fixture claim in `result.json` has at least one evidence item containing `source_url`, `source_type`, `retrieved_at`, and `snippet` or PDF `page_number` where applicable.
4. Fixture pages with missing/uncertain fields produce `unknown` or `needs_manual_check`, not fabricated values.
5. Negative pages such as news/events/alumni/donate/staff/jobs/blog fixtures are rejected or classified as `irrelevant`.
6. Discovery tests prove `max_pages`, `max_depth`, and domain policy are enforced.
7. Conflict/stale fixtures produce warning records and retain source URLs for both sides.
8. Report output contains source/evidence appendix and warnings/manual-check section.
9. Report and JSON contain no automated admissions verdict and no UI/backend feature is introduced.
10. Optional live crawl/LLM/ScrapeGraphAI paths are skipped/guarded in tests unless credentials/network flags are explicitly supplied.
11. A full offline fixture run spans discovery -> fetch -> classify -> extract -> normalize -> report and includes at least one HTML source, one PDF-like source, one conflict case, and one manual-check case.
12. Adapter-contract tests prove all fetch engines produce the same required source/evidence fields.
13. Incremental/diff behavior records changed source hashes or field values when a previous result exists; first-run absence of prior data is reported explicitly, not treated as failure.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| University sites vary widely | Missing or misclassified pages | Modular scoring, warnings/manual-check, fixture suite, optional live smoke |
| LLM hallucination | Unsafe admissions claims | Evidence-first post-validation; optional provider; unsupported claims downgraded/rejected |
| PDF tables are hard to parse | Missing prerequisites/fees | Page-indexed PDF interface, bounded processing, manual-check warnings |
| Crawl4AI/browser dependency friction | Setup failures | Isolate adapter; fixture/static fetcher; document optional install path |
| Optional dependency drift / browser setup failures | CI or local installs fail unpredictably | Optional extras/groups, pinned versions or lockfile policy, and fixture-first tests that do not require optional engines |
| Hosted ScrapeGraphAI credentials/cost | Blocked tests or unexpected spend | Optional adapter only; explicit confirmation for credentials |
| Conflicting official pages | Wrong requirement chosen | Preserve both sources, confidence downgrades, conflict warnings |
| Stale academic year pages | Outdated guidance | Extract/flag academic_year/retrieved_at; stale warnings |

## Verification Steps

1. Run unit tests: `pytest`.
2. Run full offline fixture CLI smoke: e.g. `python -m university_admissions_crawler.cli tests/fixtures/mini_university_site/index.html --fixture --output-dir /tmp/uac-smoke`, covering HTML + PDF-like source + conflict + manual-check cases.
3. Inspect generated JSON for evidence coverage, nested claim evidence links, source hashes, diff metadata (when prior output exists), and warnings.
4. Inspect generated Markdown for fact/inference/manual-check separation.
5. Optionally run a bounded live smoke only with explicit network intent and low caps, e.g. `--max-pages 20 --max-depth 2`.

## Available-Agent-Types Roster

- `planner` — task sequencing and risk flags.
- `architect` — architecture, module boundaries, adapter tradeoffs.
- `dependency-expert` — crawl4ai/ScrapeGraphAI/PDF/parser dependency evaluation.
- `executor` — implementation of package modules.
- `test-engineer` — fixture design, unit/integration/smoke tests.
- `verifier` — final evidence and acceptance validation.
- `critic` / `code-reviewer` — adversarial plan/code review.
- `writer` — README/report/user guidance.
- `explore` — repo-local lookup after implementation starts.

## Follow-up Staffing Guidance

### Recommended Ultragoal path

Use `$ultragoal` as the durable goal ledger after this plan. Suggested goal breakdown:

1. Schema/evidence foundation — `executor` + `test-engineer`; reasoning medium/high.
2. Discovery/filtering/fetcher abstraction — `executor` + `dependency-expert` if adding crawl4ai; reasoning medium/high.
3. Classification/extraction/normalization — `executor` + `test-engineer`; reasoning medium.
4. CLI/report/docs — `executor` + `writer`; reasoning medium/high.
5. Final verification — `verifier` + `critic`; reasoning high.

### Recommended Team path

Use Team + Ultragoal if parallel delivery is desired. Team lanes:

- Lane A (`executor`): schema/evidence/warning models.
- Lane B (`executor`): crawler filters/discovery/fetcher interface.
- Lane C (`executor`): classifier/extractors/normalizer.
- Lane D (`test-engineer`): fixtures and acceptance tests.
- Lane E (`writer` or `executor`): CLI/report/README.
- Verification lane (`verifier`/`critic`): acceptance matrix and risk review.

Team members must not overlap write scopes without coordination.

### Team launch hints

```text
$team .omx/plans/prd-university-admissions-crawler.md .omx/plans/test-spec-university-admissions-crawler.md
```

or, if invoking via CLI runtime:

```bash
omx team start --task "Implement broad MVP university admissions crawler from .omx/plans/prd-university-admissions-crawler.md and .omx/plans/test-spec-university-admissions-crawler.md"
```

Team verification path:

1. Each lane reports changed files and tests run.
2. Team verifier runs full tests and fixture smoke.
3. Team returns checkpoint-ready evidence: test output, generated fixture JSON/report paths, unresolved warnings/risks.
4. Ultragoal records durable completion checkpoints from that evidence.

### Ralph fallback

Use `$ralph` only if the user explicitly wants a legacy-style persistent single-owner loop for sequential implementation/verification. It is not the default follow-up.

## Goal-Mode Follow-up Suggestions

- `$ultragoal` — recommended default after plan approval for durable implementation tracking.
- `$team` + `$ultragoal` — recommended if the user wants faster coordinated parallel implementation.
- `$autoresearch-goal` — not the primary fit; this is implementation work, not a research deliverable, although dependency facts may be gathered via bounded best-practice research during execution.
- `$performance-goal` — not applicable unless later optimizing crawl throughput/latency/memory with measurable benchmarks.

## Plan Changelog

- Initial consensus draft created from deep-interview spec.
- Applied Architect review improvements: explicit capability-based fetch engine policy, single validation-system decision point, optional extras/credential policy, nested evidence invariants, failure recovery, adapter contract, LLM chunk/evidence rules, PDF warning behavior, offline end-to-end fixture, adapter-contract tests, and incremental diff acceptance.
