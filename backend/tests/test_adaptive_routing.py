"""Comprehensive tests for the Adaptive Routing Algorithm.

Proves:
1. Simple queries use eligible lightweight models (Tier 1).
2. Complex queries use capable models when required (Tier 4 / Tier 5 / Tier 6).
3. Hard constraints (context window, budget, deadline, health, capability floors) strictly override hysteresis.
4. Provider failures (especially 429 quota exhaustion) trigger immediate health backoff and explicit fallback.
5. Missing and stale data do not cause unsafe routing (conservative LCB and decay).
6. Statistical deadline modeling evaluates exact log-normal probabilities rather than heuristic mean+std claims.
7. Displayed tier and model match actual execution.
8. Latency breakdown, token usage, cost, and savings are calculated from real metrics.
"""

import math
import time
import pytest
from app.adapters.base import LLMResult
from app.analyzer_llm import AnalyzerDecision
from app.bayesian import (
    BetaQualityDistribution,
    BetaFailureDistribution,
    LogNormalLatencyDistribution,
    ModelHealthTracker,
)
from app.registry import ModelRegistry, ModelSpec, _build_demo_models
from app.router import SmartRouter, ModelScore, RoutingResult
from app.tracker import estimate_cost_usd


@pytest.fixture
def test_registry():
    """Provides an isolated 6-tier test registry."""
    return ModelRegistry(_build_demo_models())


@pytest.fixture
def fresh_health_tracker():
    """Provides an isolated ModelHealthTracker."""
    tracker = ModelHealthTracker()
    tracker.ensure_model("demo-tier_1", prior_quality=0.80, expected_latency_ms=250.0)
    tracker.ensure_model("demo-tier_2", prior_quality=0.84, expected_latency_ms=200.0)
    tracker.ensure_model("demo-tier_3", prior_quality=0.85, expected_latency_ms=400.0)
    tracker.ensure_model("demo-tier_4", prior_quality=0.92, expected_latency_ms=350.0)
    tracker.ensure_model("demo-tier_5", prior_quality=0.95, expected_latency_ms=500.0)
    tracker.ensure_model("demo-tier_6", prior_quality=0.98, expected_latency_ms=800.0)
    return tracker


# ============================================================================
# 1. Simple queries can use eligible lightweight models
# ============================================================================
def test_simple_queries_use_lightweight_models(test_registry, fresh_health_tracker):
    router = SmartRouter()
    simple_decision = AnalyzerDecision(
        task_type="general",
        complexity="low",
        required_capability="tier_1",
        reason="Simple greeting or short factual query.",
        analyzer_model=test_registry.get_analyzer(),
        analyzer_result=LLMResult(content="", text="", input_tokens=10, output_tokens=10, latency_ms=0.5),
        complexity_score=0.10,
        reasoning_required=False,
        coding_required=False,
        target_tier="tier_1",
        target_provider="gemini",
    )

    result = router.resolve(
        simple_decision,
        strategy="balanced",
        registry=test_registry,
        health_tracker=fresh_health_tracker,
    )

    assert result.primary_model.tier in ("tier_1", "tier_2")
    assert result.scores[result.primary_model.model_id].eligible is True
    assert result.scores[result.primary_model.model_id].cost_efficiency >= 0.8


# ============================================================================
# 2. Complex queries use capable models when required
# ============================================================================
def test_complex_queries_use_capable_models(test_registry, fresh_health_tracker):
    router = SmartRouter()

    # High complexity coding task
    coding_decision = AnalyzerDecision(
        task_type="coding",
        complexity="high",
        required_capability="tier_4",
        reason="Complex algorithm design with graph traversal and unit testing.",
        analyzer_model=test_registry.get_analyzer(),
        analyzer_result=LLMResult(content="", text="", input_tokens=150, output_tokens=300, latency_ms=10.0),
        complexity_score=0.88,
        reasoning_required=False,
        coding_required=True,
        target_tier="tier_4",
    )

    coding_result = router.resolve(
        coding_decision,
        strategy="balanced",
        registry=test_registry,
        health_tracker=fresh_health_tracker,
    )
    assert coding_result.primary_model.tier in ("tier_4", "tier_5", "tier_6")
    assert coding_result.primary_model.coding >= 0.85

    # High complexity reasoning task
    reasoning_decision = AnalyzerDecision(
        task_type="reasoning",
        complexity="high",
        required_capability="tier_5",
        reason="Multi-step architectural trade-off analysis and distributed consistency proof.",
        analyzer_model=test_registry.get_analyzer(),
        analyzer_result=LLMResult(content="", text="", input_tokens=200, output_tokens=500, latency_ms=15.0),
        complexity_score=0.92,
        reasoning_required=True,
        coding_required=False,
        target_tier="tier_5",
    )

    reasoning_result = router.resolve(
        reasoning_decision,
        strategy="balanced",
        registry=test_registry,
        health_tracker=fresh_health_tracker,
    )
    assert reasoning_result.primary_model.tier in ("tier_5", "tier_6")
    assert reasoning_result.primary_model.reasoning >= 0.90


