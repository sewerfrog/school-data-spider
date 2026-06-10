from university_admissions_crawler.config import CrawlConfig, smoke_config
from university_admissions_crawler.crawler import fetcher
from university_admissions_crawler.crawler.json_content import (
    _dedupe_preserve_order,
    _extract_json_links,
    _json_to_text,
    dedupe_preserve_order,
    extract_json_links,
    json_to_text,
)
from university_admissions_crawler.crawler.source_types import (
    content_type_for_source_type,
    looks_like_pdf_url,
    source_type_for_fixture_path,
    source_type_for_url_or_content,
)
from university_admissions_crawler.crawler.types import FetchResult, Fetcher
from university_admissions_crawler.crawler.sitemap import parse_sitemap_urls
from university_admissions_crawler.evidence.provenance import source_from_text
from university_admissions_crawler.evidence.store import source_hashes
from university_admissions_crawler.extractor.html_extractor import _looks_like_false_english_requirement
from university_admissions_crawler.extractor.schema import AdmissionsData, Institution, RunMetadata, SourceType
from university_admissions_crawler.pipeline.merge import _merge_data, merge_data


def test_merge_private_alias_remains_compatible():
    assert _merge_data is merge_data


def test_fetcher_type_and_source_type_compatibility_aliases_remain():
    assert fetcher.FetchResult is FetchResult
    assert fetcher.Fetcher is Fetcher
    assert fetcher._source_type_for_url_or_content is source_type_for_url_or_content
    assert fetcher._source_type_for_fixture_path is source_type_for_fixture_path
    assert fetcher._content_type_for_source_type is content_type_for_source_type
    assert fetcher._looks_like_pdf_url is looks_like_pdf_url
    assert source_type_for_url_or_content("https://example.edu/file.pdf", "application/octet-stream") == SourceType.PDF
    assert content_type_for_source_type(SourceType.JSON) == "application/json"


def test_json_content_private_aliases_remain_compatible():
    assert _json_to_text is json_to_text
    assert _extract_json_links is extract_json_links
    assert _dedupe_preserve_order is dedupe_preserve_order
    assert _json_to_text('{"b": 2, "a": 1}') == json_to_text('{"b": 2, "a": 1}')
    assert _extract_json_links('{"url": "/admissions.html"}', "https://example.edu/base/") == ["https://example.edu/admissions.html"]
    assert _dedupe_preserve_order(["a", "b", "a"]) == ["a", "b"]


def test_smoke_config_is_conservative_crawl_config():
    config = smoke_config()
    assert isinstance(config, CrawlConfig)
    assert config.max_depth == 2
    assert config.max_pages == 20
    assert config.max_pdf_pages == 5
    assert config.enable_live_network is False
    assert config.enable_llm is False


def test_parse_sitemap_urls_canonicalizes_and_dedupes():
    xml = """
    <urlset>
      <url><loc>/admissions/?utm_source=x</loc></url>
      <url><loc>https://example.edu/admissions/</loc></url>
      <url><loc>https://example.edu/programmes/?b=2&amp;a=1</loc></url>
    </urlset>
    """
    assert parse_sitemap_urls(xml, "https://example.edu/sitemap.xml") == [
        "https://example.edu/admissions",
        "https://example.edu/programmes?a=1&b=2",
    ]


def test_source_hashes_accepts_model_and_serialized_result():
    source = source_from_text(source_url="https://example.edu/admissions", text="Admissions")
    data = AdmissionsData(institution=Institution(homepage_url="https://example.edu"), run=RunMetadata(input_url="https://example.edu"), sources=[source])
    expected = {"https://example.edu/admissions": source.content_hash}
    assert source_hashes(data) == expected
    assert source_hashes(data.to_dict()) == expected


def test_false_english_requirement_filter_still_rejects_programme_lists():
    assert _looks_like_false_english_requirement(
        "Programme Entrance Requirements Bachelor of Science Bachelor of Business programme programme programme programme programme"
    )
