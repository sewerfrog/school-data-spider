# Deep Interview Context Snapshot — university-admissions-crawler

## Task statement
User invoked `$deep-interview` with `/Users/jax/something/university-admissions-crawler-codex-prompt.md` and asked to read the document, then discuss implementation.

## Desired outcome
Clarify whether and how to implement a system that takes a university official website URL and automatically discovers/extracts undergraduate admissions information with evidence-backed outputs.

## Stated solution
The source document is itself a Codex prompt asking for analysis/design first, and optionally an MVP code phase later. It suggests prioritizing `crawl4ai` for URL discovery and Markdown extraction; LLM extraction can start as a replaceable interface/mock.

## Probable intent hypothesis
The user likely wants to turn the prompt into concrete implementation requirements for this empty `school-data-spider` repository, avoiding misaligned crawler code before scope, data schema, tool choice, and verification boundaries are clarified.

## Known facts/evidence
- Current working repository: `/Users/jax/project/school-data-spider`.
- Repository currently has no non-`.omx` project files at max depth 3.
- External prompt document size: 6,298 bytes, prompt-safe; oversized summary gate is not needed.
- Prompt language: Chinese.
- Prompt asks for Chinese output, practical/executable plan, and clear distinction among facts, engineering inference, and unknown risks.
- Prompt target information includes institution, admissions entry, international requirements, deadlines, qualifications, English/standardized tests, documents, programmes, prerequisites, interviews/tests/portfolio, fees, scholarships, housing, visa/student pass, contacts, and evidence fields.
- Prompt constraints include: no unbounded crawl, official sources preferred, max_depth/max_pages/domain whitelist/keyword filtering/dedup/recovery, PDFs marked with `source_type=pdf` and page references where possible, unknown/needs_manual_check instead of fabrication, academic_year/retrieved_at for volatile info, and no race/skin color/parents' race as eligibility variables unless official source explicitly requires it.
- Prompt asks to compare ScrapeGraphAI vs crawl4ai and avoid overclaiming tool capability.
- Prompt asks not to write production code immediately; optional appended section says MVP code may be implemented after analysis if clear.

## Constraints
- Deep-interview mode: requirements only; no direct implementation inside this mode.
- Must use `omx question` for every user-facing interview round.
- No new dependencies without explicit request in repo working agreements.
- Must verify before completion and produce artifacts under `.omx/interviews/` and `.omx/specs/` when ready.

## Unknowns/open questions
- Does the user want this session to produce only a clarified implementation spec/plan, or continue later into MVP implementation via handoff?
- MVP scope: discovery-only, extraction-only, report-generation, or full end-to-end prototype?
- Which target universities/regions should drive first-pass assumptions (NUS only vs globally)?
- LLM provider availability/allowed usage, credentials, and whether network/live crawling is allowed during tests.
- Which fields are mandatory in v1 vs deferred.
- Evidence granularity and confidence thresholds required before output can be considered acceptable.
- Persistence/storage preference (files, SQLite, JSONL, etc.).

## Decision-boundary unknowns
- What OMX may decide autonomously during planning/implementation: file layout, dependency choices, crawl limits, provider abstraction, sample universities, schema details, test strategy.
- Which choices require user confirmation: adding dependencies, live network crawl scope, API/LLM provider choice/cost, large architectural changes, and acceptance of residual risk.

## Likely codebase touchpoints
- New Python project scaffold is likely needed because repository is empty.
- Candidate paths from prompt: `crawler/discovery.py`, `crawler/classifier.py`, `extractor/schema.py`, `extractor/html_extractor.py`, `extractor/pdf_extractor.py`, `pipeline/run_university_scan.py`, `reports/render_report.py`, `tests/`.

## Prompt-safe initial-context summary status
not_needed — source prompt is 6,298 bytes and has been summarized above without needing user-provided compression.