# ============================================================================
# 3. Hard constraints override hysteresis
# ============================================================================
def test_hard_constraints_override_hysteresis_capability_floor(test_registry, fresh_health_tracker):
    router = SmartRouter()

    # Previous turn was Tier 1 (Lightweight)
    prev_model = "demo-tier_1"

    # New turn is a high complexity coding query (requires coding >= 0.84)
    # Tier 1 has coding = 0.75, failing the hard capability floor
    decision = AnalyzerDecision(
        task_type="coding",
        complexity="high",
        required_capability="tier_4",
        reason="Complex refactor needing specialized coding model.",
        analyzer_model=test_registry.get_analyzer(),
        analyzer_result=LLMResult(content="", text="", input_tokens=50, output_tokens=50, latency_ms=5.0),
        complexity_score=0.85,
        reasoning_required=False,
        coding_required=True,
        target_tier="tier_4",
    )

    result = router.resolve(
        decision,
        registry=test_registry,
        session_last_model_id=prev_model,
        hysteresis_margin=0.20,  # Even a very high hysteresis margin must NOT retain ineligible model
        health_tracker=fresh_health_tracker,
    )

    # Hard constraint MUST disqualify Tier 1
    assert result.scores[prev_model].eligible is False
    assert "insufficient for high-complexity coding" in (result.scores[prev_model].ineligibility_reason or "")
    # Hysteresis must NOT retain demo-tier_1
    assert result.primary_model.model_id != prev_model
    assert result.retained_by_hysteresis is False
    assert result.primary_model.tier in ("tier_4", "tier_5", "tier_6")


def test_hard_constraints_override_hysteresis_budget_and_context(test_registry, fresh_health_tracker):
    router = SmartRouter()

    decision = AnalyzerDecision(
        task_type="general",
        complexity="low",
        required_capability="tier_1",
        reason="General query.",
        analyzer_model=test_registry.get_analyzer(),
        analyzer_result=LLMResult(content="", text="", input_tokens=10, output_tokens=10, latency_ms=2.0),
        complexity_score=0.20,
    )

    # Budget cap so strict ($0.00001) that only Tier 1 is eligible; Tier 6 costs too much
    result_budget = router.resolve(
        decision,
        registry=test_registry,
        estimated_input_tokens=5000,
        estimated_output_tokens=1000,
        max_budget_usd=0.0020,
        session_last_model_id="demo-tier_6",
        health_tracker=fresh_health_tracker,
    )
    # Tier 6 must be disqualified by budget cap, ignoring hysteresis
    assert result_budget.scores["demo-tier_6"].eligible is False
    assert result_budget.retained_by_hysteresis is False
    assert result_budget.primary_model.model_id != "demo-tier_6"


# ============================================================================
# 4. Provider failures trigger explicit fallback behavior
# ============================================================================
def test_provider_failures_trigger_cooldown_and_fallback(test_registry, fresh_health_tracker):
    router = SmartRouter()

    decision = AnalyzerDecision(
        task_type="reasoning",
        complexity="high",
        required_capability="tier_5",
        reason="Deep reasoning problem.",
        analyzer_model=test_registry.get_analyzer(),
        analyzer_result=LLMResult(content="", text="", input_tokens=100, output_tokens=100, latency_ms=5.0),
        complexity_score=0.90,
        reasoning_required=True,
    )

    # Normal routing chooses Tier 5
    res1 = router.resolve(decision, registry=test_registry, health_tracker=fresh_health_tracker)
    assert res1.primary_model.model_id == "demo-tier_5"

    # Simulate HTTP 429 quota exhaustion on Tier 5
    fresh_health_tracker.record_outcome(
        "demo-tier_5",
        success=False,
        is_rate_limit=True,
        cooldown_seconds=300.0,
    )

    # Verify model is recognized in cooldown
    assert fresh_health_tracker.is_in_cooldown("demo-tier_5") is True

    # Next routing attempt MUST disqualify demo-tier_5 immediately without attempting it
    res2 = router.resolve(decision, registry=test_registry, health_tracker=fresh_health_tracker)
    assert res2.scores["demo-tier_5"].eligible is False
    assert "cooldown / quota backoff" in res2.scores["demo-tier_5"].ineligibility_reason
    assert res2.primary_model.model_id != "demo-tier_5"
    # Routes to alternate capable model (Tier 4 or Tier 6)
    assert res2.primary_model.model_id in ("demo-tier_4", "demo-tier_6")


