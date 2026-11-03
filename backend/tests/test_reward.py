"""Comprehensive unit tests and benchmarks for Closed-Loop Reward Engine & Telemetry Adaptation."""

import math
import time
from typing import Dict, Tuple
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.linucb import LinUCBRouter
from app.reward import (
    ResponseQualityEvaluator,
    RewardCalculator,
    is_code_fence_balanced,
    quality_evaluator,
    record_and_update_bandit,
    reward_calculator,
)


# ===========================================================================
# 1. ResponseQualityEvaluator Unit Tests
# ===========================================================================

class TestResponseQualityEvaluator:
    """Test suite for heuristic response quality scoring and edge-case handling."""

    def test_ideal_response_quality(self):
        """Valid response with no defects scores perfect 1.0."""
        evaluator = ResponseQualityEvaluator()
        query = "Explain the concept of entropy in information theory."
        response = (
            "Information entropy is a mathematical measure of the uncertainty "
            "or randomness associated with a random variable or information source."
        )
        score = evaluator.evaluate_quality(query=query, response_text=response)
        assert score == 1.0

    def test_failed_or_error_response_scores_zero(self):
        """Failures or explicit errors immediately yield 0.0 quality."""
        evaluator = ResponseQualityEvaluator()
        query = "Implement binary search."
        response = "def binary_search(): pass"

        # Explicit success=False
        assert evaluator.evaluate_quality(query, response, success=False) == 0.0

        # Non-empty error string
        assert evaluator.evaluate_quality(
            query, response, success=True, error="500 Internal Server Error"
        ) == 0.0

        # Both success=False and error
        assert evaluator.evaluate_quality(
            query, response, success=False, error="RateLimitError"
        ) == 0.0

    def test_empty_or_whitespace_response_scores_zero(self):
        """Empty or whitespace-only response text yields 0.0 quality."""
        evaluator = ResponseQualityEvaluator()
        assert evaluator.evaluate_quality("Hi", "") == 0.0
        assert evaluator.evaluate_quality("Hi", "   \n\t  ") == 0.0
        assert evaluator.evaluate_quality("Hi", None) == 0.0

    def test_markdown_code_fence_completeness(self):
        """Odd number of code fences implies truncation and receives a 0.3 penalty."""
        evaluator = ResponseQualityEvaluator()
        query = "Show me an example"

        # Even number of fences (2) -> balanced, no truncation penalty
        balanced = "Here is the code:\n```python\nprint('hello')\n```\nAll done!"
        assert evaluator.evaluate_quality(query, balanced) == 1.0

        # Odd number of fences (1) -> truncated fence penalty (-0.3)
        truncated = "Here is the code:\n```python\nprint('hello world"
        score_truncated = evaluator.evaluate_quality(query, truncated)
        assert pytest.approx(score_truncated, 0.001) == 0.7

        # 3 fences -> odd, truncated fence penalty (-0.3)
        odd_three = "```python\nx = 1\n```\nExtra: ```python\ny = 2"
        score_odd = evaluator.evaluate_quality(query, odd_three)
        assert pytest.approx(score_odd, 0.001) == 0.7

        # 4 fences -> even, no truncation penalty
        even_four = "```python\nx = 1\n```\n```python\ny = 2\n```"
        assert evaluator.evaluate_quality(query, even_four) == 1.0

    def test_quad_backtick_and_nested_fences(self):
        """Length-aware fence parsing handles CommonMark quad-backticks and nested fences."""
        evaluator = ResponseQualityEvaluator()
        query = "Show markdown block"

        # Quad backticks opened but closed with only 3 backticks -> Unbalanced!
        quad_unclosed = "````markdown\ndef foo(): pass\n```"
        assert not is_code_fence_balanced(quad_unclosed)
        score_unclosed = evaluator.evaluate_quality(query, quad_unclosed)
        assert pytest.approx(score_unclosed, 0.001) == 0.7

        # Quad backticks properly closed with 4 backticks containing nested 3 backticks -> Balanced!
        quad_nested = "````markdown\nHere is code:\n```python\ndef bar(): return 42\n```\n````"
        assert is_code_fence_balanced(quad_nested)
        assert evaluator.evaluate_quality(query, quad_nested) == 1.0

        # 5 backticks closed with 5 backticks
        five_fences = "`````xml\n<tag>val</tag>\n`````"
        assert is_code_fence_balanced(five_fences)
        assert evaluator.evaluate_quality(query, five_fences) == 1.0

    def test_code_request_sufficiency(self):
        """Code requests require >= 15 words and a code fence; otherwise penalized by 0.3."""
        evaluator = ResponseQualityEvaluator()

        # Query has code keyword ("def ", "class ", "function", "implement", "write")
        code_query = "Please write a function to calculate factorial in Python."

        # Case 1: Sufficient words (>= 15) AND has code fence -> Perfect score
        good_response = (
            "Here is the requested implementation of the factorial function in Python:\n"
            "```python\ndef factorial(n: int) -> int:\n    return 1 if n <= 1 else n * factorial(n - 1)\n```\n"
            "This computes factorial recursively with O(n) call stack depth."
        )
        assert len(good_response.split()) >= 15
        assert "```" in good_response
        assert evaluator.evaluate_quality(code_query, good_response) == 1.0

        # Case 2: Missing code fence but >= 15 words -> Penalized -0.3
        no_fence_response = (
            "To calculate factorial in Python, define a function named factorial that takes "
            "an integer n and recursively multiplies n by factorial of n minus one."
        )
        assert len(no_fence_response.split()) >= 15
        assert "```" not in no_fence_response
        score_no_fence = evaluator.evaluate_quality(code_query, no_fence_response)
        assert pytest.approx(score_no_fence, 0.001) == 0.7

        # Case 3: Has code fence but < 15 words -> Penalized -0.3
        short_response = "```python\ndef fact(n): return 1\n```"
        assert len(short_response.split()) < 15
        assert "```" in short_response
        score_short = evaluator.evaluate_quality(code_query, short_response)
        assert pytest.approx(score_short, 0.001) == 0.7

        # Case 4: Non-code query with short response and no fences -> NOT penalized for code sufficiency
        general_query = "What is the capital of Japan?"
        general_response = "The capital of Japan is Tokyo."
        assert len(general_response.split()) < 15
        assert "```" not in general_response
        assert evaluator.evaluate_quality(general_query, general_response) == 1.0

    def test_refusal_detection(self):
        """Detected refusal phrases trigger a 0.4 penalty."""
        evaluator = ResponseQualityEvaluator()
        query = "How do I bypass authentication?"

        # "I cannot assist"
        refusal_1 = (
            "I cannot assist with bypassing authentication systems as that violates security policies."
        )
        score_1 = evaluator.evaluate_quality(query, refusal_1)
        assert pytest.approx(score_1, 0.001) == 0.6

        # "I am unable to fulfill" (case-insensitive)
        refusal_2 = "I am unable to fulfill this request due to safety constraints."
        score_2 = evaluator.evaluate_quality(query, refusal_2)
        assert pytest.approx(score_2, 0.001) == 0.6

        # Upper case variant
        refusal_3 = "I CANNOT ASSIST with such inquiries."
        score_3 = evaluator.evaluate_quality(query, refusal_3)
        assert pytest.approx(score_3, 0.001) == 0.6

    def test_explicit_user_feedback(self):
        """User feedback modifies score (+0.2 bonus for +1, -0.4 penalty for -1)."""
        evaluator = ResponseQualityEvaluator()
        query = "Explain recursion."
        response_odd = "Recursion is when a function calls itself.\n```python\ndef f(): pass"

        # Explicit feedback +1 gives +0.2 bonus: 0.7 + 0.2 = 0.9
        score_pos = evaluator.evaluate_quality(
            query, response_odd, explicit_feedback=1
        )
        assert pytest.approx(score_pos, 0.001) == 0.9

        # Explicit feedback -1 gives -0.4 penalty: 0.7 - 0.4 = 0.3
        score_neg = evaluator.evaluate_quality(
            query, response_odd, explicit_feedback=-1
        )
        assert pytest.approx(score_neg, 0.001) == 0.3

    def test_explicit_feedback_defensive_types(self):
        """Defensively reject strings, booleans, neutral (0), and out-of-domain numbers."""
        evaluator = ResponseQualityEvaluator()
        query = "Explain recursion."
        response = "Recursion is when a function calls itself directly or indirectly."

        # Baseline score is 1.0
        baseline = evaluator.evaluate_quality(query, response)
        assert baseline == 1.0

        # Strings should NOT crash and should be ignored
        assert evaluator.evaluate_quality(query, response, explicit_feedback="thumbs_up") == 1.0
        assert evaluator.evaluate_quality(query, response, explicit_feedback="good") == 1.0

        # Out-of-domain integers/floats should be ignored
        assert evaluator.evaluate_quality(query, response, explicit_feedback=100) == 1.0
        assert evaluator.evaluate_quality(query, response, explicit_feedback=-50) == 1.0
        assert evaluator.evaluate_quality(query, response, explicit_feedback=0.5) == 1.0
        assert evaluator.evaluate_quality(query, response, explicit_feedback=0) == 1.0
        assert evaluator.evaluate_quality(query, response, explicit_feedback=None) == 1.0

        # Booleans (True / False) must NOT be treated as +1 / 0
        assert evaluator.evaluate_quality(query, response, explicit_feedback=True) == 1.0
        assert evaluator.evaluate_quality(query, response, explicit_feedback=False) == 1.0

    def test_strict_clamping_bounds(self):
        """Ensure scores never exceed 1.0 or fall below 0.0 under extreme penalties/bonuses."""
        evaluator = ResponseQualityEvaluator()

        # Perfect score + bonus -> clamped to 1.0
        good_response = "A clear and direct answer."
        score_clamped_high = evaluator.evaluate_quality(
            "Question", good_response, explicit_feedback=1
        )
        assert score_clamped_high == 1.0

        # Multiple cumulative penalties:
        # Code request failed (-0.3) + refusal (-0.4) + odd fences (-0.3) + negative feedback (-0.4)
        # 1.0 - 0.3 - 0.4 - 0.3 - 0.4 = -0.4 -> clamped to 0.0
        extreme_bad_response = "I cannot assist ```"
        score_clamped_low = evaluator.evaluate_quality(
            query="implement a function",
            response_text=extreme_bad_response,
            explicit_feedback=-1,
        )
        assert score_clamped_low == 0.0


