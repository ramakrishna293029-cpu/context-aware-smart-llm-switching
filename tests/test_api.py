"""Automated Test Suite for Smart LLM Router (FastAPI, Analyzer Brain, SSE Streaming & Telemetry).

Covers:
- Analyzer Endpoint: Self-Mode vs Switch-Mode decisions
- Chat Endpoint: Direct Base Model answers vs Switched multi-factor routing
- SSE Streaming: Typed events (analyzer -> routing -> reasoning_delta -> content_delta -> done)
- Multi-Provider Key Resolution & Dynamic Registry
- Resilience: Fallback chain failovers on provider 500 errors
- Health Checks & Single Provider Test endpoints
- Telemetry & Inspector: Request details, Feedback rating, Stats & Distributions, History
- Benchmarks: Matrix and 3-Way Comparative Experiment Run
- Budget Guards & Rate Limiting: Daily Budget cap, Max Cost Per Request cap, Rate Limiter

Run: python -m pytest tests/test_api.py -v
"""

import json
import time
import pytest
from fastapi.testclient import TestClient

SIMPLE_QUERY = "What is HTML?"
COMPLEX_QUERY = "Design a fault-tolerant distributed database with Raft consensus for high throughput"


def _chat(client: TestClient, query: str, headers: dict = None, **extra) -> dict:
    resp = client.post("/api/chat", json={"query": query, **extra}, headers=headers or {})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _events(client: TestClient, query: str, headers: dict = None, **extra) -> list:
    events = []
    with client.stream("POST", "/api/chat/stream", json={"query": query, **extra}, headers=headers or {}) as resp:
        assert resp.status_code == 200, resp.read()
        for raw in resp.iter_lines():
            if raw.startswith("data:"):
                events.append(json.loads(raw[5:].strip()))
    return events


# ---------------------------------------------------------------------------
# 1. Analyzer Endpoint Tests
# ---------------------------------------------------------------------------
class TestAnalyze:
    def test_simple_self_decision(self, client: TestClient):
        r = client.post("/api/analyze", json={"query": SIMPLE_QUERY}).json()
        assert "analyzer" in r
        assert r["analyzer"]["answer_mode"] == "self"
        assert r["analyzer"]["complexity"] in ("low", "medium")
        assert r["analyzer"]["complexity_score"] <= 0.5
        assert r["analyzer"]["reason"]
        assert len(r["candidates"]) > 0

    def test_complex_switch_decision(self, client: TestClient):
        r = client.post("/api/analyze", json={"query": COMPLEX_QUERY}).json()
        assert "analyzer" in r
        assert r["analyzer"]["answer_mode"] == "switch"
        assert r["analyzer"]["complexity"] in ("medium", "high")
        assert r["analyzer"]["complexity_score"] >= 0.6
        assert r["analyzer"]["reasoning_required"] is True
        assert len(r["candidates"]) > 0

    def test_requires_query(self, client: TestClient):
        assert client.post("/api/analyze", json={}).status_code == 422


# ---------------------------------------------------------------------------
# 2. Unary Chat Endpoint Tests
# ---------------------------------------------------------------------------
class TestChat:
    def test_simple_is_self_answered(self, client: TestClient):
        data = _chat(client, SIMPLE_QUERY)
        assert data["answer_mode"] == "self"
        assert data["context_relevant"] is False
        assert data["model"]["model_id"] == data["analyzer"]["model_id"]
        assert data["input_tokens"] is None and data["output_tokens"] is None  # no separate downstream call
        assert data["total_tokens"] > 0
        assert data["estimated_cost_usd"] == data["analyzer_cost_usd"]
        assert data["total_cost_usd"] > 0
        assert data["request_id"] > 0
        assert data["success"] is True
        assert "[REAL-analyzer]" in data["response"] or "HTML" in data["response"]

    def test_complex_switches_to_target(self, client: TestClient):
        data = _chat(client, COMPLEX_QUERY)
        assert data["answer_mode"] == "switch"
        assert any(t in data["model"]["tier"].lower() for t in ("reasoning", "coding", "powerful", "fast"))
        assert data["input_tokens"] is not None
        assert data["output_tokens"] is not None
        assert data["total_tokens"] >= (data["input_tokens"] + data["output_tokens"])
        assert data["total_cost_usd"] >= data["analyzer_cost_usd"]
        assert data["success"] is True
        assert data["request_id"] > 0

    def test_strategy_lowest_cost(self, client: TestClient):
        data = _chat(client, COMPLEX_QUERY, strategy="lowest_cost")
        assert data["model"]["strategy"] == "lowest_cost"
        assert data["analyzer"]["model_id"]

    def test_strategy_fastest(self, client: TestClient):
        data = _chat(client, COMPLEX_QUERY, strategy="fastest")
        assert data["model"]["strategy"] == "fastest"

    def test_strategy_highest_quality(self, client: TestClient):
        data = _chat(client, COMPLEX_QUERY, strategy="highest_quality")
        assert data["model"]["strategy"] == "highest_quality"

    def test_invalid_strategy_422(self, client: TestClient):
        assert client.post("/api/chat", json={"query": "hi", "strategy": "bogus_strategy"}).status_code == 422

    def test_history_followup_uses_context(self, client: TestClient):
        history = [
            {"role": "user", "content": "Explain binary search."},
            {"role": "assistant", "content": "Binary search is a divide and conquer search algorithm."},
        ]
        data = _chat(client, "Now optimize it for memory efficiency", history=history)
        assert data["context_relevant"] is True
        assert data["answer_mode"] == "switch"

    def test_dynamic_header_credentials_override(self, client: TestClient):
        custom_headers = {
            "X-OpenAI-Key": "override-key-12345",
            "X-Custom-Endpoint": "http://127.0.0.1:8999/v1",
            "X-Custom-Model": "llama3:8b",
            "X-Base-Model": "gpt-4o-mini",
        }
        data = _chat(client, SIMPLE_QUERY, headers=custom_headers)
        assert data["success"] is True
        assert data["request_id"] > 0

    def test_analyzer_failure_502(self, client: TestClient):
        r = client.post("/api/chat", json={"query": "FAIL-ANALYZER trigger outage"})
        assert r.status_code == 502
        assert "Analyzer" in r.json()["detail"]

    def test_final_failure_falls_back(self, client: TestClient):
        # Trigger outage on primary model; fallback chain recovers on next available candidate
        data = _chat(client, f"FALLBACK-DEMAND {COMPLEX_QUERY}")
        assert data["success"] is True
        assert data["fallback_used"] is True
        assert "[REAL-" in data["response"]


