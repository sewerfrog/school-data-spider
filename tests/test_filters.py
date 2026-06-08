from university_admissions_crawler.crawler.filters import DomainPolicy, canonicalize_url, is_pdf_url, score_url


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
