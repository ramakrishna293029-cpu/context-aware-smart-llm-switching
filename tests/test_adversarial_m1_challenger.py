"""
Empirical Adversarial Challenge Test Suite for Milestone 1
Tests greeting triage, definition triage, complex query escalation, and 500 fallback logic.
"""
import pytest
import asyncio
from fastapi.testclient import TestClient
from app.main import app, clear_completion_cache
from app.analyzer_llm import run_analyzer
from app.pipeline import run_unary_chat


# -----------------------------------------------------------------------------
# Challenge 1: Greeting Permutations in Self-Mode
# -----------------------------------------------------------------------------
class TestGreetingPermutations:
    GREETINGS = [
        "hey",
        "hello",
        "hi there",
        "good evening",
        "how are you?",
        "Good morning!",
        "Who are you?",
        "What can you do?",
        "howdy",
        "greetings",
        "sup",
        "yo",
        "thanks",
        "thank you",
        "bye",
        "goodbye",
        "hey there",
        "hello assistant",
        "hi bot",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", GREETINGS)
    async def test_greeting_permutations_analyzer_self_mode(self, query):
        """Every greeting permutation must directly resolve to answer_mode='self' without switching."""
        clear_completion_cache()
        decision = await run_analyzer(query, history=[])
        assert decision.answer_mode == "self", f"Failed for query '{query}': got answer_mode={decision.answer_mode}"
        assert decision.switch_required is False, f"Failed for query '{query}': switch_required is True"
        assert decision.answer is not None and len(decision.answer.strip()) > 0, f"Empty answer for '{query}'"
        assert decision.complexity in ("low", "medium")
        assert decision.complexity_score <= 0.35

    @pytest.mark.parametrize("query", GREETINGS)
    def test_greeting_permutations_chat_endpoint(self, client, query):
        """Test chat endpoint directly returns self-mode response for greetings."""
        clear_completion_cache()
        resp = client.post("/api/chat", json={"query": query})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["answer_mode"] == "self"
        assert len(data["response"]) > 0


# -----------------------------------------------------------------------------
# Challenge 1b: Greeting vs Non-Greeting Boundary & Trap Testing
# -----------------------------------------------------------------------------
class TestGreetingBoundaryTraps:
    """Adversarially probe queries containing greeting words or phrases that MUST NOT be trapped in self mode."""

    BOUNDARY_QUERIES = [
        ("hey, write quicksort in c++", "coding"),
        ("hello, prove sqrt(2) is irrational", "reasoning"),
        ("hi there, explain raft consensus in distributed systems", "technical"),
        ("good evening, what is the time complexity of dijkstra?", "technical"),
        ("who are you compared to GPT-4o and Claude 3.5 Sonnet?", "factual"),
        ("tell me how are you handling distributed consensus in raft", "technical"),
        ("how are you going to implement a lock-free queue in c++", "coding"),
        ("what can you do to optimize this postgres query: SELECT * FROM users JOIN orders ON users.id = orders.user_id", "technical"),
        ("help me debug this memory leak in c++ with valgrind", "coding"),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query, expected_domain", BOUNDARY_QUERIES)
    async def test_non_greetings_not_trapped_in_self_mode(self, query, expected_domain):
        """Queries that contain greeting phrases but demand complex assistance MUST NOT be trapped in self-mode."""
        clear_completion_cache()
        decision = await run_analyzer(query, history=[])
        assert decision.answer_mode == "switch", (
            f"TRAPPED IN SELF-MODE! Query '{query}' was intercepted as greeting with "
            f"answer='{decision.answer}' instead of routing to target model!"
        )
        assert decision.switch_required is True


# -----------------------------------------------------------------------------
# Challenge 2: Complex Queries Switching to Appropriate Tiers
# -----------------------------------------------------------------------------
class TestComplexQueryEscalation:
    COMPLEX_CASES = [
        ("write quicksort in c++", ("tier_4", "tier_5", "tier_6", "coding")),
        ("prove sqrt(2) is irrational", ("tier_5", "tier_6", "reasoning")),
        ("distributed database with raft", ("tier_3", "tier_4", "tier_5", "tier_6", "planning", "technical")),
        ("Design a fault-tolerant distributed database with Raft consensus for high throughput", ("tier_4", "tier_5", "tier_6", "reasoning")),
        ("Implement a thread-safe lock-free ring buffer in C++ with memory barriers", ("tier_4", "tier_5", "tier_6", "coding")),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query, expected_tiers", COMPLEX_CASES)
    async def test_complex_queries_tier_escalation(self, query, expected_tiers):
        clear_completion_cache()
        decision = await run_analyzer(query, history=[])
        assert decision.answer_mode == "switch", f"Complex query '{query}' was trapped in self-mode!"
        assert decision.switch_required is True
        assert decision.complexity in ("medium", "high")
        norm_cap = decision.required_capability.lower()
        task_type = decision.task_type.lower()
        matches = any(t in norm_cap or t in task_type for t in expected_tiers)
        assert matches, f"Query '{query}' resolved to capability '{decision.required_capability}' (task={decision.task_type}), expected one of {expected_tiers}"

    @pytest.mark.parametrize("query, expected_tiers", COMPLEX_CASES)
    def test_complex_queries_chat_endpoint_switches(self, client, query, expected_tiers):
        clear_completion_cache()
        resp = client.post("/api/chat", json={"query": query})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["answer_mode"] == "switch"
        tier = data["model"]["tier"].lower()
        matches = any(t in tier for t in expected_tiers)
        assert matches, f"Model tier '{tier}' does not match expected {expected_tiers}"


# -----------------------------------------------------------------------------
# Challenge 3: Fallback Behavior with Simulated 500 Outages
# -----------------------------------------------------------------------------
class TestFallbackSimulated500:
    def test_unary_chat_fallback_on_primary_outage(self, client):
        clear_completion_cache()
        query = "FALLBACK-DEMAND Design a fault-tolerant distributed database with Raft consensus for high throughput"
        resp = client.post("/api/chat", json={"query": query})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["fallback_used"] is True, "fallback_used must be True when primary 500s"
        assert "[REAL-" in data["response"]
        assert data["fallback_reason"] is not None

    def test_stream_fallback_on_primary_outage(self, client):
        clear_completion_cache()
        query = "FALLBACK-DEMAND Design a fault-tolerant distributed database with Raft consensus for high throughput"
        events = []
        with client.stream("POST", "/api/chat/stream", json={"query": query}) as stream:
            assert stream.status_code == 200
            for line in stream.iter_lines():
                if line.startswith("data:"):
                    events.append(line[5:].strip())
        done_events = [e for e in events if '"event": "done"' in e]
        assert len(done_events) > 0, "Expected done event in stream"
        done_text = done_events[0]
        assert '"fallback_used": true' in done_text or '"fallback_used": True' in done_text

    def test_fallback_chain_different_candidate_selected(self, client):
        """Verify the model selected under fallback is distinct from the primary failed model."""
        clear_completion_cache()
        normal_resp = client.post("/api/chat", json={"query": "Design a fault-tolerant distributed database with Raft consensus for high throughput"}).json()
        primary_model = normal_resp["model"]["model_id"]

        clear_completion_cache()
        fallback_resp = client.post("/api/chat", json={"query": "FALLBACK-DEMAND Design a fault-tolerant distributed database with Raft consensus for high throughput"}).json()
        fallback_model = fallback_resp["model"]["model_id"]

        assert fallback_resp["fallback_used"] is True
        assert fallback_model != primary_model, f"Fallback model '{fallback_model}' must be distinct from primary '{primary_model}'"
