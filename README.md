# Retailer Data Validator

Microsoft-native pipeline that reads an Excel file of retailer names and enriches each row with website, "about" blurb, product categories, brands carried, sample prices, phone, email, and address. Low-confidence rows are routed to a separate `needs_review` sheet.

Stack: **Semantic Kernel + Azure OpenAI (gpt-4o-mini) + Bing Search v7 + OpenPyXL**.

## Architecture

Per retailer the pipeline runs a fixed sequence (no auto-planner) for predictability and cost control:

1. **Search** — Bing v7 query: `"{name} official website"`, top 5 results.
2. **Pick domain** — fuzzy domain-name match first; on miss, a tiny SK chat call (via `Kernel` + `AzureChatCompletion`) picks the best result.
3. **Scrape** — `requests` + BS4 fetch of `/`, `/about`, `/contact`, `/products`. Pages cached in SQLite by URL.
4. **Extract** — single Azure OpenAI call with Pydantic structured output (`client.beta.chat.completions.parse`) → `ExtractedRetailer`.
5. **Validate** — rule-based confidence scoring + flagging (no LLM).

Why SK *and* the OpenAI SDK? The Kernel handles the chat-style domain-pick call (and is the entry point for adding `@kernel_function` plugins or planners later). The OpenAI SDK is used directly for the extraction call because Azure OpenAI's `.parse()` API gives the cleanest Pydantic-typed structured output. Both hit the same Azure deployment.

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
