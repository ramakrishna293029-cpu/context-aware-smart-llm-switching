# Context-Aware Smart LLM Switching for Cost & Performance Optimization

A conversational AI product with an **Analyzer-LLM-first routing brain**: every user message is read by a real **Analyzer LLM** which decides — *answer it myself* (self) or *switch to a more capable model* (switch) — with the reasoning, models, real token usage, latency and cost of both calls recorded and shown end to end.

**Simple query → answered by the analyzer itself (cheap, fast) · Complex coding/debugging/math → switched to the most capable real model.**

## Features

- **Analyzer LLM decides routing** — no keyword rules. The analyzer receives the query + relevant conversation context and returns a structured decision: `answer_mode` (`self`/`switch`), `context_relevant`, `reason`, `target_model` and its own real answer when it chooses `self`. Analyzer failures are surfaced as errors — never faked answers.
- **Self vs switch** — greetings, casual chat, simple facts and math are answered directly by the analyzer (one cheap call); hard coding/debugging, proofs and architecture questions are switched to the best available real model. Follow-ups only carry conversation context when the analyzer marks them context-dependent.
- **4 routing strategies** — `balanced`, `lowest_cost`, `fastest`, `highest_quality` (switchable per request; guides the analyzer's target choice and the fallback scoreboard).
- **Real multi-provider support** — OpenAI, Azure, OpenRouter, Groq and any OpenAI-compatible endpoint via one adapter. Real streaming (SSE) with provider-reported token usage and TTFT; typed provider errors; automatic **fallback chain** to the next-best real model when the target fails.
- **Honest telemetry** — analyzer call (model, tokens, latency, TTFT, cost) and final call (model, tokens, latency, TTFT, cost) are persisted per request from provider usage. When a provider omits usage, the UI shows **"Unavailable"** — nothing is ever estimated or fabricated.
- **100% real-data dashboard** — requests, success rate, latency (final and analyzer+final total), real cost, real tokens, self vs switched decisions, analyzer model usage, savings vs the strongest model at the same actual token usage, fallbacks, feedback, live auto-refresh.
- **Honest demo mode** — without API keys the app runs on clearly-labelled simulated models (tagged `DEMO`); real responses are tagged `REAL`. Demo models are only registered when no real provider is configured.
- **Request inspector** — click any history row for the full story: analyzer decision + reason, routed vs served model, fallback, both calls' tokens/latency/cost, totals, candidate scoreboard.
- **Budgets** — daily/monthly USD caps (429 when exhausted) and `MAX_COST_PER_REQUEST` enforced against the analyzer's *measured* input tokens.

## Architecture

```
USER
 │
 ▼
FRONTEND (static HTML/CSS/JS)      ← chat UI + strategy selector + inspector + live dashboard
 │  /api/chat (SSE)  /api/analyze  /api/requests/{id}  /api/feedback  /api/stats
 ▼
API LAYER (FastAPI)                ← streaming, budgets, rate limiting, structured logs
 │
 ▼
ANALYZER LLM (app/analyzer_llm.py) ← the routing DECISION brain (a real configured model)
 │   decides: answer itself? context relevant? switch to which model?
 │   answers simple requests directly (self)
 ▼
MODEL SWITCH (only when the analyzer says "switch")
 │   target model from the analyzer + fallback chain
 │   scoreboard (router.py) provides display info + fallback ordering only — it never overrides the analyzer
 ▼
LLM ADAPTER LAYER                  ← stream() + generate(), typed errors, TTFT, provider usage
 ├── OpenAI-compatible adapter     ← OpenAI, Azure, OpenRouter, Groq, Ollama…
 └── Mock adapter                  ← honest demo mode
 ▼
METRICS TRACKER                    ← analyzer + final telemetry, decisions, feedback (schema v3)
 ▼
SQLite                             ← persistent metrics + request inspector data
```

## Components

| Component | Responsibility |
|---|---|
| `app/analyzer_llm.py` | Builds the analyzer prompt (model pool, decision rules, JSON contract, conversation), calls the configured Analyzer LLM, parses/validates the structured decision, resolves the target model. |
| `app/analyzer.py` | Deterministic analysis profile (task, complexity, reasoning) — used only for the display scoreboard, not for routing decisions. |
| `app/router.py` | 7-factor scoreboard + strategy profiles + fallback ordering (display/resilience only). |
| `app/registry.py` | Declarative model metadata (provider, prices, latency, capability, context window); `KNOWN_MODELS` table with tier defaults; auto-mode demo exclusion. |
| `app/context.py` | Builds the LLM message list with cost-aware history trimming (`MAX_CONTEXT_TOKENS`) and system prompt. |
| `app/adapters/` | `LLMAdapter` interface with `generate()`/`stream()`, TTFT measurement, `usage_source` (`provider`/`unavailable`/`demo`), typed errors; mock adapter. |
| `app/tracker.py` | SQLite persistence (schema v3): analyzer + final telemetry, decisions, budgets, distributions, feedback, dashboard aggregations. |
| `app/main.py` | FastAPI app: SSE chat (`analyzer` → `routing` → `delta` → `done` events), chat, analyze, budgets, rate limiting, CORS. |
| `static/` | Frontend: streaming chat with analyzer/final model badges and SELF/SWITCH tags, request inspector, auto-refreshing dashboard. |

## Getting started

### 1. Install

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

### 2. Configure

```bash
copy .env.example .env        # Windows
# cp .env.example .env       # Linux/macOS
```

Without any API keys the app runs in **demo mode** (clearly labelled). To use **real LLMs**, add at least one provider key to `.env`. Each configured provider registers a *fast* tier (cheap/quick) and a *powerful* tier (strong/capable):

| Provider | Env vars | Default fast / powerful |
|---|---|---|
| OpenAI | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_FAST_MODEL`, `OPENAI_POWERFUL_MODEL` | `gpt-4o-mini` / `gpt-4o` |
| Groq | `GROQ_API_KEY`, `GROQ_BASE_URL`, `GROQ_FAST_MODEL`, `GROQ_POWERFUL_MODEL` | `llama-3.1-8b-instant` / `llama-3.3-70b-versatile` |
| OpenRouter | `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_FAST_MODEL`, `OPENROUTER_POWERFUL_MODEL` | `meta-llama/llama-3.1-8b-instruct` / `anthropic/claude-3.5-sonnet` |
| Any OpenAI-compatible (Azure, Ollama…) | `EXTRA_PROVIDERS` JSON array with `name`, `base_url`, `api_key`, `fast_model`, `powerful_model` | — |

`MOCK_MODELS_ENABLED` controls demo models: `auto` (default — demo only when no real provider is configured), `true` (always), `false` (never).

**Analyzer LLM** — `ANALYZER_MODEL=auto` (default) uses the cheapest available real model; set it to a registered `model_id` (e.g. `openrouter-fast`) to pin it. `ANALYZER_MAX_OUTPUT_TOKENS` bounds the analyzer's JSON decision output.

**Budget controls** (all optional, 0 = unlimited): `MAX_COST_PER_REQUEST` (USD — switch targets whose expected cost, from the analyzer's *measured* input tokens, exceed the cap are filtered; 429 when nothing fits), `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD` (UTC day/month; requests blocked with 429 when exhausted).

**Never commit `.env`** — it is git-ignored, and API keys never reach the frontend.

### 3. Run

```bash
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Try `Hi`, `What is 5+5?` (self-answered) and a debugging/architecture question (switched), then open the **Dashboard** tab — it refreshes live and every row opens the full decision inspector.

### Docker

```bash
docker build -t smart-llm-router .
docker run -p 8000:8000 --env-file .env smart-llm-router
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/chat/stream` | SSE chat: `analyzer` (decision + analyzer telemetry) → `routing` (target, on switch) → `delta`… → `done` (+`error` events on fallback attempts / analyzer failure) |
| `POST /api/chat` | Non-streaming chat (fallback used by the UI) |
| `POST /api/analyze` | Run the Analyzer LLM and return its decision + candidate scoreboard (no final answer) |
| `POST /api/feedback` | `{request_id, rating: 1\|-1}` |
| `GET /api/requests/{id}` | Full request detail for the inspector (analyzer + final telemetry, decision, fallback, totals) |
| `GET /api/stats` | Dashboard analytics (real recorded data only) + budget status |
| `GET /api/models` | Registered models and metadata |
| `GET /api/history` | Recent requests |
| `GET /health` | Liveness + mode + architecture |

## Telemetry honesty

- Tokens/cost always come from provider usage; `usage_source` is `provider`, `unavailable` (provider omitted usage — UI shows **"Unavailable"**), or `demo`.
- For self answers the analyzer call *is* the final answer: its usage is recorded as the analyzer call, and the final-model token fields are null (no double counting).
- Dashboard savings = baseline (strongest model charged at the request's *actual* token usage) − actual cost, all from stored records.

## Testing

```bash
python -m pytest tests/test_api.py -v        # 27 API tests: analyzer decision, self/switch, streaming, fallback, inspector, stats, budgets, guards
python tests/test_real_providers.py          # real-provider flow against the fake OpenAI server
python tests/test_real_providers.py fallback # target fails -> fallback chain verified
```

The fake OpenAI-compatible provider in `tests/` plays both the analyzer (returns structured JSON decisions) and the final model, with failure simulation — the full pipeline is exercised without spending API credits.

## Project structure

```
├── app/
│   ├── main.py          # FastAPI app + endpoints
│   ├── config.py        # .env settings (providers, weights, budgets, analyzer)
│   ├── analyzer_llm.py  # the Analyzer LLM decision brain (prompt + parsing + target resolution)
│   ├── analyzer.py      # deterministic analysis profile (display scoreboard only)
│   ├── router.py        # scoreboard + strategy profiles + fallback ordering
│   ├── registry.py      # model registry + KNOWN_MODELS metadata
│   ├── tracker.py       # SQLite metrics + feedback (schema v3)
│   ├── context.py       # cost-aware history trimming + system prompt
│   ├── schemas.py       # API contracts
│   └── adapters/        # LLM provider adapters (openai-compatible, mock)
├── static/              # frontend (chat + strategy selector + inspector + dashboard)
├── tests/               # fake provider + API/integration tests
├── data/                # SQLite database (git-ignored, auto-created)
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Roadmap

Adaptive analyzer selection (pick the cheapest model that still decides well), semantic caching of analyzer decisions, A/B strategy testing, and advanced analytics.
