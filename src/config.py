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

    bing_search_key: str | None
    bing_search_endpoint: str
    google_api_key: str | None
    google_cse_id: str | None
    search_primary: str  # "bing" or "google"

    request_timeout_s: float = 15.0
    page_char_cap: int = 12_000
    bing_qps: float = 3.0
    google_qps: float = 5.0
    max_product_pages: int = 5
    cache_path: str = ".cache/http_cache.sqlite"
    user_agent: str = "RetailerValidator/1.0 (+https://example.com/bot)"
    confidence_threshold: float = 0.7


def load_settings() -> Settings:
    missing = [
        var for var in (
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
        ) if not os.getenv(var)
    ]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    bing_key = os.getenv("BING_SEARCH_KEY") or None
    google_key = os.getenv("GOOGLE_API_KEY") or None
    google_cse = os.getenv("GOOGLE_CSE_ID") or None

    if not bing_key and not (google_key and google_cse):
        raise RuntimeError(
            "Configure at least one search backend: BING_SEARCH_KEY, "
            "or GOOGLE_API_KEY + GOOGLE_CSE_ID."
        )

    primary = (os.getenv("SEARCH_PRIMARY") or "bing").lower()
    if primary not in ("bing", "google"):
        raise RuntimeError(f"SEARCH_PRIMARY must be 'bing' or 'google', got '{primary}'")

    return Settings(
        azure_openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_openai_api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_openai_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        bing_search_key=bing_key,
        bing_search_endpoint=os.getenv(
            "BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search"
        ),
        google_api_key=google_key,
        google_cse_id=google_cse,
        search_primary=primary,
    )
