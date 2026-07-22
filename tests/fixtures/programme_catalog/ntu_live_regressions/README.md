# NTU live programme catalog regressions

These fixtures are minimal reproductions derived from the official NTU page structures
diagnosed through `outputs/ntu-live-20260717` and revalidated against the live site on
2026-07-21. The canonical positive control is based on NTU's official degree-programmes
page, which the failed run did not capture. The fixtures preserve the structures needed
for regression coverage without copying complete live pages or treating generated
output as an authority.

- `hass_title_pipe.html` preserves a pipe-delimited page heading and section-based
  degree listing.
- `ccds_visible_css.html` preserves visible Sitefinity CSS followed by programme
  cards.
- `ccds_json_ld_course_cards.html` preserves the official `ItemList` / `Course`
  JSON-LD boundary used when Sitefinity card markup produces no typed blocks.
- `curriculum_care_serve_learn.html` preserves a curriculum table that contains a
  compulsory course row.
- `detail_related_programmes.html` preserves a detail-page heading and a separate
  related-programmes section.
- `old_cohort_minor.html` preserves an old-cohort minor curriculum table.
- `canonical_degree_table.html` is the positive control for an authoritative
  programme/degree table.

`cases.json` is the acceptance oracle. Negative regressions are initially strict
xfails. They must become ordinary passing tests when the block-aware extraction steps
are implemented.
