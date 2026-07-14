"""Optional LLM provider interface with evidence-gated mock support."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from university_admissions_crawler.extractor.schema import EvidenceItem, PageCategory, WarningCode, WarningRecord


MAX_SOURCE_PLAN_URLS = 20
MAX_SOURCE_PLAN_QUERIES = 20
MAX_SOURCE_PLAN_REASON_LENGTH = 240
MAX_SOURCE_PLAN_QUERY_LENGTH = 160
MAX_SOURCE_PLAN_URL_LENGTH = 300
MAX_SOURCE_PLAN_CATEGORY_LENGTH = 80
MAX_SOURCE_PLAN_PATH_PATTERNS = 20
MAX_SOURCE_PLAN_PATH_PATTERN_LENGTH = 160
MAX_CLASSIFICATION_REASON_LENGTH = 300
MAX_CLASSIFICATION_SIGNAL_LENGTH = 80
MAX_CLASSIFICATION_SIGNALS = 20
MAX_PROGRAMME_HINT_REASON_LENGTH = 300
MAX_PROGRAMME_HINT_SIGNAL_LENGTH = 80
MAX_PROGRAMME_HINT_SIGNALS = 20
MAX_STRUCTURED_CANDIDATE_FACTS = 30
MAX_STRUCTURED_CLAIM_PATH_LENGTH = 160
MAX_STRUCTURED_VALUE_LENGTH = 2000
MAX_STRUCTURED_SNIPPET_LENGTH = 4000
MAX_STRUCTURED_SOURCE_URL_LENGTH = 300
MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH = 300
MAX_STRUCTURED_WARNINGS = 20
OPENAI_DEFAULT_MODEL = "gpt-4.1-mini"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com"
OPENAI_DEFAULT_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
OPENAI_DEFAULT_CHAT_RESPONSE_FORMAT = "json_schema"
OPENAI_DEFAULT_USER_AGENT = "school-data-spider/0.1"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_CHAT_JSON_CONTRACTS = {
    "source_plan": "Return only strict JSON with keys candidate_urls, candidate_path_patterns, candidate_queries, and warnings. candidate_urls items must use url, reason, and expected_category.",
    "classification_assist": "Return only strict JSON with keys category, reason, confidence, and signals.",
    "programme_catalog_hint": "Return only strict JSON with keys category, mode, reason, confidence, and signals.",
    "structured_extraction": "Return only strict JSON with keys candidate_facts and warnings. candidate_facts items must use claim_path, value, evidence_snippet, source_url, and confidence.",
}
PROGRAMME_CATALOG_CATEGORY_VALUES = ("degree_programme", "major", "minor", "special_programme", "dual_degree", "unknown")
PROGRAMME_CATALOG_MODE_VALUES = ("full-time", "part-time", "unknown")
STRUCTURED_EXTRACTION_ALLOWED_CLAIM_PATHS = (
    "admissions.application_period",
    "admissions.application_deadline",
    "admissions.application_entry",
    "admissions.requirements.academic",
    "admissions.requirements.english",
    "admissions.required_documents",
    "admissions.fees",
    "admissions.scholarships",
    "admissions.contact",
    "programme_catalog[].name",
    "programme_catalog[].degree",
    "programme_catalog[].faculty_or_school",
    "programme_catalog[].duration",
    "programme_catalog[].entry_requirements",
    "programme_catalog[].source_url",
)
SOURCE_PLAN_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["candidate_urls", "candidate_path_patterns", "candidate_queries", "warnings"],
    "properties": {
        "candidate_urls": {
            "type": "array",
            "maxItems": MAX_SOURCE_PLAN_URLS,
            "items": {
                "type": "object",
                "required": ["url", "reason", "expected_category"],
                "properties": {
                    "url": {"type": "string", "maxLength": MAX_SOURCE_PLAN_URL_LENGTH},
                    "reason": {"type": "string", "maxLength": MAX_SOURCE_PLAN_REASON_LENGTH},
                    "expected_category": {"type": "string", "maxLength": MAX_SOURCE_PLAN_CATEGORY_LENGTH},
                },
                "additionalProperties": False,
            },
        },
        "candidate_path_patterns": {
            "type": "array",
            "items": {"type": "string", "maxLength": MAX_SOURCE_PLAN_PATH_PATTERN_LENGTH},
            "maxItems": MAX_SOURCE_PLAN_PATH_PATTERNS,
        },
        "candidate_queries": {"type": "array", "items": {"type": "string", "maxLength": MAX_SOURCE_PLAN_QUERY_LENGTH}, "maxItems": MAX_SOURCE_PLAN_QUERIES},
        "warnings": {"type": "array", "items": {"type": "string", "maxLength": MAX_SOURCE_PLAN_REASON_LENGTH}, "maxItems": MAX_SOURCE_PLAN_QUERIES},
    },
    "additionalProperties": False,
}
CLASSIFICATION_ASSIST_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["category", "reason", "confidence", "signals"],
    "properties": {
        "category": {"type": "string", "enum": [str(item) for item in PageCategory]},
        "reason": {"type": "string", "maxLength": MAX_CLASSIFICATION_REASON_LENGTH},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "signals": {"type": "array", "items": {"type": "string", "maxLength": MAX_CLASSIFICATION_SIGNAL_LENGTH}, "maxItems": MAX_CLASSIFICATION_SIGNALS},
    },
    "additionalProperties": False,
}
PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["category", "mode", "reason", "confidence", "signals"],
    "properties": {
        "category": {"type": "string", "enum": list(PROGRAMME_CATALOG_CATEGORY_VALUES)},
        "mode": {"type": "string", "enum": list(PROGRAMME_CATALOG_MODE_VALUES)},
        "reason": {"type": "string", "maxLength": MAX_PROGRAMME_HINT_REASON_LENGTH},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "signals": {"type": "array", "items": {"type": "string", "maxLength": MAX_PROGRAMME_HINT_SIGNAL_LENGTH}, "maxItems": MAX_PROGRAMME_HINT_SIGNALS},
    },
    "additionalProperties": False,
}
STRUCTURED_EXTRACTION_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["candidate_facts", "warnings"],
    "properties": {
        "candidate_facts": {
            "type": "array",
            "maxItems": MAX_STRUCTURED_CANDIDATE_FACTS,
            "items": {
                "type": "object",
                "required": ["claim_path", "value", "evidence_snippet", "source_url", "confidence"],
                "properties": {
                    "claim_path": {"type": "string", "maxLength": MAX_STRUCTURED_CLAIM_PATH_LENGTH},
                    "value": {"type": "string", "maxLength": MAX_STRUCTURED_VALUE_LENGTH},
                    "evidence_snippet": {"type": "string", "maxLength": MAX_STRUCTURED_SNIPPET_LENGTH},
                    "source_url": {"type": "string", "maxLength": MAX_STRUCTURED_SOURCE_URL_LENGTH},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "reason": {"type": "string", "maxLength": MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH},
                    "source_title": {"type": "string", "maxLength": MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH},
                    "candidate_type": {"type": "string", "maxLength": MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH},
                    "normalization_hint": {"type": "string", "maxLength": MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH},
                },
                "additionalProperties": False,
            },
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string", "maxLength": MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH},
            "maxItems": MAX_STRUCTURED_WARNINGS,
        },
    },
    "additionalProperties": False,
}


@dataclass(slots=True)
class LLMCandidateClaim:
    claim_path: str
    value: str
    evidence_snippet: str
    confidence: str = "low"
    source_url: str | None = None


@dataclass(slots=True)
class LLMValidationResult:
    accepted: list[LLMCandidateClaim] = field(default_factory=list)
    warnings: list[WarningRecord] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SourcePlanCandidateURL:
    url: str
    reason: str
    expected_category: str

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "reason": self.reason,
            "expected_category": self.expected_category,
        }


@dataclass(frozen=True, slots=True)
class SourcePlanResult:
    candidate_urls: tuple[SourcePlanCandidateURL, ...] = ()
    candidate_path_patterns: tuple[str, ...] = ()
    candidate_queries: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_urls": [item.to_dict() for item in self.candidate_urls],
            "candidate_path_patterns": list(self.candidate_path_patterns),
            "candidate_queries": list(self.candidate_queries),
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class SourcePlanGenerationResult:
    source_plan: SourcePlanResult
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClassificationAssistResult:
    category: PageCategory
    reason: str
    confidence: str = "low"
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "category": str(self.category),
            "reason": self.reason,
            "confidence": self.confidence,
            "signals": list(self.signals),
        }


@dataclass(frozen=True, slots=True)
class ProgrammeCatalogClassificationHint:
    category: str
    mode: str = "unknown"
    reason: str = ""
    confidence: str = "low"
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "mode": self.mode,
            "reason": self.reason,
            "confidence": self.confidence,
            "signals": list(self.signals),
        }


@dataclass(slots=True)
class ProgrammeCatalogClassificationHintResult:
    hint: ProgrammeCatalogClassificationHint | None = None
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMStructuredExtractionSource:
    source_url: str
    text: str
    title: str | None = None
    source_type: str = "html"


@dataclass(frozen=True, slots=True)
class LLMStructuredCandidateFact:
    claim_path: str
    value: str
    evidence_snippet: str
    source_url: str
    confidence: float
    reason: str | None = None
    source_title: str | None = None
    candidate_type: str | None = None
    normalization_hint: str | None = None

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "claim_path": self.claim_path,
            "value": self.value,
            "evidence_snippet": self.evidence_snippet,
            "source_url": self.source_url,
            "confidence": self.confidence,
        }
        if self.reason is not None:
            out["reason"] = self.reason
        if self.source_title is not None:
            out["source_title"] = self.source_title
        if self.candidate_type is not None:
            out["candidate_type"] = self.candidate_type
        if self.normalization_hint is not None:
            out["normalization_hint"] = self.normalization_hint
        return out


@dataclass(frozen=True, slots=True)
class LLMStructuredExtractionResult:
    candidate_facts: tuple[LLMStructuredCandidateFact, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_facts": [item.to_dict() for item in self.candidate_facts],
            "warnings": list(self.warnings),
        }


class LLMProvider(Protocol):
    def extract_candidates(self, source_text: str, schema_hint: str) -> list[LLMCandidateClaim]:
        ...


class ClassificationAssistProvider(Protocol):
    name: str

    def classify_page_payload(self, url: str, title: str | None, text: str, schema: dict[str, object]) -> dict[str, object]:
        ...


class SourcePlanProvider(Protocol):
    name: str

    def generate_source_plan_payload(self, context: dict[str, object], schema: dict[str, object]) -> dict[str, object]:
        ...


class ProgrammeCatalogAssistProvider(Protocol):
    name: str

    def classify_programme_candidate_payload(self, candidate_text: str, source_url: str, title: str | None, schema: dict[str, object]) -> dict[str, object]:
        ...


class StructuredExtractionProvider(Protocol):
    name: str

    def extract_structured_candidate_payload(
        self,
        source: LLMStructuredExtractionSource,
        allowed_claim_paths: tuple[str, ...],
        schema: dict[str, object],
    ) -> dict[str, object]:
        ...


class MockLLMProvider:
    """Deterministic provider for tests; never calls a hosted API."""

    def __init__(self, candidates: list[LLMCandidateClaim]) -> None:
        self._candidates = list(candidates)

    def extract_candidates(self, source_text: str, schema_hint: str) -> list[LLMCandidateClaim]:
        return list(self._candidates)


class MockClassificationAssistProvider:
    """Deterministic page-classification assist provider for diagnostics tests."""

    name = "mock"

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = dict(payload) if payload is not None else None
        self._error = error

    def classify_page_payload(self, url: str, title: str | None, text: str, schema: dict[str, object]) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        if self._payload is not None:
            return dict(self._payload)
        lowered = f"{url} {title or ''} {text[:1200]}".lower()
        if "tuition" in lowered or "fee" in lowered:
            category = PageCategory.FEES
            signals = ["tuition_or_fee"]
        elif "deadline" in lowered or "apply by" in lowered:
            category = PageCategory.APPLICATION_DEADLINES
            signals = ["deadline"]
        elif "ielts" in lowered or "toefl" in lowered or "english" in lowered:
            category = PageCategory.INTERNATIONAL_REQUIREMENTS
            signals = ["english_requirement"]
        elif "scholarship" in lowered:
            category = PageCategory.SCHOLARSHIPS
            signals = ["scholarship"]
        elif "undergraduate" in lowered or "admission" in lowered:
            category = PageCategory.UNDERGRADUATE_ADMISSIONS
            signals = ["undergraduate_admissions"]
        else:
            category = PageCategory.IRRELEVANT
            signals = []
        return {
            "category": str(category),
            "reason": "Mock classification assist based on bounded keyword hints.",
            "confidence": "low",
            "signals": signals,
        }


class MockSourcePlanProvider:
    """Deterministic source-plan provider for diagnostics-only tests."""

    name = "mock"

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = dict(payload) if payload is not None else None
        self._error = error

    def generate_source_plan_payload(self, context: dict[str, object], schema: dict[str, object]) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        if self._payload is not None:
            return dict(self._payload)
        seed_url = str(context.get("input_url") or "").rstrip("/")
        host_hint = seed_url.split("/")[2] if "://" in seed_url else "example.edu"
        return {
            "candidate_urls": [
                {
                    "url": f"https://{host_hint}/admissions",
                    "reason": "Mock official admissions landing page candidate.",
                    "expected_category": "undergraduate_admissions",
                },
                {
                    "url": f"https://{host_hint}/programmes",
                    "reason": "Mock official programmes index candidate.",
                    "expected_category": "programme_list",
                },
            ],
            "candidate_queries": [
                f"site:{host_hint} undergraduate admissions",
                f"site:{host_hint} undergraduate programmes",
            ],
            "candidate_path_patterns": [
                "/admissions",
                "/programmes",
            ],
            "warnings": [],
        }


class MockProgrammeCatalogAssistProvider:
    """Deterministic programme-candidate category hint provider for tests."""

    name = "mock"

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = dict(payload) if payload is not None else None
        self._error = error

    def classify_programme_candidate_payload(self, candidate_text: str, source_url: str, title: str | None, schema: dict[str, object]) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        if self._payload is not None:
            return dict(self._payload)
        lowered = candidate_text.lower()
        if "major:" in lowered or "primary major" in lowered:
            category = "major"
        elif "special programme" in lowered or "nus college" in lowered or "scholars programme" in lowered:
            category = "special_programme"
        elif "double degree" in lowered or "dual degree" in lowered:
            category = "dual_degree"
        elif "bachelor" in lowered or "bsc" in lowered or "beng" in lowered or "bba" in lowered:
            category = "degree_programme"
        else:
            category = "unknown"
        return {
            "category": category,
            "mode": _mode_hint_from_text(candidate_text),
            "reason": "Mock programme catalog hint based only on the captured candidate row.",
            "confidence": "low",
            "signals": [category] if category != "unknown" else [],
        }


class MockStructuredExtractionProvider:
    """Deterministic structured-candidate provider for Phase 6 plumbing tests."""

    name = "mock"

    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self._payload = dict(payload) if payload is not None else None
        self._error = error
        self.requests: list[dict[str, object]] = []

    def extract_structured_candidate_payload(
        self,
        source: LLMStructuredExtractionSource,
        allowed_claim_paths: tuple[str, ...],
        schema: dict[str, object],
    ) -> dict[str, object]:
        self.requests.append(
            {
                "source_url": source.source_url,
                "title": source.title,
                "text": source.text,
                "source_type": source.source_type,
                "allowed_claim_paths": allowed_claim_paths,
                "schema": schema,
            }
        )
        if self._error is not None:
            raise self._error
        if self._payload is not None:
            return dict(self._payload)
        return {"candidate_facts": [], "warnings": []}


class OpenAIProvider:
    """OpenAI-backed provider for guarded source/classification/programme assist.

    This provider returns bounded JSON payloads only.  It does not create facts
    directly; callers still run the existing deterministic validators.
    """

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 45.0,
        url: str = OPENAI_RESPONSES_URL,
        transport: Any | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", OPENAI_DEFAULT_MODEL)
        self.timeout_seconds = timeout_seconds
        self.url = url
        self._transport = transport

    def generate_source_plan_payload(self, context: dict[str, object], schema: dict[str, object]) -> dict[str, object]:
        return self._json_schema_response(
            schema_name="source_plan",
            schema=schema,
            instructions=(
                "You help a university admissions crawler find official source pages. "
                "Return only candidate official HTTPS URLs, path patterns, queries, and warnings. "
                "Do not invent admissions facts. Prefer undergraduate admissions, programmes, fees, "
                "requirements, scholarships, and official bulletin/catalog pages. Stay within the "
                "same official university site context."
            ),
            user_payload=context,
        )

    def classify_page_payload(self, url: str, title: str | None, text: str, schema: dict[str, object]) -> dict[str, object]:
        return self._json_schema_response(
            schema_name="classification_assist",
            schema=schema,
            instructions=(
                "Classify one captured official university web page for diagnostics only. "
                "Use only the supplied URL, title, and text. Return the closest allowed category, "
                "confidence, short reason, and compact signals. Do not extract admissions facts."
            ),
            user_payload={
                "url": url,
                "title": title,
                "text": text[:4000],
            },
        )

    def classify_programme_candidate_payload(self, candidate_text: str, source_url: str, title: str | None, schema: dict[str, object]) -> dict[str, object]:
        return self._json_schema_response(
            schema_name="programme_catalog_hint",
            schema=schema,
            instructions=(
                "Classify one captured programme catalog candidate row. "
                "Use only the supplied candidate row, source URL, and page title. "
                "Return a category and mode hint only. Do not add programme names, requirements, or facts."
            ),
            user_payload={
                "candidate_text": candidate_text[:1200],
                "source_url": source_url,
                "title": title,
            },
        )

    def extract_structured_candidate_payload(
        self,
        source: LLMStructuredExtractionSource,
        allowed_claim_paths: tuple[str, ...],
        schema: dict[str, object],
    ) -> dict[str, object]:
        return self._json_schema_response(
            schema_name="structured_extraction",
            schema=schema,
            instructions=(
                "Extract candidate undergraduate admissions facts only from the supplied captured official source text. "
                "Return candidate facts, not final facts. Do not infer, summarize, complete, or invent missing values. "
                "Every evidence_snippet must be a contiguous verbatim substring of the supplied source text. "
                "Every value must be a contiguous verbatim substring inside its evidence_snippet. "
                "Every source_url must equal the supplied source URL. Every claim_path must be one of the allowed claim paths. "
                "If the supplied text does not explicitly contain a supported fact with direct evidence, return an empty candidate_facts list. "
                "Do not return admissions advice, eligibility verdicts, or facts from outside the captured source."
            ),
            user_payload={
                "source_url": source.source_url,
                "title": source.title,
                "source_type": source.source_type,
                "text": source.text[:6000],
                "allowed_claim_paths": list(allowed_claim_paths),
            },
        )

    def _json_schema_response(self, *, schema_name: str, schema: dict[str, object], instructions: str, user_payload: dict[str, object]) -> dict[str, object]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for --llm-provider openai.")
        request_payload = {
            "model": self.model,
            "store": False,
            "instructions": instructions,
            "input": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        raw = self._post_json(request_payload)
        return _extract_openai_json_payload(raw)

    def _post_json(self, payload: dict[str, object]) -> dict[str, object]:
        if self._transport is not None:
            return self._transport(payload)
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API request failed with HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc.reason}") from exc
        parsed = json.loads(response_body)
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI API response must be a JSON object.")
        return parsed


class ChatCompletionsProvider:
    """OpenAI-compatible chat completions provider for guarded LLM adapters."""

    name = "openai-chat"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        chat_completions_path: str | None = None,
        reasoning_effort: str | None = None,
        chat_response_format: str | None = None,
        user_agent: str | None = None,
        timeout_seconds: float = 45.0,
        transport: Any | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", OPENAI_DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or OPENAI_DEFAULT_BASE_URL).rstrip("/")
        path = chat_completions_path or os.environ.get("OPENAI_CHAT_COMPLETIONS_PATH") or OPENAI_DEFAULT_CHAT_COMPLETIONS_PATH
        self.chat_completions_path = "/" + path.lstrip("/")
        self.url = self.base_url + self.chat_completions_path
        raw_reasoning_effort = reasoning_effort if reasoning_effort is not None else os.environ.get("OPENAI_REASONING_EFFORT")
        self.reasoning_effort = raw_reasoning_effort.strip() if isinstance(raw_reasoning_effort, str) else None
        raw_chat_response_format = chat_response_format if chat_response_format is not None else os.environ.get("OPENAI_CHAT_RESPONSE_FORMAT")
        self.chat_response_format = _normalise_chat_response_format(raw_chat_response_format)
        raw_user_agent = user_agent if user_agent is not None else os.environ.get("OPENAI_USER_AGENT")
        self.user_agent = raw_user_agent.strip() if isinstance(raw_user_agent, str) and raw_user_agent.strip() else OPENAI_DEFAULT_USER_AGENT
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def generate_source_plan_payload(self, context: dict[str, object], schema: dict[str, object]) -> dict[str, object]:
        return self._json_schema_response(
            schema_name="source_plan",
            schema=schema,
            instructions=(
                "You help a university admissions crawler find official source pages. "
                "Return only candidate official HTTPS URLs, path patterns, queries, and warnings. "
                "Do not invent admissions facts. Prefer undergraduate admissions, programmes, fees, "
                "requirements, scholarships, and official bulletin/catalog pages. Stay within the "
                "same official university site context."
            ),
            user_payload=context,
        )

    def classify_page_payload(self, url: str, title: str | None, text: str, schema: dict[str, object]) -> dict[str, object]:
        return self._json_schema_response(
            schema_name="classification_assist",
            schema=schema,
            instructions=(
                "Classify one captured official university web page for diagnostics only. "
                "Use only the supplied URL, title, and text. Return the closest allowed category, "
                "confidence, short reason, and compact signals. Do not extract admissions facts."
            ),
            user_payload={
                "url": url,
                "title": title,
                "text": text[:4000],
            },
        )

    def classify_programme_candidate_payload(self, candidate_text: str, source_url: str, title: str | None, schema: dict[str, object]) -> dict[str, object]:
        return self._json_schema_response(
            schema_name="programme_catalog_hint",
            schema=schema,
            instructions=(
                "Classify one captured programme catalog candidate row. "
                "Use only the supplied candidate row, source URL, and page title. "
                "Return a category and mode hint only. Do not add programme names, requirements, or facts."
            ),
            user_payload={
                "candidate_text": candidate_text[:1200],
                "source_url": source_url,
                "title": title,
            },
        )

    def extract_structured_candidate_payload(
        self,
        source: LLMStructuredExtractionSource,
        allowed_claim_paths: tuple[str, ...],
        schema: dict[str, object],
    ) -> dict[str, object]:
        return self._json_schema_response(
            schema_name="structured_extraction",
            schema=schema,
            instructions=(
                "Extract candidate undergraduate admissions facts only from the supplied captured official source text. "
                "Return candidate facts, not final facts. Do not infer, summarize, complete, or invent missing values. "
                "Every evidence_snippet must be a contiguous verbatim substring of the supplied source text. "
                "Every value must be a contiguous verbatim substring inside its evidence_snippet. "
                "Every source_url must equal the supplied source URL. Every claim_path must be one of the allowed claim paths. "
                "If the supplied text does not explicitly contain a supported fact with direct evidence, return an empty candidate_facts list. "
                "Do not return admissions advice, eligibility verdicts, or facts from outside the captured source."
            ),
            user_payload={
                "source_url": source.source_url,
                "title": source.title,
                "source_type": source.source_type,
                "text": source.text[:6000],
                "allowed_claim_paths": list(allowed_claim_paths),
            },
        )

    def _json_schema_response(self, *, schema_name: str, schema: dict[str, object], instructions: str, user_payload: dict[str, object]) -> dict[str, object]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for --llm-provider openai-chat.")
        effective_instructions = instructions
        if self.chat_response_format != "json_schema":
            effective_instructions = f"{instructions} {OPENAI_CHAT_JSON_CONTRACTS.get(schema_name, 'Return only strict JSON.')}"
        request_payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": effective_instructions},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
            ],
        }
        if self.chat_response_format == "json_schema":
            request_payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            }
        elif self.chat_response_format == "json_object":
            request_payload["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            request_payload["reasoning_effort"] = self.reasoning_effort
        raw = self._post_json(request_payload)
        return _extract_chat_completions_json_payload(raw)

    def _post_json(self, payload: dict[str, object]) -> dict[str, object]:
        if self._transport is not None:
            return self._transport(payload)
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers=self._request_headers(),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI chat completions request failed with HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI chat completions request failed: {exc.reason}") from exc
        parsed = json.loads(response_body)
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI chat completions response must be a JSON object.")
        return parsed

    def _request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }


def generate_source_plan_diagnostic(context: dict[str, object], provider: SourcePlanProvider) -> dict[str, object]:
    """Return source-planning diagnostics before deterministic URL validation."""

    provider_name = getattr(provider, "name", type(provider).__name__)
    started = perf_counter()
    try:
        payload = provider.generate_source_plan_payload(context, SOURCE_PLAN_OUTPUT_SCHEMA)
        source_plan = source_plan_from_payload(payload)
        return {
            "provider": provider_name,
            "schema": "SOURCE_PLAN_OUTPUT_SCHEMA",
            "fallback": False,
            "elapsed_ms": _elapsed_ms(started),
            "trigger_reasons": _bounded_text_list(context.get("trigger_reasons", []), field="trigger_reasons", max_items=MAX_SOURCE_PLAN_QUERIES, max_length=MAX_SOURCE_PLAN_REASON_LENGTH),
            "candidate_urls": [item.to_dict() for item in source_plan.candidate_urls],
            "candidate_path_patterns": list(source_plan.candidate_path_patterns),
            "candidate_queries": list(source_plan.candidate_queries),
            "warnings": list(source_plan.warnings),
            "applied": False,
            "note": "Source planning only proposes candidates. Deterministically accepted URLs may be used as bounded crawl frontier hints, but they never create admissions facts directly.",
        }
    except Exception as exc:
        return {
            "provider": provider_name,
            "schema": "SOURCE_PLAN_OUTPUT_SCHEMA",
            "fallback": True,
            "elapsed_ms": _elapsed_ms(started),
            "trigger_reasons": _bounded_text_list(context.get("trigger_reasons", []), field="trigger_reasons", max_items=MAX_SOURCE_PLAN_QUERIES, max_length=MAX_SOURCE_PLAN_REASON_LENGTH),
            "candidate_urls": [],
            "candidate_path_patterns": [],
            "candidate_queries": [],
            "warnings": ["llm_source_plan_fallback"],
            "applied": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "note": "Source planning only proposes candidates. Deterministically accepted URLs may be used as bounded crawl frontier hints, but they never create admissions facts directly.",
        }


def generate_classification_assist_diagnostic(
    *,
    url: str,
    title: str | None,
    text: str,
    rule_category: PageCategory,
    rule_score: int,
    provider: ClassificationAssistProvider,
) -> dict[str, object]:
    """Return model-assisted classification diagnostics without changing the rule result."""

    provider_name = getattr(provider, "name", type(provider).__name__)
    started = perf_counter()
    try:
        payload = provider.classify_page_payload(url, title, text[:4000], CLASSIFICATION_ASSIST_OUTPUT_SCHEMA)
        assist = classification_assist_from_payload(payload)
        return {
            "url": url,
            "provider": provider_name,
            "schema": "CLASSIFICATION_ASSIST_OUTPUT_SCHEMA",
            "fallback": False,
            "elapsed_ms": _elapsed_ms(started),
            "rule_category": str(rule_category),
            "rule_score": rule_score,
            "candidate": assist.to_dict(),
            "applied": False,
        }
    except Exception as exc:
        return {
            "url": url,
            "provider": provider_name,
            "schema": "CLASSIFICATION_ASSIST_OUTPUT_SCHEMA",
            "fallback": True,
            "elapsed_ms": _elapsed_ms(started),
            "rule_category": str(rule_category),
            "rule_score": rule_score,
            "candidate": None,
            "applied": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def generate_programme_catalog_classification_hint(
    *,
    candidate_text: str,
    source_url: str,
    title: str | None,
    provider: ProgrammeCatalogAssistProvider,
) -> ProgrammeCatalogClassificationHintResult:
    """Return a bounded category hint for one captured programme candidate row."""

    provider_name = getattr(provider, "name", type(provider).__name__)
    started = perf_counter()
    try:
        payload = provider.classify_programme_candidate_payload(candidate_text, source_url, title, PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA)
        hint = programme_catalog_classification_hint_from_payload(payload)
        return ProgrammeCatalogClassificationHintResult(
            hint=hint,
            diagnostics={
                "provider": provider_name,
                "schema": "PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA",
                "fallback": False,
                "elapsed_ms": _elapsed_ms(started),
                "applied": hint.category != "unknown" or hint.mode != "unknown",
            },
        )
    except Exception as exc:
        return ProgrammeCatalogClassificationHintResult(
            hint=None,
            diagnostics={
                "provider": provider_name,
                "schema": "PROGRAMME_CATALOG_CLASSIFICATION_OUTPUT_SCHEMA",
                "fallback": True,
                "elapsed_ms": _elapsed_ms(started),
                "applied": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )


def programme_catalog_classification_hint_from_payload(payload: dict[str, object]) -> ProgrammeCatalogClassificationHint:
    allowed_keys = {"category", "mode", "reason", "confidence", "signals"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported programme catalog hint fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Programme catalog hint missing required fields: {', '.join(sorted(missing_keys))}")
    category = _required_text(payload.get("category"), field="category")
    if category not in PROGRAMME_CATALOG_CATEGORY_VALUES:
        raise ValueError(f"Unsupported programme catalog category: {category}")
    mode = _required_text(payload.get("mode"), field="mode")
    if mode not in PROGRAMME_CATALOG_MODE_VALUES:
        raise ValueError(f"Unsupported programme catalog mode: {mode}")
    confidence = _required_text(payload.get("confidence"), field="confidence")
    if confidence not in {"low", "medium", "high"}:
        raise ValueError(f"Unsupported programme catalog confidence: {confidence}")
    return ProgrammeCatalogClassificationHint(
        category=category,
        mode=mode,
        reason=_bounded_text(_required_text(payload.get("reason"), field="reason"), field="reason", max_length=MAX_PROGRAMME_HINT_REASON_LENGTH),
        confidence=confidence,
        signals=tuple(_bounded_text_list(payload.get("signals", []), field="signals", max_items=MAX_PROGRAMME_HINT_SIGNALS, max_length=MAX_PROGRAMME_HINT_SIGNAL_LENGTH)),
    )


def classification_assist_from_payload(payload: dict[str, object]) -> ClassificationAssistResult:
    allowed_keys = {"category", "reason", "confidence", "signals"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported classification assist fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Classification assist missing required fields: {', '.join(sorted(missing_keys))}")
    category_value = _required_text(payload.get("category"), field="category")
    try:
        category = PageCategory(category_value)
    except ValueError as exc:
        raise ValueError(f"Unsupported classification category: {category_value}") from exc
    confidence = _required_text(payload.get("confidence"), field="confidence")
    if confidence not in {"low", "medium", "high"}:
        raise ValueError(f"Unsupported classification confidence: {confidence}")
    return ClassificationAssistResult(
        category=category,
        reason=_bounded_text(_required_text(payload.get("reason"), field="reason"), field="reason", max_length=MAX_CLASSIFICATION_REASON_LENGTH),
        confidence=confidence,
        signals=tuple(_bounded_text_list(payload.get("signals", []), field="signals", max_items=MAX_CLASSIFICATION_SIGNALS, max_length=MAX_CLASSIFICATION_SIGNAL_LENGTH)),
    )


def structured_extraction_result_from_payload(payload: dict[str, object]) -> LLMStructuredExtractionResult:
    allowed_keys = {"candidate_facts", "warnings"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported structured extraction fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Structured extraction payload missing required fields: {', '.join(sorted(missing_keys))}")
    candidate_facts = tuple(
        _structured_candidate_fact_from_payload(item)
        for item in _required_generic_dict_list(
            payload.get("candidate_facts"),
            field="candidate_facts",
            max_items=MAX_STRUCTURED_CANDIDATE_FACTS,
        )
    )
    warnings = tuple(
        _bounded_text_list(
            payload.get("warnings", []),
            field="warnings",
            max_items=MAX_STRUCTURED_WARNINGS,
            max_length=MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH,
        )
    )
    return LLMStructuredExtractionResult(candidate_facts=candidate_facts, warnings=warnings)


def _structured_candidate_fact_from_payload(payload: dict[str, object]) -> LLMStructuredCandidateFact:
    required_keys = {"claim_path", "value", "evidence_snippet", "source_url", "confidence"}
    allowed_keys = required_keys | {"reason", "source_title", "candidate_type", "normalization_hint"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported structured candidate fields: {', '.join(sorted(extra_keys))}")
    missing_keys = required_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Structured candidate missing required fields: {', '.join(sorted(missing_keys))}")
    return LLMStructuredCandidateFact(
        claim_path=_required_non_empty_bounded_text(payload.get("claim_path"), field="claim_path", max_length=MAX_STRUCTURED_CLAIM_PATH_LENGTH),
        value=_required_non_empty_bounded_text(payload.get("value"), field="value", max_length=MAX_STRUCTURED_VALUE_LENGTH),
        evidence_snippet=_required_non_empty_bounded_text(payload.get("evidence_snippet"), field="evidence_snippet", max_length=MAX_STRUCTURED_SNIPPET_LENGTH),
        source_url=_required_non_empty_bounded_text(payload.get("source_url"), field="source_url", max_length=MAX_STRUCTURED_SOURCE_URL_LENGTH),
        confidence=_required_confidence(payload.get("confidence"), field="confidence"),
        reason=_optional_bounded_text(payload.get("reason"), field="reason", max_length=MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH),
        source_title=_optional_bounded_text(payload.get("source_title"), field="source_title", max_length=MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH),
        candidate_type=_optional_bounded_text(payload.get("candidate_type"), field="candidate_type", max_length=MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH),
        normalization_hint=_optional_bounded_text(payload.get("normalization_hint"), field="normalization_hint", max_length=MAX_STRUCTURED_OPTIONAL_TEXT_LENGTH),
    )


def validate_llm_candidates(candidates: list[LLMCandidateClaim], evidence: list[EvidenceItem], source_text: str) -> LLMValidationResult:
    """Accept only candidates whose snippet is grounded in captured source text.

    This is intentionally strict: unsupported claims are not promoted into the
    admissions schema by the MVP.  Callers may surface warnings/manual checks.
    """

    result = LLMValidationResult()
    evidence_by_path: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        evidence_by_path.setdefault(item.claim_path, []).append(item)
    for candidate in candidates:
        snippet = candidate.evidence_snippet.strip()
        matching_path_evidence = evidence_by_path.get(candidate.claim_path, [])
        path_snippet_match = any(
            snippet
            and snippet == item.snippet.strip()
            and (candidate.source_url is None or candidate.source_url == item.source_url)
            for item in matching_path_evidence
        )
        value_supported = str(candidate.value).strip().lower() in snippet.lower()
        if snippet and snippet in source_text and path_snippet_match and value_supported:
            result.accepted.append(candidate)
        else:
            result.warnings.append(
                WarningRecord(
                    WarningCode.LLM_UNSUPPORTED_CLAIM,
                    "LLM candidate claim was rejected because its evidence snippet was not found in captured source text.",
                    field=candidate.claim_path,
                )
            )
    return result


def source_plan_from_payload(payload: dict[str, object]) -> SourcePlanResult:
    allowed_keys = {"candidate_urls", "candidate_path_patterns", "candidate_queries", "warnings"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported source plan fields: {', '.join(sorted(extra_keys))}")
    required_keys = {"candidate_urls", "candidate_queries", "warnings"}
    missing_keys = required_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Source plan missing required fields: {', '.join(sorted(missing_keys))}")
    candidate_urls = tuple(_source_plan_candidate_from_payload(item) for item in _required_dict_list(payload.get("candidate_urls"), field="candidate_urls", max_items=MAX_SOURCE_PLAN_URLS))
    candidate_path_patterns = tuple(
        _bounded_text_list(
            payload.get("candidate_path_patterns", []),
            field="candidate_path_patterns",
            max_items=MAX_SOURCE_PLAN_PATH_PATTERNS,
            max_length=MAX_SOURCE_PLAN_PATH_PATTERN_LENGTH,
        )
    )
    candidate_queries = tuple(_bounded_text_list(payload.get("candidate_queries", []), field="candidate_queries", max_items=MAX_SOURCE_PLAN_QUERIES, max_length=MAX_SOURCE_PLAN_QUERY_LENGTH))
    warnings = tuple(_bounded_text_list(payload.get("warnings", []), field="warnings", max_items=MAX_SOURCE_PLAN_QUERIES, max_length=MAX_SOURCE_PLAN_REASON_LENGTH))
    return SourcePlanResult(candidate_urls=candidate_urls, candidate_path_patterns=candidate_path_patterns, candidate_queries=candidate_queries, warnings=warnings)


def _source_plan_candidate_from_payload(payload: dict[str, object]) -> SourcePlanCandidateURL:
    allowed_keys = {"url", "reason", "expected_category"}
    extra_keys = set(payload) - allowed_keys
    if extra_keys:
        raise ValueError(f"Unsupported source plan candidate fields: {', '.join(sorted(extra_keys))}")
    missing_keys = allowed_keys - set(payload)
    if missing_keys:
        raise ValueError(f"Source plan candidate missing required fields: {', '.join(sorted(missing_keys))}")
    return SourcePlanCandidateURL(
        url=_bounded_text(_required_text(payload.get("url"), field="url"), field="url", max_length=MAX_SOURCE_PLAN_URL_LENGTH),
        reason=_bounded_text(_required_text(payload.get("reason"), field="reason"), field="reason", max_length=MAX_SOURCE_PLAN_REASON_LENGTH),
        expected_category=_bounded_text(_required_text(payload.get("expected_category"), field="expected_category"), field="expected_category", max_length=MAX_SOURCE_PLAN_CATEGORY_LENGTH),
    )


def _extract_openai_json_payload(response: dict[str, object]) -> dict[str, object]:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return _loads_json_object(output_text)
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    return _loads_json_object(text)
    raise ValueError("OpenAI response did not include JSON output text.")


def _extract_chat_completions_json_payload(response: dict[str, object]) -> dict[str, object]:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return _loads_json_object(content)
                if isinstance(content, list):
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            return _loads_json_object(text)
    raise ValueError("OpenAI chat completions response did not include JSON message content.")


def _loads_json_object(text: str) -> dict[str, object]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("OpenAI structured output must be a JSON object.")
    return payload


def _normalise_chat_response_format(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        return OPENAI_DEFAULT_CHAT_RESPONSE_FORMAT
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"none", "off", "disabled"}:
        return "none"
    if normalized in {"json", "json_object"}:
        return "json_object"
    if normalized == "json_schema":
        return "json_schema"
    return OPENAI_DEFAULT_CHAT_RESPONSE_FORMAT


def _required_dict_list(value: object, *, field: str, max_items: int) -> list[dict[str, object]]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Source plan field {field} must be a list.")
    if len(value) > max_items:
        raise ValueError(f"Source plan field {field} exceeds {max_items} items.")
    out: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Source plan field {field} must contain only objects.")
        out.append(item)
    return out


def _required_generic_dict_list(value: object, *, field: str, max_items: int) -> list[dict[str, object]]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Field {field} must be a list.")
    if len(value) > max_items:
        raise ValueError(f"Field {field} exceeds {max_items} items.")
    out: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"Field {field} must contain only objects.")
        out.append(item)
    return out


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Classification assist field {field} must be a string.")
    return value


def _bounded_text(value: str, *, field: str, max_length: int) -> str:
    stripped = value.strip()
    if len(stripped) > max_length:
        raise ValueError(f"Classification assist field {field} exceeds {max_length} characters.")
    return stripped


def _required_non_empty_bounded_text(value: object, *, field: str, max_length: int) -> str:
    text = _bounded_text(_required_text(value, field=field), field=field, max_length=max_length)
    if not text:
        raise ValueError(f"Structured extraction field {field} must not be empty.")
    return text


def _optional_bounded_text(value: object, *, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    text = _bounded_text(_required_text(value, field=field), field=field, max_length=max_length)
    return text or None


def _required_confidence(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Structured extraction field {field} must be a number.")
    confidence = float(value)
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError(f"Structured extraction field {field} must be between 0.0 and 1.0.")
    return confidence


def _bounded_text_list(value: object, *, field: str, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Classification assist field {field} must be a list of strings.")
    if len(value) > max_items:
        raise ValueError(f"Classification assist field {field} exceeds {max_items} items.")
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"Classification assist field {field} must contain only strings.")
        bounded = _bounded_text(item, field=field, max_length=max_length)
        if bounded and bounded not in seen:
            seen.add(bounded)
            out.append(bounded)
    return out


def _mode_hint_from_text(text: str) -> str:
    lowered = text.lower()
    if "full-time" in lowered or "full time" in lowered:
        return "full-time"
    if "part-time" in lowered or "part time" in lowered:
        return "part-time"
    return "unknown"
