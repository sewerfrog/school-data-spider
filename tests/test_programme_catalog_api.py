import json

from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.extractor.programme_catalog_api import extract_programme_catalog_api, programme_catalog_api_diagnostics
from university_admissions_crawler.extractor.schema import AdmissionsData, Institution, RunMetadata, SourceType
from university_admissions_crawler.pipeline.diagnostics import attach_run_diagnostics
from university_admissions_crawler.reports.programme_catalog_csv import render_programme_catalog_csv


def test_extract_programme_catalog_api_maps_public_json_rows_to_catalog_csv():
    text = json.dumps(
        {
            "total": 2,
            "items": [
                {
                    "programmeName": "Bachelor of Science",
                    "degree": "BSc",
                    "school": "School of Science",
                    "studyMode": "Full-time",
                    "duration": "4 years",
                    "code": "BSCI",
                },
                {
                    "title": "Bachelor of Engineering (Mechanical Engineering)",
                    "award": "Bachelor of Engineering",
                    "faculty": "Faculty of Engineering",
                    "specialisations": ["Robotics"],
                },
            ],
        }
    )
    source = source_from_text(
        source_url="https://example.edu/api/programmes",
        source_type=SourceType.JSON,
        title="Programmes API",
        text=text,
    )
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu/"),
        run=RunMetadata(input_url="https://example.edu/"),
        sources=[source],
    )

    candidate_diagnostics: list[dict[str, object]] = []
    rows = extract_programme_catalog_api(text, source, candidate_diagnostics=candidate_diagnostics)
    for row, evidence in rows:
        data.programme_catalog.append(row)
        data.evidence.extend(evidence)
    data.run.config["programme_catalog_api_diagnostics"] = [
        {
            "url": source.source_url,
            "source_type": str(source.source_type),
            "status": "captured_json",
            **programme_catalog_api_diagnostics(text, accepted_row_count=len(rows)),
        }
    ]
    data.run.config["programme_catalog_candidate_diagnostics"] = candidate_diagnostics

    attach_run_diagnostics(data)

    assert [row.name for row in data.programme_catalog] == [
        "Bachelor of Science",
        "Bachelor of Engineering (Mechanical Engineering)",
    ]
    assert all(row.source_url == "https://example.edu/api/programmes" for row in data.programme_catalog)
    assert all(item.source_url == "https://example.edu/api/programmes" for item in data.evidence)
    assert data.programme_catalog[0].category == "degree_programme"
    assert data.programme_catalog[0].parse_status == "parsed"
    assert data.run.config["programme_catalog_summary"]["api_response_count"] == 1
    assert data.run.config["programme_catalog_summary"]["api_accepted_row_count"] == 2
    assert data.run.config["programme_catalog_summary"]["api_total_count"] == 2
    assert data.run.config["programme_catalog_summary"]["api_pagination_complete"] is True
    assert data.run.config["programme_catalog_summary"]["api_to_csv_ratio"] == 1.0
    assert data.run.config["programme_catalog_summary"]["accepted_source_role_counts"] == {"canonical_catalog": 2}
    assert data.run.config["programme_catalog_summary"]["accepted_structural_anchor_counts"] == {
        "api_programme_name_field": 2
    }
    assert data.run.config["programme_catalog_summary"]["accepted_without_structural_anchor_count"] == 0

    csv_text = render_programme_catalog_csv(data)
    assert "programme_id,name,faculty_or_school" in csv_text
    assert "Bachelor of Science" in csv_text
    assert "Bachelor of Engineering (Mechanical Engineering)" in csv_text


def test_programme_catalog_api_diagnostics_marks_total_count_gap():
    text = json.dumps(
        {
            "total": 3,
            "items": [
                {"programmeName": "Bachelor of Arts", "degree": "BA"},
                {"name": "Filter", "type": "filterOption"},
            ],
        }
    )
    source = source_from_text(
        source_url="https://example.edu/api/catalog",
        source_type=SourceType.JSON,
        text=text,
    )

    rows = extract_programme_catalog_api(text, source)
    diagnostics = programme_catalog_api_diagnostics(text, accepted_row_count=len(rows))

    assert len(rows) == 1
    assert diagnostics["candidate_object_count"] == 2
    assert diagnostics["accepted_row_count"] == 1
    assert diagnostics["rejected_row_count"] == 1
    assert diagnostics["api_total_count"] == 3
    assert diagnostics["api_pagination_complete"] is False
    assert diagnostics["api_pagination_incomplete"] is True


def test_programme_catalog_api_quarantines_name_only_ambiguous_object():
    text = json.dumps({"items": [{"programmeName": "Computer Science"}]})
    source = source_from_text(
        source_url="https://example.edu/api/programmes",
        source_type=SourceType.JSON,
        text=text,
    )
    candidate_diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog_api(text, source, candidate_diagnostics=candidate_diagnostics)

    assert rows == []
    assert candidate_diagnostics == [
        {
            "source_url": "https://example.edu/api/programmes",
            "source_title": None,
            "candidate_text": '{"programmeName":"Computer Science"}',
            "decision": "rejected",
            "reason": "ambiguous_api_programme_entity",
            "parser_stage": "api_entity_gate",
            "candidate_shape": "json_object",
            "block_kind": "json_object",
            "parser_branch": "json_object",
            "source_role": "canonical_catalog",
            "structural_anchor": "api_programme_name_field",
            "name_quality_passed": False,
            "institution_consistent": True,
            "name": "Computer Science",
        }
    ]
