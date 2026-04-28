from unittest.mock import MagicMock

import pytest

from src.models import OfficialSiteAnswer
from src.plugins.search import FoundryGroundingSearch, _heuristic_domain, _is_aggregator


def test_heuristic_catches_clean_names():
    assert _heuristic_domain("Sephora") == "https://www.sephora.com"
    assert _heuristic_domain("Target") == "https://www.target.com"


def test_heuristic_skips_ambiguous_names():
    # Names with punctuation/spaces that don't map cleanly should fall through
    # to the agent, not produce a wrong .com guess.
    assert _heuristic_domain("B&H Photo") is None
    assert _heuristic_domain("Crate & Barrel") is None


def test_heuristic_rejects_too_short_or_long():
    assert _heuristic_domain("AB") is None
    assert _heuristic_domain("a" * 30) is None


def test_aggregator_detection():
    assert _is_aggregator("https://www.yelp.com/biz/joe")
    assert _is_aggregator("https://en.wikipedia.org/wiki/Target")
    assert _is_aggregator("https://www.amazon.com/store/something")
    assert not _is_aggregator("https://www.bestbuy.com")


@pytest.mark.asyncio
async def test_short_circuit_skips_agent_call():
    search = FoundryGroundingSearch.__new__(FoundryGroundingSearch)
    search._openai_client = MagicMock()
    search._agent_name = "agent"
    search._agent_version = "1"
    search._project_client = MagicMock()
    search._settings = MagicMock()
    search._lock = None  # unused on this path

    url = await search.find_official_site("Sephora")
    assert url == "https://www.sephora.com"
    search._openai_client.responses.parse.assert_not_called()


@pytest.mark.asyncio
async def test_calls_agent_for_ambiguous_name():
    search = FoundryGroundingSearch.__new__(FoundryGroundingSearch)
    fake_resp = MagicMock()
    fake_resp.output_parsed = OfficialSiteAnswer(
        website="https://www.bhphotovideo.com",
        reasoning="exact retailer match",
    )
    fake_client = MagicMock()
    fake_client.responses.parse.return_value = fake_resp
    search._openai_client = fake_client
    search._agent_name = "agent"
    search._agent_version = "1"
    search._project_client = MagicMock()
    search._settings = MagicMock()

    url = await search.find_official_site("B&H Photo")
    assert url == "https://www.bhphotovideo.com"
    fake_client.responses.parse.assert_called_once()


@pytest.mark.asyncio
async def test_rejects_aggregator_response():
    search = FoundryGroundingSearch.__new__(FoundryGroundingSearch)
    fake_resp = MagicMock()
    fake_resp.output_parsed = OfficialSiteAnswer(
        website="https://www.yelp.com/biz/joes-hardware",
        reasoning="found on yelp",
    )
    fake_client = MagicMock()
    fake_client.responses.parse.return_value = fake_resp
    search._openai_client = fake_client
    search._agent_name = "agent"
    search._agent_version = "1"
    search._project_client = MagicMock()
    search._settings = MagicMock()

    url = await search.find_official_site("Joe's Hardware")
    assert url is None


@pytest.mark.asyncio
async def test_returns_none_when_agent_returns_null():
    search = FoundryGroundingSearch.__new__(FoundryGroundingSearch)
    fake_resp = MagicMock()
    fake_resp.output_parsed = OfficialSiteAnswer(website=None, reasoning="not found")
    fake_client = MagicMock()
    fake_client.responses.parse.return_value = fake_resp
    search._openai_client = fake_client
    search._agent_name = "agent"
    search._agent_version = "1"
    search._project_client = MagicMock()
    search._settings = MagicMock()

    url = await search.find_official_site("Asdfqwer Mart")
    assert url is None


@pytest.mark.asyncio
async def test_swallows_agent_exception():
    search = FoundryGroundingSearch.__new__(FoundryGroundingSearch)
    fake_client = MagicMock()
    fake_client.responses.parse.side_effect = RuntimeError("network down")
    search._openai_client = fake_client
    search._agent_name = "agent"
    search._agent_version = "1"
    search._project_client = MagicMock()
    search._settings = MagicMock()

    url = await search.find_official_site("Some Retailer With Spaces")
    assert url is None
