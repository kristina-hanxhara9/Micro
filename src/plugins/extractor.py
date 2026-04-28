from __future__ import annotations

import json
import logging

from openai import AsyncAzureOpenAI

from ..models import ExtractedRetailer

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You extract structured business information about a retailer from scraped web pages. "
    "Use ONLY the provided text — never invent details. If a field isn't supported by the "
    "text, leave it null or empty. Keep `about` under 500 characters. Limit `sample_prices` "
    "to 5 entries that appear directly in the text. Return brand names exactly as written."
)


def _build_user_prompt(retailer: str, pages: list[tuple[str, str]]) -> str:
    blocks = "\n\n".join(f"--- {url} ---\n{text}" for url, text in pages)
    return f"Retailer: {retailer}\n\nScraped pages:\n{blocks}"


async def extract_retailer(
    client: AsyncAzureOpenAI,
    deployment: str,
    retailer: str,
    pages: list[tuple[str, str]],
) -> ExtractedRetailer:
    if not pages:
        return ExtractedRetailer()

    try:
        resp = await client.beta.chat.completions.parse(
            model=deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(retailer, pages)},
            ],
            response_format=ExtractedRetailer,
            temperature=0,
        )
        parsed = resp.choices[0].message.parsed
        if parsed is None:
            log.warning("Parsed extraction was None for %s; falling back to empty.", retailer)
            return ExtractedRetailer()
        return parsed
    except Exception as e:
        # Some Azure API versions reject `response_format` on `.parse`; fall back to JSON mode.
        log.warning("Structured parse failed for %s (%s); using JSON fallback.", retailer, e)
        return await _extract_json_fallback(client, deployment, retailer, pages)


async def _extract_json_fallback(
    client: AsyncAzureOpenAI,
    deployment: str,
    retailer: str,
    pages: list[tuple[str, str]],
) -> ExtractedRetailer:
    schema_hint = json.dumps(ExtractedRetailer.model_json_schema(), indent=2)
    resp = await client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + f"\n\nReturn JSON matching this schema:\n{schema_hint}"},
            {"role": "user", "content": _build_user_prompt(retailer, pages)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        return ExtractedRetailer.model_validate_json(raw)
    except Exception:
        return ExtractedRetailer()