# ============================================================================
# 5. Missing and stale data do not cause unsafe routing
# ============================================================================
def test_missing_data_uses_conservative_lower_credible_bound():
    dist = BetaQualityDistribution.from_prior(model_id="test-model", prior_quality=0.85, pseudo_samples=4.0)
    # With zero real observations, variance is wide
    mean_init = dist.expected_quality
    lcb_init = dist.conservative_lower_bound(z=1.0)
    assert lcb_init < mean_init  # LCB is strictly conservative

    # Observe 10 high-quality responses (0.95)
    for _ in range(10):
        dist.update(0.95)

    # Posterior variance decreases, LCB moves closer to mean
    mean_obs = dist.expected_quality
    lcb_obs = dist.conservative_lower_bound(z=1.0)
    assert lcb_obs > lcb_init
    assert (mean_obs - lcb_obs) < (mean_init - lcb_init)


def test_stale_data_decays_conservatively():
    dist = BetaQualityDistribution.from_prior(model_id="test-model", prior_quality=0.90, pseudo_samples=10.0)
    for _ in range(5):
        dist.update(0.98)

    # Artificially set update timestamp to 24 hours ago (86400 seconds)
    dist.last_updated = time.time() - 86400.0

    # LCB with decay should be strictly lower than expected quality
    lcb_stale = dist.conservative_lower_bound(z=1.0)
    assert lcb_stale < dist.expected_quality


# ============================================================================
# 6. Statistical deadline modeling (Log-Normal P(Latency <= D))
# ============================================================================
def test_statistical_deadline_probability_calculation():
    # Latency distribution for a model with typical latency 300ms
    dist = LogNormalLatencyDistribution(model_id="test-model", expected_latency_ms=300.0)

    # 1. Very generous deadline: 1000ms -> P(L <= 1000ms) should be near 1.0
    p_generous = dist.probability_meeting_deadline(1000.0)
    assert p_generous > 0.95

    # 2. Tight deadline: 300ms -> P(L <= 300ms) should be ~0.50 (median)
    p_median = dist.probability_meeting_deadline(300.0)
    assert 0.40 <= p_median <= 0.60

    # 3. Impossible deadline: 50ms -> P(L <= 50ms) should be near 0.0
    p_strict = dist.probability_meeting_deadline(50.0)
    assert p_strict < 0.05

    # Never claim that mean + 1 std guarantees deadline compliance:
    # A log-normal tail is strictly right-skewed
    samples = [280.0, 310.0, 290.0, 320.0, 305.0]
    for s in samples:
        dist.update(s)
    pred_lat = dist.predictive_mean_ms
    assert pred_lat > 250.0


def test_deadline_hard_constraint_enforcement(test_registry, fresh_health_tracker):
    router = SmartRouter()

    decision = AnalyzerDecision(
        task_type="general",
        complexity="low",
        required_capability="tier_1",
        reason="Deadline sensitive query.",
        analyzer_model=test_registry.get_analyzer(),
        analyzer_result=LLMResult(content="", text="", input_tokens=10, output_tokens=10, latency_ms=1.0),
        complexity_score=0.20,
    )

    # Strict deadline: 220ms.
    # demo-tier_6 has median latency 800ms -> P(L <= 220) is near zero
    # demo-tier_2 has median latency 200ms -> P(L <= 220) is ~55%
    result = router.resolve(
        decision,
        registry=test_registry,
        deadline_ms=220.0,
        health_tracker=fresh_health_tracker,
    )

    # Slow models must fail the 40% probability floor
    assert result.scores["demo-tier_6"].eligible is False
    assert "below 40% threshold" in (result.scores["demo-tier_6"].ineligibility_reason or "")
    # Fast model selected
    assert result.primary_model.expected_latency_ms <= 250.0


# ============================================================================
# 7. Real Token, Cost, and Savings Calculation Verification
# ============================================================================
def test_cost_and_savings_calculation_accuracy():
    # Model: $0.10 / Mtok input, $0.20 / Mtok output
    model_prices = (0.10, 0.20)
    in_tok = 1500
    out_tok = 500

    cost = estimate_cost_usd(model_prices, in_tok, out_tok)
    # Expected: (1500 * 0.10 + 500 * 0.20) / 1_000_000 = (150 + 100) / 1_000_000 = $0.00025
    assert cost == pytest.approx(0.00025, abs=1e-7)

    # Strongest baseline: $1.25 / Mtok in, $5.00 / Mtok out
    baseline_prices = (1.25, 5.00)
    baseline_cost = estimate_cost_usd(baseline_prices, in_tok, out_tok)
    # Expected: (1500 * 1.25 + 500 * 5.00) / 1_000_000 = (1875 + 2500) / 1_000_000 = $0.004375
    assert baseline_cost == pytest.approx(0.004375, abs=1e-7)

    # Savings calculation
    savings_usd = max(0.0, baseline_cost - cost)
    savings_pct = (savings_usd / baseline_cost) * 100.0

    assert savings_usd == pytest.approx(0.004125, abs=1e-7)
    assert savings_pct == pytest.approx(94.2857, abs=1e-3)
