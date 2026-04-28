"""@ai_function tools the orchestrator agent uses.

Two custom tools (HostedWebSearchTool is the third, hosted by Foundry):

- scrape_retailer_site(url) -> short summary; full result cached by URL
- extract_retailer_fields(retailer_name, scraped_url) -> structured fields

The scrape result is cached in a process-local dict so the orchestrator
shuttles only a URL between the two calls, not megabytes of HTML."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from agent_framework import tool
from openai import AsyncAzureOpenAI
from pydantic import Field

from .config import Settings, load_settings
from .models import ExtractedRetailer
from .plugins.extractor import extract_retailer
from .plugins.scraper import ScrapedPage, Scraper

log = logging.getLogger(__name__)

_settings: Settings | None = None
_scraper: Scraper | None = None
_openai_client: AsyncAzureOpenAI | None = None
_scrape_cache: dict[str, list[ScrapedPage]] = {}
_init_lock = asyncio.Lock()


async def _ensure_init() -> Settings:
    global _settings, _scraper, _openai_client
    if _settings is not None:
        return _settings
    async with _init_lock:
        if _settings is not None:
            return _settings
        _settings = load_settings()
        _scraper = Scraper(_settings)
        from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        _openai_client = AsyncAzureOpenAI(
            azure_ad_token_provider=token_provider,
            api_version=_settings.azure_openai_api_version,
            azure_endpoint=_settings.azure_openai_endpoint,
        )
        return _settings


async def aclose() -> None:
    """Tear down module-level clients. Call once per process at shutdown."""
    global _openai_client
    if _openai_client is not None:
        await _openai_client.close()
        _openai_client = None
    _scrape_cache.clear()


def reset_scrape_cache() -> None:
    """Drop cached scrape results between retailers to bound memory growth."""
    _scrape_cache.clear()


@tool(
    description=(
        "Fetch the retailer's website. Pass the official site URL you found via "
        "web search. Returns a short summary; the full content is held server-side "
        "and consumed by extract_retailer_fields. Always call this BEFORE "
        "extract_retailer_fields."
    )
)
async def scrape_retailer_site(
    url: Annotated[str, Field(description="Full URL of the retailer's official website.")],
) -> str:
    await _ensure_init()
    assert _scraper is not None
    try:
        pages = await _scraper.fetch_site(url)
    except Exception as e:
        log.warning("scrape_retailer_site failed for %s: %s", url, e)
        return f"Scrape failed: {e}"
    if not pages:
        return f"Scraped {url} but found no usable pages."
    _scrape_cache[url] = pages
    total_text = sum(len(p.text) for p in pages)
    total_jsonld = sum(len(p.json_ld) for p in pages)
    return (
        f"Scraped {len(pages)} pages from {url} "
        f"({total_text} chars text, {total_jsonld} JSON-LD blobs). "
        f"Now call extract_retailer_fields with this same URL."
    )


@tool(
    description=(
        "Extract structured business fields (about, categories, brands, sample "
        "prices, phone, email, address) from a previously-scraped site. Pass the "
        "same URL you used in scrape_retailer_site. Returns the structured fields."
    )
)
async def extract_retailer_fields(
    retailer_name: Annotated[str, Field(description="The retailer's name as given by the user.")],
    scraped_url: Annotated[str, Field(description="The URL previously passed to scrape_retailer_site.")],
) -> dict[str, Any]:
    settings = await _ensure_init()
    assert _openai_client is not None
    pages = _scrape_cache.get(scraped_url)
    if not pages:
        return {
            "error": f"URL {scraped_url} not found in scrape cache. "
            f"Call scrape_retailer_site first."
        }
    page_tuples = [(p.url, p.text) for p in pages]
    json_ld_blobs = [b for p in pages for b in p.json_ld]
    extracted: ExtractedRetailer = await extract_retailer(
        _openai_client,
        settings.extraction_deployment,
        retailer_name,
        page_tuples,
        json_ld_blobs,
    )
    out = extracted.model_dump()
    out["sources"] = [p.url for p in pages]
    return out
