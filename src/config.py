from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_openai_api_version: str
    bing_search_key: str
    bing_search_endpoint: str

    request_timeout_s: float = 15.0
    page_char_cap: int = 12_000
    bing_qps: float = 3.0
    cache_path: str = ".cache/http_cache.sqlite"
    user_agent: str = "RetailerValidator/1.0 (+https://example.com/bot)"
    confidence_threshold: float = 0.7


def load_settings() -> Settings:
    missing = [
        var for var in (
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
            "BING_SEARCH_KEY",
        ) if not os.getenv(var)
    ]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    return Settings(
        azure_openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_openai_api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_openai_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        bing_search_key=os.environ["BING_SEARCH_KEY"],
        bing_search_endpoint=os.getenv(
            "BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search"
        ),
    )
