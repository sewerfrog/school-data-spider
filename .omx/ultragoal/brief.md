# Ultragoal Brief — University Admissions Crawler Broad MVP

Use the approved planning artifacts:

- PRD: `.omx/plans/prd-university-admissions-crawler.md`
- Test spec: `.omx/plans/test-spec-university-admissions-crawler.md`
- Requirements source: `.omx/specs/deep-interview-university-admissions-crawler.md`

Implement the broad MVP in durable sequential slices. Start with the first implementation slice recommended by the PRD:

1. schema/evidence/warning models
2. fixture fetcher
3. offline fixture pipeline
4. JSON/Markdown report smoke

Then continue with discovery/filtering, classifier/extractors/normalizer, PDF/LLM adapter boundaries, CLI/report/docs, and final verification. The implementation must remain evidence-first, bounded, offline-testable by default, and must not add UI/backend or automated admissions verdicts. Optional live crawling, browser/crawl4ai, PDF parser, LLM, and ScrapeGraphAI capabilities must be guarded behind optional dependencies/flags and not required for deterministic tests.
