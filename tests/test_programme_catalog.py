import json
from pathlib import Path

from university_admissions_crawler.crawler.html_text import extract_html_text_document
from university_admissions_crawler.evidence.provenance import evidence_from_source, source_from_text
from university_admissions_crawler.extractor.llm_provider import MockProgrammeCatalogAssistProvider
from university_admissions_crawler.extractor.programme_catalog import extract_programme_catalog
from university_admissions_crawler.extractor.schema import (
    AdmissionsData,
    ClaimStatus,
    Confidence,
    FieldValue,
    Institution,
    ProgrammeCatalogRecord,
    RunMetadata,
    WarningCode,
    attach_validation_warnings,
)
from university_admissions_crawler.pipeline.diagnostics import attach_run_diagnostics
from university_admissions_crawler.reports.programme_catalog_csv import render_programme_catalog_csv


FIXTURE = Path(__file__).parent / "fixtures" / "programme_catalog" / "nus" / "expected_catalog.json"
SOURCE_SAMPLES = Path(__file__).parent / "fixtures" / "programme_catalog" / "nus" / "source_samples.json"
SAVED_SOURCES = Path(__file__).parent / "fixtures" / "saved_sources"
LLM_FIXTURES = Path(__file__).parent / "fixtures" / "llm"
NON_STANDARD_CATALOG_FIXTURES = Path(__file__).parent / "fixtures" / "programme_catalog" / "non_standard"
NTU_LIVE_REGRESSION_FIXTURES = Path(__file__).parent / "fixtures" / "programme_catalog" / "ntu_live_regressions"


def _load_nus_expected_catalog() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _load_nus_source_samples() -> dict:
    return json.loads(SOURCE_SAMPLES.read_text(encoding="utf-8"))


def _extract_saved_programme_catalog(school: str, slug: str):
    base = SAVED_SOURCES / school / slug
    meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    text = base.with_suffix(".txt").read_text(encoding="utf-8")
    source = source_from_text(source_url=meta["source_url"], title=meta["title"], text=text)
    return [row for row, _evidence in extract_programme_catalog(text, source)]


def _extract_typed_html_fixture(name: str, *, source_url: str, title: str):
    document = extract_html_text_document((NTU_LIVE_REGRESSION_FIXTURES / name).read_text(encoding="utf-8"))
    source = source_from_text(source_url=source_url, title=title, text=document.plain_text)
    diagnostics: list[dict[str, object]] = []
    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )
    return rows, diagnostics


def test_nus_programme_catalog_fixture_covers_required_record_types():
    fixture = _load_nus_expected_catalog()
    rows = fixture["rows"]

    assert fixture["fixture_origin"] == "outputs/nus-live-programmes/result.json"
    assert {row["category"] for row in rows} == {"degree_programme", "major", "special_programme"}
    assert [row["name"] for row in rows if row["category"] == "degree_programme"] == [
        "Bachelor of Business Administration with Honours",
        "Bachelor of Computing in Computer Science",
        "Bachelor of Engineering (Mechanical Engineering)",
    ]
    assert any(row["name"] == "BBA Major: Finance" for row in rows)
    assert any(row["name"] == "NUS College" for row in rows)
    assert any(row["name"] == "CHS Primary Major: Chinese Languages and Cultures" for row in rows)
    assert all(row["source_url"].startswith("https://") for row in rows)
    assert all("nus.edu.sg" in row["source_url"] for row in rows)


def test_nus_programme_catalog_fixture_preserves_expected_row_contract():
    rows = {row["id"]: row for row in _load_nus_expected_catalog()["rows"]}

    business = rows["nus-ug-001"]
    assert business["name"] == "Bachelor of Business Administration with Honours"
    assert business["source_url"] == "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/school-of-business/undergraduate-education"
    assert "BBA curriculum lists 9 majors" in business["evidence_snippet"]
    assert business["parse_status"] == "parsed"
    assert "Finance" in business["specialisations_or_majors"]

    computing = rows["nus-ug-013"]
    assert computing["name"] == "Bachelor of Computing in Computer Science"
    assert computing["source_url"].endswith("/school-of-computing/undergraduate-education/")
    assert "School of Computing degrees offered include Bachelor of Computing in Computer Science" in computing["evidence_snippet"]
    assert computing["parse_status"] == "parsed"

    engineering = rows["nus-ug-031"]
    assert engineering["name"] == "Bachelor of Engineering (Mechanical Engineering)"
    assert engineering["source_url"].endswith("/college-of-design-and-engineering/undergraduate-education/")
    assert "160-unit curriculum" in engineering["evidence_snippet"]
    assert engineering["parse_status"] == "parsed"

    major = rows["nus-ug-007"]
    assert major["name"] == "BBA Major: Finance"
    assert major["category"] == "major"
    assert major["source_url"] == business["source_url"]
    assert "Finance" in major["evidence_snippet"]
    assert major["parse_status"] == "parsed"

    special = rows["nus-special-001"]
    assert special["name"] == "NUS College"
    assert special["category"] == "special_programme"
    assert special["source_url"] == "https://nus.edu.sg/oam/undergraduate-programmes"
    assert "special programmes" in special["evidence_snippet"]
    assert special["parse_status"] == "parsed"

    chs = rows["nus-ug-071"]
    assert chs["name"] == "CHS Primary Major: Chinese Languages and Cultures"
    assert chs["faculty_or_school"] == "College of Humanities and Sciences"
    assert chs["category"] == "major"
    assert chs["source_url"] == "https://chs.nus.edu.sg/programmes/"
    assert "CHS page lists cross-disciplinary programmes" in chs["evidence_snippet"]
    assert chs["parse_status"] == "parsed"


def test_nus_programme_catalog_fixture_maps_to_schema_with_evidence():
    fixture = _load_nus_expected_catalog()
    data = AdmissionsData(
        institution=Institution(homepage_url=fixture["university"]["homepage_url"]),
        run=RunMetadata(input_url=fixture["university"]["homepage_url"]),
    )

    for row in fixture["rows"]:
        source = source_from_text(
            source_url=row["source_url"],
            title=row["source_title"],
            text=row["evidence_snippet"],
        )
        data.sources.append(source)
        data.evidence.append(
            evidence_from_source(
                claim_path=row["evidence_path"],
                source=source,
                snippet=row["evidence_snippet"],
                confidence=Confidence(row["evidence_confidence"]),
            )
        )
        data.programme_catalog.append(
            ProgrammeCatalogRecord(
                name=row["name"],
                faculty_or_school=row["faculty_or_school"],
                degree_or_award=row["degree_or_award"],
                category=row["category"],
                mode=row["mode"],
                duration_or_units=row["duration_or_units"],
                admissions_choice_name=row["admissions_choice_name"],
                specialisations_or_majors=row["specialisations_or_majors"],
                source_url=row["source_url"],
                evidence_snippet=row["evidence_snippet"],
                evidence_confidence=Confidence(row["evidence_confidence"]),
                evidence_path=row["evidence_path"],
                parse_status=row["parse_status"],
            )
        )

    attach_validation_warnings(data)

    dumped = data.to_dict()
    assert dumped["programme_catalog"][0]["name"] == "Bachelor of Business Administration with Honours"
    assert dumped["programme_catalog"][4]["name"] == "NUS College"
    assert dumped["programme_catalog"][5]["name"] == "CHS Primary Major: Chinese Languages and Cultures"
    assert all(row["parse_status"] == "parsed" for row in dumped["programme_catalog"])
    assert not [warning for warning in data.warnings if warning.code == WarningCode.MISSING_EVIDENCE and "programme_catalog" in (warning.field or "")]


def test_nus_source_samples_extract_end_to_end_catalog_and_csv():
    fixture = _load_nus_source_samples()
    data = AdmissionsData(
        institution=Institution(
            name=FieldValue(value=fixture["university"]["name"], status=ClaimStatus.KNOWN, confidence=Confidence.HIGH),
            homepage_url=fixture["university"]["homepage_url"],
        ),
        run=RunMetadata(input_url=fixture["university"]["homepage_url"], config={"university_id": fixture["university"]["id"]}),
    )

    for sample in fixture["sources"]:
        source = source_from_text(
            source_url=sample["source_url"],
            title=sample["source_title"],
            text=sample["text"],
        )
        data.sources.append(source)
        for record, evidence in extract_programme_catalog(sample["text"], source, start_index=len(data.programme_catalog)):
            data.programme_catalog.append(record)
            data.evidence.extend(evidence)

    attach_validation_warnings(data)
    attach_run_diagnostics(data)
    rows_by_name = {row.name: row for row in data.programme_catalog}

    assert set(rows_by_name) == {
        "Bachelor of Business Administration with Honours",
        "BBA Major: Finance",
        "Bachelor of Computing in Computer Science",
        "Bachelor of Engineering (Mechanical Engineering)",
        "CHS Primary Major: Chinese Languages and Cultures",
        "NUS College",
    }
    assert rows_by_name["Bachelor of Business Administration with Honours"].category == "degree_programme"
    assert rows_by_name["BBA Major: Finance"].category == "major"
    assert rows_by_name["CHS Primary Major: Chinese Languages and Cultures"].faculty_or_school == "College of Humanities and Sciences"
    assert rows_by_name["CHS Primary Major: Chinese Languages and Cultures"].admissions_choice_name == "Humanities & Sciences"
    assert rows_by_name["NUS College"].category == "special_programme"
    assert rows_by_name["NUS College"].parse_status == "parsed"
    assert any(
        warning.message.startswith("category_inferred:")
        for warning in rows_by_name["NUS College"].warnings
    )
    assert not [warning for warning in data.warnings if warning.code == WarningCode.MISSING_EVIDENCE and "programme_catalog" in (warning.field or "")]
    assert data.run.config["programme_catalog_summary"]["candidate_count"] == 6
    assert data.run.config["programme_catalog_summary"]["by_programme_type"] == {
        "degree_programme": 3,
        "major": 2,
        "special_programme": 1,
    }

    csv_text = render_programme_catalog_csv(data)
    assert "programme_id,name,faculty_or_school" in csv_text
    assert "nus,National University of Singapore,programme-catalog-001,Bachelor of Business Administration with Honours" in csv_text
    assert "CHS Primary Major: Chinese Languages and Cultures" in csv_text
    assert "NUS College" in csv_text


