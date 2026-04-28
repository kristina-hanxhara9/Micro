from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class PriceSample(BaseModel):
    item: str
    price: float | None = None
    currency: str = "USD"


class BingResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str


class ExtractedRetailer(BaseModel):
    """LLM-facing schema. No confidence/flags here — those are computed locally."""

    about: str | None = Field(default=None, description="Short description, ≤500 chars.")
    categories: list[str] = Field(default_factory=list, description="What they sell, e.g. ['electronics', 'home goods'].")
    brands: list[str] = Field(default_factory=list, description="Named brands carried.")
    sample_prices: list[PriceSample] = Field(
        default_factory=list,
        description="Up to 20 specific products with prices when prices are visible. "
        "If a product is mentioned without a price, leave price null.",
    )
    phone: str | None = None
    email: str | None = None
    address: str | None = None


class RetailerRecord(BaseModel):
    name: str
    website: str | None = None
    about: str | None = None
    categories: list[str] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    sample_prices: list[PriceSample] = Field(default_factory=list)
    phone: str | None = None
    email: EmailStr | str | None = None
    address: str | None = None
    confidence: float = 0.0
    flags: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
