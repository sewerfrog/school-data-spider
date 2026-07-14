from pathlib import Path

from university_admissions_crawler.evidence.validator import validate_llm_candidate_fact
from university_admissions_crawler.extractor.llm_provider import (
    CLASSIFICATION_ASSIST_OUTPUT_SCHEMA,
    ChatCompletionsProvider,
    LLMStructuredExtractionSource,
    PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA,
    SOURCE_PLAN_OUTPUT_SCHEMA,
    STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
    STRUCTURED_EXTRACTION_OUTPUT_SCHEMA,
    OpenAIProvider,
    structured_extraction_result_from_payload,
)
from university_admissions_crawler.pipeline.llm_runtime import resolve_llm_provider_name


ROOT = Path(__file__).resolve().parents[1]


def test_env_example_documents_openai_variables_without_real_key():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY=" in text
    assert "OPENAI_MODEL=gpt-4.1-mini" in text
    assert "OPENAI_BASE_URL=" in text
    assert "OPENAI_CHAT_COMPLETIONS_PATH=/v1/chat/completions" in text
    assert "OPENAI_CHAT_RESPONSE_FORMAT=json_schema" in text
    assert "OPENAI_REASONING_EFFORT=" in text
    assert "OPENAI_USER_AGENT=" in text
    assert "UAC_LLM_PROVIDER=" in text
    assert "sk-" not in text


def test_openai_chat_provider_can_be_selected_from_env(monkeypatch):
    monkeypatch.setenv("UAC_LLM_PROVIDER", "openai-chat")

    assert resolve_llm_provider_name(None) == "openai-chat"


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


def test_chat_completions_provider_reads_env_and_uses_chat_request_shape(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "chat-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.5")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://relay.example.test")
    monkeypatch.setenv("OPENAI_CHAT_COMPLETIONS_PATH", "/v1/chat/completions")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "medium")
    monkeypatch.setenv("OPENAI_USER_AGENT", "curl/8.7.1")
    calls = []

    def transport(payload):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"candidate_urls":[{"url":"https://example.edu/admissions","reason":"Official admissions page.","expected_category":"undergraduate_admissions"}],"candidate_path_patterns":["/admissions"],"candidate_queries":["site:example.edu undergraduate admissions"],"warnings":[]}',
                    }
                }
            ]
        }

    provider = ChatCompletionsProvider(transport=transport)
    payload = provider.generate_source_plan_payload({"input_url": "https://example.edu/"}, SOURCE_PLAN_OUTPUT_SCHEMA)

    assert provider.url == "https://relay.example.test/v1/chat/completions"
    assert provider.model == "gpt-5.5"
    assert provider.user_agent == "curl/8.7.1"
    assert payload["candidate_urls"][0]["url"] == "https://example.edu/admissions"
    request = calls[0]
    assert request["model"] == "gpt-5.5"
    assert request["reasoning_effort"] == "medium"
    assert request["messages"][0]["role"] == "system"
    assert "Do not invent admissions facts" in request["messages"][0]["content"]
    assert request["messages"][1]["role"] == "user"
    assert '"input_url": "https://example.edu/"' in request["messages"][1]["content"]
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["name"] == "source_plan"
    assert request["response_format"]["json_schema"]["schema"] == SOURCE_PLAN_OUTPUT_SCHEMA
    assert "chat-test-key" not in str(request)


def test_chat_completions_provider_request_headers_are_configurable(monkeypatch):
    monkeypatch.setenv("OPENAI_USER_AGENT", "curl/8.7.1")

    provider = ChatCompletionsProvider(api_key="chat-test-key")
    headers = provider._request_headers()

    assert headers["Accept"] == "application/json"
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == "curl/8.7.1"
    assert headers["Authorization"] == "Bearer chat-test-key"