def test_hku_saved_undergraduate_courses_extract_catalog_card_rows():
    rows = _extract_saved_programme_catalog("hku", "programme_catalog_undergraduate_courses")
    by_name = {row.name: row for row in rows}

    assert set(by_name) == {
        "Bachelor of Arts in Architectural Studies",
        "Bachelor of Science in Surveying",
        "Bachelor of Business Administration",
    }
    assert by_name["Bachelor of Arts in Architectural Studies"].faculty_or_school == "Faculty of Architecture"
    assert by_name["Bachelor of Arts in Architectural Studies"].duration_or_units == "4-year"
    assert by_name["Bachelor of Arts in Architectural Studies"].category == "degree_programme"
    assert by_name["Bachelor of Arts in Architectural Studies"].admissions_choice_name == "6004"
    assert by_name["Bachelor of Business Administration"].faculty_or_school == "HKU Business School"


def test_ntu_saved_undergraduate_programmes_extract_degree_rows_without_admissions_longform_noise():
    rows = _extract_saved_programme_catalog("ntu", "programme_catalog_hass")
    by_name = {row.name: row for row in rows}

    assert set(by_name) == {
        "Bachelor of Fine Arts (BFA) in Design Art",
        "Bachelor of Arts (Hons)",
        "Bachelor of Social Sciences (Hons)",
    }
    assert by_name["Bachelor of Fine Arts (BFA) in Design Art"].category == "degree_programme"
    assert by_name["Bachelor of Fine Arts (BFA) in Design Art"].faculty_or_school == "School of Art, Design and Media"
    assert by_name["Bachelor of Fine Arts (BFA) in Design Art"].specialisations_or_majors == [
        "Interaction Design",
        "Product Design",
        "Visual Communication",
    ]
    assert by_name["Bachelor of Arts (Hons)"].specialisations_or_majors == [
        "Chinese",
        "English",
        "History",
        "Linguistics and Multilingual Studies",
        "Philosophy",
    ]
    assert by_name["Bachelor of Arts (Hons)"].faculty_or_school == "School of Humanities"
    assert by_name["Bachelor of Social Sciences (Hons)"].specialisations_or_majors == [
        "Economics",
        "Psychology",
        "Public Policy and Global Affairs",
        "Sociology",
    ]
    assert by_name["Bachelor of Social Sciences (Hons)"].faculty_or_school == "School of Social Sciences"

    admissions_rows = _extract_saved_programme_catalog("ntu", "347ce27695edcec6")
    assert admissions_rows == []


def test_ntu_hass_section_context_emits_field_evidence_and_diagnostics():
    base = SAVED_SOURCES / "ntu" / "programme_catalog_hass"
    meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    text = base.with_suffix(".txt").read_text(encoding="utf-8")
    source = source_from_text(source_url=meta["source_url"], title=meta["title"], text=text)
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)
    by_name = {row.name: (row, evidence) for row, evidence in rows}

    arts, arts_evidence = by_name["Bachelor of Arts (Hons)"]
    assert arts.parse_status == "parsed"
    assert [item.claim_path for item in arts_evidence] == [
        "/programme_catalog/1/name",
        "/programme_catalog/1/faculty_or_school",
    ]
    assert arts_evidence[1].snippet == "The School of Humanities offers degrees in Chinese, English, History, Linguistics and Multilingual Studies, and Philosophy."
    assert any("section_context_inherited:" in warning.message for warning in arts.warnings)

    context_rows = [item for item in diagnostics if item.get("reason") == "section_context_captured"]
    assert len(context_rows) == 3
    assert all(item["candidate_shape"] == "section_context_row" for item in context_rows)
    accepted = [item for item in diagnostics if item.get("decision") == "accepted"]
    assert all(item["candidate_shape"] == "section_context_candidate" for item in accepted)
    assert all(item["section_context_fields"] == ["faculty"] for item in accepted)
    assert accepted[1]["field_evidence_paths"] == {
        "faculty_or_school": "/programme_catalog/1/faculty_or_school",
    }


def test_programme_catalog_section_context_stops_at_non_catalog_boundary():
    text = (
        "Undergraduate Programmes\n"
        "School of Humanities\n"
        "Bachelor of Arts (Hons)\n"
        "Admissions Requirements\n"
        "Bachelor of Science applicants must submit supporting documents."
    )
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)
    by_name = {row.name: row for row, _evidence in rows}

    assert by_name["Bachelor of Arts (Hons)"].faculty_or_school == "School of Humanities"
    assert "Bachelor of Science applicants" not in by_name
    rejected = next(item for item in diagnostics if item["candidate_text"].startswith("Bachelor of Science applicants"))
    assert rejected["reason"] == "admissions_explainer"
    assert "section_context_fields" not in rejected


def test_programme_catalog_keeps_explicit_degree_on_section_context_line():
    text = "Undergraduate Programmes\nSchool of Law offers Bachelor of Laws (LLB)."
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert len(rows) == 1
    row, evidence = rows[0]
    assert row.name == "Bachelor of Laws (LLB)"
    assert row.faculty_or_school == "School of Law"
    assert [item.claim_path for item in evidence] == [
        "/programme_catalog/0/name",
        "/programme_catalog/0/faculty_or_school",
    ]
    accepted = next(item for item in diagnostics if item.get("decision") == "accepted")
    assert accepted["name"] == "Bachelor of Laws (LLB)"
    assert accepted["section_context_fields"] == ["faculty"]


def test_block_aware_hass_catalog_uses_heading_sections_without_treating_title_pipe_as_table():
    rows, diagnostics = _extract_typed_html_fixture(
        "hass_title_pipe.html",
        source_url="https://www.ntu.edu.sg/hass/admissions/programmes",
        title="Undergraduate Programmes | College of Humanities, Arts and Social Sciences | NTU Singapore",
    )
    by_name = {row.name: row for row, _evidence in rows}

    assert list(by_name) == [
        "Bachelor of Fine Arts in Art, Design and Media",
        "Bachelor of Arts (Hons)",
        "Bachelor of Social Sciences (Hons)",
    ]
    assert by_name["Bachelor of Arts (Hons)"].faculty_or_school == "School of Humanities"
    assert by_name["Bachelor of Arts (Hons)"].specialisations_or_majors == [
        "Chinese",
        "English",
        "History",
        "Linguistics and Multilingual Studies",
        "Philosophy",
    ]

    title_diagnostic = diagnostics[0]
    assert title_diagnostic["block_kind"] == "heading"
    assert title_diagnostic["parser_branch"] == "heading_candidate"
    assert title_diagnostic["candidate_shape"] == "heading_candidate"
    assert title_diagnostic["reason"] == "no_programme_name"
    assert title_diagnostic["section_path"] == [title_diagnostic["candidate_text"]]
    accepted = [item for item in diagnostics if item["decision"] == "accepted"]
    assert all(item["block_kind"] == "heading" for item in accepted)
    assert all(item["parser_branch"] == "heading_candidate" for item in accepted)
    assert all(item["source_role"] == "faculty_catalog" for item in accepted)
    assert all(item["structural_anchor"] == "faculty_degree_heading" for item in accepted)
    assert len([item for item in diagnostics if item["reason"] == "section_context_captured"]) == 3


def test_block_aware_canonical_table_routes_header_and_rows_by_real_cells():
    rows, diagnostics = _extract_typed_html_fixture(
        "canonical_degree_table_with_eligibility.html",
        source_url="https://www.ntu.edu.sg/education/degree-programmes",
        title="Degree Programmes | NTU Singapore",
    )

    assert [row.name for row, _evidence in rows] == [
        "Accountancy",
        "Computer Science",
        "Environmental Earth Systems Science",
        "Medicine",
    ]
    header = next(item for item in diagnostics if item["reason"] == "table_header_captured")
    assert header["candidate_text"] == "Programme | Degree Title"
    assert header["block_kind"] == "table_row"
    assert header["parser_branch"] == "table_header"
    accepted = [item for item in diagnostics if item["decision"] == "accepted"]
    assert all(item["candidate_shape"] == "header_mapped_table" for item in accepted)
    assert all(item["block_kind"] == "table_row" for item in accepted)
    assert all(item["parser_branch"] == "table_row" for item in accepted)
    assert all(item["source_role"] == "canonical_catalog" for item in accepted)
    assert all(item["structural_anchor"] == "programme_table_cell" for item in accepted)
    eligibility_rows = [
        item
        for item in diagnostics
        if item["reason"] == "minor_or_second_major_eligibility_table"
    ]
    assert {item["parser_branch"] for item in eligibility_rows} == {
        "non_catalog_table_header",
        "non_catalog_table_row",
    }
    assert all(item["decision"] == "rejected" for item in eligibility_rows)
    assert not any(item.get("name", "").startswith("All except:") for item in accepted)


