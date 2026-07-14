"""Shared LLM runtime resolution for CLI and batch scans."""

from __future__ import annotations

import argparse
import os
from typing import Any

from university_admissions_crawler.extractor.llm_provider import (
    ChatCompletionsProvider,
    MockClassificationAssistProvider,
    MockProgrammeCatalogAssistProvider,
    MockSourcePlanProvider,
    MockStructuredExtractionProvider,
    OpenAIProvider,
)
from university_admissions_crawler.extractor.schema import AdmissionsData


def resolve_llm_provider_name(requested_provider: str | None) -> str | None:
    requested = (requested_provider or os.environ.get("UAC_LLM_PROVIDER") or "auto").strip().lower()
    if requested in {"none", "off", "disabled"}:
        return None
    if requested == "auto":
        return "openai" if os.environ.get("OPENAI_API_KEY") else None
    return requested


def llm_providers_for_args(args: argparse.Namespace):
    if not args.enable_llm:
        return None, None, None, None
    provider_name = getattr(args, "resolved_llm_provider", None)
    if provider_name is None:
        provider_name = resolve_llm_provider_name(args.llm_provider)
        args.resolved_llm_provider = provider_name
    if provider_name is None:
        return None, None, None, None
    if provider_name == "mock":
        return (
            MockClassificationAssistProvider() if args.enable_classification_assist else None,
            MockProgrammeCatalogAssistProvider() if args.enable_classification_assist else None,
            MockSourcePlanProvider() if args.enable_source_planning else None,
            MockStructuredExtractionProvider() if args.enable_llm_structured_extraction else None,
        )
    if provider_name == "openai":
        provider = OpenAIProvider()
        return (
            provider if args.enable_classification_assist else None,
            provider if args.enable_classification_assist else None,
            provider if args.enable_source_planning else None,
            provider if args.enable_llm_structured_extraction else None,
        )
    if provider_name == "openai-chat":
        provider = ChatCompletionsProvider()
        return (
            provider if args.enable_classification_assist else None,
            provider if args.enable_classification_assist else None,
            provider if args.enable_source_planning else None,
            provider if args.enable_llm_structured_extraction else None,
        )
    raise ValueError(f"Unsupported LLM provider: {provider_name}")


def attach_llm_runtime_config(data: AdmissionsData, args: argparse.Namespace) -> None:
    requested_provider = args.llm_provider or os.environ.get("UAC_LLM_PROVIDER") or "auto"
    resolved_provider = getattr(args, "resolved_llm_provider", None) or "none"
    data.run.config["llm_runtime"] = {
        "enabled": bool(args.enable_llm),
        "provider": resolved_provider,
        "requested_provider": requested_provider,
        "features": {
            "source_planning": bool(args.enable_source_planning),
            "classification_assist": bool(args.enable_classification_assist),
            "structured_extraction": bool(args.enable_llm_structured_extraction),
        },
        "note": "Live scans use LLM-assisted crawling by default when a provider is available; deterministic validation still controls fact writes.",
    }