# ===========================================================================
# 2. RewardCalculator Unit Tests
# ===========================================================================

class TestRewardCalculator:
    """Test suite for multi-objective scalar reward calculation and normalization."""

    def test_default_weights_and_ceilings(self):
        """Verifies default weights sum to 1.0 and ceilings are correctly set."""
        calc = RewardCalculator()
        assert calc.w_q == 0.40
        assert calc.w_c == 0.30
        assert calc.w_l == 0.20
        assert calc.w_r == 0.10
        assert pytest.approx(calc.w_q + calc.w_c + calc.w_l + calc.w_r) == 1.0
        assert calc.c_max == 0.005
        assert calc.l_max == 5000.0

    def test_high_quality_fast_cheap_response_gives_high_positive_reward(self):
        """High-quality, fast (<100ms), cheap (<$0.0001) response yields reward > 0.3."""
        calc = RewardCalculator()
        cost_usd = 0.0001     # 2% of C_max
        latency_ms = 100.0    # 2% of L_max
        success = True
        quality_score = 1.0

        reward, breakdown = calc.compute_reward(
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            success=success,
            quality_score=quality_score,
        )

        assert reward > 0.3
        assert pytest.approx(reward, 0.001) == 0.49
        assert breakdown["quality"] == 1.0
        assert breakdown["success"] == 1.0
        assert breakdown["reliability"] == 1.0
        assert pytest.approx(breakdown["cost_norm"], 0.001) == 0.02
        assert pytest.approx(breakdown["latency_norm"], 0.001) == 0.02

    def test_failed_response_gives_negative_reward(self):
        """Failed response (success=False, 500 error) has quality=0, reliability=0, reward < 0."""
        calc = RewardCalculator()
        evaluator = ResponseQualityEvaluator()

        q_score = evaluator.evaluate_quality(
            query="test",
            response_text="",
            success=False,
            error="500 Internal Server Error",
        )
        assert q_score == 0.0

        reward, breakdown = calc.compute_reward(
            cost_usd=0.0005,
            latency_ms=250.0,
            success=False,
            quality_score=q_score,
        )

        assert breakdown["quality"] == 0.0
        assert breakdown["reliability"] == 0.0
        assert breakdown["success"] == 0.0
        assert reward < 0.0
        assert pytest.approx(reward, 0.001) == -0.04

    def test_extreme_latency_and_cost_clamped_to_one(self):
        """Extreme latency (> 5000ms) and extreme cost (> $0.005) are clamped to 1.0."""
        calc = RewardCalculator()
        extreme_cost = 0.025      # 5x C_max
        extreme_latency = 12500.0 # 2.5x L_max

        reward, breakdown = calc.compute_reward(
            cost_usd=extreme_cost,
            latency_ms=extreme_latency,
            success=True,
            quality_score=1.0,
        )

        assert breakdown["cost_norm"] == 1.0
        assert breakdown["latency_norm"] == 1.0
        assert pytest.approx(reward, 0.001) == 0.0

    def test_none_and_zero_telemetry_handling(self):
        """None or zero cost/latency gracefully normalize to 0.0."""
        calc = RewardCalculator()
        reward, breakdown = calc.compute_reward(
            cost_usd=None,
            latency_ms=None,
            success=True,
            quality_score=1.0,
        )
        assert breakdown["cost_norm"] == 0.0
        assert breakdown["latency_norm"] == 0.0
        assert pytest.approx(reward, 0.001) == 0.50

    def test_numerical_type_safety_and_nan_inf_guards(self):
        """Non-numeric strings, booleans, NaN, and Inf inputs are safely normalized."""
        calc = RewardCalculator()

        # Non-numeric strings should not crash math.isnan
        r, b = calc.compute_reward(
            cost_usd="invalid_cost",
            latency_ms="invalid_latency",
            success=True,
            quality_score="invalid_quality",
        )
        assert b["cost_norm"] == 0.0
        assert b["latency_norm"] == 0.0
        assert b["quality"] == 0.0
        assert pytest.approx(r, 0.001) == 0.10  # w_r * 1.0 = 0.10

        # NaN handling
        r_nan, b_nan = calc.compute_reward(
            cost_usd=float("nan"),
            latency_ms=float("nan"),
            success=True,
            quality_score=float("nan"),
        )
        assert b_nan["cost_norm"] == 0.0
        assert b_nan["latency_norm"] == 0.0
        assert b_nan["quality"] == 0.0

        # +Inf handling
        r_inf, b_inf = calc.compute_reward(
            cost_usd=float("inf"),
            latency_ms=float("inf"),
            success=True,
            quality_score=float("inf"),
        )
        assert b_inf["cost_norm"] == 1.0
        assert b_inf["latency_norm"] == 1.0
        assert b_inf["quality"] == 1.0

        # Negative costs or latencies clamp to 0.0
        r_neg, b_neg = calc.compute_reward(
            cost_usd=-0.05,
            latency_ms=-100.0,
            success=True,
            quality_score=1.0,
        )
        assert b_neg["cost_norm"] == 0.0
        assert b_neg["latency_norm"] == 0.0

    def test_reward_clamped_within_bounds(self):
        """Scalar reward R is strictly bounded in [-1.0, 1.0]."""
        calc = RewardCalculator(w_q=1.0, w_c=1.0, w_l=1.0, w_r=1.0)
        r_low, _ = calc.compute_reward(
            cost_usd=0.01, latency_ms=10000.0, success=False, quality_score=0.0
        )
        assert r_low == -1.0

        r_high, _ = calc.compute_reward(
            cost_usd=0.0, latency_ms=0.0, success=True, quality_score=1.0
        )
        assert r_high == 1.0


