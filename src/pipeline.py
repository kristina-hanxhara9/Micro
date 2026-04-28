from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from openai import AsyncAzureOpenAI
from semantic_kernel import Kernel

from .config import Settings
from .kernel_setup import build_kernel
from .models import ExtractedRetailer, RetailerRecord
from .plugins.extractor import extract_retailer
from .plugins.scraper import Scraper
from .plugins.search import BingSearch, pick_official_site
from .plugins.validator import score_record

log = logging.getLogger(__name__)


@dataclass
class PipelineDeps:
    settings: Settings
    kernel: Kernel
    bing: BingSearch
    scraper: Scraper
    openai_client: AsyncAzureOpenAI


def build_deps(settings: Settings) -> PipelineDeps:
    return PipelineDeps(
        settings=settings,
        kernel=build_kernel(settings),
        bing=BingSearch(settings),
        scraper=Scraper(settings),
        # Direct OpenAI client used only for the structured-output extraction call,
        # which relies on `client.beta.chat.completions.parse(response_format=...)`.
        openai_client=AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        ),
    )


async def process_retailer(name: str, deps: PipelineDeps) -> RetailerRecord:
    deployment = deps.settings.azure_openai_deployment

    try:
        results = await deps.bing.search(f"{name} official website")
    except Exception as e:
        log.error("Bing search failed for %s: %s", name, e)
        return score_record(name, None, ExtractedRetailer(), [])

    website = await pick_official_site(deps.kernel, name, results)
    if not website:
        return score_record(name, None, ExtractedRetailer(), [])

    try:
        pages = await deps.scraper.fetch_site(website)
    except Exception as e:
        log.error("Scrape failed for %s (%s): %s", name, website, e)
        pages = []

    page_tuples = [(p.url, p.text) for p in pages]
    extracted = await extract_retailer(deps.openai_client, deployment, name, page_tuples)
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
