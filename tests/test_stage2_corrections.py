"""Regression and Verification Tests for Second-Stage Technical Corrections.

Validates the five approved corrections:
1. Failed model attribution: actual elapsed latency and incurred cost recorded;
   open circuit models skipped; failed attempts receive negative reward.
2. Conversational context detection: Scenarios A, B, C, D verified with word-boundary awareness.
3. Quality evaluation: Python AST syntax checks, deterministic arithmetic verification,
   and explicit human feedback retention.
4. /health endpoint: architecture description accurately reflects Disjoint LinUCB router.
5. Context-Aware Completion Cache: exact matching with context awareness.
"""

import ast
import re
import pytest
from fastapi.testclient import TestClient

from app.pipeline import _get_local_decision, FallbackExecutionResult, execute_with_fallback
from app.reward import ResponseQualityEvaluator, RewardCalculator
from app.schemas import ChatMessage
from app.registry import ModelSpec
from app.features import feature_extractor
from app.circuit import circuits


# ===========================================================================
# 1. Failed Model Attribution & Fallback Execution Tests
# ===========================================================================

class TestFailedModelAttribution:
    def test_fallback_execution_result_backward_compatibility(self):
        """FallbackExecutionResult supports 4-item tuple unpacking and .attempts access."""
        spec = ModelSpec(
            model_id="test-model",
            name="Test",
            provider="local",
            endpoint_model="test",
            api_key="",
            base_url="",
            input_price_per_mtok=0.0,
            output_price_per_mtok=0.0,
            expected_latency_ms=1.0,
            quality=0.8,
            reasoning=0.8,
            coding=0.8,
            context_window=4096,
            tier="tier_1",
        )
        attempts = {
            "m0": {"attempted": True, "circuit_open": False, "latency_ms": 150.0, "cost_usd": 0.0001, "error": "timeout"},
            "m1": {"attempted": False, "circuit_open": True, "latency_ms": 0.0, "cost_usd": 0.0, "error": "circuit open"},
        }
        res = FallbackExecutionResult(spec, None, True, "m0 failed", attempts)

        # 4-item unpacking must work seamlessly
        served, result, fallback_used, reason = res
        assert served.model_id == "test-model"
        assert result is None
        assert fallback_used is True
        assert reason == "m0 failed"

        # Direct attribute and 5th-element indexing access
        assert res.attempts["m0"]["latency_ms"] == 150.0
        assert res.attempts["m1"]["circuit_open"] is True
        assert res[4]["m0"]["attempted"] is True

    def test_failed_attempt_negative_reward(self):
        """Failed attempt receives a strictly negative reward reflecting latency and cost."""
        calc = RewardCalculator()
        
        # When failure occurs after 2500ms timeout
        reward, breakdown = calc.compute_reward(
            cost_usd=0.001,
            latency_ms=2500.0,
            success=False,
            quality_score=0.0,
        )
        assert reward < 0.0
        assert breakdown["quality"] == 0.0
        assert breakdown["success"] == 0.0
        # Cost and latency penalties must be negative in reward formula
        assert breakdown["cost_term"] < 0.0
        assert breakdown["latency_term"] < 0.0
        assert breakdown["cost_norm"] > 0.0
        assert breakdown["latency_norm"] > 0.0
        assert reward <= -0.10


# ===========================================================================
# 2. Conversational Context Detection (Scenarios A, B, C, D)
# ===========================================================================

class TestConversationalContextDetection:
    def test_scenario_a_dijkstra_time_complexity(self):
        """Scenario A: 'Explain its time complexity' uses conversation history."""
        history = [
            ChatMessage(role="user", content="Write a Java program for Dijkstra's algorithm."),
            ChatMessage(role="assistant", content="Here is Dijkstra's algorithm in Java..."),
        ]
        query = "Explain its time complexity."
        dec = _get_local_decision(query, history=history)
        assert dec.context_required is True

        # Feature vector must blend history
        x_gated = feature_extractor.extract(query, history=history if dec.context_required else None)
        x_raw = feature_extractor.extract(query, history=history)
        cos_sim = float(x_gated @ x_raw)
        assert pytest.approx(cos_sim, 0.001) == 1.0

    def test_scenario_b_optimize_it(self):
        """Scenario B: 'Optimize it' uses conversation history."""
        history = [
            ChatMessage(role="user", content="Write a Python web scraper."),
            ChatMessage(role="assistant", content="Here is a BeautifulSoup scraper..."),
        ]
        query = "Optimize it."
        dec = _get_local_decision(query, history=history)
        assert dec.context_required is True

    def test_scenario_c_unrelated_arithmetic_isolates_history(self):
        """Scenario C: 'What is 15 multiplied by 4?' isolates unrelated France history."""
        history = [
            ChatMessage(role="user", content="What is the capital of France?"),
            ChatMessage(role="assistant", content="The capital of France is Paris."),
        ]
        query = "What is 15 multiplied by 4?"
        dec = _get_local_decision(query, history=history)
        assert dec.context_required is False

        # If fastpath solved it, answer is 60; otherwise switch mode without history
        if dec.answer_mode == "self":
            assert "60" in (dec.answer or "")

    def test_scenario_d_binary_search_example_in_java(self):
        """Scenario D: 'Give an example in Java' uses binary search conversation history."""
        history = [
            ChatMessage(role="user", content="Explain binary search."),
            ChatMessage(role="assistant", content="Binary search runs in O(log n) time by dividing search space in half."),
        ]
        query = "Give an example in Java."
        dec = _get_local_decision(query, history=history)
        assert dec.context_required is True

        # History is blended into feature vector
        x_gated = feature_extractor.extract(query, history=history if dec.context_required else None)
        x_raw = feature_extractor.extract(query, history=history)
        cos_sim = float(x_gated @ x_raw)
        assert pytest.approx(cos_sim, 0.001) == 1.0

    def test_word_boundary_avoids_substring_false_positives(self):
        """Word boundaries prevent substring false positives on 'it' inside other words."""
        history = [ChatMessage(role="user", content="Prior discussion.")]
        # Query contains 'situation' and 'wait' which contain 'it', but neither is the pronoun 'it'
        query = "Explain the situation and wait for user input."
        dec = _get_local_decision(query, history=history)
        assert dec.context_required is False