def test_flattened_canonical_table_closes_scope_at_second_major_eligibility_header():
    text = (
        "Degree Programmes . Programme | Degree Title . "
        "Accountancy | Bachelor of Accountancy . "
        "Second Major | School offering the Second Major | "
        "Offered to students in the following College/Programmes . "
        "Education Studies | National Institute of Education | "
        "All except: NIE BA/BSc (Academic Discipline & Education) student teachers"
    )
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/education/degree-programmes",
        title="Degree Programmes | NTU Singapore",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert [row.name for row, _evidence in rows] == ["Accountancy"]
    eligibility_rows = [
        item
        for item in diagnostics
        if item["reason"] == "minor_or_second_major_eligibility_table"
    ]
    assert {item["parser_branch"] for item in eligibility_rows} == {
        "non_catalog_table_header",
        "non_catalog_table_row",
    }
    assert all(item["decision"] == "rejected" for item in eligibility_rows)


def test_block_aware_non_standard_table_keeps_reordered_and_grouped_rows():
    document = extract_html_text_document(
        "<main><h1>Undergraduate Degree Programmes</h1><table>"
        "<tr><th>Faculty</th><th>Award</th><th>Programme</th><th>Study Mode</th></tr>"
        "<tr><td>School of Computing</td><td>Bachelor of Computing (Honours)</td>"
        "<td>Computer Science</td><td>Full-time</td></tr>"
        "<tr><td>Data Science and Artificial Intelligence</td><td>Part-time</td></tr>"
        "</table></main>"
    )
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Degree Programmes",
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )
    by_name = {row.name: row for row, _evidence in rows}

    assert list(by_name) == ["Computer Science", "Data Science and Artificial Intelligence"]
    assert by_name["Computer Science"].degree_or_award == "Bachelor of Computing (Honours)"
    assert by_name["Data Science and Artificial Intelligence"].faculty_or_school == "School of Computing"
    assert by_name["Data Science and Artificial Intelligence"].mode == "part-time"
    assert by_name["Data Science and Artificial Intelligence"].parse_status == "parsed"
    grouped = next(item for item in diagnostics if item.get("name") == "Data Science and Artificial Intelligence")
    assert grouped["candidate_shape"] == "grouped_table_row"
    assert grouped["parser_branch"] == "table_row"


def test_block_aware_entity_gate_rejects_unanchored_paragraph_and_related_section():
    document = extract_html_text_document(
        "<main><h1>Undergraduate Programmes</h1><h2>School of Humanities</h2>"
        "<h3>Bachelor of Arts (Hons)</h3>"
        "<table><tr><th>Requirement</th><th>Units</th></tr><tr><td>Core</td><td>20</td></tr></table>"
        "<p>Bachelor of Science in Data Science</p>"
        "<h2>Related Programmes</h2><ul><li>Bachelor of Arts in History</li></ul></main>"
    )
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=document.plain_text,
    )

    diagnostics: list[dict[str, object]] = []
    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )
    by_name = {row.name: row for row, _evidence in rows}

    assert by_name["Bachelor of Arts (Hons)"].faculty_or_school == "School of Humanities"
    assert "Bachelor of Science in Data Science" not in by_name
    assert "Bachelor of Arts in History" not in by_name
    reasons = {item["reason"] for item in diagnostics if item["decision"] == "rejected"}
    assert "unanchored_degree_mention" in reasons
    assert "related_programme_container" in reasons


def test_block_aware_paragraph_path_rejects_unanchored_bachelor_mention():
    document = extract_html_text_document(
        "<main><h1>Undergraduate Programmes</h1>"
        "<p>Our graduates with a Bachelor of Science build careers across many industries.</p></main>"
    )
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )

    assert rows == []
    paragraph = next(item for item in diagnostics if item.get("block_kind") == "paragraph")
    assert paragraph["decision"] == "rejected"
    assert paragraph["reason"] == "sentence_like_name"
    assert paragraph["parser_branch"] == "paragraph_sentence"
    assert paragraph["parser_stage"] == "entity_gate"


def test_block_aware_detail_page_rejects_heading_that_does_not_match_page_identity():
    document = extract_html_text_document(
        "<main><h1>Bachelor of Arts (Hons) in Chinese</h1>"
        "<h2>Bachelor of Arts (Hons) in English</h2></main>"
    )
    source = source_from_text(
        source_url="https://example.edu/programmes/detail/bachelor-of-arts-in-chinese",
        title="Bachelor of Arts (Hons) in Chinese | Example University",
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )

    assert [row.name for row, _evidence in rows] == ["Bachelor of Arts (Hons) in Chinese"]
    accepted = next(item for item in diagnostics if item["decision"] == "accepted")
    assert accepted["source_role"] == "programme_detail"
    assert accepted["structural_anchor"] == "detail_h1"
    rejected = next(item for item in diagnostics if item.get("name") == "Bachelor of Arts (Hons) in English")
    assert rejected["reason"] == "detail_name_mismatch"


def test_detail_page_uses_source_title_when_body_has_no_programme_heading():
    document = extract_html_text_document(
        "<main><p>Application information and admission requirements.</p></main>"
    )
    source = source_from_text(
        source_url=(
            "https://www.ntu.edu.sg/computing/admissions/undergraduate-programmes/detail/"
            "bachelor-of-computing-hons-in-artificial-intelligence-and-society"
        ),
        title=(
            "Bachelor of Computing (Hons) in Artificial Intelligence (AI) and Society | "
            "College of Computing and Data Science | NTU Singapore"
        ),
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )

    assert len(rows) == 1
    row, evidence = rows[0]
    assert row.name == "Bachelor of Computing (Hons) in Artificial Intelligence (AI) and Society"
    assert row.faculty_or_school == "College of Computing and Data Science"
    accepted = next(item for item in diagnostics if item["decision"] == "accepted")
    assert accepted["parser_branch"] == "detail_source_title"
    assert accepted["structural_anchor"] == "detail_source_identity"
    faculty_path = accepted["field_evidence_paths"]["faculty_or_school"]
    assert next(item for item in evidence if item.claim_path == faculty_path).snippet == source.title


def test_detail_page_accepts_long_official_source_title_identity():
    document = extract_html_text_document(
        "<main><p>Application information and admission requirements.</p></main>"
    )
    source = source_from_text(
        source_url=(
            "https://www.ntu.edu.sg/hass/admissions/programmes/undergraduate-programmes/detail/"
            "bachelor-of-arts-(hons)-in-double-major---chinese-and-linguistics-and-multilingual-studies"
        ),
        title=(
            "Bachelor of Arts (Hons) in Double Major - Chinese and Linguistics and Multilingual Studies | "
            "College of Humanities, Arts and Social Sciences | NTU Singapore"
        ),
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )

    assert len(rows) == 1
    row, _evidence = rows[0]
    assert row.name == (
        "Bachelor of Arts (Hons) in Double Major - Chinese and Linguistics and Multilingual Studies"
    )
    assert row.faculty_or_school == "College of Humanities, Arts and Social Sciences"
    accepted = next(item for item in diagnostics if item["decision"] == "accepted")
    assert accepted["parser_branch"] == "detail_source_title"
    assert accepted["structural_anchor"] == "detail_source_identity"
    assert accepted["name_quality_passed"] is True


def test_detail_page_source_title_identity_does_not_override_prose_markers():
    document = extract_html_text_document("<main><p>Undergraduate programme information.</p></main>")
    source = source_from_text(
        source_url="https://example.edu/programmes/detail/bachelor-of-science-provides-students-with-broad-training",
        title="Bachelor of Science provides students with broad training | Example University",
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )

    assert rows == []
    rejected = next(item for item in diagnostics if item.get("parser_branch") == "detail_source_title")
    assert rejected["reason"] == "sentence_like_name"
    assert rejected["structural_anchor"] == "detail_source_identity"


def test_block_aware_list_link_rejects_cross_institution_target():
    document = extract_html_text_document(
        "<main><h1>Undergraduate Programmes</h1><ul>"
        "<li><a href='/programmes/computer-science'>Bachelor of Science in Computer Science</a></li>"
        "<li><a href='https://other.example.org/programmes/business'>Bachelor of Business Administration</a></li>"
        "</ul></main>"
    )
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )

    assert [row.name for row, _evidence in rows] == ["Bachelor of Science in Computer Science"]
    accepted = next(item for item in diagnostics if item["decision"] == "accepted")
    assert accepted["structural_anchor"] == "programme_primary_link"
    rejected = next(item for item in diagnostics if item.get("name") == "Bachelor of Business Administration")
    assert rejected["reason"] == "institution_context_mismatch"
    assert rejected["institution_consistent"] is False


def test_legacy_text_fallback_keeps_table_compatibility_and_marks_diagnostics():
    text = (
        "Undergraduate Programmes\n"
        "Programme | Degree\n"
        "Computer Science | Bachelor of Computing in Computer Science"
    )
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert [row.name for row, _evidence in rows] == ["Computer Science"]
    assert diagnostics
    assert all(item["parser_branch"] == "legacy_text_fallback" for item in diagnostics)
    assert all(item["block_kind"] == "legacy_text" for item in diagnostics)
    accepted = next(item for item in diagnostics if item["decision"] == "accepted")
    assert accepted["structural_anchor"] == "legacy_table_row"
    assert accepted["source_role"] == "faculty_catalog"


def test_legacy_text_fallback_does_not_treat_a_collapsed_pipe_page_as_one_table_row():
    document = extract_html_text_document((NTU_LIVE_REGRESSION_FIXTURES / "hass_title_pipe.html").read_text(encoding="utf-8"))
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/hass/admissions/programmes",
        title="Undergraduate Programmes | College of Humanities, Arts and Social Sciences | NTU Singapore",
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(document.plain_text, source, candidate_diagnostics=diagnostics)

    assert rows
    assert all(len(row.name) <= 160 for row, _evidence in rows)
    assert not any("Home to over 6,000" in row.name for row, _evidence in rows)
    assert all(item["parser_branch"] == "legacy_text_fallback" for item in diagnostics)


