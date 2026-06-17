import pytest

from university_admissions_crawler.crawler.relevance import (
    BM25LikeRelevanceStrategy,
    KEYWORD_PLAN_OUTPUT_SCHEMA,
    RuleBasedRelevanceStrategy,
    build_relevance_strategy,
    keyword_plan_from_payload,
    keyword_plan_from_query,
)
from university_admissions_crawler.extractor.llm_provider import (
    CLASSIFICATION_ASSIST_OUTPUT_SCHEMA,
    MockClassificationAssistProvider,
    MockKeywordPlanProvider,
    classification_assist_from_payload,
    generate_classification_assist_diagnostic,
    generate_keyword_plan_with_fallback,
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


def test_keyword_plan_from_payload_validates_negative_keywords_and_schema_shape():
    plan = keyword_plan_from_payload(
        {
            "query": "undergraduate admission plan",
            "positive_keywords": ["admission", "fees"],
            "negative_keywords": ["alumni", "postgraduate"],
            "url_hints": ["/admissions"],
            "source": "llm",
            "warnings": ["low_confidence"],
        }
    )

    assert KEYWORD_PLAN_OUTPUT_SCHEMA["required"] == ["query", "positive_keywords", "negative_keywords", "url_hints", "source", "warnings"]
    assert plan.negative_keywords == ("alumni", "postgraduate")
    assert plan.to_dict()["source"] == "llm"


def test_keyword_plan_from_payload_rejects_extra_fields_and_long_query():
    with pytest.raises(ValueError, match="Unsupported keyword plan fields"):
        keyword_plan_from_payload({"query": "x", "positive_keywords": [], "negative_keywords": [], "url_hints": [], "source": "llm", "warnings": [], "extra": True})

    with pytest.raises(ValueError, match="missing required fields"):
        keyword_plan_from_payload({"query": "x", "positive_keywords": []})

    with pytest.raises(ValueError, match="exceeds"):
        keyword_plan_from_payload({"query": "x" * 501, "positive_keywords": [], "negative_keywords": [], "url_hints": [], "source": "llm", "warnings": []})


def test_build_relevance_strategy_preserves_default_and_requires_keyword_plan_for_bm25():
    keyword_plan, strategy = build_relevance_strategy()
    assert keyword_plan is None
    assert isinstance(strategy, RuleBasedRelevanceStrategy)

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


def test_mock_keyword_plan_provider_validates_payload_and_records_diagnostics():
    result = generate_keyword_plan_with_fallback(
        "fees tuition",
        MockKeywordPlanProvider(
            {
                "query": "fees tuition",
                "positive_keywords": ["fees", "tuition"],
                "negative_keywords": [],
                "url_hints": ["/fees"],
                "source": "llm",
                "warnings": [],
            }
        ),
    )

    assert result.keyword_plan.source == "llm"
    assert result.keyword_plan.positive_keywords == ("fees", "tuition")
    assert result.diagnostics["provider"] == "mock"
    assert result.diagnostics["fallback"] is False


def test_keyword_plan_provider_falls_back_to_user_query_on_invalid_payload():
    result = generate_keyword_plan_with_fallback("fees tuition", MockKeywordPlanProvider({"query": "fees tuition"}))

    assert result.keyword_plan.source == "user"
    assert result.diagnostics["fallback"] is True
    assert "llm_keyword_plan_fallback" in result.keyword_plan.warnings


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
