# Execution Spec — Broad MVP University Admissions Crawler

## Metadata

- Source mode: `$deep-interview`
- Profile: standard
- Context type: brownfield initialization; repository is effectively empty
- Source prompt: `/Users/jax/something/university-admissions-crawler-codex-prompt.md`
- Context snapshot: .omx/context/university-admissions-crawler-20260601T063209Z.md
- Transcript: .omx/interviews/university-admissions-crawler-20260601T064351Z.md
- Final ambiguity: ~18% (threshold: 20%)
- Date crystallized: 2026-06-01
- Direct implementation in this mode: none

## Intent

Build a first-version automated crawler/extractor for university undergraduate admissions information. The system should start from one official university homepage URL, discover likely undergraduate admissions/programme/requirements pages, extract structured information, and preserve evidence for every claim.

The purpose is not to replace admissions judgment. It is to produce a structured, source-traceable evidence package that a student or reviewer can inspect.

## Desired outcome

A broad MVP that can be handed to planning/implementation. The eventual implementation should provide:

1. CLI entry point that accepts one university official URL.
2. Bounded URL discovery from homepage/sitemap/links.
3. Page classification for admissions-related categories.
4. HTML/Markdown extraction and PDF extraction path where feasible.
5. Structured normalized JSON output.
6. Markdown report with evidence, warnings, and manual-check markers.
7. Tests/fixtures/smoke checks proving the evidence-first behavior.

## In scope for MVP

- Input: one university official homepage URL, e.g. `https://www.nus.edu.sg`.
- Output: structured JSON plus Markdown report.
- Discovery:
  - homepage links;
  - sitemap discovery when available;
  - same-domain and controlled subdomain traversal;
  - admissions/programme/requirements keyword prioritization;
  - explicit max depth/pages/time limits;
  - duplicate URL canonicalization;
  - irrelevant-page filtering.
- Page categories:
  - `undergraduate_admissions`
  - `international_requirements`
  - `application_deadlines`
  - `accepted_qualifications`
  - `programme_list`
  - `programme_prerequisites`
  - `fees`
  - `scholarships`
  - `visa`
  - `housing`
  - `contact`
  - `irrelevant`
- Extraction fields from the source prompt, including institution, source metadata, academic year, applicant group, qualifications, application periods, requirements, documents, English requirements, standardized tests, programmes, prerequisites, interviews/tests/portfolio, fees, scholarships, visa, evidence, confidence, and warnings.
- Evidence-first normalization: every non-unknown field should carry source URL and evidence snippet/page metadata where available.
- Support for unknown / needs_manual_check when evidence is insufficient or conflicting.
- Optional LLM-backed extraction behind an interface; must not be the only way tests can pass.
- Optional ScrapeGraphAI adapter or spike if useful; primary path may prefer crawl4ai/local extraction for controllability.

## Out of scope / non-goals

- No Web UI or admin/backend system in v1.
- No automated final admissions decision or “you can/cannot get admitted” verdict.
- No unbounded full-site crawl.
- No unsupported factual inference to increase coverage.
- No treating non-official blogs/news/forums as primary evidence.
- No race/skin-color/parents-race eligibility logic unless an official source explicitly requires it; even then it must be evidence-marked and warning-tagged.

## Decision boundaries

Implementation/planning agents may decide without further confirmation:

- Python project structure and module boundaries.
- Default crawl limits such as `max_pages`, `max_depth`, timeout, link scoring, and dedupe rules.
- Dependency/tool combination, including whether to add crawl4ai, PDF parsers, HTML parsers, Pydantic, or ScrapeGraphAI adapters, as long as choices are justified and reviewable.
- LLM strategy: mock/rule-based extractor, provider interface, optional real provider, chunking, unknown/manual-check policy.
- JSON schema details, confidence/warning structures, and report layout, as long as the source prompt’s required concepts are preserved.
- Test university/fixture choices and validation scripts.
- Whether to deliver in staged milestones or one integrated pass.

Still requires explicit user confirmation if encountered later:

- Running or storing real paid API credentials.
- Large-scale live crawling beyond MVP limits.
- Adding a persistent production database/service/UI.
- Changing the product from evidence report to admissions recommendation.

## Constraints

