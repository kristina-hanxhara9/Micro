from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import requests
from rapidfuzz import fuzz
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import ChatHistory

from ..config import Settings
from ..kernel_setup import CHAT_SERVICE_ID
from ..models import BingResult

log = logging.getLogger(__name__)


class BingSearch:
    def __init__(self, settings: Settings) -> None:
        self._endpoint = settings.bing_search_endpoint
        self._headers = {"Ocp-Apim-Subscription-Key": settings.bing_search_key}
        self._timeout = settings.request_timeout_s
        # Bing free tier caps at 3 QPS; one global gate keeps us under it
        # regardless of asyncio concurrency.
        self._gate = asyncio.Semaphore(max(1, int(settings.bing_qps)))

    async def search(self, query: str, count: int = 5) -> list[BingResult]:
        async with self._gate:
            return await asyncio.to_thread(self._search_sync, query, count)

    def _search_sync(self, query: str, count: int) -> list[BingResult]:
        params = {"q": query, "count": count, "responseFilter": "Webpages", "mkt": "en-US"}
        r = requests.get(self._endpoint, headers=self._headers, params=params, timeout=self._timeout)
        r.raise_for_status()
        webpages = r.json().get("webPages", {}).get("value", [])
        results: list[BingResult] = []
        for w in webpages[:count]:
            try:
                results.append(BingResult(title=w["name"], url=w["url"], snippet=w.get("snippet", "")))
            except Exception:
                continue
        return results


def _heuristic_pick(retailer: str, results: list[BingResult]) -> int | None:
    """Fuzzy-match retailer name against the result domain root.
    Used as a fallback (and a sanity cross-check) for the LLM picker."""
    if not results:
        return None
    best_idx, best_score = 0, -1
    for i, r in enumerate(results):
        host = urlparse(str(r.url)).hostname or ""
        root = host.replace("www.", "").split(".")[0]
        score = fuzz.token_set_ratio(retailer.lower(), root.lower())
        # Penalize known directory/aggregator domains.
        if any(bad in host for bad in ("yelp.", "yellowpages.", "wikipedia.", "facebook.", "linkedin.", "amazon.", "bbb.")):
            score -= 40
        if score > best_score:
            best_idx, best_score = i, score
    return best_idx if best_score > 30 else None


async def pick_official_site(
    kernel: Kernel,
    retailer: str,
    results: list[BingResult],
) -> str | None:
    if not results:
        return None

    # Cheap heuristic first; saves the LLM call ~80% of the time.
    h_idx = _heuristic_pick(retailer, results)
    if h_idx is not None:
        host = urlparse(str(results[h_idx].url)).hostname or ""
        root = host.replace("www.", "").split(".")[0]
        if fuzz.token_set_ratio(retailer.lower(), root.lower()) >= 80:
            return str(results[h_idx].url)

    listing = "\n".join(
        f"{i}. {r.title} — {r.url}\n   {r.snippet}" for i, r in enumerate(results)
    )
    prompt = (
        f"Retailer: {retailer}\n\n"
        f"Search results:\n{listing}\n\n"
        "Return ONLY the integer index (0-based) of the result that is the retailer's "
        "OWN official website. Skip directories (Yelp, BBB, Yellow Pages), Wikipedia, "
        "social media, and resellers. If none look official, return -1."
    )

    try:
        chat: AzureChatCompletion = kernel.get_service(CHAT_SERVICE_ID)  # type: ignore[assignment]
        history = ChatHistory()
        history.add_user_message(prompt)
        settings = chat.instantiate_prompt_execution_settings(
            service_id=CHAT_SERVICE_ID, temperature=0, max_tokens=4,
        )
        response = await chat.get_chat_message_content(chat_history=history, settings=settings)
        raw = (response.content or "").strip()
        idx = int(raw.split()[0])
    except Exception as e:
        log.warning("LLM domain pick failed for %s: %s", retailer, e)
        return str(results[h_idx].url) if h_idx is not None else None

    if 0 <= idx < len(results):
        return str(results[idx].url)
    return None
