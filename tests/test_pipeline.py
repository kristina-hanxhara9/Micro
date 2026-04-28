"""Tests for the v3 orchestrator pipeline. The agent itself is mocked so no
Azure credentials are needed to run these."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src import tools as tools_mod
from src.models import OrchestratorOutput, PriceSample
from src.pipeline import (
    PipelineDeps,
    _coerce_output,
    _heuristic_domain,
    _is_aggregator,
    _is_grounded_website,
    _same_host,
    process_retailer,
)


def test_heuristic_catches_clean_names():
    assert _heuristic_domain("Sephora") == "https://www.sephora.com"
    assert _heuristic_domain("Target") == "https://www.target.com"


def test_heuristic_skips_ambiguous_names():
    assert _heuristic_domain("B&H Photo") is None
    assert _heuristic_domain("Crate & Barrel") is None
    assert _heuristic_domain("Joe's Hardware") is None


def test_heuristic_rejects_too_short_or_long():
    assert _heuristic_domain("AB") is None
    assert _heuristic_domain("a" * 30) is None


def test_aggregator_detection():
    assert _is_aggregator("https://www.yelp.com/biz/joe")
    assert _is_aggregator("https://en.wikipedia.org/wiki/Target")
    assert _is_aggregator("https://www.amazon.com/store/something")
    assert _is_aggregator("https://www.facebook.com/joeshardware")
    assert not _is_aggregator("https://www.bestbuy.com")
    assert not _is_aggregator("https://www.sephora.com")


def test_coerce_output_from_value_attr():
    out = OrchestratorOutput(website="https://x.com", about="hi")
    result = MagicMock(value=out)
    assert _coerce_output(result) is out


def test_coerce_output_from_text_json():
    payload = OrchestratorOutput(website="https://x.com").model_dump_json()
    result = MagicMock(spec=["text"])
    result.text = payload
    coerced = _coerce_output(result)
    assert coerced is not None
    assert coerced.website == "https://x.com"


def test_coerce_output_returns_none_on_garbage():
    result = MagicMock(spec=["text"])
    result.text = "not json"
    assert _coerce_output(result) is None


def _mock_deps(agent_run_result, simulated_scrape_urls: list[str] | None = None) -> PipelineDeps:
    """The mocked agent.run optionally simulates the scrape tool by appending
    URLs into the per-task ContextVar. This mirrors what the real scrape tool
    does and lets us exercise the hallucination guard."""

    async def _run(*_args, **_kwargs):
        if simulated_scrape_urls:
            bound = tools_mod._scraped_urls_ctx.get()
            if bound is not None:
                bound.extend(simulated_scrape_urls)
        return agent_run_result

    agent = MagicMock()
    agent.run = AsyncMock(side_effect=_run)
    return PipelineDeps(settings=MagicMock(), agent=agent, client=MagicMock())


def test_same_host_helper():
    assert _same_host("https://www.sephora.com/", "https://sephora.com/about")
    assert _same_host("http://www.target.com/x", "https://target.com/y")
    assert not _same_host("https://www.sephora.com/", "https://sephoria.com/")
    assert not _same_host("https://www.target.com/", "https://www.walmart.com/")


def test_grounded_website_accepts_hint_match():
    assert _is_grounded_website(
        "https://www.sephora.com/",
        scraped_urls=[],
        hint="https://www.sephora.com",
    )


def test_grounded_website_accepts_scrape_match():
    assert _is_grounded_website(
        "https://www.bhphotovideo.com/",
        scraped_urls=["https://www.bhphotovideo.com"],
        hint=None,
    )


def test_grounded_website_rejects_unknown_host():
    assert not _is_grounded_website(
        "https://made-up-domain.com/",
        scraped_urls=["https://www.bhphotovideo.com"],
        hint="https://www.bhphoto.com",
    )


@pytest.mark.asyncio
async def test_process_retailer_happy_path():
    out = OrchestratorOutput(
        website="https://www.sephora.com",
        about="Beauty retailer",
        categories=["beauty", "cosmetics"],
        brands=["Dior", "Chanel"],
        sample_prices=[PriceSample(item="Lipstick", price=22.0)],
        phone="+1-415-555-0100",
        sources=["https://www.sephora.com/", "https://www.sephora.com/about"],
    )
    result = MagicMock(value=out)
    deps = _mock_deps(result)

    rec = await process_retailer("Sephora", deps)

    assert rec.name == "Sephora"
    assert rec.website == "https://www.sephora.com"
    assert rec.about == "Beauty retailer"
    assert "Dior" in rec.brands
    assert rec.sample_prices[0].item == "Lipstick"
    assert rec.confidence > 0.5
    assert "https://www.sephora.com/" in rec.sources
    deps.agent.run.assert_awaited_once()
    # heuristic hint should be in the prompt
    call_args = deps.agent.run.await_args
    assert "Likely website: https://www.sephora.com" in call_args.args[0]


@pytest.mark.asyncio
async def test_process_retailer_passes_no_hint_for_ambiguous_names():
    out = OrchestratorOutput(website="https://www.bhphotovideo.com")
    deps = _mock_deps(
        MagicMock(value=out),
        simulated_scrape_urls=["https://www.bhphotovideo.com"],
    )

    rec = await process_retailer("B&H Photo", deps)

    user_msg = deps.agent.run.await_args.args[0]
    assert "Likely website" not in user_msg
    assert "Retailer: B&H Photo" in user_msg
    assert rec.website == "https://www.bhphotovideo.com"


@pytest.mark.asyncio
async def test_hallucinated_website_is_dropped():
    """Agent returns a website it never scraped and that doesn't match the
    heuristic hint -> guard kicks in and drops it."""
    out = OrchestratorOutput(
        website="https://made-up-store.com",
        about="Some store",
    )
    deps = _mock_deps(
        MagicMock(value=out),
        simulated_scrape_urls=[],  # agent didn't actually scrape anything
    )

    rec = await process_retailer("B&H Photo", deps)

    assert rec.website is None
    assert "no_website_found" in rec.flags


@pytest.mark.asyncio
async def test_process_retailer_strips_aggregator_website():
    out = OrchestratorOutput(
        website="https://www.yelp.com/biz/joes-hardware",
        about="Local hardware store",
    )
    deps = _mock_deps(MagicMock(value=out))

    rec = await process_retailer("Joe's Hardware", deps)

    assert rec.website is None
    assert "no_website_found" in rec.flags


@pytest.mark.asyncio
async def test_process_retailer_swallows_agent_exception():
    deps = _mock_deps(None)
    deps.agent.run = AsyncMock(side_effect=RuntimeError("boom"))

    rec = await process_retailer("Some Retailer", deps)

    assert rec.website is None
    assert rec.confidence == 0.0


@pytest.mark.asyncio
async def test_process_retailer_handles_unparseable_response():
    bad = MagicMock(spec=["text"])
    bad.text = "the agent rambled"
    deps = _mock_deps(bad)

    rec = await process_retailer("Some Retailer", deps)

    assert rec.website is None
    assert rec.confidence == 0.0


@pytest.mark.asyncio
async def test_process_retailer_handles_null_website():
    out = OrchestratorOutput(website=None)
    deps = _mock_deps(MagicMock(value=out))

    rec = await process_retailer("Asdfqwer Mart", deps)

    assert rec.website is None
    assert "no_website_found" in rec.flags
