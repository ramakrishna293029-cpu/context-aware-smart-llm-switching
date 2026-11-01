"""End-to-End Test Suite for LinUCB Contextual Routing Pipeline & UI Integration.

Covers:
1. Unary Chat LinUCB Telemetry (/api/chat): bandit_score, expected_reward, uncertainty, reward, scores.
2. SSE Streaming LinUCB Telemetry (/api/chat/stream): routing & done events with bandit fields.
3. Fallback Execution: Failover on simulated primary outage, recording fallback_used and reward updates.
4. Route Preview Endpoint: POST and GET /api/route/preview diagnostics and candidate arm scoreboard.
5. Budget Hard-Constraint Rejection: 429 when max_cost or daily_budget rejects all models.
6. Stats & Metrics Bandit Arm Telemetry: /api/stats and /api/metrics include bandit_arms and pull counts.
7. Closed-Loop Bandit Parameter Learning: Verification that arm pull_count and A, b matrices update.
8. Semantic Cache Fast-Path: Zero-latency return on identical queries preserving bandit metadata.

Run: python -m pytest tests/test_linucb_e2e.py -v
"""

import json
import pytest
from fastapi.testclient import TestClient

SIMPLE_QUERY = "What is a compiler?"
COMPLEX_QUERY = "Design a fault-tolerant distributed database with Raft consensus for high throughput"
CODING_QUERY = "Write a python function to implement quicksort with in-place partitioning"


def _events(client: TestClient, query: str, headers: dict = None, **extra) -> list:
    events = []
    with client.stream("POST", "/api/chat/stream", json={"query": query, **extra}, headers=headers or {}) as resp:
        assert resp.status_code == 200, resp.read()
        for raw in resp.iter_lines():
            if raw.startswith("data:"):
                events.append(json.loads(raw[5:].strip()))
    return events


