from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    foundry_project_endpoint: str
    azure_openai_endpoint: str
    azure_openai_api_version: str
    agent_deployment: str
    extraction_deployment: str

    request_timeout_s: float = 15.0
    page_char_cap: int = 12_000
    max_product_pages: int = 5
    cache_path: str = ".cache/http_cache.sqlite"
    user_agent: str = "RetailerValidator/1.0 (+https://example.com/bot)"
    confidence_threshold: float = 0.7


def load_settings() -> Settings:
    required = (
        "FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT_AGENT",
        "AZURE_OPENAI_DEPLOYMENT_EXTRACTION",
    )
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    return Settings(
        foundry_project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        azure_openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-03-01-preview"),
        agent_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_AGENT"],
        extraction_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT_EXTRACTION"],
    )
