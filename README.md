# Context-Aware Smart LLM Switching for Cost & Performance Optimization

An intelligent LLM orchestration prototype. It **understands the query first, then decides which model should answer it** — balancing quality, reasoning needs, latency, token usage and cost across multiple LLMs.

**Simple query → cheap/fast model · Coding/medium query → balanced model · Complex reasoning → powerful model.**

## Architecture

## Architecture

```
USER
 │
 ▼
FRONTEND (static HTML/CSS/JS)      ← chat UI + routing transparency + dashboard
 │  /api/chat  /api/feedback  /api/stats
 ▼
API LAYER (FastAPI)
 │
 ▼
CONTEXT ANALYZER                   ← rule-based complexity/task/reasoning profile
 │
 ▼
SMART ROUTER                       ← multi-factor scoring over available models
 │
 ├── MODEL REGISTRY                ← declarative metadata per model
 ▼
LLM ADAPTER LAYER                  ← common interface; providers plug in
 ├── OpenAI-compatible adapter     ← OpenAI, Azure, OpenRouter, Groq, Ollama…
 └── Mock adapter                  ← honest demo mode without API keys
 ▼
RESPONSE + METRICS TRACKER         ← tokens, cost, latency, success per request
 │
 ▼
SQLite                             ← persistent metrics + user feedback
 │
 ▼
DASHBOARD                          ← savings, model distribution, latency…
```

## Components

| Component | Responsibility |
|---|---|
| `app/analyzer.py` | Classifies task type (coding/math/reasoning/creative/factual/general), estimates complexity 0–1 and reasoning requirement. Fully transparent: emits a human-readable signal list. |
| `app/registry.py` | Declarative model metadata: provider, prices, latency, capability scores, context window, availability. Add/remove models without touching the router. |
| `app/router.py` | Scores every available model on **quality suitability, complexity compatibility, cost efficiency, latency efficiency, historical performance** (configurable weights). A hard capability gate prevents underpowered models from winning on cost alone. |
| `app/adapters/` | `LLMAdapter` interface + OpenAI-compatible adapter + mock adapter. Providers are swappable. |
| `app/tracker.py` | SQLite persistence: every request's metrics, baseline (no-router) cost, and user feedback. |
| `app/main.py` | FastAPI app wiring the pipeline, fallback chain, and analytics endpoints. |
| `static/` | Frontend: chat UI with full routing transparency + analytics dashboard. |

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

The prototype runs immediately in **demo mode** with three built-in simulated models (`demo-fast`, `demo-balanced`, `demo-powerful`). To use real LLMs, set `OPENAI_API_KEY` in `.env` (works with any OpenAI-compatible endpoint: OpenAI, Azure OpenAI via custom `OPENAI_BASE_URL`, OpenRouter, Groq, Ollama…). Real models are added automatically; demo models can be disabled with `MOCK_MODELS_ENABLED=false`.

**Never commit `.env`** — it is git-ignored, and API keys never reach the frontend.

### 3. Run

```bash
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

Try the example queries in the chat to see the router pick different models, then open the **Dashboard** tab to see the cost savings vs. a "always use the most powerful model" baseline.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/chat` | `{query, history[]}` → response + routing decision, tokens, cost, latency |
| `POST /api/feedback` | `{request_id, rating: 1|-1}` → feedback loop input |
| `GET /api/stats` | Dashboard analytics incl. estimated savings |
| `GET /api/models` | Registered models and metadata |
| `GET /api/history` | Recent requests |

## Routing score

```
model_score = w₁·quality_suitability + w₂·complexity_compatibility
            + w₃·cost_efficiency      + w₄·latency_efficiency
            + w₅·historical_performance        (weights in .env: W_*)
```

- **Quality suitability** — how well the model's capability meets the query's required level; underpowered models are penalised heavily, overpowered ones mildly (avoids waste).
- **Complexity compatibility** — closeness of model capability to query complexity.
- **Cost / latency efficiency** — relative to the cheapest/fastest available model.
- **Historical performance** — blends past user feedback and success rate per (task type, model); neutral when no data exists yet.

If the chosen model fails, the router falls back down the ranking; only if all models fail does the request record a failure.

## Project structure

```
├── app/
│   ├── main.py          # FastAPI app + endpoints
│   ├── config.py        # .env settings
│   ├── analyzer.py      # context analysis
│   ├── router.py        # smart routing engine
│   ├── registry.py      # model registry
│   ├── tracker.py       # SQLite metrics + feedback
│   ├── schemas.py       # API contracts
│   └── adapters/        # LLM provider adapters
├── static/              # frontend (chat + dashboard)
├── data/                # SQLite database (git-ignored, auto-created)
├── requirements.txt
└── .env.example
```

## Roadmap

The architecture is designed to evolve into: ML-based query classification, adaptive/learned routing, dynamic pricing, budget-aware routing, A/B routing strategies, automatic failover policies, and advanced analytics.