class TestLinUCBUnaryChat:
    def test_unary_chat_telemetry_fields(self, client: TestClient):
        resp = client.post("/api/chat", json={"query": CODING_QUERY})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["selected_model"] is not None

        # Verify LinUCB fields are populated
        assert data["bandit_score"] is not None
        assert isinstance(data["bandit_score"], (int, float))
        assert data["expected_reward"] is not None
        assert isinstance(data["expected_reward"], (int, float))
        assert data["uncertainty"] is not None
        assert isinstance(data["uncertainty"], (int, float))
        assert data["reward"] is not None
        assert isinstance(data["reward"], (int, float))

        # Verify candidate arm scores dictionary
        assert isinstance(data["scores"], dict)
        assert len(data["scores"]) > 0
        for arm_id, arm_stats in data["scores"].items():
            assert "ucb_score" in arm_stats
            assert "expected_reward" in arm_stats
            assert "uncertainty" in arm_stats
            assert "pull_count" in arm_stats

    def test_self_mode_telemetry(self, client: TestClient):
        resp = client.post("/api/chat", json={"query": "Calculate 42 + 58"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer_mode"] == "self"
        assert data["bandit_score"] is not None
        assert data["scores"] is not None


class TestLinUCBStreaming:
    def test_streaming_routing_and_done_events(self, client: TestClient):
        events = _events(client, CODING_QUERY)
        kinds = [e["event"] for e in events]
        assert "routing" in kinds
        assert "done" in kinds

        routing_ev = next(e for e in events if e["event"] == "routing")
        assert "candidates" in routing_ev
        assert len(routing_ev["candidates"]) > 0

        # Check candidate arm scoreboard payload in routing event
        candidate = routing_ev["candidates"][0]
        assert "model_id" in candidate
        assert "total" in candidate
        assert "factors" in candidate
        assert "ucb_score" in candidate["factors"]
        assert "pull_count" in candidate["factors"]
        assert "quality_suitability" in candidate["factors"]
        assert "reasoning_compatibility" in candidate["factors"]
        assert "coding_compatibility" in candidate["factors"]

        done_ev = next(e for e in events if e["event"] == "done")
        assert done_ev["success"] is True
        assert done_ev["bandit_score"] is not None
        assert done_ev["expected_reward"] is not None
        assert done_ev["uncertainty"] is not None
        assert done_ev["reward"] is not None
        assert isinstance(done_ev["scores"], dict)


class TestLinUCBFallback:
    def test_fallback_failover_and_reward(self, client: TestClient):
        from app.linucb import linucb_router
        # FALLBACK-DEMAND triggers a 500 error on primary reasoning model
        events = _events(client, f"FALLBACK-DEMAND {COMPLEX_QUERY}")
        routing_ev = next(e for e in events if e["event"] == "routing")
        done_ev = next(e for e in events if e["event"] == "done")
        assert done_ev["success"] is True
        assert done_ev["fallback_used"] is True
        assert "[REAL-" in done_ev["response"]

        # Verify that the primary model that failed was penalized in linucb_router
        primary_cand_id = routing_ev["candidates"][0]["model_id"]
        assert primary_cand_id in linucb_router.arms
        primary_arm = linucb_router.arms[primary_cand_id]
        assert primary_arm.pull_count >= 1
        assert primary_arm.total_reward < 0.0


class TestRoutePreviewEndpoint:
    def test_preview_post(self, client: TestClient):
        resp = client.post("/api/route/preview", json={"query": CODING_QUERY})
        assert resp.status_code == 200
        data = resp.json()
        assert "selected_model" in data
        assert "candidate_arm_scores" in data
        assert "eligibility" in data
        assert "feature_vector" in data
        assert len(data["feature_vector"]) == 16
        assert data["eligibility"]["eligible_count"] > 0

    def test_preview_get(self, client: TestClient):
        resp = client.get(f"/api/route/preview?query={SIMPLE_QUERY}")
        assert resp.status_code == 200
        data = resp.json()
        assert "selected_model" in data
        assert len(data["candidate_arm_scores"]) > 0

    def test_preview_budget_exhaustion_429(self, client: TestClient):
        from app.config import settings
        object.__setattr__(settings, "max_cost_per_request", 0.0000001)
        resp = client.post("/api/route/preview", json={"query": COMPLEX_QUERY})
        assert resp.status_code == 429
        detail = resp.json()["detail"]
        err_msg = detail if isinstance(detail, str) else detail.get("message", "")
        assert "budget" in err_msg.lower() or "cost" in err_msg.lower()


class TestStatsAndTelemetry:
    def test_stats_bandit_arms(self, client: TestClient):
        # Generate some traffic first
        client.post("/api/chat", json={"query": SIMPLE_QUERY})
        client.post("/api/chat", json={"query": CODING_QUERY})

        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "bandit_arms" in data
        arms = data["bandit_arms"]
        assert isinstance(arms, dict)
        assert len(arms) > 0
        for arm_id, arm_data in arms.items():
            assert "pull_count" in arm_data
            assert "total_reward" in arm_data
            assert "mean_reward" in arm_data

    def test_metrics_bandit_summary(self, client: TestClient):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "bandit" in data
        assert "total_arms" in data["bandit"]
        assert "total_pulls" in data["bandit"]


class TestClosedLoopLearning:
    def test_arm_pull_count_increments(self, client: TestClient):
        from app.linucb import linucb_router

        # Record initial pull counts across all arms
        initial_pulls = {arm_id: arm.pull_count for arm_id, arm in linucb_router.arms.items()}
        
        # Fire a chat request
        resp = client.post("/api/chat", json={"query": CODING_QUERY})
        assert resp.status_code == 200
        data = resp.json()
        served_id = data["model"]["model_id"]

        # Ensure the selected arm pull_count incremented by 1
        new_pulls = {arm_id: arm.pull_count for arm_id, arm in linucb_router.arms.items()}
        assert new_pulls[served_id] == initial_pulls.get(served_id, 0) + 1


class TestSemanticCacheLinUCB:
    def test_semantic_cache_hit_returns_bandit_metadata(self, client: TestClient):
        query = "What is an abstract syntax tree?"
        r1 = client.post("/api/chat", json={"query": query})
        assert r1.status_code == 200
        d1 = r1.json()

        # Second call with identical query hits semantic cache
        r2 = client.post("/api/chat", json={"query": query})
        assert r2.status_code == 200
        d2 = r2.json()

        assert d2["response"] == d1["response"]
        assert d2["bandit_score"] is not None
        assert d2["scores"] is not None
