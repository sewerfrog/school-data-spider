import pytest

from university_admissions_crawler.extractor.llm_provider import (
    LLMStructuredExtractionSource,
    MockStructuredExtractionProvider,
    STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
    STRUCTURED_EXTRACTION_OUTPUT_SCHEMA,
    structured_extraction_result_from_payload,
)


def test_structured_extraction_schema_requires_candidate_fact_evidence_fields():
    candidate_schema = STRUCTURED_EXTRACTION_OUTPUT_SCHEMA["properties"]["candidate_facts"]["items"]

    assert STRUCTURED_EXTRACTION_OUTPUT_SCHEMA["required"] == ["candidate_facts", "warnings"]
    assert candidate_schema["required"] == [
        "claim_path",
        "value",
        "evidence_snippet",
        "source_url",
        "confidence",
    ]
    assert candidate_schema["additionalProperties"] is False
    assert "admissions.fees" in STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS
    assert "programme_catalog[].name" in STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS


def test_mock_structured_extraction_provider_records_captured_source_boundary():
    provider = MockStructuredExtractionProvider(
        {
            "candidate_facts": [
                {
                    "claim_path": "admissions.fees",
                    "value": "Tuition fees are published annually.",
                    "evidence_snippet": "Tuition fees are published annually.",
                    "source_url": "https://example.edu/admissions/fees",
                    "confidence": 0.72,
                    "reason": "Captured fee source mentions tuition fees.",
                }
            ],
            "warnings": [],
        }
    )
    source = LLMStructuredExtractionSource(
        source_url="https://example.edu/admissions/fees",
        title="Undergraduate fees",
        text="Tuition fees are published annually.",
    )

    payload = provider.extract_structured_candidate_payload(
        source,
        STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
        STRUCTURED_EXTRACTION_OUTPUT_SCHEMA,
    )
    result = structured_extraction_result_from_payload(payload)

    assert provider.requests == [
        {
            "source_url": "https://example.edu/admissions/fees",
            "title": "Undergraduate fees",
            "text": "Tuition fees are published annually.",
            "source_type": "html",
            "allowed_claim_paths": STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS,
            "schema": STRUCTURED_EXTRACTION_OUTPUT_SCHEMA,
        }
    ]
    assert len(result.candidate_facts) == 1
    assert result.candidate_facts[0].claim_path == "admissions.fees"
    assert result.candidate_facts[0].confidence == 0.72
    assert result.candidate_facts[0].to_dict()["source_url"] == "https://example.edu/admissions/fees"


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"candidate_facts": []}, "missing required fields: warnings"),
        ({"candidate_facts": [], "warnings": [], "facts": []}, "Unsupported structured extraction fields: facts"),
        (
            {
                "candidate_facts": [
                    {
                        "claim_path": "admissions.fees",
                        "value": "Tuition fees are published annually.",
                        "evidence_snippet": "Tuition fees are published annually.",
                        "source_url": "https://example.edu/admissions/fees",
                    }
                ],
                "warnings": [],
            },
            "missing required fields: confidence",
        ),
        (
            {
                "candidate_facts": [
                    {
                        "claim_path": "admissions.fees",
                        "value": "Tuition fees are published annually.",
                        "evidence_snippet": "Tuition fees are published annually.",
                        "source_url": "https://example.edu/admissions/fees",
                        "confidence": 1.2,
                    }
                ],
                "warnings": [],
            },
            "confidence must be between 0.0 and 1.0",
        ),
    ],
)
def test_structured_extraction_payload_parser_fails_closed(payload, error):
    with pytest.raises(ValueError, match=error):
        structured_extraction_result_from_payload(payload)
