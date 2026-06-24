from pathlib import Path

from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url, is_low_value_source_url, is_pdf_url, looks_like_blocked_or_challenge_source, score_url, should_follow_url, validate_source_plan_candidate_url


SAVED = Path("tests/fixtures/saved_sources")


def test_canonicalize_url_drops_fragments_tracking_and_sorts_query():
    url = canonicalize_url("HTTPS://EXAMPLE.EDU/admissions/?utm_source=x&b=2&a=1#top")
    assert url == "https://example.edu/admissions?a=1&b=2"


def test_domain_policy_allows_same_host_and_official_subdomain():
    policy = DomainPolicy("https://www.example.edu/")
    assert policy.is_allowed("https://www.example.edu/admissions")
    assert policy.is_allowed("https://apply.example.edu/undergraduate")
    assert not policy.is_allowed("https://example.com/admissions")


def test_domain_policy_can_disable_subdomain_expansion():
    policy = DomainPolicy("https://www.example.edu/", allow_official_subdomains=False)
    assert not policy.is_allowed("https://apply.example.edu/undergraduate")


def test_score_url_prefers_admissions_and_penalizes_news():
    assert score_url("https://example.edu/admissions/undergraduate") > 0
    assert score_url("https://example.edu/news/alumni-admissions-fair") < 0


def test_is_pdf_url():
    assert is_pdf_url("https://example.edu/prospectus.pdf")
    assert not is_pdf_url("https://example.edu/prospectus.html")


def test_low_value_source_urls_are_not_followed_even_on_admissions_domain():
    policy = DomainPolicy("https://admissions.example.edu/")

    assert is_low_value_source_url("https://admissions.example.edu/core/assets/base.css?t=x")
    assert is_low_value_source_url("https://admissions.example.edu/sites/default/files/favicon.ico")
    assert is_low_value_source_url("https://admissions.example.edu/files/GDPR%20Privacy%20Notice%20Applicants.pdf")
    assert not is_low_value_source_url("https://admissions.example.edu/files/undergraduate-admissions-prospectus.pdf")
    assert score_url("https://admissions.example.edu/core/assets/base.css?t=x") < 0
    assert score_url("https://admissions.example.edu/files/GDPR%20Privacy%20Notice%20Applicants.pdf") < 0
    assert not should_follow_url("https://admissions.example.edu/core/assets/base.css?t=x", policy)
    assert not should_follow_url("https://admissions.example.edu/files/GDPR%20Privacy%20Notice%20Applicants.pdf", policy)
    assert should_follow_url("https://admissions.example.edu/files/undergraduate-admissions-prospectus.pdf", policy)


def test_low_value_document_filter_blocks_privacy_cookie_and_terms_pdfs():
    policy = DomainPolicy("https://admissions.example.edu/")
    urls = [
        "https://admissions.example.edu/files/privacy-notice-applicants.pdf",
        "https://admissions.example.edu/files/GDPR%20Privacy%20Notice%20Applicants.pdf",
        "https://admissions.example.edu/files/cookie-policy.pdf",
        "https://admissions.example.edu/files/terms-of-use.pdf",
        "https://admissions.example.edu/files/Personal%20Information%20Collection%20Statement.pdf",
    ]

    for url in urls:
        assert is_low_value_source_url(url)
        assert score_url(url) < 0
        assert not should_follow_url(url, policy)


def test_low_value_document_filter_keeps_admissions_pdf_counterexamples():
    policy = DomainPolicy("https://admissions.example.edu/")
    urls = [
        "https://admissions.example.edu/files/2026-undergraduate-admissions-prospectus.pdf",
        "https://admissions.example.edu/files/international-entry-requirements.pdf",
        "https://admissions.example.edu/files/undergraduate-tuition-fees.pdf",
        "https://admissions.example.edu/files/programme-requirements.pdf",
    ]

    for url in urls:
        assert not is_low_value_source_url(url)
        assert should_follow_url(url, policy)


def test_blocked_or_challenge_detector_recognizes_incapsula_fixture():
    text = (SAVED / "nus/incapsula_challenge.html").read_text(encoding="utf-8")

    assert looks_like_blocked_or_challenge_source(
        "https://www.nus.edu.sg/oam/undergraduate-programmes",
        "Request unsuccessful",
        text,
    )


def test_blocked_or_challenge_detector_recognizes_common_block_pages():
    assert looks_like_blocked_or_challenge_source(
        "https://admissions.example.edu/apply",
        "Access Denied",
        "Access Denied. Please enable JavaScript and complete the captcha.",
    )
    assert looks_like_blocked_or_challenge_source(
        "https://admissions.example.edu/_Incapsula_Resource?SWUDNSAI=1",
        None,
        "",
    )


def test_blocked_or_challenge_detector_keeps_regular_admissions_pages():
    text = (
        "Undergraduate Admissions. Applications open on 1 October 2026. "
        "Students should review programme requirements, tuition fees, scholarships, and contact details."
    )

    assert not looks_like_blocked_or_challenge_source(
        "https://admissions.example.edu/undergraduate",
        "Undergraduate Admissions",
        text,
    )


def test_source_plan_candidate_url_validation_accepts_official_https_subdomains():
    policy = DomainPolicy("https://www.nus.edu.sg/oam/undergraduate-programmes", allowed_domains={"nus.edu.sg"})

    assert validate_source_plan_candidate_url("https://www.nus.edu.sg/nusbulletin/ay202526/programmes/", policy) == (True, "accepted")
    assert validate_source_plan_candidate_url("https://chs.nus.edu.sg/programmes/", policy) == (True, "accepted")
    assert validate_source_plan_candidate_url("https://dentistry.nus.edu.sg/education/undergraduate/", policy) == (True, "accepted")


def test_source_plan_candidate_url_validation_rejects_unsafe_or_unofficial_urls():
    policy = DomainPolicy("https://www.nus.edu.sg/oam/undergraduate-programmes", allowed_domains={"nus.edu.sg"})

    assert validate_source_plan_candidate_url("http://www.nus.edu.sg/admissions", policy) == (False, "non_https")
    assert validate_source_plan_candidate_url("https://example.com/nus/admissions", policy) == (False, "outside_allowed_domain")
    assert validate_source_plan_candidate_url("https://facebook.com/nusadmissions", policy) == (False, "outside_allowed_domain")
    assert validate_source_plan_candidate_url("https://www.nus.edu.sg/redirect?target=https://example.com", policy) == (False, "tracking_or_redirect_url")
    assert validate_source_plan_candidate_url("https://www.nus.edu.sg/files/privacy-notice.pdf", policy) == (False, "low_value_source_url")
