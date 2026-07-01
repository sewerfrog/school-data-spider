from pathlib import Path

from university_admissions_crawler.extractor.llm_provider import (
    CLASSIFICATION_ASSIST_OUTPUT_SCHEMA,
    LLMStructuredExtractionSource,
    PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA,
    SOURCE_PLAN_OUTPUT_SCHEMA,
    STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
    STRUCTURED_EXTRACTION_OUTPUT_SCHEMA,
    OpenAIProvider,
)


ROOT = Path(__file__).resolve().parents[1]


def test_env_example_documents_openai_variables_without_real_key():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY=" in text
    assert "OPENAI_MODEL=gpt-4.1-mini" in text
    assert "sk-" not in text


def test_openai_source_plan_provider_uses_structured_output_schema():
    calls = []

    def transport(payload):
        calls.append(payload)
        return {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"candidate_urls":[{"url":"https://example.edu/admissions","reason":"Official admissions page.","expected_category":"undergraduate_admissions"}],"candidate_path_patterns":["/admissions"],"candidate_queries":["site:example.edu undergraduate admissions"],"warnings":[]}',
                        }
                    ]
                }
            ]
        }

    provider = OpenAIProvider(api_key="test-key", model="test-model", transport=transport)
    payload = provider.generate_source_plan_payload({"input_url": "https://example.edu/"}, SOURCE_PLAN_OUTPUT_SCHEMA)

    assert payload["candidate_urls"][0]["url"] == "https://example.edu/admissions"
    request = calls[0]
    assert request["model"] == "test-model"
    assert request["store"] is False
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["schema"] == SOURCE_PLAN_OUTPUT_SCHEMA
    assert "Do not invent admissions facts" in request["instructions"]


def test_openai_classification_and_programme_hint_payloads_are_schema_bounded():
    responses = [
        {
            "output_text": '{"category":"fees","reason":"The text mentions tuition fees.","confidence":"low","signals":["fees"]}',
        },
        {
            "output_text": '{"category":"special_programme","mode":"full-time","reason":"The row says scholars programme full-time.","confidence":"low","signals":["special_programme"]}',
        },
    ]
    calls = []

    def transport(payload):
        calls.append(payload)
        return responses.pop(0)

    provider = OpenAIProvider(api_key="test-key", transport=transport)
    classification = provider.classify_page_payload(
        "https://example.edu/fees",
        "Fees",
        "Undergraduate tuition fees.",
        CLASSIFICATION_ASSIST_OUTPUT_SCHEMA,
    )
    programme_hint = provider.classify_programme_candidate_payload(
        "Scholars Programme full-time",
        "https://example.edu/programmes",
        "Undergraduate Programmes",
        PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA,
    )

    assert classification["category"] == "fees"
    assert programme_hint["category"] == "special_programme"
    assert calls[0]["text"]["format"]["schema"] == CLASSIFICATION_ASSIST_OUTPUT_SCHEMA
    assert calls[1]["text"]["format"]["schema"] == PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA
    assert "Do not extract admissions facts" in calls[0]["instructions"]
    assert "Do not add programme names" in calls[1]["instructions"]


def test_openai_structured_extraction_provider_uses_captured_source_boundary():
    calls = []

    def transport(payload):
        calls.append(payload)
        return {
            "output_text": '{"candidate_facts":[{"claim_path":"admissions.fees","value":"SGD 20,000","evidence_snippet":"Undergraduate tuition fee is SGD 20,000 per year.","source_url":"https://example.edu/admissions/fees","confidence":0.76}],"warnings":[]}',
        }

    provider = OpenAIProvider(api_key="test-key", model="test-model", transport=transport)
    source = LLMStructuredExtractionSource(
        source_url="https://example.edu/admissions/fees",
        title="Undergraduate fees",
        source_type="html",
        text="Undergraduate tuition fee is SGD 20,000 per year.",
    )

    payload = provider.extract_structured_candidate_payload(
        source,
        STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
        STRUCTURED_EXTRACTION_OUTPUT_SCHEMA,
    )

    assert payload["candidate_facts"][0]["claim_path"] == "admissions.fees"
    request = calls[0]
    assert request["model"] == "test-model"
    assert request["store"] is False
    assert request["text"]["format"]["name"] == "structured_extraction"
    assert request["text"]["format"]["schema"] == STRUCTURED_EXTRACTION_OUTPUT_SCHEMA
    assert "contiguous verbatim substring" in request["instructions"]
    assert "Return candidate facts, not final facts" in request["instructions"]
    assert "Every source_url must equal the supplied source URL" in request["instructions"]
    assert "test-key" not in str(request)
    assert '"allowed_claim_paths"' in request["input"]
    assert "admissions.fees" in request["input"]