def test_legacy_text_fallback_rejects_unbounded_faceted_programme_cards():
    text = (
        "Undergraduate Programmes\n"
        "Computing | Engineering Bachelor of Engineering (Hons) in Computer Engineering "
        "Offered by the school, this programme combines computing and engineering."
    )
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert rows == []
    rejected = next(item for item in diagnostics if "Bachelor of Engineering" in item["candidate_text"])
    assert rejected["reason"] == "unbounded_programme_card"
    assert rejected["parser_branch"] == "legacy_text_fallback"


def test_json_ld_primary_link_does_not_override_sentence_like_name_markers():
    document = extract_html_text_document(
        '<script type="application/ld+json">'
        '{"@type":"Course","name":"Bachelor of Science provides students with broad training",'
        '"url":"/undergraduate/programmes/science"}'
        "</script><div>Undergraduate Programmes "
        "Bachelor of Science provides students with broad training</div>"
    )
    source = source_from_text(
        source_url="https://example.edu/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )

    assert rows == []
    rejected = next(item for item in diagnostics if item.get("name"))
    assert rejected["reason"] == "sentence_like_name"
    assert rejected["structural_anchor"] == "programme_primary_link"


def test_polyu_saved_jupas_programme_list_extracts_rows_after_empty_baseline():
    rows = _extract_saved_programme_catalog("polyu", "programme_catalog_jupas")
    by_name = {row.name: row for row in rows}

    assert set(by_name) == {
        "Architectural Studies",
        "Applied Mathematics and Finance Analytics",
        "Computing and AI",
    }
    assert by_name["Architectural Studies"].degree_or_award == "Bachelor of Science (Honours)"
    assert by_name["Architectural Studies"].admissions_choice_name == "JS3140"
    assert by_name["Architectural Studies"].mode == "full-time"
    assert by_name["Applied Mathematics and Finance Analytics"].category == "degree_programme"
    assert by_name["Applied Mathematics and Finance Analytics"].specialisations_or_majors == [
        "Applied Mathematics",
        "Investment Science and Finance Analytics",
        "Quantitative Finance and FinTech",
    ]


def test_programme_catalog_summary_counts_types_sources_and_manual_review_rows():
    source = source_from_text(
        source_url="https://example.edu/catalogue/undergraduate",
        title="Undergraduate Catalogue",
        text="Bachelor of Science in Data Science. BSc Major: Statistics.",
    )
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(input_url="https://example.edu"),
        sources=[source],
    )
    data.programme_catalog.append(
        ProgrammeCatalogRecord(
            name="Bachelor of Science in Data Science",
            faculty_or_school="Faculty of Science",
            degree_or_award="Bachelor of Science",
            category="degree_programme",
            source_url=source.source_url,
            evidence_snippet="Bachelor of Science in Data Science.",
            evidence_path="/programme_catalog/0/name",
            parse_status="parsed",
        )
    )
    data.programme_catalog.append(
        ProgrammeCatalogRecord(
            name="Bachelor of Science in Data Science",
            faculty_or_school="Faculty of Science",
            category="degree_programme",
            source_url=source.source_url,
            evidence_snippet="Bachelor of Science in Data Science.",
            evidence_path="/programme_catalog/1/name",
            parse_status="raw_needs_manual_review",
        )
    )
    data.programme_catalog.append(
        ProgrammeCatalogRecord(
            name="BSc Major: Statistics",
            faculty_or_school="Faculty of Science",
            category="major",
            source_url=source.source_url,
            evidence_snippet="BSc Major: Statistics.",
            evidence_path="/programme_catalog/2/name",
            parse_status="parsed",
        )
    )

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert summary["candidate_count"] == 3
    assert summary["accepted_count"] == 3
    assert summary["rejected_count"] == 0
    assert summary["candidate_source_count"] == 1
    assert summary["crawled_catalog_source_count"] == 1
    assert summary["accepted_row_count"] == 3
    assert summary["raw_needs_review_count"] == 1
    assert summary["accepted_to_candidate_source_ratio"] == 3.0
    assert summary["quality_adjustment_applied"] is False
    assert summary["quality_adjusted_accepted_row_count"] == 3
    assert summary["quality_excluded_accepted_row_count"] == 0
    assert summary["quality_adjusted_accepted_to_candidate_source_ratio"] == 3.0
    assert summary["raw_low_row_yield"] is False
    assert summary["low_row_yield"] is False
    assert summary["source_status_counts"] == {"candidate_source": 1}
    assert summary["probable_incomplete_catalog"] is True
    assert summary["recommended_next_action"] == "manual_review_raw_rows"
    assert summary["duplicate_count"] == 1
    assert summary["duplicate_names"] == [{"name": "Bachelor of Science in Data Science", "count": 2}]
    assert summary["by_programme_type"] == {"degree_programme": 2, "major": 1}
    assert summary["by_faculty_or_school"] == {"Faculty of Science": 3}
    assert summary["parse_status_counts"] == {"parsed": 2, "raw_needs_manual_review": 1}
    assert summary["sources_count"] == 1
    assert summary["source_urls"] == [source.source_url]
    assert summary["manual_review_count"] == 1


def test_programme_catalog_summary_flags_low_row_yield_across_many_candidate_sources():
    candidate_urls = [f"https://example.edu/programmes/{index}" for index in range(14)]
    source = source_from_text(
        source_url=candidate_urls[0],
        title="Undergraduate Programmes",
        text="Programme | Degree\nData Science | Bachelor of Science",
    )
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(
            input_url="https://example.edu",
            config={
                "source_strategy": [
                    {
                        "url": url,
                        "source_type": "html",
                        "category": "programme_list",
                        "strategy": "html_page",
                    }
                    for url in candidate_urls
                ]
            },
        ),
        sources=[source],
    )
    for index, name in enumerate(("Data Science", "Computing", "Accountancy")):
        data.programme_catalog.append(
            ProgrammeCatalogRecord(
                name=name,
                degree_or_award="Bachelor of Science",
                category="degree_programme",
                source_url=candidate_urls[index],
                evidence_snippet=f"{name} | Bachelor of Science",
                evidence_path=f"/programme_catalog/{index}/name",
                parse_status="parsed",
            )
        )

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert summary["candidate_source_count"] == 14
    assert summary["accepted_row_count"] == 3
    assert summary["accepted_to_candidate_source_ratio"] == 0.214
    assert summary["quality_adjustment_applied"] is False
    assert summary["quality_adjusted_accepted_row_count"] == 3
    assert summary["quality_adjusted_accepted_to_candidate_source_ratio"] == 0.214
    assert summary["raw_low_row_yield"] is True
    assert summary["low_row_yield"] is True
    assert summary["source_status_counts"] == {"html_candidate": 14}
    assert summary["probable_incomplete_catalog"] is True
    assert summary["recommended_next_action"] == "improve_table_segmentation"


def test_programme_catalog_quality_adjustment_prevents_weak_accepted_rows_from_hiding_low_yield():
    candidate_urls = [f"https://example.edu/programmes/{index}" for index in range(5)]
    source = source_from_text(
        source_url=candidate_urls[0],
        title="Undergraduate Programmes",
        text="Programme | Degree\nData Science | Bachelor of Science",
    )
    rows = [
        ProgrammeCatalogRecord(
            name=name,
            degree_or_award="Bachelor of Science",
            category="degree_programme",
            source_url=candidate_urls[index],
            evidence_snippet=f"{name} | Bachelor of Science",
            evidence_path=f"/programme_catalog/{index}/name",
            parse_status="parsed",
        )
        for index, name in enumerate(("Data Science", "Navigation", "Apply Now", "Study With Us"))
    ]
    candidate_diagnostics = [
        {
            "source_url": row.source_url,
            "source_role": "canonical_catalog" if index == 0 else "faculty_catalog",
            "decision": "accepted",
            "reason": "accepted_manual_review" if index == 3 else "accepted_parsed",
            "claim_path": row.evidence_path,
            "structural_anchor": None if index == 1 else "programme_table_cell",
            "name_quality_passed": index != 2,
            "institution_consistent": True,
        }
        for index, row in enumerate(rows)
    ]
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(
            input_url="https://example.edu",
            config={
                "source_strategy": [
                    {
                        "url": url,
                        "source_type": "html",
                        "category": "programme_list",
                        "strategy": "html_page",
                        "source_role": "canonical_catalog" if index == 0 else "faculty_catalog",
                    }
                    for index, url in enumerate(candidate_urls)
                ],
                "programme_catalog_candidate_diagnostics": candidate_diagnostics,
            },
        ),
        sources=[source],
        programme_catalog=rows,
    )

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert len(data.programme_catalog) == 4
    assert summary["accepted_row_count"] == 4
    assert summary["accepted_to_candidate_source_ratio"] == 0.8
    assert summary["raw_low_row_yield"] is False
    assert summary["quality_adjustment_applied"] is True
    assert summary["quality_adjusted_accepted_row_count"] == 1
    assert summary["quality_excluded_accepted_row_count"] == 3
    assert summary["quality_exclusion_reason_counts"] == {
        "accepted_manual_review": 1,
        "missing_structural_anchor": 1,
        "name_quality_failed": 1,
    }
    assert summary["quality_adjusted_accepted_to_candidate_source_ratio"] == 0.2
    assert summary["low_row_yield"] is True
    assert "row_yield_not_suspicious" in summary["catalog_completeness_failure_reasons"]
    assert summary["recommended_next_action"] == "improve_table_segmentation"
    template = data.run.config["template_completeness"]["programme_catalog"]
    assert template["quality_adjusted_accepted_row_count"] == 1
    assert template["quality_exclusion_reason_counts"] == summary["quality_exclusion_reason_counts"]
    assert template["raw_low_row_yield"] is False
    assert template["low_row_yield"] is True


