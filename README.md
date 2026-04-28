# Retailer Data Validator

Microsoft-native pipeline that reads an Excel file of retailer names and enriches each row with website, "about" blurb, product categories, brands carried, sample prices, phone, email, and address. Low-confidence rows are routed to a separate `needs_review` sheet.

Stack: **Microsoft Agent Framework 1.2** + **Azure AI Foundry** (FoundryChatClient + hosted Web Search) + **Azure OpenAI** (gpt-4o orchestrator + gpt-4o-mini extraction) + **OpenPyXL**.

## Architecture

A real **orchestrator agent** decides per retailer which of three tools to call:

```
INPUT: retailer name
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ ORCHESTRATOR  Agent(FoundryChatClient, model=gpt-4o)    │
│                                                         │
│ tools = [                                               │
│   client.get_web_search_tool()  # Foundry hosted        │
│   scrape_retailer_site,         # @tool function        │
│   extract_retailer_fields,      # @tool function        │
│ ]                                                       │
│                                                         │
│ instructions: search → scrape → extract; skip aggregators│
│ response_format = OrchestratorOutput (Pydantic)         │
└────────────────────┬────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────────┐
│ LOCAL VALIDATOR (deterministic, rule-based)             │
│ phone normalization • confidence score • flags          │
└────────────────────┬────────────────────────────────────┘
                     ▼
                RetailerRecord  →  Excel
```

**Why an orchestrator?** Each retailer is messy in its own way (some need a search, some have an obvious domain, some have JS-heavy sites that scrape poorly). Letting gpt-4o decide which tool to call when, and how to recover, beats a hard-coded sequence on the long tail. Cost is ~3× the LLM tokens of a hard-coded pipeline but still cents per retailer.

**Why a deterministic validator after the agent?** Confidence scores from LLMs aren't calibrated. Phone-number normalization, domain-name matching, and field-presence checks are pure functions of the data — better to compute them locally than to ask the agent for them.

### Tool details

| Tool | Source | Purpose |
|---|---|---|
| Web search (Foundry-hosted) | `FoundryChatClient.get_web_search_tool()` | Find candidate URL for the retailer |
| `scrape_retailer_site(url)` | `@tool` in `src/tools.py` | Fetch `/`, `/about`, `/contact`, product pages; pull JSON-LD; cache for the next call |
| `extract_retailer_fields(name, url)` | `@tool` in `src/tools.py` | Read scraped pages from cache; one gpt-4o-mini call to `chat.completions.parse` returns `ExtractedRetailer` |

Token-efficiency trick: `scrape_retailer_site` returns only a 1-line summary to the orchestrator. The full scraped text never enters the orchestrator's context — it lives in a process-local dict that `extract_retailer_fields` reads on the next turn. Without this, scraped HTML would burn ~10× the orchestrator tokens.

### Pre-agent heuristic

Before invoking the agent, single-word alphanumeric retailer names (Sephora, Target, Walmart) are mapped to `https://www.<name>.com` and passed in the prompt as a `Likely website:` hint. The agent verifies via search before trusting it. This saves the agent a search call on roughly half of inputs.

## Setup

### 1. Provision Azure resources

- **Azure AI Foundry project** — create in Foundry portal; note the project endpoint.
- **Foundry Web Search connection** — add via Foundry portal → Project → Connected resources → Add → Web Search. `HostedWebSearchTool` uses this connection automatically.
- **Azure OpenAI** — deploy `gpt-4o` (orchestrator) and `gpt-4o-mini` (extraction) in the same Azure OpenAI resource attached to the project.

### 2. Auth

`DefaultAzureCredential` is used for both the orchestrator (FoundryChatClient) and the extraction client (Azure OpenAI). For local dev: `az login` once. In production: managed identity. No API keys.

### 3. Install + configure

```bash
pip install -r requirements.txt
cp .env.example .env       # fill in the values
az login                   # local dev only
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
| Foundry Web Search call | ~$0.005 | ~$5 |
| Orchestrator (gpt-4o, ~3 tool decisions) | ~$0.012 | ~$12 |
| Extraction (gpt-4o-mini) | ~$0.001 | ~$1 |
| Heuristic short-circuit on search (~50%) | -50% search only | -~$2.50 |
| **Total** | **~$0.013** | **~$13** |

## Tests

```bash
pytest tests/
```

Tests mock `Agent.run` so no Azure credentials are needed. Each test calls the real pipeline functions with a faked agent response.

## Code map

| File | Purpose |
|---|---|
| `src/main.py` | CLI entry point |
| `src/config.py` | Env-var loading |
| `src/agent.py` | `build_orchestrator(settings)` — wires FoundryChatClient + 3 tools |
| `src/tools.py` | Two `@tool`-decorated functions and their lazy-init clients |
| `src/pipeline.py` | `process_retailer` (heuristic + agent.run + post-filter + validate) and `run_pipeline` (concurrency wrapper) |
| `src/models.py` | Pydantic schemas (`OrchestratorOutput`, `ExtractedRetailer`, `RetailerRecord`, `PriceSample`) |
| `src/plugins/scraper.py` | HTTP fetch + JSON-LD parse — wrapped by `scrape_retailer_site` |
| `src/plugins/extractor.py` | gpt-4o-mini structured-output extraction — wrapped by `extract_retailer_fields` |
| `src/plugins/validator.py` | Phone normalization, confidence scoring, flags |
| `src/excel_io.py` | Excel read/write |
