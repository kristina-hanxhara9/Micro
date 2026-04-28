from __future__ import annotations

from urllib.parse import urlparse

import phonenumbers
from rapidfuzz import fuzz

from ..models import ExtractedRetailer, RetailerRecord


def normalize_phone(raw: str | None, default_region: str = "US") -> tuple[str | None, bool]:
    if not raw:
        return None, False
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException:
        return raw, False
    if not phonenumbers.is_valid_number(parsed):
        return raw, False
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), True


def score_record(
    name: str,
    website: str | None,
    extracted: ExtractedRetailer,
    sources: list[str],
) -> RetailerRecord:
    flags: list[str] = []
    confidence = 0.0

    if website:
        confidence += 0.3
        host = urlparse(website).hostname or ""
        root = host.replace("www.", "").split(".")[0] if host else ""
        if root and fuzz.token_set_ratio(name.lower(), root.lower()) >= 60:
            confidence += 0.2
        else:
            flags.append("domain_mismatch")
    else:
        flags.append("no_website_found")

    phone_norm, phone_ok = normalize_phone(extracted.phone)
    if extracted.phone:
        if phone_ok:
            confidence += 0.1
        else:
            flags.append("phone_invalid")

    if extracted.address and len(extracted.address) >= 10:
        confidence += 0.1
    elif extracted.address:
        flags.append("address_short")

    if extracted.brands or extracted.categories:
        confidence += 0.2
    else:
        flags.append("no_products_found")

    if extracted.about and len(extracted.about) >= 50:
        confidence += 0.1
    elif not extracted.about:
        flags.append("no_about_text")

    if not sources:
        flags.append("no_sources_scraped")

    return RetailerRecord(
        name=name,
        website=website,
        about=extracted.about,
        categories=extracted.categories,
        brands=extracted.brands,
        sample_prices=extracted.sample_prices,
        phone=phone_norm,
        email=extracted.email,
        address=extracted.address,
        confidence=round(min(confidence, 1.0), 2),
        flags=flags,
        sources=sources,
    )
