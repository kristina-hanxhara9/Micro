from __future__ import annotations

import json
import logging

from openai import AsyncAzureOpenAI

from ..models import ExtractedRetailer

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You extract structured business information about a retailer from scraped web pages "
    "and JSON-LD structured data. Use ONLY the provided content — never invent details. "
    "If a field isn't supported, leave it null or empty.\n\n"
    "Rules:\n"
    "- `about`: ≤500 chars, drawn from the homepage or /about page.\n"
    "- `categories`: high-level product categories the retailer sells (e.g. 'electronics', "
    "  'apparel', 'home goods'). Up to 8.\n"
    "- `brands`: third-party brand names the retailer CARRIES (not their own house brand "
    "  unless it's distinct). Exact spelling. Up to 25.\n"
    "- `sample_prices`: up to 20 specific products. Prefer JSON-LD Product/Offer entries "
    "  (most reliable), then product detail pages, then the homepage. Include price ONLY "
    "  when explicitly shown in the source. If a product is mentioned without a price, "
    "  include it with `price: null`. Use the listed currency or default to USD.\n"
    "- `phone`, `email`, `address`: prefer the contact page; only what's explicitly listed."
)


def _summarize_json_ld(blobs: list[dict]) -> str:
    """Pull just the fields we care about from JSON-LD so we don't bloat the prompt."""
    keep_types = {"Product", "Offer", "Organization", "LocalBusiness", "Store"}
    out: list[dict] = []
    for blob in blobs:
        types = blob.get("@type")
        if isinstance(types, list):
            type_set = set(types)
        elif isinstance(types, str):
            type_set = {types}
        else:
            continue
        if not type_set & keep_types:
            continue
        slim = {k: blob.get(k) for k in (
            "@type", "name", "brand", "category",
            "offers", "price", "priceCurrency",
            "telephone", "email", "address", "description",
        ) if blob.get(k) is not None}
        out.append(slim)
        if len(out) >= 50:
            break
    if not out:
        return ""
    return "\n\nJSON-LD structured data:\n" + json.dumps(out, ensure_ascii=False)[:8000]


def _build_user_prompt(
    retailer: str,
    pages: list[tuple[str, str]],
    json_ld_blobs: list[dict],
) -> str:
    blocks = "\n\n".join(f"--- {url} ---\n{text}" for url, text in pages)
    return f"Retailer: {retailer}\n\nScraped pages:\n{blocks}{_summarize_json_ld(json_ld_blobs)}"


async def extract_retailer(
    client: AsyncAzureOpenAI,
    deployment: str,
    retailer: str,
    pages: list[tuple[str, str]],
    json_ld_blobs: list[dict] | None = None,
) -> ExtractedRetailer:
    if not pages:
        return ExtractedRetailer()
    json_ld_blobs = json_ld_blobs or []

    try:
        resp = await client.beta.chat.completions.parse(
            model=deployment,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(retailer, pages, json_ld_blobs)},
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
        return await _extract_json_fallback(client, deployment, retailer, pages, json_ld_blobs)


async def _extract_json_fallback(
    client: AsyncAzureOpenAI,
    deployment: str,
    retailer: str,
    pages: list[tuple[str, str]],
    json_ld_blobs: list[dict],
) -> ExtractedRetailer:
    schema_hint = json.dumps(ExtractedRetailer.model_json_schema(), indent=2)
    resp = await client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT + f"\n\nReturn JSON matching this schema:\n{schema_hint}"},
            {"role": "user", "content": _build_user_prompt(retailer, pages, json_ld_blobs)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        return ExtractedRetailer.model_validate_json(raw)
    except Exception:
        return ExtractedRetailer()
