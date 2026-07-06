import json
from pathlib import Path

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
    assert rows_by_name["NUS College"].parse_status == "raw_needs_manual_review"
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
    assert by_name["Bachelor of Social Sciences (Hons)"].specialisations_or_majors == [
        "Economics",
        "Psychology",
        "Public Policy and Global Affairs",
        "Sociology",
    ]

    admissions_rows = _extract_saved_programme_catalog("ntu", "347ce27695edcec6")
    assert admissions_rows == []


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
    assert summary["low_row_yield"] is True
    assert summary["source_status_counts"] == {"html_candidate": 14}
    assert summary["probable_incomplete_catalog"] is True
    assert summary["recommended_next_action"] == "improve_table_segmentation"


def test_programme_catalog_summary_recommends_browser_or_api_for_dynamic_shell():
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
    assert summary["recommended_next_action"] == "enable_browser_or_api_capture"


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


def test_programme_catalog_quality_warnings_for_ambiguous_inferred_rows():
    text = "Undergraduate Programmes\nSpecial Programme in Science (SPS)"
    source = source_from_text(
        source_url="https://example.edu/programmes/undergraduate",
        title="Undergraduate Programmes",
        text=text,
    )

    rows = extract_programme_catalog(text, source)

    assert len(rows) == 1
    row = rows[0][0]
    warning_messages = [warning.message for warning in row.warnings]
    assert row.name == "Special Programme in Science (SPS)"
    assert row.parse_status == "raw_needs_manual_review"
    assert any("ambiguous_degree:" in message for message in warning_messages)
    assert any("missing_faculty:" in message for message in warning_messages)
    assert any("category_inferred:" in message for message in warning_messages)
    assert any("raw_needs_manual_review:" in message for message in warning_messages)


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
    assert by_name["Special Programme in Science (SPS)"].parse_status == "raw_needs_manual_review"
    assert by_name["Special Programme in Science (SPS)"].warnings


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

    assert extract_programme_catalog(text, source) == []