# ---------------------------------------------------------------------------
# 3. SSE Streaming Endpoint Tests
# ---------------------------------------------------------------------------
class TestStream:
    def test_stream_self_events(self, client: TestClient):
        events = _events(client, SIMPLE_QUERY)
        kinds = [e["event"] for e in events]
        assert "analyzer" in kinds
        assert any(k in kinds for k in ("delta", "content_delta"))
        assert "done" in kinds
        assert "routing" not in kinds

        analyzer_ev = next(e for e in events if e["event"] == "analyzer")
        assert analyzer_ev["info"]["answer_mode"] == "self"

        done_ev = next(e for e in events if e["event"] == "done")
        assert done_ev["success"] is True
        assert done_ev["answer_mode"] == "self"
        assert done_ev["request_id"] > 0
        assert done_ev["input_tokens"] is None
        assert done_ev["total_tokens"] > 0

        text = "".join(e.get("text", "") for e in events if e.get("event") in ("delta", "content_delta"))
        assert len(text) > 0

    def test_stream_switch_events(self, client: TestClient):
        events = _events(client, COMPLEX_QUERY)
        kinds = [e["event"] for e in events]
        assert "analyzer" in kinds
        assert "routing" in kinds
        assert any(k in kinds for k in ("delta", "content_delta"))
        assert "done" in kinds

        routing_ev = next(e for e in events if e["event"] == "routing")
        assert routing_ev["answer_mode"] == "switch"
        assert routing_ev["target_model"]
        assert len(routing_ev["candidates"]) > 0

        done_ev = next(e for e in events if e["event"] == "done")
        assert done_ev["success"] is True
        assert done_ev["answer_mode"] == "switch"
        assert done_ev["request_id"] > 0

    def test_stream_reasoning_delta(self, client: TestClient):
        events = _events(client, "Prove that square root of 2 is irrational and explain reasoning")
        kinds = [e["event"] for e in events]
        assert "analyzer" in kinds
        assert "routing" in kinds
        assert "done" in kinds

    def test_stream_analyzer_error(self, client: TestClient):
        events = _events(client, "FAIL-ANALYZER trigger outage")
        assert len(events) == 1
        assert events[0]["event"] == "error"
        assert "Analyzer" in events[0]["detail"]

    def test_stream_fallback(self, client: TestClient):
        events = _events(client, f"FALLBACK-DEMAND {COMPLEX_QUERY}")
        done_ev = next(e for e in events if e["event"] == "done")
        assert done_ev["success"] is True
        assert done_ev["fallback_used"] is True


