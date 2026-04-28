from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from openai import AsyncAzureOpenAI

from .config import Settings
from .models import ExtractedRetailer, RetailerRecord
from .plugins.extractor import extract_retailer
from .plugins.scraper import Scraper
from .plugins.search import FoundryGroundingSearch
from .plugins.validator import score_record

log = logging.getLogger(__name__)


@dataclass
class PipelineDeps:
    settings: Settings
    search: FoundryGroundingSearch
    scraper: Scraper
    openai_client: AsyncAzureOpenAI


@asynccontextmanager
async def build_deps(settings: Settings) -> AsyncIterator[PipelineDeps]:
    """Sets up the Foundry agent + clients, yields deps, tears down on exit."""
    if settings.azure_openai_api_key:
        openai_client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
    else:
        # AAD auth path: token comes from DefaultAzureCredential.
        from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        openai_client = AsyncAzureOpenAI(
            azure_ad_token_provider=token_provider,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )

    async with FoundryGroundingSearch(settings) as search:
        try:
            yield PipelineDeps(
                settings=settings,
                search=search,
                scraper=Scraper(settings),
                openai_client=openai_client,
            )
        finally:
            await openai_client.close()


async def process_retailer(name: str, deps: PipelineDeps) -> RetailerRecord:
    website = await deps.search.find_official_site(name)
    if not website:
        return score_record(name, None, ExtractedRetailer(), [])

    try:
        pages = await deps.scraper.fetch_site(website)
    except Exception as e:
        log.error("Scrape failed for %s (%s): %s", name, website, e)
        pages = []

    page_tuples = [(p.url, p.text) for p in pages]
    json_ld_blobs = [b for p in pages for b in p.json_ld]
    extracted = await extract_retailer(
        deps.openai_client,
        deps.settings.extraction_deployment,
        name,
        page_tuples,
        json_ld_blobs,
    )
    sources = [p.url for p in pages]
    return score_record(name, website, extracted, sources)


async def run_pipeline(
    names: list[str],
    deps: PipelineDeps,
    concurrency: int = 10,
) -> list[RetailerRecord]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(n: str) -> RetailerRecord:
        async with sem:
            try:
                rec = await process_retailer(n, deps)
                log.info("done: %s (conf=%.2f, flags=%s)", n, rec.confidence, rec.flags)
                return rec
            except Exception as e:
                log.exception("Unhandled error processing %s: %s", n, e)
                return score_record(n, None, ExtractedRetailer(), [])

    return await asyncio.gather(*(_one(n) for n in names))