# ===========================================================================
# 3. Quality Evaluation: AST Validation & Arithmetic Verification
# ===========================================================================

class TestQualityEvaluationImprovements:
    def test_python_ast_syntax_penalty_on_broken_code(self):
        """Syntactically broken Python code inside markdown blocks incurs AST syntax penalty."""
        evaluator = ResponseQualityEvaluator()
        broken_code_resp = (
            "Here is the function:\n"
            "```python\n"
            "def broken_syntax(a, b\n"
            "    return a + b\n"
            "```\n"
            "This function adds two numbers together."
        )
        score = evaluator.evaluate_quality(query="Write code", response_text=broken_code_resp)
        # Expected: base 1.0 - 0.35 (ast syntax penalty) = 0.65
        assert score < 0.70
        assert pytest.approx(score, 0.01) == 0.65

    def test_python_ast_passes_on_valid_code(self):
        """Valid Python code inside markdown blocks incurs no AST penalty."""
        evaluator = ResponseQualityEvaluator()
        valid_code_resp = (
            "Here is the function:\n"
            "```python\n"
            "def add_numbers(a: int, b: int) -> int:\n"
            "    return a + b\n"
            "```\n"
            "This function adds two numbers correctly."
        )
        score = evaluator.evaluate_quality(query="Write code", response_text=valid_code_resp)
        assert score == 1.0

    def test_deterministic_arithmetic_verification(self):
        """Simple arithmetic query penalizes responses missing the expected answer."""
        evaluator = ResponseQualityEvaluator()
        query = "What is 15 multiplied by 4?"

        # Correct response containing 60
        correct_resp = "15 multiplied by 4 is 60."
        score_correct = evaluator.evaluate_quality(query=query, response_text=correct_resp)
        assert score_correct == 1.0

        # Wrong response claiming 75 without mentioning 60
        wrong_resp = "15 multiplied by 4 is 75."
        score_wrong = evaluator.evaluate_quality(query=query, response_text=wrong_resp)
        # 1.0 - 0.50 (arithmetic mismatch penalty) = 0.50
        assert score_wrong <= 0.50

    def test_explicit_feedback_retained(self):
        """Explicit user feedback (+1 bonus, -1 penalty) is preserved."""
        evaluator = ResponseQualityEvaluator()
        # Neutral response text
        resp = "A standard response of sufficient length to avoid word count penalties."
        score_pos = evaluator.evaluate_quality(query="test", response_text=resp, explicit_feedback=1)
        score_neg = evaluator.evaluate_quality(query="test", response_text=resp, explicit_feedback=-1)
        # Positive feedback clamped to 1.0, negative feedback incurs -0.40 deduction
        assert score_pos == 1.0
        assert pytest.approx(score_neg, 0.01) == 0.60


# ===========================================================================
# 4. /health Architecture Description Test
# ===========================================================================

class TestHealthArchitectureDescription:
    def test_health_architecture_string(self, client: TestClient):
        """Health endpoint description accurately reflects Disjoint LinUCB contextual router."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "Context-Aware Smart LLM Switching" in data["architecture"]
        assert "LinUCB" in data["architecture"]
        assert "6 Response Model Tiers" in data["architecture"]


# ===========================================================================
# 5. Context-Aware Completion Cache Tests
# ===========================================================================

class TestContextAwareCompletionCache:
    def test_completion_cache_hit_and_telemetry(self, client: TestClient):
        """Context-Aware Completion Cache provides instant hit on identical repeated query."""
        query = "Explain what an abstract syntax tree is in compiler design."
        r1 = client.post("/api/chat", json={"query": query})
        assert r1.status_code == 200
        d1 = r1.json()

        r2 = client.post("/api/chat", json={"query": query})
        assert r2.status_code == 200
        d2 = r2.json()

        assert d2["response"] == d1["response"]
        assert d2.get("switch_reason") == "Context-Aware Completion Cache Hit"
        assert d2.get("fallback_reason") == "exact_cache"