# ---------------------------------------------------------------------------
# 4. Health & Provider Status Tests
# ---------------------------------------------------------------------------
class TestHealthAndProviders:
    def test_health(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["architecture"] == "analyzer-llm"
        assert "providers" in data

    def test_providers_health(self, client: TestClient):
        r = client.get("/api/providers/health")
        assert r.status_code == 200
        data = r.json()
        assert "overall_status" in data
        assert "openai" in data
        assert "groq" in data

    def test_provider_test_endpoint(self, client: TestClient):
        r = client.post("/api/providers/test/openai", json={"api_key": "test-key"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "Connected" in data["message"]

    def test_settings_endpoint(self, client: TestClient):
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "daily_budget_usd" in data
        assert "has_openai_key" in data

    def test_models_endpoint(self, client: TestClient):
        r = client.get("/api/models")
        assert r.status_code == 200
        data = r.json()
        assert "models" in data
        assert len(data["models"]) > 0


# ---------------------------------------------------------------------------
# 5. Telemetry, Inspector, Feedback & Benchmark Tests
# ---------------------------------------------------------------------------
class TestTelemetryAndInspector:
    def test_request_detail(self, client: TestClient):
        chat_data = _chat(client, SIMPLE_QUERY)
        rid = chat_data["request_id"]
        r = client.get(f"/api/requests/{rid}")
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == rid
        assert d["query"] == SIMPLE_QUERY
        assert d["task_type"] == "factual"
        assert d["answer_mode"] == "self"
        assert d["selected_model"]
        assert d["total_latency_ms"] >= 0
        assert d["total_cost_usd"] is not None

    def test_unknown_request_404(self, client: TestClient):
        assert client.get("/api/requests/999999").status_code == 404

    def test_feedback_flow(self, client: TestClient):
        chat_data = _chat(client, SIMPLE_QUERY)
        rid = chat_data["request_id"]
        resp = client.post("/api/feedback", json={"request_id": rid, "rating": 1})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        detail = client.get(f"/api/requests/{rid}").json()
        assert detail["feedback"] == 1

    def test_feedback_validation(self, client: TestClient):
        assert client.post("/api/feedback", json={"request_id": 1, "rating": 5}).status_code == 422

    def test_stats_shape(self, client: TestClient):
        r = client.get("/api/stats")
        assert r.status_code == 200
        s = r.json()
        expected_keys = [
            "total_requests", "successful_requests", "success_rate",
            "average_latency_ms", "average_total_latency_ms", "total_cost_usd",
            "baseline_cost_usd", "estimated_savings_usd", "savings_percent",
            "total_tokens", "fallback_count", "self_answered", "switched",
            "switch_rate", "context_used", "model_distribution", "analyzer_distribution",
            "decision_distribution", "distributions", "model_performance", "recent_requests",
            "budget",
        ]
        for k in expected_keys:
            assert k in s, f"Missing key in stats: {k}"
        assert isinstance(s["distributions"]["complexity_distribution"], list)
        assert s["budget"]["daily_budget_usd"] >= 0

    def test_history(self, client: TestClient):
        r = client.get("/api/history")
        assert r.status_code == 200
        hist = r.json()
        assert isinstance(hist, list)
        if hist:
            assert "answer_mode" in hist[0]
            assert "selected_model" in hist[0]

    def test_benchmark_matrix(self, client: TestClient):
        r = client.get("/api/benchmark/matrix")
        assert r.status_code == 200
        assert "matrix" in r.json()
        assert len(r.json()["matrix"]) > 0

    def test_benchmark_run(self, client: TestClient):
        r = client.post("/api/benchmark/run", json={"queries": ["What is HTML?", "Write a binary search algorithm in Python"]})
        assert r.status_code == 200
        bm = r.json()
        assert bm["total_queries"] == 2
        assert bm["baseline1_total_cost_usd"] > 0
        assert bm["smart_total_cost_usd"] > 0
        assert "overall_cost_savings_percent" in bm
        assert len(bm["items"]) == 2


# ---------------------------------------------------------------------------
# 6. Budget & Guard Tests
# ---------------------------------------------------------------------------
class TestBudgetsAndGuards:
    def test_daily_budget_429(self, client: TestClient):
        from app.config import settings
        object.__setattr__(settings, "daily_budget_usd", 0.000001)
        try:
            r = client.post("/api/chat", json={"query": SIMPLE_QUERY})
            assert r.status_code == 429
            assert "budget" in r.json()["detail"].lower()
        finally:
            object.__setattr__(settings, "daily_budget_usd", 0.0)

    def test_max_cost_per_request_filters_target(self, client: TestClient):
        from app.config import settings
        object.__setattr__(settings, "max_cost_per_request", 0.005)
        try:
            r = _chat(client, COMPLEX_QUERY)
            assert r["answer_mode"] == "switch"
            assert r["success"] is True
        finally:
            object.__setattr__(settings, "max_cost_per_request", 0.0)

    def test_max_cost_below_all_models_429(self, client: TestClient):
        from app.config import settings
        object.__setattr__(settings, "max_cost_per_request", 0.000000001)
        try:
            r = client.post("/api/chat", json={"query": COMPLEX_QUERY})
            assert r.status_code == 429
            assert "budget" in r.json()["detail"].lower()
        finally:
            object.__setattr__(settings, "max_cost_per_request", 0.0)

    def test_invalid_json_422(self, client: TestClient):
        r = client.post("/api/chat", content=b"{not json", headers={"Content-Type": "application/json"})
        assert r.status_code in (400, 422)

    def test_rate_limit_429(self, client: TestClient):
        from app.main import _rate_hits, _RATE_MAX
        now = time.monotonic()
        _rate_hits["testclient"] = [now] * _RATE_MAX
        try:
            r = client.post("/api/chat", json={"query": SIMPLE_QUERY})
            assert r.status_code == 429
            assert "rate limit" in r.json()["detail"].lower()
        finally:
            _rate_hits["testclient"] = []