def test_programme_catalog_summary_recommends_browser_network_capture_for_dynamic_shell():
    url = "https://example.edu/undergraduate-programmes"
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(
            input_url="https://example.edu",
            config={
                "source_strategy": [
                    {
                        "url": url,
                        "source_type": "html",
                        "category": "programme_list",
                        "strategy": "html_page",
                        "catalog_source_status": "dynamic_shell_no_rows",
                    }
                ],
                "extraction_diagnostics": [
                    {
                        "url": url,
                        "source_type": "html",
                        "category": "programme_list",
                        "attempts": [
                            {
                                "field": "programme_catalog",
                                "extractor": "extract_programme_catalog",
                                "status": "no_match",
                                "reason": "category_route",
                                "record_count": 0,
                                "evidence_count": 0,
                            }
                        ],
                    }
                ],
            },
        ),
    )

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert summary["candidate_source_count"] == 1
    assert summary["accepted_row_count"] == 0
    assert summary["source_status_counts"] == {
        "dynamic_shell_no_rows": 1,
        "html_candidate": 1,
        "parsed_zero_rows": 1,
    }
    assert summary["probable_incomplete_catalog"] is True
    assert summary["api_candidate_zero_reason"] == "browser_network_capture_not_triggered"
    assert summary["recommended_next_action"] == "capture_browser_network_api"


def test_programme_catalog_summary_distinguishes_browser_capture_without_network_json():
    url = "https://example.edu/undergraduate-programmes"
    data = AdmissionsData(
        institution=Institution(homepage_url="https://example.edu"),
        run=RunMetadata(
            input_url="https://example.edu",
            config={
                "programme_catalog_browser_capture": {
                    "triggered": True,
                    "attempted_urls": [url],
                    "captured_urls": [f"{url}?page=1"],
                    "rejected_urls": [],
                    "network_response_count": 0,
                    "network_body_count": 0,
                },
                "source_strategy": [
                    {
                        "url": f"{url}?page=1",
                        "source_type": "html",
                        "category": "programme_list",
                        "strategy": "html_page",
                        "catalog_source_status": "dynamic_shell_no_rows",
                    }
                ],
                "extraction_diagnostics": [
                    {
                        "url": f"{url}?page=1",
                        "source_type": "html",
                        "category": "programme_list",
                        "attempts": [
                            {
                                "field": "programme_catalog",
                                "extractor": "extract_programme_catalog",
                                "status": "no_match",
                                "reason": "category_route",
                                "record_count": 0,
                                "evidence_count": 0,
                            }
                        ],
                    }
                ],
            },
        ),
    )

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert summary["api_candidate_zero_reason"] == "browser_capture_no_network_json"
    assert summary["recommended_next_action"] == "discover_public_catalog_api"


def test_programme_catalog_summary_reports_source_family_bias():
    candidate_urls = [
        "https://www.ntu.edu.sg/adm/programmes/undergraduate-programmes/bfa",
        "https://www.ntu.edu.sg/adm/programmes/undergraduate-programmes/media-art",
        "https://www.ntu.edu.sg/hass/admissions/programmes",
        "https://www.ntu.edu.sg/admissions/undergraduate-programmes",
        "https://www.ntu.edu.sg/ase/admissions/undergraduate-programmes",
        "https://www.ntu.edu.sg/wkwsci/admissions/useful-links/undergraduate",
    ]
    data = AdmissionsData(
        institution=Institution(homepage_url="https://www.ntu.edu.sg"),
        run=RunMetadata(
            input_url="https://www.ntu.edu.sg",
            config={
                "source_strategy": [
                    {
                        "url": url,
                        "source_type": "html",
                        "category": "programme_list",
                        "strategy": "html_page",
                    }
                    for url in candidate_urls
                ]
            },
        ),
    )
    for index in range(6):
        data.programme_catalog.append(
            ProgrammeCatalogRecord(
                name=f"ADM Programme {index}",
                degree_or_award="Bachelor of Fine Arts",
                category="degree_programme",
                source_url=f"https://www.ntu.edu.sg/adm/programmes/undergraduate-programmes/programme-{index}",
                evidence_snippet="ADM programme",
                evidence_path=f"/programme_catalog/{index}/name",
                parse_status="parsed",
            )
        )

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert summary["catalog_source_family_counts"]["www.ntu.edu.sg/adm/programmes"] == 8
    assert summary["accepted_source_family_counts"] == {"www.ntu.edu.sg/adm/programmes": 6}
    assert summary["source_family_bias"] is True
    assert summary["dominant_source_family"] == "www.ntu.edu.sg/adm/programmes"
    assert summary["recommended_next_action"] == "review_source_family_bias"


def test_extract_programme_catalog_from_table_text():
    source = source_from_text(
        source_url="https://www.nus.edu.sg/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education/",
        title="NUS Bulletin AY2025/26 - School of Computing Undergraduate Education",
        text=(
            "Programme | Degree | Duration | Admissions Choice\n"
            "Bachelor of Computing in Computer Science | Bachelor of Computing (Honours) in Computer Science | "
            "four-year / at least 160 units | Common Computer Science Programmes\n"
            "Bachelor of Science in Business Analytics | Bachelor of Science (Business Analytics) | "
            "four-year direct honours / 160 units | Business Analytics"
        ),
    )

    rows = extract_programme_catalog(
        "Programme | Degree | Duration | Admissions Choice\n"
        "Bachelor of Computing in Computer Science | Bachelor of Computing (Honours) in Computer Science | "
        "four-year / at least 160 units | Common Computer Science Programmes\n"
        "Bachelor of Science in Business Analytics | Bachelor of Science (Business Analytics) | "
        "four-year direct honours / 160 units | Business Analytics",
        source,
    )

    assert [row.name for row, _evidence in rows] == [
        "Bachelor of Computing in Computer Science",
        "Bachelor of Science in Business Analytics",
    ]
    first, evidence = rows[0]
    assert first.faculty_or_school == "School of Computing"
    assert first.category == "degree_programme"
    assert first.degree_or_award == "Bachelor of Computing (Honours) in Computer Science"
    assert first.duration_or_units == "four-year / at least 160 units"
    assert first.admissions_choice_name == "Common Computer Science Programmes"
    assert first.parse_status == "parsed"
    assert first.evidence_path == "/programme_catalog/0/name"
    assert evidence[0].snippet.startswith("Bachelor of Computing in Computer Science")


def test_extract_programme_catalog_splits_flattened_programme_degree_table():
    text = (
        "Degree Programmes The following single degree programmes are offered. "
        "Programme | Degree Title . "
        "Accountancy | Bachelor of Accountancy . "
        "Aerospace Engineering | Bachelor of Engineering (Aerospace Engineering) . "
        "Computer Science | Bachelor of Computing in Computer Science . "
        "Medicine | Bachelor of Medicine and Bachelor of Surgery"
    )
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/admissions/undergraduate-programmes",
        title="NTU Undergraduate Programmes",
        text=text,
    )

    rows = extract_programme_catalog(text, source)
    by_name = {row.name: row for row, _evidence in rows}

    assert list(by_name) == ["Accountancy", "Aerospace Engineering", "Computer Science", "Medicine"]
    assert by_name["Accountancy"].degree_or_award == "Bachelor of Accountancy"
    assert by_name["Aerospace Engineering"].degree_or_award == "Bachelor of Engineering (Aerospace Engineering)"
    assert by_name["Computer Science"].degree_or_award == "Bachelor of Computing in Computer Science"
    assert by_name["Medicine"].category == "degree_programme"
    assert all(row.evidence_path == f"/programme_catalog/{index}/name" for index, (row, _evidence) in enumerate(rows))


def test_extract_programme_catalog_maps_reordered_non_standard_table_columns():
    text = (NON_STANDARD_CATALOG_FIXTURES / "reordered_columns.txt").read_text(encoding="utf-8")
    source = source_from_text(
        source_url="https://example.edu/academics/undergraduate/programme-catalogue",
        title="Undergraduate Programme Catalogue",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)
    by_name = {row.name: (row, evidence) for row, evidence in rows}

    assert list(by_name) == [
        "Data Science and Artificial Intelligence",
        "Public Policy and Global Affairs",
        "Cybersecurity",
        "Architecture",
        "Economics",
        "Global Studies",
    ]
    data_science, evidence = by_name["Data Science and Artificial Intelligence"]
    assert data_science.degree_or_award == "Bachelor of Science (Honours)"
    assert data_science.faculty_or_school == "School of Computing"
    assert data_science.mode == "full-time"
    assert data_science.specialisations_or_majors == ["Machine Learning", "Business Analytics"]
    assert data_science.parse_status == "parsed"
    assert evidence[0].claim_path == data_science.evidence_path
    assert evidence[0].snippet.startswith("Full-time | Data Science and Artificial Intelligence")

    cybersecurity, _evidence = by_name["Cybersecurity"]
    assert cybersecurity.degree_or_award == "Bachelor of Computing (Honours)"
    assert cybersecurity.specialisations_or_majors == []
    assert cybersecurity.faculty_or_school == "School of Computing"

    architecture, _evidence = by_name["Architecture"]
    assert architecture.category == "degree_programme"
    assert architecture.degree_or_award is None
    assert architecture.parse_status == "parsed"

    economics, _evidence = by_name["Economics"]
    assert economics.category == "major"
    assert economics.degree_or_award is None
    assert economics.parse_status == "parsed"
    assert any("ambiguous_degree:" in warning.message for warning in economics.warnings)

    accepted = [item for item in diagnostics if item["decision"] == "accepted"]
    assert len(accepted) == 6
    assert all(item["candidate_shape"] == "header_mapped_table" for item in accepted)


