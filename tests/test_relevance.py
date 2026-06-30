import pytest

from university_admissions_crawler.crawler.relevance import (
    AdmissionsProgrammeRelevanceStrategy,
    BM25LikeRelevanceStrategy,
    RuleBasedRelevanceStrategy,
    build_relevance_strategy,
    keyword_plan_from_query,
)
from university_admissions_crawler.extractor.llm_provider import (
    CLASSIFICATION_ASSIST_OUTPUT_SCHEMA,
    MockClassificationAssistProvider,
    classification_assist_from_payload,
    generate_classification_assist_diagnostic,
)
from university_admissions_crawler.extractor.schema import PageCategory


def test_keyword_plan_from_query_normalizes_tokens_and_url_hints():
    plan = keyword_plan_from_query(" Undergraduate,Admissions / IELTS fees fees ")

    assert plan.query == "Undergraduate,Admissions / IELTS fees fees"
    assert plan.positive_keywords == ("undergraduate", "admissions", "ielts", "fees")
    assert "/admissions" in plan.url_hints
    assert "/fees" in plan.url_hints
    assert plan.source == "user"
    assert plan.warnings == ()


def test_keyword_plan_debug_query_rejects_llm_source_and_long_query():
    with pytest.raises(ValueError, match="Unsupported keyword plan source"):
        keyword_plan_from_query("fees tuition", source="llm")
    with pytest.raises(ValueError, match="exceeds"):
        keyword_plan_from_query("x" * 501)


def test_build_relevance_strategy_uses_admissions_programme_profile_by_default():
    keyword_plan, strategy = build_relevance_strategy()
    assert keyword_plan is None
    assert isinstance(strategy, AdmissionsProgrammeRelevanceStrategy)
    assert strategy.name == "admissions_programme_profile"

    keyword_plan, explicit_rule_strategy = build_relevance_strategy(relevance_strategy="rule-based")
    assert keyword_plan is None
    assert isinstance(explicit_rule_strategy, RuleBasedRelevanceStrategy)

    with pytest.raises(ValueError, match="requires"):
        build_relevance_strategy(relevance_strategy="bm25-like")

    keyword_plan, strategy = build_relevance_strategy(relevance_strategy="bm25-like", keyword_query="fees tuition")
    assert keyword_plan is not None
    assert isinstance(strategy, BM25LikeRelevanceStrategy)


def test_build_relevance_strategy_rejects_non_string_config_values():
    with pytest.raises(ValueError, match="Relevance strategy must be a string"):
        build_relevance_strategy(relevance_strategy=42)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Keyword query must be a string"):
        build_relevance_strategy(keyword_query=["fees"])  # type: ignore[arg-type]


def test_admissions_programme_profile_prioritizes_template_sources_without_keyword_query():
    strategy = AdmissionsProgrammeRelevanceStrategy()
    programme_url = "https://example.edu/catalogue/undergraduate/majors"
    programme_text = "Undergraduate degree programmes, majors and minors."
    news_url = "https://example.edu/news/alumni-programmes"
    news_text = "Alumni news article about giving and staff updates."

    programme_score = strategy.score(programme_url, "Undergraduate Majors", programme_text)
    news_score = strategy.score(news_url, "Alumni Programmes News", news_text)
    diagnostics = strategy.diagnose(programme_url, "Undergraduate Majors", programme_text)

    assert programme_score > news_score
    assert programme_score > 0
    assert diagnostics.strategy == "admissions_programme_profile"
    assert "profile_programme_catalog_source" in diagnostics.signals
    assert "profile_positive:/catalogue" in diagnostics.signals


def test_classification_assist_payload_is_schema_bounded_and_diagnostic_only():
    payload = {
        "category": "fees",
        "reason": "The page mentions tuition and annual fee amounts.",
        "confidence": "low",
        "signals": ["tuition", "fees"],
    }
    assist = classification_assist_from_payload(payload)

    assert CLASSIFICATION_ASSIST_OUTPUT_SCHEMA["required"] == ["category", "reason", "confidence", "signals"]
    assert assist.category == PageCategory.FEES
    assert assist.to_dict()["category"] == "fees"

    diagnostics = generate_classification_assist_diagnostic(
        url="https://example.edu/ambiguous",
        title="Student information",
        text="Tuition information for undergraduate applicants.",
        rule_category=PageCategory.UNDERGRADUATE_ADMISSIONS,
        rule_score=1,
        provider=MockClassificationAssistProvider(payload),
    )
    assert diagnostics["fallback"] is False
    assert diagnostics["rule_category"] == "undergraduate_admissions"
    assert diagnostics["candidate"]["category"] == "fees"
    assert diagnostics["applied"] is False

    with pytest.raises(ValueError, match="Unsupported classification assist fields"):
        classification_assist_from_payload({**payload, "extra": True})
