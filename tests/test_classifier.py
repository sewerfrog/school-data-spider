from university_admissions_crawler.classifier.page_classifier import classify_page
from university_admissions_crawler.extractor.schema import PageCategory


def check(category: PageCategory, url: str, title: str, text: str):
    result = classify_page(url, title, text)
    assert result.category == category
    assert result.score > 0


def test_classifies_required_categories():
    check(PageCategory.UNDERGRADUATE_ADMISSIONS, "https://x.edu/admissions", "Undergraduate Admissions", "How to apply")
    check(PageCategory.INTERNATIONAL_REQUIREMENTS, "https://x.edu/international", "International Requirements", "English requirements")
    check(PageCategory.APPLICATION_DEADLINES, "https://x.edu/deadlines", "Application Deadlines", "Deadline: 1 Jan 2027")
    check(PageCategory.ACCEPTED_QUALIFICATIONS, "https://x.edu/qualifications", "Accepted Qualifications", "A-level accepted")
    check(PageCategory.PROGRAMME_LIST, "https://x.edu/programmes", "Undergraduate Programmes", "Bachelor degree programmes")
    check(PageCategory.PROGRAMME_PREREQUISITES, "https://x.edu/prerequisites", "Programme Prerequisites", "Mathematics required")
    check(PageCategory.FEES, "https://x.edu/fees", "Tuition Fees", "Fees per year")
    check(PageCategory.SCHOLARSHIPS, "https://x.edu/scholarships", "Scholarships", "Scholarship available")
    check(PageCategory.VISA, "https://x.edu/visa", "Student Visa", "Student pass required")
    check(PageCategory.HOUSING, "https://x.edu/housing", "Housing", "Accommodation")
    check(PageCategory.CONTACT, "https://x.edu/contact", "Admissions Office Contact", "Email and phone")


def test_negative_news_page_is_irrelevant_even_with_admissions_mention():
    result = classify_page("https://x.edu/news/alumni-fair", "Alumni News", "Admissions fair in the news")
    assert result.category == PageCategory.IRRELEVANT


def test_admissions_url_is_not_rejected_by_global_navigation_negative_words():
    nav_noise = "Alumni News Giving Staff Jobs"
    result = classify_page(
        "https://www.ntu.edu.sg/admissions/undergraduate/admission-guide/international-qualifications",
        "International Qualifications",
        f"{nav_noise} IELTS TOEFL English language requirements for international applicants.",
    )
    assert result.category == PageCategory.INTERNATIONAL_REQUIREMENTS


def test_tuition_fees_page_is_not_rejected_by_global_navigation_negative_words():
    result = classify_page(
        "https://www.ntu.edu.sg/admissions/undergraduate/financial-matters/tuition-fees",
        "Tuition Fees",
        "Alumni News Giving Staff Jobs Tuition fees for undergraduate students.",
    )
    assert result.category == PageCategory.FEES


def test_polyu_non_admissions_pages_do_not_become_international_requirements():
    assert classify_page(
        "https://www.polyu.edu.hk/current-students/",
        "Current Students",
        "International exchange English summer programme website requirements.",
    ).category == PageCategory.IRRELEVANT
    assert classify_page(
        "https://www.polyu.edu.hk/education/",
        "Exchange Programmes and Overseas Internship Opportunities",
        "English Language Centre Institute for Higher Education Research and Development Quick Links General University Requirements.",
    ).category == PageCategory.IRRELEVANT


def test_programme_catalog_source_signals_classify_as_programme_list():
    checks = (
        (
            "https://www.nus.edu.sg/nusbulletin/ay202526/programmes/school-of-computing/undergraduate-education/",
            "NUS Bulletin AY2025/26 - School of Computing Undergraduate Education",
            "Bachelor of Computing in Computer Science and other degree programmes.",
        ),
        (
            "https://example.edu/catalogue/undergraduate/majors",
            "Undergraduate Catalogue - Majors",
            "Students may choose majors and minors from the undergraduate catalogue.",
        ),
        (
            "https://example.edu/study/undergraduate/degree-programmes",
            "Undergraduate Degree Programmes",
            "Bachelor degree programmes are listed by faculty.",
        ),
    )
    for url, title, text in checks:
        assert classify_page(url, title, text).category == PageCategory.PROGRAMME_LIST


def test_programme_catalog_signals_do_not_override_non_admissions_context():
    assert classify_page(
        "https://example.edu/news/summer-programme-for-high-school-students",
        "Summer Programme News",
        "Pre-university summer programme for high school students.",
    ).category == PageCategory.IRRELEVANT
    assert classify_page(
        "https://example.edu/alumni/mentoring-programmes",
        "Alumni Mentoring Programmes",
        "Alumni mentoring programmes and networking events.",
    ).category == PageCategory.IRRELEVANT
