"""Orchestrator agent: Agent with three tools (Foundry-hosted web search +
two @tool functions). The orchestrator decides when to search, scrape,
and extract per retailer."""

from __future__ import annotations

import logging

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import DefaultAzureCredential

from .config import Settings
from .tools import extract_retailer_fields, scrape_retailer_site

log = logging.getLogger(__name__)


INSTRUCTIONS = """\
You enrich retailer data. For each user message containing a retailer name:

1. Use the web search tool to find the retailer's OWN official site. Skip
   directories (Yelp, BBB, Yellow Pages), marketplaces (Amazon, eBay, Etsy),
   social media (Facebook, Instagram, X/Twitter, LinkedIn), Wikipedia, and
   resellers. If the user message includes "Likely website:", verify that URL
   in search results before trusting it.
2. Call scrape_retailer_site(url) on the chosen URL.
3. Call extract_retailer_fields(retailer_name, scraped_url) using the same
   URL you scraped.
4. Return a structured result with the website, extracted fields, and the
   source URLs that were scraped.

Rules:
- If you cannot find a clearly-official site after one search, set website
  to null and return empty fields. Do NOT call scrape on an aggregator.
- Never invent product names, prices, brands, or contact info. Only use
  what extract_retailer_fields returns.
- Always call the tools in this order: search -> scrape -> extract."""


def build_orchestrator(settings: Settings) -> tuple[Agent, FoundryChatClient]:
    """Returns (agent, client). Caller closes the client at shutdown."""
    credential = DefaultAzureCredential()
    client = FoundryChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        model=settings.agent_deployment,
        credential=credential,
    )
    web_search_tool = client.get_web_search_tool()
    agent = Agent(
        client=client,
        instructions=INSTRUCTIONS,
        name="retailer_orchestrator",
        tools=[
            web_search_tool,
            scrape_retailer_site,
            extract_retailer_fields,
        ],
    )
    log.info(
        "Orchestrator agent built (model=%s, project=%s)",
        settings.agent_deployment,
        settings.foundry_project_endpoint,
    )
    return agent, client