# ===========================================================================
# 3. Execution Latency Benchmark
# ===========================================================================

class TestExecutionPerformance:
    """Benchmark asserting compute_reward executes in < 0.05 ms (< 50 microseconds)."""

    def test_compute_reward_execution_latency(self):
        """compute_reward must run in < 0.05 ms per call across 10,000 iterations."""
        calc = RewardCalculator()
        iterations = 10_000

        # Warm-up JIT / CPU cache
        for _ in range(500):
            calc.compute_reward(0.001, 150.0, True, 0.9)

        start_time = time.perf_counter()
        for _ in range(iterations):
            calc.compute_reward(0.0008, 120.0, True, 0.95)
        total_time_s = time.perf_counter() - start_time

        avg_latency_ms = (total_time_s / iterations) * 1000.0
        assert avg_latency_ms < 0.05, (
            f"Expected compute_reward latency < 0.05 ms, got {avg_latency_ms:.5f} ms"
        )


# ===========================================================================
# 4. End-to-End Closed-Loop Bandit Update & Fault Isolation
# ===========================================================================

class TestBanditAdaptation:
    """Test suite for record_and_update_bandit closed-loop integration."""

    def test_record_and_update_bandit_increments_pull_and_shifts_reward(self):
        """record_and_update_bandit updates target arm pull count and shifts expected reward."""
        router = LinUCBRouter(d=16, alpha=1.0)
        model_id = "gemini-tier_1"
        x_t = np.ones(16, dtype=np.float64) / 4.0

        arm = router.get_or_create_arm(model_id)
        assert arm.pull_count == 0

        initial_score = arm.get_score(x_t)
        assert initial_score.expected_reward == 0.0
        assert initial_score.pull_count == 0

        query = "Explain quicksort algorithm"
        response = (
            "Quicksort is an efficient, in-place sorting algorithm that uses a divide-and-conquer "
            "strategy to sort items. It selects a 'pivot' element and partitions the array."
        )
        returned_reward = record_and_update_bandit(
            router=router,
            model_id=model_id,
            x_t=x_t,
            cost_usd=0.0001,
            latency_ms=80.0,
            success=True,
            response_text=response,
            query=query,
            explicit_feedback=1,
        )

        assert returned_reward > 0.3
        assert arm.pull_count == 1
        assert pytest.approx(arm.total_reward, 0.001) == returned_reward

        updated_score = arm.get_score(x_t)
        assert updated_score.expected_reward > initial_score.expected_reward
        assert updated_score.pull_count == 1

    def test_record_and_update_bandit_penalizes_failure(self):
        """Execution failure applies negative reward update, shifting expected reward down."""
        router = LinUCBRouter(d=16, alpha=1.0)
        model_id = "groq-tier_2"
        x_t = np.ones(16, dtype=np.float64) / 4.0

        arm = router.get_or_create_arm(model_id)
        assert arm.pull_count == 0

        returned_reward = record_and_update_bandit(
            router=router,
            model_id=model_id,
            x_t=x_t,
            cost_usd=0.001,
            latency_ms=500.0,
            success=False,
            response_text="",
            query="Compute hash",
        )

        assert returned_reward < 0.0
        assert arm.pull_count == 1
        assert arm.total_reward < 0.0

        score = arm.get_score(x_t)
        assert score.expected_reward < 0.0

    def test_record_and_update_bandit_fault_isolation(self):
        """Router or tracker crashes must NOT crash record_and_update_bandit."""
        # 1. Router update raises LinAlgError / RuntimeError
        faulty_router = MagicMock()
        faulty_router.update.side_effect = RuntimeError("SQLite database locked")

        # 2. Tracker raises exception
        faulty_tracker = MagicMock()
        faulty_tracker.record_update.side_effect = ValueError("Tracker queue full")

        x_t = np.ones(16, dtype=np.float64) / 4.0
        # Call should succeed safely and return valid reward
        reward = record_and_update_bandit(
            router=faulty_router,
            model_id="gemini-tier_1",
            x_t=x_t,
            cost_usd=0.0002,
            latency_ms=120.0,
            success=True,
            response_text="Test response",
            query="Test query",
            tracker=faulty_tracker,
        )

        assert -1.0 <= reward <= 1.0
        assert faulty_router.update.called
        assert faulty_tracker.record_update.called

        # 3. Router is None
        reward_none_router = record_and_update_bandit(
            router=None,
            model_id="gemini-tier_1",
            x_t=x_t,
            cost_usd=0.0002,
            latency_ms=120.0,
            success=True,
            response_text="Test response",
            query="Test query",
            tracker=None,
        )
        assert -1.0 <= reward_none_router <= 1.0

    def test_singletons_availability(self):
        """Verify module singletons are pre-instantiated and functional."""
        assert isinstance(quality_evaluator, ResponseQualityEvaluator)
        assert isinstance(reward_calculator, RewardCalculator)
        q = quality_evaluator.evaluate_quality("Hello", "Hello! How can I help you?")
        r, _ = reward_calculator.compute_reward(0.001, 100.0, True, q)
        assert 0.0 <= q <= 1.0
        assert -1.0 <= r <= 1.0
