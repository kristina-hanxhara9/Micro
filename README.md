# Retailer Data Validator

Microsoft-native pipeline that reads an Excel file of retailer names and enriches each row with website, "about" blurb, product categories, brands carried, sample prices, phone, email, and address. Low-confidence rows are routed to a separate `needs_review` sheet.

Stack: **Semantic Kernel + Azure OpenAI (gpt-4o-mini) + Bing Search v7 / Google CSE + OpenPyXL**.

## Architecture

Per retailer the pipeline runs a fixed sequence (no auto-planner) for predictability and cost control:

1. **Search** — query `"{name} official website"`. Tries primary engine first (Bing or Google), falls back to the other if results are empty or the picker can't find a plausible match. Either engine alone works; configuring both gives best coverage.
2. **Pick domain** — fuzzy domain-name match first; on miss, a tiny SK chat call (via `Kernel` + `AzureChatCompletion`) picks the best result and skips Yelp/BBB/Wikipedia/socials.
3. **Scrape** — `requests` + BS4 fetches `/`, `/about`, `/contact`, `/products`, `/shop`, `/store`, `/collections`, `/catalog`, `/menu`. Then crawls up to 5 individual product pages discovered via internal links (`/product/...`, `/p/...`, `/item/...`, `/collections/.../products/...`). Pages cached in SQLite by URL for 7 days.
4. **JSON-LD harvest** — schema.org structured data (`Product`, `Offer`, `Organization`, `LocalBusiness`) is parsed directly out of `<script type="application/ld+json">` tags. This is the gold standard for product names + prices.
5. **Extract** — single Azure OpenAI call with Pydantic structured output (`client.beta.chat.completions.parse`) using BOTH the trimmed page text and the JSON-LD blobs → `ExtractedRetailer` (about, categories, brands, up to 20 products w/ prices, phone, email, address).
6. **Validate** — rule-based confidence scoring + flagging (no LLM): website found, domain matches name, phone parses, brands/categories present, etc.

Why SK *and* the OpenAI SDK? The Kernel handles the chat-style domain-pick call (and is the entry point for adding `@kernel_function` plugins or planners later). The OpenAI SDK is used directly for the extraction call because Azure OpenAI's `.parse()` API gives the cleanest Pydantic-typed structured output. Both hit the same Azure deployment.

## Search backend setup

You need at least one. Configuring both is recommended — they cover different long tails.

**Bing Search v7** (Azure resource):
- Create a "Bing Search v7" resource in Azure portal.
- Copy the key to `BING_SEARCH_KEY`.
- Pricing: S1 tier = $3 per 1,000 queries.

**Google Custom Search JSON API**:
- In Google Cloud, enable "Custom Search API" and create an API key → `GOOGLE_API_KEY`.
- At https://programmablesearchengine.google.com create a search engine that searches the entire web. Copy the engine ID → `GOOGLE_CSE_ID`.
- Pricing: 100 queries/day free, then $5 per 1,000 (cap 10k/day).

Set `SEARCH_PRIMARY=bing` (default) or `SEARCH_PRIMARY=google` to choose which engine is tried first.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env       # fill in your Azure + Bing keys
```

## Run

```bash
python -m src.main --input retailers.xlsx --output enriched.xlsx
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--input` | required | input `.xlsx`, retailer names in column A (header optional) |
| `--output` | required | output `.xlsx` with two sheets: `enriched`, `needs_review` |
| `--concurrency` | `10` | retailers processed in parallel |
| `--threshold` | `0.7` | confidence cutoff for the `enriched` sheet |
| `--name-column` | `name` | column header containing retailer names |

## Cost

~$0.004 per retailer (gpt-4o-mini + Bing S1). 1,000 retailers ≈ **$4** and ~6 minutes at concurrency 10.

## Tests

```bash
pytest tests/
```

Scraper tests use cached HTML fixtures and don't hit the network.
