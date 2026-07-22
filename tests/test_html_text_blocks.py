import json
from pathlib import Path
from types import SimpleNamespace

from university_admissions_crawler.crawler.fetcher import FixtureFetcher
from university_admissions_crawler.crawler.html_text import _html_to_text, extract_html_text_document
from university_admissions_crawler.pipeline.scan_context import source_text_context


FIXTURES = Path(__file__).parent / "fixtures" / "programme_catalog" / "ntu_live_regressions"


def _document(name: str):
    return extract_html_text_document((FIXTURES / name).read_text(encoding="utf-8"))


def test_typed_blocks_preserve_legacy_plain_text_contract():
    html = (FIXTURES / "canonical_degree_table.html").read_text(encoding="utf-8")
    document = extract_html_text_document(html)

    assert document.plain_text == _html_to_text(html)
    assert document.plain_text == (
        "Degree Programmes | NTU Singapore The undergraduate degree programmes are shown below. "
        "Programme | Degree Title . Accountancy | Bachelor of Accountancy . Computer Science | "
        "Bachelor of Computing in Computer Science . Environmental Earth Systems Science | Bachelor "
        "of Science in Environmental Earth Systems Science . Medicine | Bachelor of Medicine and "
        "Bachelor of Surgery"
    )


def test_pipe_delimited_heading_stays_a_heading_with_section_paths():
    document = _document("hass_title_pipe.html")

    assert all(block.kind != "table_row" for block in document.blocks)
    assert document.blocks[0].kind == "heading"
    assert document.blocks[0].heading_level == 1
    assert document.blocks[0].text == "Undergraduate Programmes | College of Humanities, Arts and Social Sciences | NTU Singapore"
    assert document.blocks[0].section_path == (document.blocks[0].text,)

    degree = next(block for block in document.blocks if block.text == "Bachelor of Fine Arts in Art, Design and Media")
    assert degree.kind == "heading"
    assert degree.heading_level == 3
    assert degree.section_path == (
        document.blocks[0].text,
        "School of Art, Design and Media",
        degree.text,
    )


def test_real_table_rows_keep_cell_boundaries_and_order():
    document = _document("canonical_degree_table.html")
    table_rows = [block for block in document.blocks if block.kind == "table_row"]

    assert [block.cells for block in table_rows] == [
        ("Programme", "Degree Title"),
        ("Accountancy", "Bachelor of Accountancy"),
        ("Computer Science", "Bachelor of Computing in Computer Science"),
        (
            "Environmental Earth Systems Science",
            "Bachelor of Science in Environmental Earth Systems Science",
        ),
        ("Medicine", "Bachelor of Medicine and Bachelor of Surgery"),
    ]
    assert all(block.section_path == ("Degree Programmes | NTU Singapore",) for block in table_rows)


def test_visible_css_is_retained_and_marked_without_marking_programme_headings():
    document = _document("ccds_visible_css.html")
    css_block = next(block for block in document.blocks if "MASTER STYLESHEET" in block.text)

    assert css_block.kind == "paragraph"
    assert css_block.flags == ("css_like",)
    assert ".ccds-card" in css_block.text
    assert next(block for block in document.blocks if block.text.startswith("Bachelor of Computing")).flags == ()


def test_json_ld_courses_become_card_blocks_only_when_visible_blocks_are_empty():
    document = _document("ccds_json_ld_course_cards.html")

    assert [block.kind for block in document.blocks] == ["card", "card", "card", "card"]
    assert [block.text for block in document.blocks] == [
        "Bachelor of Computing (Hons) in Artificial Intelligence (AI) and Society",
        "Bachelor of Engineering (Hons) in Computer Engineering",
        "Bachelor of Applied Computing in Finance",
        "Bachelor of Engineering (Hons) in Computer Engineering with a Second Major in Data Analytics",
    ]
    assert all(block.links and block.links[0].text == block.text for block in document.blocks)
    assert "Computing | Engineering Bachelor of Engineering" in document.plain_text


def test_json_ld_fallback_ignores_malformed_payloads_and_does_not_duplicate_visible_blocks():
    malformed = extract_html_text_document(
        '<script type="application/ld+json">{not valid json}</script><div>Undergraduate programmes</div>'
    )
    visible = extract_html_text_document(
        '<script type="application/ld+json">'
        '{"@type":"Course","name":"Bachelor of Science","url":"/science"}'
        "</script><h1>Bachelor of Science</h1>"
    )
    hidden = extract_html_text_document(
        '<script type="application/ld+json">'
        '{"@type":"Course","name":"Bachelor of Arts","url":"/arts"}'
        "</script><div>Undergraduate programmes</div>"
    )

    assert malformed.blocks == ()
    assert [(block.kind, block.text) for block in visible.blocks] == [("heading", "Bachelor of Science")]
    assert hidden.blocks == ()


def test_json_ld_course_fallback_has_a_per_page_candidate_limit():
    courses = [
        {
            "@type": "Course",
            "name": f"Bachelor of Science in Subject {index}",
            "url": f"/programmes/subject-{index}",
        }
        for index in range(501)
    ]
    payload = {
        "@graph": courses
    }
    visible_names = " ".join(course["name"] for course in courses)

    document = extract_html_text_document(
        f'<script type="application/ld+json">{json.dumps(payload)}</script><div>{visible_names}</div>'
    )

    assert len(document.blocks) == 500
    assert document.blocks[0].text == "Bachelor of Science in Subject 0"
    assert document.blocks[-1].text == "Bachelor of Science in Subject 499"


def test_list_item_link_metadata_stays_in_related_programmes_section():
    document = _document("detail_related_programmes.html")
    related_items = [block for block in document.blocks if block.kind == "list_item"]

    assert [block.text for block in related_items] == [
        "Bachelor of Arts (Hons) in English",
        "Bachelor of Arts (Hons) in Philosophy",
    ]
    assert related_items[0].section_path == (
        "Bachelor of Arts (Hons) in Chinese",
        "Related Programmes",
    )
    assert related_items[0].links[0].text == related_items[0].text
    assert related_items[0].links[0].href.endswith("bachelor-of-arts-in-english")


def test_script_and_style_are_removed_while_br_boundary_is_preserved():
    document = extract_html_text_document(
        "<main><h1>Programmes</h1><style>.hidden { color: red; }</style>"
        "<p>First line<br>Second line<script>ignored()</script></p>"
        "<ul><li>Bachelor of Science</li></ul></main>"
    )

    assert [(block.kind, block.text) for block in document.blocks] == [
        ("heading", "Programmes"),
        ("paragraph", "First line\nSecond line"),
        ("list_item", "Bachelor of Science"),
    ]


def test_fetch_and_source_context_carry_html_blocks_but_json_does_not():
    html_result = FixtureFetcher(FIXTURES).fetch("https://fixture.test/hass_title_pipe.html")
    text_context = source_text_context(SimpleNamespace(warnings=[]), html_result, SimpleNamespace())
    json_result = FixtureFetcher(Path("tests/fixtures/mini_university_site")).fetch(
        "https://fixture.test/api/programmes.json"
    )

    assert html_result.content_blocks
    assert text_context.content_blocks == html_result.content_blocks
    assert text_context.extraction_text == html_result.markdown
    assert json_result.content_blocks == ()