- Evidence correctness has priority over field coverage.
- Every extracted claim must be traceable to official source evidence when possible.
- Use `unknown` / `needs_manual_check` rather than filling uncertain values.
- Record `retrieved_at`; record `academic_year` when page content states or implies it.
- PDF-derived information should have `source_type: "pdf"` and page reference where technically available.
- Bounded crawl: define max depth, max pages, whitelist, keyword scoring, dedupe, and failure recovery.
- Prefer official admissions/undergraduate/programme/registrar pages over news/blog/forum/search-result pages.
- Flag stale, conflicting, or date-sensitive information with warnings.
- Keep implementation reviewable and modular.

## Tool facts and engineering implications

### Crawl4AI

Official Crawl4AI docs describe:

- `AsyncWebCrawler` for asynchronous crawling.
- `BrowserConfig` and `CrawlerRunConfig` for browser/run behavior.
- Markdown generation via `DefaultMarkdownGenerator` with optional content filters.
- CSS/XPath extraction and LLM extraction strategies.
- Dynamic JavaScript page crawling support.
- LLM provider configuration via provider strings and token/base-url settings.

Engineering implication: crawl4ai is a strong candidate for the primary local crawl + Markdown extraction layer because the MVP needs controllable crawling, page content capture, and source-preserving processing.

### ScrapeGraphAI

Official ScrapeGraphAI docs describe:

- AI-powered web data extraction services and SDKs.
- v2 API services: scrape, extract, search, crawl, monitor, schema, and history.
- API-key authentication for hosted API usage.
- Open-source core package `scrapegraph-ai` and SDK/integration ecosystem.
- v1 endpoint names are deprecated in favor of v2 API endpoints.

Engineering implication: ScrapeGraphAI can be treated as an optional extraction/crawl adapter or benchmark path, especially for LLM-driven structured extraction. It should not be a hard dependency for offline tests unless the implementation deliberately chooses its open-source core and verifies local usability.

## Recommended architecture

```text
university_admissions_crawler/
  crawler/
    discovery.py          # homepage/sitemap/link traversal and scoring
    fetcher.py            # crawl4ai or fallback fetch abstraction
    filters.py            # domain, keyword, irrelevant-page filters
  classifier/
    page_classifier.py    # rule-based and optional LLM classification
  extractor/
    schema.py             # Pydantic/dataclass JSON schema
    html_extractor.py     # HTML/Markdown field extraction
    pdf_extractor.py      # PDF text/page extraction interface
    llm_provider.py       # optional provider interface/mock
    normalizer.py         # merge fields, evidence, confidence, warnings
  evidence/
    store.py              # raw/markdown/evidence persistence
    provenance.py         # source_url/title/retrieved_at/snippet/page metadata
  pipeline/
    run_university_scan.py
  reports/
    render_report.py
  tests/
    fixtures/
```

Actual names may differ; preserve these responsibilities.

## Suggested default MVP parameters

Implementation may tune these, but initial defaults should be bounded:

- `max_depth`: 3–4 from homepage.
- `max_pages`: 80–150 for broad MVP, with a lower smoke-test mode such as 20.
- `max_pdf_pages`: bounded, e.g. first 30–50 pages unless target PDF is clearly admissions-specific.
- `request_timeout_seconds`: explicit and configurable.
- `allowed_domains`: same registrable domain plus manually admitted admissions/programme subdomains discovered via official links.
- `keyword_priority`: admissions, undergraduate, apply, international, requirements, qualifications, deadlines, programme/program, prerequisites, tuition, fees, scholarships, visa, student pass, housing, contact.
- `negative_keywords`: news, events, alumni, donate/giving, media, press, staff directory, jobs/careers, procurement, blog, sports, magazine.

## Data schema requirements

A normalized record should include at least:

```json
{
  "institution": {
    "name": "string|null",
    "homepage_url": "string",
    "country_or_region": "string|null"
  },
  "run": {
    "input_url": "string",
    "retrieved_at": "ISO-8601",
    "crawler_version": "string|null",
    "config": {}
  },
  "sources": [
    {
      "source_url": "string",
      "source_type": "html|pdf|other",
      "title": "string|null",
      "retrieved_at": "ISO-8601",
      "academic_year": "string|null",
      "page_number": "integer|null",
      "content_hash": "string|null"
    }
  ],
  "admissions": {
    "undergraduate_application_entry": {},
    "international_requirements": [],
    "accepted_qualifications": [],
    "application_periods": [],
    "required_documents": [],
    "english_requirements": [],
    "standardized_tests": [],
    "selection_tests_or_interviews": []
  },
  "programmes": [
    {
      "name": "string",
      "degree": "string|null",
      "faculty_or_school": "string|null",
      "source_url": "string",
      "prerequisites": [],
      "evidence": []
    }
  ],
  "fees": [],
  "scholarships": [],
  "visa": [],
  "housing": [],
  "contacts": [],
  "evidence": [
    {
      "claim_path": "json.pointer.or.field.path",
      "source_url": "string",
      "source_type": "html|pdf|other",
      "title": "string|null",
      "retrieved_at": "ISO-8601",
      "academic_year": "string|null",
      "page_number": "integer|null",
      "snippet": "string",
      "confidence": "high|medium|low",
      "warnings": []
    }
  ],
  "confidence": "high|medium|low",
  "warnings": [
    {
      "code": "stale_page|conflict|missing_evidence|needs_manual_check|non_official_source|ambiguous_applicant_group",
      "message": "string",
      "field": "string|null",
      "source_urls": []
    }
  ]
}
```