def test_extract_programme_catalog_splits_flattened_reordered_table_columns():
    text = (
        "Study Mode | Programme | Award . "
        "Full-time | Accountancy | Bachelor of Accountancy . "
        "Full-time | Aerospace Engineering | Bachelor of Engineering (Aerospace Engineering)"
    )
    source = source_from_text(
        source_url="https://example.edu/admissions/undergraduate-programmes",
        title="Undergraduate Programmes",
        text=text,
    )

    rows = extract_programme_catalog(text, source)

    assert [row.name for row, _evidence in rows] == ["Accountancy", "Aerospace Engineering"]
    assert rows[0][0].degree_or_award == "Bachelor of Accountancy"
    assert rows[0][0].mode == "full-time"
    assert rows[1][0].degree_or_award == "Bachelor of Engineering (Aerospace Engineering)"


def test_extract_programme_catalog_inherits_grouped_table_context_with_explicit_warnings():
    text = (NON_STANDARD_CATALOG_FIXTURES / "grouped_rows.txt").read_text(encoding="utf-8")
    source = source_from_text(
        source_url="https://example.edu/academics/undergraduate/grouped-programmes",
        title="Undergraduate Degree Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)
    by_name = {row.name: (row, evidence) for row, evidence in rows}

    assert list(by_name) == [
        "Computer Science",
        "Data Science and Artificial Intelligence",
        "Marketing",
        "Business Analytics",
    ]
    computer_science, _evidence = by_name["Computer Science"]
    assert computer_science.parse_status == "parsed"
    assert computer_science.degree_or_award == "Bachelor of Computing (Honours)"

    data_science, evidence = by_name["Data Science and Artificial Intelligence"]
    assert data_science.faculty_or_school == "School of Computing"
    assert data_science.degree_or_award == "Bachelor of Computing (Honours)"
    assert data_science.mode == "full-time"
    assert data_science.parse_status == "parsed"
    assert evidence[0].snippet == "Data Science and Artificial Intelligence | Full-time"
    assert [item.claim_path for item in evidence] == [
        "/programme_catalog/1/name",
        "/programme_catalog/1/degree_or_award",
        "/programme_catalog/1/faculty_or_school",
    ]
    assert evidence[1].snippet == "School of Computing | Bachelor of Computing (Honours) | Computer Science | Full-time"
    assert evidence[2].snippet == "School of Computing | Bachelor of Computing (Honours) | Computer Science | Full-time"
    assert any("grouped_context_inherited:" in warning.message for warning in data_science.warnings)

    marketing, marketing_evidence = by_name["Marketing"]
    assert marketing.faculty_or_school == "School of Business"
    assert marketing.degree_or_award == "Bachelor of Business Administration (Honours)"
    assert marketing.parse_status == "parsed"
    assert marketing_evidence[1].snippet == "School of Business | Bachelor of Business Administration (Honours) | | Programme Group"
    assert marketing_evidence[2].snippet == "School of Business | Bachelor of Business Administration (Honours) | | Programme Group"
    assert by_name["Business Analytics"][0].mode == "part-time"

    context_rows = [item for item in diagnostics if item["decision"] == "context"]
    assert len(context_rows) == 1
    assert context_rows[0]["reason"] == "group_context_captured"
    assert context_rows[0]["context_fields"] == ["award", "faculty"]
    inherited_rows = [item for item in diagnostics if item.get("candidate_shape") == "grouped_table_row"]
    assert len(inherited_rows) == 3
    assert all(item["inherited_context_fields"] == ["award", "faculty"] for item in inherited_rows)
    data_science_diagnostic = next(item for item in inherited_rows if item["name"] == "Data Science and Artificial Intelligence")
    assert data_science_diagnostic["field_evidence_paths"] == {
        "degree_or_award": "/programme_catalog/1/degree_or_award",
        "faculty_or_school": "/programme_catalog/1/faculty_or_school",
    }


def test_extract_programme_catalog_does_not_leak_group_context_across_table_headers():
    text = (
        "Undergraduate Degree Programmes\n"
        "Faculty | Award | Programme | Study Mode\n"
        "School of Computing | Bachelor of Computing (Honours) | Computer Science | Full-time\n"
        "Programme | Study Mode\n"
        "Marketing | Full-time"
    )
    source = source_from_text(
        source_url="https://example.edu/academics/undergraduate/programmes",
        title="Undergraduate Degree Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert [row.name for row, _evidence in rows] == ["Computer Science"]
    marketing_diagnostic = next(item for item in diagnostics if item["candidate_text"] == "Marketing | Full-time")
    assert marketing_diagnostic["decision"] == "rejected"
    assert marketing_diagnostic["candidate_shape"] == "header_mapped_table"
    assert "inherited_context_fields" not in marketing_diagnostic


def test_extract_programme_catalog_links_inherited_explicit_category_to_its_context_row():
    text = (
        "Undergraduate Degree Programmes\n"
        "Programme Type | Programme | Study Mode\n"
        "Degree Programme | Computer Science | Full-time\n"
        "| Data Science | Full-time"
    )
    source = source_from_text(
        source_url="https://example.edu/academics/undergraduate/programmes",
        title="Undergraduate Degree Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    data_science, evidence = rows[1]
    assert data_science.name == "Data Science"
    assert data_science.category == "degree_programme"
    assert [item.claim_path for item in evidence] == [
        "/programme_catalog/1/name",
        "/programme_catalog/1/category",
    ]
    assert evidence[1].snippet == "Degree Programme | Computer Science | Full-time"
    diagnostic = next(item for item in diagnostics if item.get("name") == "Data Science")
    assert diagnostic["field_evidence_paths"] == {"category": "/programme_catalog/1/category"}


def test_extract_programme_catalog_deduplicates_inherited_evidence_for_repeated_role_columns():
    text = (
        "Undergraduate Degree Programmes\n"
        "Faculty | School | Award | Programme | Study Mode\n"
        "College of Engineering | School of Computing | Bachelor of Computing | Computer Science | Full-time\n"
        "| | | Data Science | Full-time"
    )
    source = source_from_text(
        source_url="https://example.edu/academics/undergraduate/programmes",
        title="Undergraduate Degree Programmes",
        text=text,
    )

    rows = extract_programme_catalog(text, source)

    data_science, evidence = rows[1]
    assert data_science.faculty_or_school == "School of Computing"
    assert [item.claim_path for item in evidence] == [
        "/programme_catalog/1/name",
        "/programme_catalog/1/degree_or_award",
        "/programme_catalog/1/faculty_or_school",
    ]


def test_extract_programme_catalog_accepts_known_metadata_columns_without_persisting_them():
    text = (NON_STANDARD_CATALOG_FIXTURES / "metadata_columns.txt").read_text(encoding="utf-8")
    source = source_from_text(
        source_url="https://example.edu/academics/undergraduate/programme-list",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)
    by_name = {row.name: row for row, _evidence in rows}

    assert list(by_name) == ["Computer Science", "Data Science and Economics"]
    computer_science = by_name["Computer Science"]
    assert computer_science.admissions_choice_name == "CS101"
    assert computer_science.degree_or_award == "Bachelor of Computing (Honours)"
    assert computer_science.mode == "full-time"
    assert computer_science.duration_or_units == "4 years"
    assert computer_science.parse_status == "parsed"

    accepted = [item for item in diagnostics if item["decision"] == "accepted"]
    assert len(accepted) == 2
    assert all(item["ignored_metadata_headers"] == ["Campus", "Details", "Intake"] for item in accepted)


def test_extract_programme_catalog_rejects_reordered_table_with_unknown_metadata_header():
    text = (
        "Undergraduate Programmes\n"
        "Campus | Programme | Award | Student Story\n"
        "Main Campus | Computer Science | Bachelor of Computing (Honours) | Graduate testimonial"
    )
    source = source_from_text(
        source_url="https://example.edu/academics/undergraduate/programmes",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert rows == []
    row_diagnostic = next(item for item in diagnostics if "Computer Science" in str(item["candidate_text"]))
    assert row_diagnostic["decision"] == "rejected"
    assert row_diagnostic["reason"] == "unknown_table_shape"
    assert row_diagnostic["candidate_shape"] == "partial_header_table"


def test_programme_catalog_marks_duplicate_rows_without_dropping_them():
    text = (
        "Programme | Degree | Faculty\n"
        "Bachelor of Computing in Computer Science | Bachelor of Computing (Honours) in Computer Science | School of Computing\n"
        "Bachelor of Computing in Computer Science | Bachelor of Computing (Honours) in Computer Science | School of Computing"
    )
    source = source_from_text(
        source_url="https://www.nus.edu.sg/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education/",
        title="School of Computing Undergraduate Education",
        text=text,
    )

    rows = extract_programme_catalog(text, source)

    assert [row.name for row, _evidence in rows] == [
        "Bachelor of Computing in Computer Science",
        "Bachelor of Computing in Computer Science",
    ]
    assert rows[0][0].evidence_path == "/programme_catalog/0/name"
    assert rows[1][0].evidence_path == "/programme_catalog/1/name"
    assert not any("duplicate_name:" in warning.message for warning in rows[0][0].warnings)
    assert any("duplicate_name:" in warning.message for warning in rows[1][0].warnings)


def test_programme_catalog_keeps_same_name_with_different_awards_separate():
    text = (
        "Programme | Degree | Faculty\n"
        "Bachelor of Engineering | Bachelor of Engineering (Mechanical Engineering) | College of Engineering\n"
        "Bachelor of Engineering | Bachelor of Engineering (Civil Engineering) | College of Engineering"
    )
    source = source_from_text(
        source_url="https://example.edu/programmes/undergraduate-engineering",
        title="Undergraduate Programmes - Engineering",
        text=text,
    )

    rows = extract_programme_catalog(text, source)

    assert [row.degree_or_award for row, _evidence in rows] == [
        "Bachelor of Engineering (Mechanical Engineering)",
        "Bachelor of Engineering (Civil Engineering)",
    ]
    assert not any("duplicate_name:" in warning.message for row, _evidence in rows for warning in row.warnings)


def test_programme_catalog_keeps_only_unresolved_field_quality_warnings_after_entity_gate_acceptance():
    text = "Undergraduate Programmes\nSpecial Programme in Science (SPS)"
    source = source_from_text(
        source_url="https://www.nus.edu.sg/programmes/undergraduate",
        title="NUS Undergraduate Programmes",
        text=text,
    )

    rows = extract_programme_catalog(text, source)

    assert len(rows) == 1
    row = rows[0][0]
    warning_messages = [warning.message for warning in row.warnings]
    assert row.name == "Special Programme in Science (SPS)"
    assert row.parse_status == "parsed"
    assert any("ambiguous_degree:" in message for message in warning_messages)
    assert any("missing_faculty:" in message for message in warning_messages)
    assert not any("category_inferred:" in message for message in warning_messages)
    assert not any("raw_needs_manual_review:" in message for message in warning_messages)


def test_ntu_profile_does_not_apply_nus_names_or_body_faculty_mentions():
    text = (
        "Undergraduate Programmes\n"
        "Our exchange partners include NUS Business School and NUS College.\n"
        "CHS Primary Major: Chinese Languages and Cultures\n"
        "FASS Major: Economics\n"
        "NUS College\n"
        "Programme | Degree\n"
        "Computer Science | Bachelor of Computing in Computer Science"
    )
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/education/degree-programmes",
        title="Degree Programmes | NTU Singapore",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert [row.name for row, _evidence in rows] == ["Computer Science"]
    assert rows[0][0].faculty_or_school is None
    assert all(item["institution_profile"] == "ntu" for item in diagnostics)
    serialized = " ".join(str(row.to_dict()) for row, _evidence in rows)
    assert not any(label in serialized for label in ("NUS Business School", "NUS College", "CHS", "FASS"))


def test_ntu_profile_rejects_explicit_nus_faculty_and_programme_labels():
    text = (
        "Undergraduate Programmes\n"
        "Programme | Degree | Faculty | Category\n"
        "Business | Bachelor of Business | NUS Business School | Degree Programme\n"
        "NUS College | Certificate | NUS College | Special Programme\n"
        "CHS Primary Major: Economics | Bachelor of Arts | College of Humanities and Sciences | Major"
    )
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/education/degree-programmes",
        title="Degree Programmes | NTU Singapore",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert rows == []
    rejected = [item for item in diagnostics if item.get("reason") == "institution_context_mismatch"]
    assert {item.get("name") for item in rejected} == {
        "Business",
        "NUS College",
        "CHS Primary Major: Economics",
    }
    assert all(item["institution_consistent"] is False for item in rejected)


def test_ntu_profile_rejects_foreign_faculty_section_inheritance():
    document = extract_html_text_document(
        "<main><h1>Undergraduate Programmes</h1>"
        "<h2>NUS Business School</h2>"
        "<h3>Bachelor of Business Administration</h3></main>"
    )
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/education/degree-programmes",
        title="Degree Programmes | NTU Singapore",
        text=document.plain_text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(
        document.plain_text,
        source,
        content_blocks=document.blocks,
        candidate_diagnostics=diagnostics,
    )

    assert rows == []
    rejected = next(item for item in diagnostics if item.get("name") == "Bachelor of Business Administration")
    assert rejected["reason"] == "institution_context_mismatch"
    assert rejected["section_context_fields"] == ["faculty"]


def test_ntu_profile_resolves_documented_faculty_aliases_from_source_title():
    aliases = (
        ("Nanyang Business School", "Nanyang Business School"),
        ("CCDS", "College of Computing and Data Science"),
        ("CoHASS", "College of Humanities, Arts and Social Sciences"),
        ("ADM", "School of Art, Design and Media"),
        ("SoH", "School of Humanities"),
        ("SSS", "School of Social Sciences"),
        ("WKWSCI", "Wee Kim Wee School of Communication and Information"),
    )
    text = (
        "Undergraduate Programmes\n"
        "Programme | Degree\n"
        "Computer Science | Bachelor of Computing in Computer Science"
    )

    for alias, expected in aliases:
        source = source_from_text(
            source_url="https://www.ntu.edu.sg/education/degree-programmes",
            title=f"{alias} Undergraduate Programmes | NTU Singapore",
            text=text,
        )

        diagnostics: list[dict[str, object]] = []
        rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

        assert len(rows) == 1, alias
        row, evidence = rows[0]
        assert row.faculty_or_school == expected, alias
        faculty_path = "/programme_catalog/0/faculty_or_school"
        assert any(item.claim_path == faculty_path and alias in item.snippet for item in evidence), alias
        assert diagnostics[-1]["field_evidence_paths"] == {"faculty_or_school": faculty_path}, alias


def test_ntu_profile_does_not_infer_faculty_from_url_alias_without_title_evidence():
    text = (
        "Undergraduate Programmes\n"
        "Programme | Degree\n"
        "Computer Science | Bachelor of Computing in Computer Science"
    )
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/ccds/programmes",
        title="Undergraduate Programmes | NTU Singapore",
        text=text,
    )

    rows = extract_programme_catalog(text, source)

    assert len(rows) == 1
    assert rows[0][0].faculty_or_school is None


def test_unknown_and_non_official_sources_do_not_enable_institution_profiles():
    text = (
        "Undergraduate Programmes\n"
        "CHS Primary Major: Chinese Languages and Cultures\n"
        "NUS College\n"
        "Programme | Degree | Faculty\n"
        "Computer Science | Bachelor of Science in Computer Science | School of Example Studies"
    )
    sources = (
        source_from_text(
            source_url="https://example.edu/programmes/undergraduate",
            title="Undergraduate Programmes",
            text=text,
        ),
        source_from_text(
            source_url="https://www.nus.edu.sg/programmes/undergraduate",
            title="NUS Undergraduate Programmes",
            text=text,
            is_official=False,
        ),
    )

    for source in sources:
        diagnostics: list[dict[str, object]] = []
        rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

        assert [row.name for row, _evidence in rows] == ["Computer Science"]
        assert rows[0][0].faculty_or_school == "School of Example Studies"
        assert all(item["institution_profile"] == "generic" for item in diagnostics)


def test_detail_page_does_not_infer_faculty_from_nav_footer_or_related_blocks():
    document = extract_html_text_document(
        "<main><nav>NUS Business School</nav>"
        "<h1>Bachelor of Science in Data Science</h1>"
        "<p>This programme covers data systems and statistics.</p>"
        "<h2>Related Programmes</h2><p>NUS Business School</p>"
        "<footer>CHS FASS NUS College</footer></main>"
    )
    source = source_from_text(
        source_url="https://www.ntu.edu.sg/education/undergraduate-programme/bachelor-of-science-in-data-science",
        title="Bachelor of Science in Data Science | NTU Singapore",
        text=document.plain_text,
    )

    rows = extract_programme_catalog(document.plain_text, source, content_blocks=document.blocks)

    assert len(rows) == 1
    assert rows[0][0].name == "Bachelor of Science in Data Science"
    assert rows[0][0].faculty_or_school is None


def test_programme_catalog_mock_llm_hint_can_classify_ambiguous_candidate():
    text = "Undergraduate Programmes\nScholars Programme full-time"
    source = source_from_text(
        source_url="https://example.edu/programmes/undergraduate",
        title="Undergraduate Programmes",
        text=text,
    )
    payload = json.loads((LLM_FIXTURES / "programme_catalog_hint_special_programme.json").read_text(encoding="utf-8"))
    provider = MockProgrammeCatalogAssistProvider(payload)

    without_hint = extract_programme_catalog(text, source)
    with_hint = extract_programme_catalog(text, source, assist_provider=provider)

    assert without_hint == []
    assert len(with_hint) == 1
    row, evidence = with_hint[0]
    assert row.name == "Scholars Programme"
    assert row.category == "special_programme"
    assert row.mode == "full-time"
    assert row.source_url == source.source_url
    assert row.evidence_snippet == "Scholars Programme full-time"
    assert evidence[0].snippet == row.evidence_snippet
    assert any("category_inferred:" in warning.message for warning in row.warnings)


def test_programme_catalog_mock_llm_hint_rejects_fact_generation_payload():
    text = "Undergraduate Programmes\nScholars Programme full-time"
    source = source_from_text(
        source_url="https://example.edu/programmes/undergraduate",
        title="Undergraduate Programmes",
        text=text,
    )
    provider = MockProgrammeCatalogAssistProvider(
        {
            "category": "special_programme",
            "mode": "full-time",
            "reason": "Invalid payload also tries to provide a programme fact.",
            "confidence": "low",
            "signals": ["scholars_programme"],
            "name": "Fabricated Bachelor of Science",
        }
    )

    assert extract_programme_catalog(text, source, assist_provider=provider) == []


def test_extract_programme_catalog_from_list_text_with_major_and_special_programme():
    text = """
    Undergraduate Programmes
    NUS Business School offers Bachelor of Business Administration with Honours, 160 units, full-time.
    BBA Major: Finance within 160-unit BBA curriculum.
    Special Programme in Science (SPS)
    """
    source = source_from_text(
        source_url="https://www.nus.edu.sg/nusbulletin/ay202526/programmes/school-of-business/undergraduate-education",
        title="NUS Bulletin AY2025/26 - School of Business Undergraduate Education",
        text=text,
    )

    rows = extract_programme_catalog(text, source)
    by_name = {row.name: row for row, _evidence in rows}

    assert by_name["Bachelor of Business Administration with Honours"].category == "degree_programme"
    assert by_name["Bachelor of Business Administration with Honours"].mode == "full-time"
    assert by_name["Bachelor of Business Administration with Honours"].duration_or_units == "160 units"
    assert by_name["BBA Major: Finance"].category == "major"
    assert by_name["BBA Major: Finance"].degree_or_award == "Major within Bachelor of Business Administration (Honours)"
    assert by_name["Special Programme in Science (SPS)"].category == "special_programme"
    assert by_name["Special Programme in Science (SPS)"].parse_status == "parsed"
    assert by_name["Special Programme in Science (SPS)"].warnings
    assert not any(
        warning.message.startswith("category_inferred:")
        for row in by_name.values()
        for warning in row.warnings
    )


def test_extract_programme_catalog_ignores_marketing_bachelor_sentence():
    text = "Our alumni mentor students and a Bachelor option can lead to many exciting careers."
    source = source_from_text(
        source_url="https://example.edu/news/alumni",
        title="Alumni news",
        text=text,
    )

    assert extract_programme_catalog(text, source) == []


def test_extract_programme_catalog_ignores_longform_overview_sentence():
    text = (
        "Undergraduate Programmes\n"
        "Bachelor of Science in Data Science gives students a broad curriculum and applicants will learn "
        "through interdisciplinary courses, admissions workshops, industry projects, exchange options, "
        "career preparation, and graduate pathways across multiple departments before choosing a final "
        "study plan with advisors and mentors throughout the programme."
    )
    source = source_from_text(
        source_url="https://example.edu/programmes/undergraduate",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    assert extract_programme_catalog(text, source, candidate_diagnostics=diagnostics) == []
    assert any(item["reason"] == "longform_prose" for item in diagnostics)


def test_programme_catalog_rejects_second_major_explainer_with_candidate_diagnostic():
    text = (
        "Undergraduate Programmes\n"
        "Students admitted to the Bachelor of Science may choose a second major in Business after admission; "
        "this option is not a separate admissions degree programme."
    )
    source = source_from_text(
        source_url="https://example.edu/programmes/undergraduate",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert rows == []
    rejected = [item for item in diagnostics if item["decision"] == "rejected"]
    assert any(item["reason"] == "second_major_explainer" for item in rejected)
    assert any("Bachelor of Science" in str(item["candidate_text"]) for item in rejected)


def test_programme_catalog_records_unknown_table_shape_candidate_diagnostics():
    text = (
        "Undergraduate Programmes\n"
        "Programme | Award | Study Mode\n"
        "Architecture | Undergraduate full-time\n"
        "Business Administration | Undergraduate full-time"
    )
    source = source_from_text(
        source_url="https://example.edu/programmes/undergraduate",
        title="Undergraduate Programmes",
        text=text,
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert rows == []
    assert any(item["reason"] == "unknown_table_shape" for item in diagnostics)
    assert all("candidate_text" in item for item in diagnostics)


def test_programme_catalog_summary_counts_candidate_rejection_reasons():
    data = AdmissionsData(institution=Institution(homepage_url="https://example.edu/"), run=RunMetadata(input_url="https://example.edu/"))
    data.run.config["programme_catalog_candidate_diagnostics"] = [
        {
            "decision": "rejected",
            "reason": "second_major_explainer",
            "candidate_shape": "text",
            "block_kind": "paragraph",
            "parser_stage": "entity_gate",
        },
        {
            "decision": "rejected",
            "reason": "unknown_table_shape",
            "candidate_shape": "table_row",
            "block_kind": "table_row",
            "parser_stage": "parse_candidate",
        },
        {
            "decision": "rejected",
            "reason": "admissions_explainer",
            "candidate_shape": "text",
            "block_kind": "paragraph",
            "parser_stage": "entity_gate",
        },
        {
            "decision": "accepted",
            "reason": "accepted_parsed",
            "candidate_shape": "header_mapped_table",
            "ignored_metadata_headers": ["Campus", "Intake"],
            "block_kind": "table_row",
            "source_role": "canonical_catalog",
            "structural_anchor": "programme_table_cell",
        },
        {
            "decision": "context",
            "reason": "group_context_captured",
            "candidate_shape": "group_context_row",
            "block_kind": "table_row",
        },
        {
            "decision": "context",
            "reason": "section_context_captured",
            "candidate_shape": "section_context_row",
            "block_kind": "heading",
        },
        {
            "decision": "accepted",
            "reason": "accepted_parsed",
            "candidate_shape": "section_context_candidate",
            "section_context_fields": ["faculty"],
            "field_evidence_paths": {"faculty_or_school": "/programme_catalog/0/faculty_or_school"},
            "block_kind": "heading",
            "source_role": "faculty_catalog",
            "structural_anchor": "faculty_degree_heading",
        },
        {
            "decision": "accepted",
            "reason": "accepted_parsed",
            "candidate_shape": "grouped_table_row",
            "inherited_context_fields": ["award", "faculty"],
            "field_evidence_paths": {
                "degree_or_award": "/programme_catalog/1/degree_or_award",
                "faculty_or_school": "/programme_catalog/1/faculty_or_school",
            },
            "block_kind": "table_row",
            "source_role": "canonical_catalog",
            "structural_anchor": "programme_table_cell",
        },
    ]
    data.run.config["programme_catalog_field_evidence"] = {
        "/programme_catalog/0/name": {"faculty_or_school": "/programme_catalog/0/faculty_or_school"},
        "/programme_catalog/1/name": {
            "degree_or_award": "/programme_catalog/1/degree_or_award",
            "faculty_or_school": "/programme_catalog/1/faculty_or_school",
        },
        "/programme_catalog/2/name": {},
        "/programme_catalog/3/name": "invalid",
    }

    attach_run_diagnostics(data)
    summary = data.run.config["programme_catalog_summary"]

    assert summary["candidate_diagnostic_count"] == 8
    assert summary["candidate_rejected_count"] == 3
    assert summary["candidate_context_count"] == 2
    assert summary["candidate_decision_counts"] == {"accepted": 3, "context": 2, "rejected": 3}
    assert summary["candidate_context_reason_counts"] == {
        "group_context_captured": 1,
        "section_context_captured": 1,
    }
    assert summary["candidate_rejection_reasons"] == {
        "admissions_explainer": 1,
        "second_major_explainer": 1,
        "unknown_table_shape": 1,
    }
    assert summary["html_false_positive_rejected_count"] == 2
    assert summary["candidate_shape_counts"] == {
        "group_context_row": 1,
        "grouped_table_row": 1,
        "header_mapped_table": 1,
        "table_row": 1,
        "section_context_candidate": 1,
        "section_context_row": 1,
        "text": 2,
    }
    assert summary["accepted_candidate_shape_counts"] == {
        "grouped_table_row": 1,
        "header_mapped_table": 1,
        "section_context_candidate": 1,
    }
    assert summary["candidate_manual_review_count"] == 0
    assert summary["entity_gate_rejected_count"] == 2
    assert summary["accepted_without_structural_anchor_count"] == 0
    assert summary["institution_context_mismatch_count"] == 0
    assert summary["accepted_source_role_counts"] == {"canonical_catalog": 2, "faculty_catalog": 1}
    assert summary["accepted_structural_anchor_counts"] == {
        "faculty_degree_heading": 1,
        "programme_table_cell": 2,
    }
    assert summary["candidate_block_kind_counts"] == {
        "heading": 2,
        "paragraph": 2,
        "table_row": 4,
    }
    assert summary["section_context_captured_count"] == 1
    assert summary["section_context_inherited_count"] == 1
    assert summary["group_context_captured_count"] == 1
    assert summary["group_context_inherited_count"] == 1
    assert summary["field_evidence_row_count"] == 2
    assert summary["field_evidence_path_count"] == 3
    assert summary["field_evidence_field_counts"] == {"degree_or_award": 1, "faculty_or_school": 2}
    assert summary["ignored_metadata_header_counts"] == {"Campus": 1, "Intake": 1}
    assert data.run.config["template_completeness"]["programme_catalog"]["candidate_rejected_count"] == 3
    assert data.run.config["template_completeness"]["programme_catalog"]["candidate_decision_counts"] == {
        "accepted": 3,
        "context": 2,
        "rejected": 3,
    }
    assert data.run.config["template_completeness"]["programme_catalog"]["candidate_context_count"] == 2
    assert data.run.config["template_completeness"]["programme_catalog"]["section_context_inherited_count"] == 1
    assert data.run.config["template_completeness"]["programme_catalog"]["field_evidence_path_count"] == 3
    assert data.run.config["template_completeness"]["programme_catalog"]["ignored_metadata_header_counts"] == {
        "Campus": 1,
        "Intake": 1,
    }
    assert data.run.config["template_completeness"]["programme_catalog"]["candidate_manual_review_count"] == 0
    assert data.run.config["template_completeness"]["programme_catalog"]["entity_gate_rejected_count"] == 2
    assert data.run.config["template_completeness"]["programme_catalog"]["accepted_without_structural_anchor_count"] == 0


def test_extract_programme_catalog_rejects_course_table_open_to_values():
    source = source_from_text(
        source_url="https://example.edu/adm/programmes/undergraduate-programmes/design-art",
        title="Undergraduate Programmes - Design Art",
        text="Undergraduate Programmes",
    )
    text = (
        "Undergraduate Programmes\n"
        "Programme | Degree\n"
        "Design Art | Bachelor of Fine Arts\n"
        "Major PE Courses | Course Code | Course Title | AU | Pre-req | Open to\n"
        "DD3010 | Form and Visualization | 3 AU | Nil | BEng SCE | BEng Design Stream"
    )
    diagnostics: list[dict[str, object]] = []

    rows = extract_programme_catalog(text, source, candidate_diagnostics=diagnostics)

    assert [row.name for row, _evidence in rows] == ["Design Art"]
    assert any(item["reason"] == "course_or_curriculum_row" for item in diagnostics)
