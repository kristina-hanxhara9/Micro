"""Find a retailer's official website via Azure AI Foundry's Grounding with
Bing Search tool. Replaces the retired standalone Bing Search v7 API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    BingGroundingSearchConfiguration,
    BingGroundingSearchToolParameters,
    BingGroundingTool,
    PromptAgentDefinition,
)
from rapidfuzz import fuzz

from ..config import Settings
from ..models import OfficialSiteAnswer

log = logging.getLogger(__name__)

AGENT_NAME = "retailer-finder"
AGENT_INSTRUCTIONS = (
    "You receive a retailer name from the user. Use the Bing grounding tool to "
    "find the retailer's OWN official corporate website. Skip directories (Yelp, "
    "BBB, Yellow Pages), marketplaces (Amazon, eBay), social media, Wikipedia, "
    "and resellers. Return the full URL in `website`, or null if nothing on the "
    "first page of results is clearly the retailer's own site. Keep `reasoning` "
    "to one sentence."
)

AGGREGATOR_HOSTS = (
    "yelp.", "yellowpages.", "wikipedia.", "facebook.", "linkedin.",
    "instagram.", "twitter.", "x.com", "amazon.", "ebay.", "bbb.",
    "tripadvisor.", "pinterest.",
)


def _domain_root(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.replace("www.", "").split(".")[0]


def _heuristic_domain(retailer: str) -> str | None:
    """If the retailer name is a single alphanumeric word, guess <name>.com.
    Only fires for unambiguous cases — names with spaces or punctuation fall
    through to the grounding agent because the .com guess is too risky."""
    name = retailer.strip().lower()
    if 3 <= len(name) <= 25 and name.isalnum():
        return f"https://www.{name}.com"
    return None


class FoundryGroundingSearch:
    """Wraps a single shared Foundry agent + the Responses-API client used to
    invoke it. Create one per pipeline run; reuse across all retailers."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._project_client: AIProjectClient | None = None
        self._openai_client: Any = None
        self._agent_name: str | None = None
        self._agent_version: str | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "FoundryGroundingSearch":
        await asyncio.to_thread(self._setup_sync)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await asyncio.to_thread(self._teardown_sync)

    def _setup_sync(self) -> None:
        from azure.identity import DefaultAzureCredential

        self._project_client = AIProjectClient(
            endpoint=self._settings.foundry_project_endpoint,
            credential=DefaultAzureCredential(),
        )
        self._openai_client = self._project_client.get_openai_client()

        tool = BingGroundingTool(
            bing_grounding=BingGroundingSearchToolParameters(
                search_configurations=[
                    BingGroundingSearchConfiguration(
                        project_connection_id=self._settings.bing_connection_id,
                    )
                ]
            )
        )
        agent = self._project_client.agents.create_version(
            agent_name=AGENT_NAME,
            definition=PromptAgentDefinition(
                model=self._settings.agent_deployment,
                instructions=AGENT_INSTRUCTIONS,
                tools=[tool],
            ),
            description="Finds the official website of a retailer using Bing grounding.",
        )
        self._agent_name = agent.name
        self._agent_version = agent.version
        log.info("Foundry agent ready: %s (version %s)", agent.name, agent.version)

    def _teardown_sync(self) -> None:
        if self._project_client and self._agent_name and self._agent_version:
            try:
                self._project_client.agents.delete_version(
                    agent_name=self._agent_name,
                    agent_version=self._agent_version,
                )
                log.info("Foundry agent deleted: %s", self._agent_name)
            except Exception as e:
                log.warning("Failed to delete agent %s: %s", self._agent_name, e)
        if self._project_client:
            try:
                self._project_client.close()
            except Exception:
                pass

    async def find_official_site(self, retailer: str) -> str | None:
        # Heuristic short-circuit: if the name maps obviously to <name>.com,
        # skip the grounding call entirely. Worth ~$0.014 saved per hit.
        guess = _heuristic_domain(retailer)
        if guess and _is_plausible_official(retailer, guess):
            log.debug("heuristic short-circuit for %s -> %s", retailer, guess)
            return guess

        try:
            answer = await asyncio.to_thread(self._call_agent_sync, retailer)
        except Exception as e:
            log.error("Grounding agent call failed for %s: %s", retailer, e)
            return None

        if not answer or not answer.website:
            return None
        if _is_aggregator(answer.website):
            log.warning("Agent returned aggregator URL for %s: %s", retailer, answer.website)
            return None
        return answer.website

    def _call_agent_sync(self, retailer: str) -> OfficialSiteAnswer | None:
        if self._openai_client is None or self._agent_name is None:
            raise RuntimeError("FoundryGroundingSearch not initialized — use async with")

        response = self._openai_client.responses.parse(
            input=f"Retailer: {retailer}",
            tool_choice="required",
            text_format=OfficialSiteAnswer,
            extra_body={
                "agent_reference": {
                    "name": self._agent_name,
                    "type": "agent_reference",
                }
            },
        )
        return getattr(response, "output_parsed", None)


def _is_aggregator(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(bad in host for bad in AGGREGATOR_HOSTS)


def _is_plausible_official(retailer: str, url: str) -> bool:
    if _is_aggregator(url):
        return False
    root = _domain_root(url)
    if not root:
        return False
    return fuzz.token_set_ratio(retailer.lower(), root) >= 70
