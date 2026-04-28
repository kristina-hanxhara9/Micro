from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator
from urllib.parse import urlparse

from agent_framework import Agent, ChatOptions
from agent_framework.foundry import FoundryChatClient

from . import tools as tools_mod
from .agent import build_orchestrator
from .config import Settings
from .models import ExtractedRetailer, OrchestratorOutput, RetailerRecord
from .plugins.validator import score_record

log = logging.getLogger(__name__)

AGGREGATOR_HOSTS = (
    "yelp.", "yellowpages.", "wikipedia.", "facebook.", "linkedin.",
    "instagram.", "twitter.", "x.com", "amazon.", "ebay.", "bbb.",
    "tripadvisor.", "pinterest.", "etsy.",
)


@dataclass
class PipelineDeps:
    settings: Settings
    agent: Agent
    client: FoundryChatClient


@asynccontextmanager
async def build_deps(settings: Settings) -> AsyncIterator[PipelineDeps]:
    agent, client = build_orchestrator(settings)
    try:
        yield PipelineDeps(settings=settings, agent=agent, client=client)
    finally:
        try:
            await client.close()
        except Exception as e:
            log.warning("FoundryChatClient close failed: %s", e)
        await tools_mod.aclose()


def _heuristic_domain(name: str) -> str | None:
    """Single-word alphanumeric retailer names map cleanly to <name>.com."""
    cleaned = name.strip().lower()
    if 3 <= len(cleaned) <= 25 and cleaned.isalnum():
        return f"https://www.{cleaned}.com"
    return None


def _is_aggregator(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(bad in host for bad in AGGREGATOR_HOSTS)


def _coerce_output(result: object) -> OrchestratorOutput | None:
    """ChatAgent.run with response_format returns an AgentRunResponse whose
    parsed payload may live on `.value`, `.parsed`, or be reconstructable from
    `.text`. Try each."""
    for attr in ("value", "parsed", "output_parsed"):
        v = getattr(result, attr, None)
        if isinstance(v, OrchestratorOutput):
            return v
    text = getattr(result, "text", None)
    if isinstance(text, str) and text.strip():
        try:
            return OrchestratorOutput.model_validate_json(text)
        except Exception:
            pass
    return None


async def process_retailer(name: str, deps: PipelineDeps) -> RetailerRecord:
    hint = _heuristic_domain(name)
    user_msg = f"Retailer: {name}"
    if hint:
        user_msg += f"\nLikely website: {hint} (verify before trusting)"

    try:
        result = await deps.agent.run(
            user_msg,
            options=ChatOptions(response_format=OrchestratorOutput),
        )
    except Exception as e:
        log.exception("Orchestrator failed for %s: %s", name, e)
        return score_record(name, None, ExtractedRetailer(), [])
    finally:
        tools_mod.reset_scrape_cache()

    output = _coerce_output(result)
    if output is None:
        log.warning("Orchestrator returned unparseable output for %s", name)
        return score_record(name, None, ExtractedRetailer(), [])

    website = output.website
    if website and _is_aggregator(website):
        log.warning("Orchestrator returned aggregator URL for %s: %s", name, website)
        website = None

    extracted = ExtractedRetailer(
        about=output.about,
        categories=output.categories,
        brands=output.brands,
        sample_prices=output.sample_prices,
        phone=output.phone,
        email=output.email,
        address=output.address,
    )
    return score_record(name, website, extracted, output.sources)


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
