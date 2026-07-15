from university_admissions_crawler.crawler.public_suffix import public_suffix, public_suffix_list_metadata, registrable_domain


def test_public_suffix_list_resource_is_available():
    metadata = public_suffix_list_metadata()

    assert metadata["available"] is True
    assert metadata["version"]
    assert metadata["commit"]
    assert metadata["exact_rule_count"] > 1000


def test_registrable_domain_uses_icann_public_suffix_rules():
    assert public_suffix("www.example.co.uk") == "co.uk"
    assert registrable_domain("www.example.co.uk") == "example.co.uk"
    assert registrable_domain("apply.example.edu.au") == "example.edu.au"
    assert registrable_domain("other.co.uk") == "other.co.uk"


def test_registrable_domain_uses_private_public_suffix_rules():
    assert public_suffix("foo.github.io") == "github.io"
    assert registrable_domain("foo.github.io") == "foo.github.io"
    assert registrable_domain("bar.foo.github.io") == "foo.github.io"


def test_public_suffix_wildcards_and_exceptions():
    assert public_suffix("www.ck") == "ck"
    assert registrable_domain("www.ck") == "www.ck"
    assert public_suffix("a.test.ck") == "test.ck"
    assert registrable_domain("a.test.ck") == "a.test.ck"
    assert registrable_domain("test.ck") is None


def test_registrable_domain_fails_closed_for_ips_and_public_suffixes():
    assert registrable_domain("127.0.0.1") is None
    assert registrable_domain("co.uk") is None