## Quality control rules

- Deduplicate by normalized URL, canonical link, content hash, and near-duplicate title/path heuristics.
- Prefer pages with admissions/programme/registrar authority over news/blog pages.
- Treat dated pages as stale if they refer to old academic years or closed cycles; do not silently use them for current requirements.
- Conflicts should create warning records and retain both sources; do not pick a winner unless there is a clear official hierarchy or newer academic year.
- Confidence should consider source authority, evidence specificity, recency/academic year, extraction method, and conflict status.
- Manual review queue should list low-confidence fields, missing key fields, stale dates, and unsupported LLM-only claims.
- Incremental update should persist previous JSON and produce a diff by source hash and field path.

## Acceptance criteria

The MVP is acceptable when:

1. A CLI command can run against a configured university URL and produce JSON + Markdown report files.
2. The crawler respects configured max pages/depth/time/domain constraints.
3. The system can classify discovered pages into the defined categories or `irrelevant`.
4. Extracted non-unknown fields include evidence metadata: `source_url`, `source_type`, `retrieved_at`, and snippet/page reference where available.
5. Missing or uncertain fields are represented as `unknown` or `needs_manual_check`, not invented.
6. The report separates facts, engineering inference, and warnings/manual-check items.
7. Tests cover URL filtering/dedup, classification, schema validation, evidence attachment, stale/conflict warnings, and report rendering.
8. A NUS-oriented sample run plan or fixture demonstrates finding admissions, international qualifications, programmes, and prerequisites pages.
9. No Web UI/backend and no admissions verdict is implemented.

## NUS sample run plan

Input: `https://www.nus.edu.sg`

Expected automated strategy:

1. Fetch homepage and sitemaps/robots when available.
2. Score links/subdomains for terms such as undergraduate, admissions, apply, international qualifications, requirements, programmes, prerequisites.
3. Prioritize official NUS domains and official admissions/programme subdomains discovered from NUS-owned pages.
4. Candidate pages to discover/classify:
   - undergraduate admissions entry;
   - international qualifications / admission requirements;
   - undergraduate programmes list;
   - programme/subject prerequisites;
   - application deadlines and application period;
   - fees/scholarships/visa/housing/contact pages when official and discoverable within limits.
5. Extract fields only when evidence snippets support them.
6. Output warnings for missing/ambiguous fields, stale academic year, PDF page-number uncertainty, or conflicting pages.

## Residual risks

- University sites vary widely in structure; broad MVP may still need manual review for many fields.
- Some admissions information may require JavaScript, PDF tables, login/session flows, or country-specific branching.
- LLM extraction can hallucinate unless constrained by schema, evidence snippets, and post-validation.
- Official pages may conflict across central admissions, faculty, and programme pages.
- ScrapeGraphAI hosted API usage requires credentials and may introduce cost/availability considerations.
- crawl4ai version behavior and browser dependencies should be pinned/verified during implementation.

## Recommended handoff

Recommended next step: `$ralplan` with this spec, then implementation via `$ultragoal` or `$autopilot` after PRD/test-spec approval.

Suggested invocation:

```text
$plan --consensus --direct .omx/specs/deep-interview-university-admissions-crawler.md
```

Alternative handoffs:

- `$autopilot .omx/specs/deep-interview-university-admissions-crawler.md` if you want planning + implementation + QA in one autonomous flow.
- `$team .omx/specs/deep-interview-university-admissions-crawler.md` if parallel lanes are useful (crawler, schema/extraction, reports/tests).
- `$ultragoal .omx/specs/deep-interview-university-admissions-crawler.md` for durable goal-mode implementation tracking after planning.
- `$ralph .omx/specs/deep-interview-university-admissions-crawler.md` only as an explicit fallback for a single-owner persistence loop.