def test_chat_completions_provider_can_omit_response_format_for_relay_compatibility(monkeypatch):
    monkeypatch.setenv("OPENAI_CHAT_RESPONSE_FORMAT", "none")
    calls = []

    def transport(payload):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"category":"fees","reason":"The text mentions tuition fees.","confidence":"low","signals":["fees"]}',
                    }
                }
            ]
        }

    provider = ChatCompletionsProvider(api_key="chat-test-key", model="chat-model", transport=transport)
    classification = provider.classify_page_payload(
        "https://example.edu/fees",
        "Fees",
        "Undergraduate tuition fees.",
        CLASSIFICATION_ASSIST_OUTPUT_SCHEMA,
    )

    assert provider.chat_response_format == "none"
    assert classification["category"] == "fees"
    assert "response_format" not in calls[0]
    assert "Return only strict JSON" in calls[0]["messages"][0]["content"]


def test_chat_completions_provider_can_use_json_object_response_format():
    calls = []

    def transport(payload):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"candidate_urls":[{"url":"https://example.edu/admissions","reason":"Official admissions page.","expected_category":"undergraduate_admissions"}],"candidate_path_patterns":["/admissions"],"candidate_queries":["site:example.edu undergraduate admissions"],"warnings":[]}',
                    }
                }
            ]
        }

    provider = ChatCompletionsProvider(api_key="chat-test-key", model="chat-model", chat_response_format="json_object", transport=transport)
    payload = provider.generate_source_plan_payload({"input_url": "https://example.edu/"}, SOURCE_PLAN_OUTPUT_SCHEMA)

    assert provider.chat_response_format == "json_object"
    assert payload["candidate_urls"][0]["url"] == "https://example.edu/admissions"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "json_schema" not in str(calls[0]["response_format"])


def test_chat_completions_provider_omits_reasoning_when_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    calls = []

    def transport(payload):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"category":"fees","reason":"The text mentions tuition fees.","confidence":"low","signals":["fees"]}',
                    }
                }
            ]
        }

    provider = ChatCompletionsProvider(api_key="chat-test-key", model="chat-model", transport=transport)
    classification = provider.classify_page_payload(
        "https://example.edu/fees",
        "Fees",
        "Undergraduate tuition fees.",
        CLASSIFICATION_ASSIST_OUTPUT_SCHEMA,
    )

    assert classification["category"] == "fees"
    assert "reasoning_effort" not in calls[0]


def test_chat_completions_provider_parses_classification_and_programme_hint_json():
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": '{"category":"fees","reason":"The text mentions tuition fees.","confidence":"low","signals":["fees"]}',
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": '{"category":"special_programme","mode":"full-time","reason":"The row says scholars programme full-time.","confidence":"low","signals":["special_programme"]}',
                    }
                }
            ]
        },
    ]
    calls = []

    def transport(payload):
        calls.append(payload)
        return responses.pop(0)

    provider = ChatCompletionsProvider(api_key="chat-test-key", model="chat-model", transport=transport)
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
    assert calls[0]["response_format"]["json_schema"]["schema"] == CLASSIFICATION_ASSIST_OUTPUT_SCHEMA
    assert calls[1]["response_format"]["json_schema"]["schema"] == PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA


def test_chat_completions_structured_extraction_stays_inside_captured_source_boundary():
    calls = []

    def transport(payload):
        calls.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"candidate_facts":[{"claim_path":"admissions.fees","value":"SGD 20,000","evidence_snippet":"Undergraduate tuition fee is SGD 20,000 per year.","source_url":"https://evil.example/fees","confidence":0.76}],"warnings":[]}',
                    }
                }
            ]
        }

    provider = ChatCompletionsProvider(api_key="chat-test-key", model="chat-model", transport=transport)
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
    result = structured_extraction_result_from_payload(payload)
    validation = validate_llm_candidate_fact(
        result.candidate_facts[0],
        captured_sources={source.source_url: source.text},
    )

    assert validation.accepted is False
    assert validation.reject_reason == "source_not_captured"
    request = calls[0]
    assert request["response_format"]["json_schema"]["name"] == "structured_extraction"
    assert request["response_format"]["json_schema"]["schema"] == STRUCTURED_EXTRACTION_OUTPUT_SCHEMA
    assert "contiguous verbatim substring" in request["messages"][0]["content"]
    assert "Return candidate facts, not final facts" in request["messages"][0]["content"]
    assert "Every source_url must equal the supplied source URL" in request["messages"][0]["content"]
    assert '"allowed_claim_paths"' in request["messages"][1]["content"]
