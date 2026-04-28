# Retailer Data Validator

Microsoft-native pipeline that reads an Excel file of retailer names and enriches each row with website, "about" blurb, product categories, brands carried, sample prices, phone, email, and address. Low-confidence rows are routed to a separate `needs_review` sheet.

Stack: **Azure AI Foundry Agent Service (Grounding with Bing Search) + Azure OpenAI (gpt-4o + gpt-4o-mini) + OpenPyXL**.

## Architecture

Per retailer the pipeline runs a fixed sequence (no auto-planner) for predictability and cost control:

1. **Heuristic shortcut** — if the name maps cleanly to `<name>.com` (e.g. "Sephora" → sephora.com), return that URL with no API call. Saves ~50% of grounding calls.
2. **Foundry agent + Grounding with Bing** — for ambiguous names, one shared agent (created at startup, deleted at shutdown) is queried via the **Responses API** with `responses.parse(text_format=OfficialSiteAnswer)`. The agent uses `BingGroundingTool` to search the web and returns a typed `{ website, reasoning }`. Aggregator domains (Yelp, Wikipedia, Amazon, etc.) are rejected post-hoc.
3. **Scrape** — `requests` + BS4 fetches `/`, `/about`, `/contact`, `/products`, `/shop`, `/store`, `/collections`, `/catalog`, `/menu`. Then crawls up to 5 individual product pages discovered via internal links. Pages cached in SQLite by URL for 7 days.
4. **JSON-LD harvest** — schema.org structured data (`Product`, `Offer`, `Organization`, `LocalBusiness`) is parsed directly out of `<script type="application/ld+json">` tags. Gold standard for product names + prices.
5. **Extract** — single Azure OpenAI call to **gpt-4o-mini** with Pydantic structured output (`client.beta.chat.completions.parse`) using both trimmed page text and JSON-LD blobs → `ExtractedRetailer` (about, categories, brands, up to 20 products w/ prices, phone, email, address).
6. **Validate** — rule-based confidence scoring + flagging (no LLM): website found, domain matches name, phone parses, brands/categories present, etc.

### Why two Azure OpenAI deployments?

`BingGroundingTool` does **not support gpt-4o-mini**. Supported models include gpt-4o, gpt-4-turbo, and gpt-4. So:

- `AZURE_OPENAI_DEPLOYMENT_AGENT` = **gpt-4o** — used by the Foundry agent for the grounding-search call.
- `AZURE_OPENAI_DEPLOYMENT_EXTRACTION` = **gpt-4o-mini** — used for the cheap structured extraction.

Both deployments live in the same Azure OpenAI resource.

## Setup

### 1. Provision Azure resources

- **Azure AI Foundry project** — create in Foundry portal. Note the project endpoint.
- **Azure OpenAI** — deploy `gpt-4o` and `gpt-4o-mini` in the same resource.
- **Grounding with Bing Search** — create a "Grounding with Bing Search" resource in Azure portal. In your Foundry project, add a Connection to it. Note the connection ID (`/subscriptions/.../connections/<name>`).

### 2. Auth

`DefaultAzureCredential` is used for the Foundry client. For local dev, run `az login` once. In production, use a managed identity.

The Azure OpenAI extraction client uses an API key by default. To use AAD instead, leave `AZURE_OPENAI_API_KEY` blank — the code falls back to `DefaultAzureCredential` with a bearer token provider.

### 3. Install + configure

```bash
pip install -r requirements.txt
cp .env.example .env       # fill in the values
az login                   # if using AAD locally
```

### 4. Run

```bash
python -m src.main --input retailers.xlsx --output enriched.xlsx
```

| Flag | Default | Description |
|---|---|---|
| `--input` | required | input `.xlsx`, retailer names in column A |
| `--output` | required | output `.xlsx` with two sheets: `enriched`, `needs_review` |
| `--concurrency` | `10` | retailers processed in parallel |
| `--threshold` | `0.7` | confidence cutoff for `enriched` |
| `--name-column` | `name` | column header containing retailer names |

## Cost (April 2026 pricing)

| Item | Per retailer | 1,000 retailers |
|---|---|---|
| Grounding with Bing transaction | $0.014 | $14 |
| Agent (gpt-4o) call | ~$0.005 | $5 |
| Heuristic short-circuit (~50% hit rate) | -50% above | ~-$10 |
| Extraction (gpt-4o-mini) | ~$0.001 | $1 |
| **Total** | **~$0.012** | **~$11** |

## Compliance note

Microsoft documents that **data sent to Grounding with Bing Search leaves the Azure compliance boundary**: the grounding service is not subject to the same data-processing terms as the rest of Foundry. Names sent for lookup will go to Bing. If your retailer names are sensitive, raise this with your security team before running at scale.

## Tests

```bash
pytest tests/
```

Tests mock the Foundry agent — no Azure credentials required to run them.

## Migration note (v1 → v2)

The old standalone Bing Search v7 API was retired Aug 11, 2025. v2 of this pipeline removes:

- `BING_SEARCH_KEY`, `BING_SEARCH_ENDPOINT`, `GOOGLE_API_KEY`, `GOOGLE_CSE_ID`, `SEARCH_PRIMARY` (env vars)
- `kernel_setup.py`, `semantic-kernel` dependency
- `BingSearch`, `GoogleCseSearch`, `SearchDispatcher` classes

Replaced by a single `FoundryGroundingSearch` that owns one shared agent and uses the Responses API.
