# API Documentation

## Context-Aware Smart LLM Switching for Cost and Performance Optimization

Base URL: `http://127.0.0.1:8000`

---

## 1. System Health & Metadata

### `GET /health`
Returns current operational mode, registered tier model identifiers, and provider connection status.

**Response (200 OK):**
```json
{
  "status": "ok",
  "mode": "real",
  "architecture": "Context-Aware Smart LLM Switching (Disjoint LinUCB Contextual Router + 6 Response Model Tiers)",
  "version": "3.0.0",
  "models_count": 6,
  "providers": {
    "gemini": true,
    "groq": true,
    "openrouter": false,
    "openai": false,
    "custom": false
  },
  "tiers": {
    "analyzer": "gemini-3.1-flash-lite",
    "tier_1": "gemini-3.5-flash-lite",
    "tier_2": "openai/gpt-oss-20b",
    "tier_3": "gemini-3.6-flash",
    "tier_4": "qwen/qwen3.8-27b",
    "tier_5": "openai/gpt-oss-120b",
    "tier_6": "gemini-3.8-flash",
    "tier_6_fallback": "gemini-3.5-flash"
  }
}
```

---

## 2. Core Conversational Endpoints

### `POST /api/chat`
Standard non-streaming chat completion endpoint with dynamic contextual bandit routing.

**Request Headers:**
`Content-Type: application/json`

**Request Body:**
```json
{
  "query": "Write a Python function to perform binary search on a sorted list.",
  "history": [
    {
      "role": "user",
      "content": "Hi, I need help with algorithms."
    },
    {
      "role": "assistant",
      "content": "Hello! I can help you with algorithm implementations. What do you need?"
    }
  ],
  "strategy": "balanced",
  "deadline_ms": 3000.0
}
```

**Response (200 OK):**
```json
{
  "request_id": "req-98f2b3e4",
  "query": "Write a Python function to perform binary search on a sorted list.",
  "response": "```python\ndef binary_search(arr, target):\n    low = 0\n    high = len(arr) - 1\n    while low <= high:\n        mid = (low + high) // 2\n        if arr[mid] == target:\n            return mid\n        elif arr[mid] < target:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return -1\n```",
  "served_model": {
    "model_id": "groq-tier_4",
    "name": "Groq Qwen3.8 27B",
    "provider": "groq",
    "tier": "tier_4"
  },
  "answer_mode": "switch",
  "switch_reason": "Routing decision based on LinUCB contextual arm selection.",
  "task_type": "coding",
  "complexity": "medium",
  "bandit_score": 0.8412,
  "telemetry": {
    "total_latency_ms": 284.5,
    "input_tokens": 78,
    "output_tokens": 124,
    "total_cost_usd": 0.0000404,
    "savings_usd": 0.000679,
    "savings_pct": 94.4
  },
  "candidates": [
    {
      "model_id": "groq-tier_4",
      "name": "Groq Qwen3.8 27B",
      "tier": "tier_4",
      "total": 0.8412,
      "selected": true
    },
    {
      "model_id": "groq-tier_5",
      "name": "Groq GPT-OSS 120B",
      "tier": "tier_5",
      "total": 0.7820,
      "selected": false
    }
  ]
}
```

---

### `POST /api/chat/stream`
Server-Sent Events (SSE) streaming endpoint providing real-time text generation and telemetry events.

**Event Stream Sequence:**
1. `event: routing` — Dispatched once the LinUCB bandit resolves the target tier.
   ```json
   {"target_model": "groq-tier_4", "tier": "tier_4", "reason": "LinUCB Selected"}
   ```
2. `event: delta` — Repeated stream chunks containing incremental text deltas.
   ```json
   {"content": "def binary_search"}
   ```
3. `event: done` — Final event carrying complete request telemetry, token usage, cost, and bandit reward.
   ```json
   {
     "request_id": "req-98f2b3e4",
     "total_latency_ms": 284.5,
     "input_tokens": 78,
     "output_tokens": 124,
     "cost_usd": 0.0000404,
     "savings_pct": 94.4,
     "bandit_reward": 0.891
   }
   ```

---

### `POST /api/analyze`
Dry-run diagnostic endpoint: extracts features, runs MCDA feasibility filtering, and scores candidate arms without invoking downstream models.

**Request Body:**
```json
{
  "query": "Explain the Paxos consensus algorithm in distributed databases."
}
```

**Response (200 OK):**
```json
{
  "task_type": "reasoning",
  "complexity": "high",
  "feature_vector_norm": 1.0,
  "top_selected_tier": "tier_6",
  "eligible_models": ["gemini-tier_6", "groq-tier_5", "gemini-tier_3"],
  "scores": {
    "gemini-tier_6": {"ucb_score": 0.9124, "expected_reward": 0.8410, "uncertainty": 0.0714},
    "groq-tier_5": {"ucb_score": 0.8651, "expected_reward": 0.7890, "uncertainty": 0.0761}
  }
}
```

---

### `POST /api/feedback`
Submits explicit user feedback (+1 for thumbs up, -1 for thumbs down) to trigger online LinUCB learning.

**Request Body:**
```json
{
  "request_id": "req-98f2b3e4",
  "rating": 1
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "request_id": "req-98f2b3e4",
  "message": "Feedback recorded. LinUCB arm updated."
}
```

---

## 3. Metrics, Telemetry & Dashboard

### `GET /api/stats`
Aggregated high-level statistics displayed on the dashboard:
* Total requests served
* Cumulative cost & savings percentage
* Overall average latency
* Tier distribution counts

### `GET /api/metrics`
Comprehensive telemetry dump including:
* Per-tier request counts, average latency, and success rates
* Circuit breaker states (`CLOSED`, `OPEN`, `HALF_OPEN`)
* LinUCB arm parameters ($\alpha$, pull counts, empirical variances)
* Daily and monthly budget utilization

### `GET /api/models`
Catalog of all 6 registered model tiers, default endpoints, provider affiliations, pricing, and health status.

### `GET /api/requests/{id}`
Returns complete audit trail for a specific request ID, including feature vector, candidate score breakdown, fallback attempts, and quality score.
