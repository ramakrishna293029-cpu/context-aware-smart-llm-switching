"""Unit test suite for MCDA Hard-Constraint Eligibility Filter for LinUCB Router."""

import math
import sys
import time
from typing import List
from unittest.mock import MagicMock
import pytest

from app.circuit import ProviderCircuit
from app.config import Settings
from app.eligibility import EligibilityFilter, EligibleSet, eligibility_filter
from app.registry import ModelSpec, registry


@pytest.fixture
def six_models() -> List[ModelSpec]:
    """Retrieve the standard 6 architecture tiers from the registry."""
    return [registry.get_by_tier(f"tier_{i}") for i in range(1, 7)]


@pytest.fixture
def demo_free_model() -> ModelSpec:
    """Zero-cost demo model for budget boundary testing."""
    return ModelSpec(
        model_id="mock-free-tier",
        name="Mock Free Tier",
        provider="mock",
        endpoint_model="mock-free",
        api_key="",
        base_url="",
        input_price_per_mtok=0.0,
        output_price_per_mtok=0.0,
        expected_latency_ms=100.0,
        quality=0.75,
        reasoning=0.70,
        coding=0.70,
        context_window=16384,
        tier="tier_1",
        demo_mode=True,
    )


@pytest.fixture
def clean_circuit() -> ProviderCircuit:
    """Fresh isolated circuit breaker instance."""
    return ProviderCircuit(fail_threshold=2, cooldown_s=30.0)


@pytest.fixture
def clean_filter(clean_circuit: ProviderCircuit) -> EligibilityFilter:
    """Isolated EligibilityFilter instance with mock tracker and clean circuit breaker."""
    mock_tracker = MagicMock()
    mock_tracker.budget_status.return_value = {
        "day_spend": 0.0,
        "month_spend": 0.0,
        "daily_budget_usd": 50.0,
        "monthly_budget_usd": 500.0,
    }
    return EligibilityFilter(
        settings=Settings(max_cost_per_request=0.50),
        circuit_registry=clean_circuit,
        tracker=mock_tracker,
        budget_cache_ttl_s=0.0,
    )


class TestEligibilityFilter:
    """Verification of 4 hard constraints, stable zero-ranking ordering, and edge cases."""

    def test_singleton_instance(self):
        """Verify module singleton is properly instantiated."""
        assert isinstance(eligibility_filter, EligibilityFilter)
        assert eligibility_filter.circuit_registry is not None
        assert eligibility_filter.tracker is not None

    def test_happy_path_all_six_models_eligible(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """Small prompt with healthy providers -> all 6 models must be eligible."""
        result = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=100,
            estimated_output_tokens=200,
        )

        assert isinstance(result, EligibleSet)
        assert result.total_evaluated == 6
        assert result.eligible_count == 6
        assert len(result.eligible_models) == 6
        assert len(result.ineligible_models) == 0

        eligible_ids = [m.model_id for m in result.eligible_models]
        assert eligible_ids == [
            "gemini-tier_1",
            "groq-tier_2",
            "gemini-tier_3",
            "groq-tier_4",
            "groq-tier_5",
            "gemini-tier_6",
        ]

    def test_context_window_boundary_10k_tokens(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """Prompt with 10,000 tokens cleanly disqualifies Groq 8k models (Tier 2, Tier 5)

        while retaining Gemini 1M models (Tier 1, Tier 3, Tier 6) and Groq 32k (Tier 4).
        """
        # 9,500 input + 500 output = 10,000 total tokens
        result = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=9500,
            estimated_output_tokens=500,
        )

        eligible_ids = [m.model_id for m in result.eligible_models]
        assert "groq-tier_2" not in eligible_ids
        assert "groq-tier_5" not in eligible_ids

        # Gemini 1M models must be retained
        assert "gemini-tier_1" in eligible_ids
        assert "gemini-tier_3" in eligible_ids
        assert "gemini-tier_6" in eligible_ids
        # Groq Qwen 32k context is also retained
        assert "groq-tier_4" in eligible_ids

        assert result.eligible_count == 4
        assert result.total_evaluated == 6
        assert len(result.ineligible_models) == 2

        # Check exact rejection reasons
        assert "Context window exceeded" in result.ineligible_models["groq-tier_2"]
        assert "8192" in result.ineligible_models["groq-tier_2"]
        assert "Context window exceeded" in result.ineligible_models["groq-tier_5"]
        assert "8192" in result.ineligible_models["groq-tier_5"]

    def test_context_window_exact_capacity_boundary(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """Exact context boundary (total_tokens == model.context_window) must remain eligible."""
        tier2 = next(m for m in six_models if m.model_id == "groq-tier_2")
        assert tier2.context_window == 8192

        # Exactly 8,192 tokens: 8,000 in + 192 out
        res_exact = clean_filter.filter(
            models=[tier2],
            estimated_input_tokens=8000,
            estimated_output_tokens=192,
        )
        assert res_exact.eligible_count == 1
        assert res_exact.eligible_models[0].model_id == "groq-tier_2"

        # 8,193 tokens (exceeds by 1) -> must be disqualified
        res_exceeded = clean_filter.filter(
            models=[tier2],
            estimated_input_tokens=8000,
            estimated_output_tokens=193,
        )
        assert res_exceeded.eligible_count == 0
        assert "groq-tier_2" in res_exceeded.ineligible_models

    def test_circuit_breaker_tripped_disqualifies_only_that_model(
        self, clean_filter: EligibilityFilter, clean_circuit: ProviderCircuit, six_models: List[ModelSpec]
    ):
        """Tripping a single model's circuit breaker cleanly disqualifies only that model."""
        clean_circuit.failure("groq-tier_4")
        clean_circuit.failure("groq-tier_4")
        assert not clean_circuit.allow("groq-tier_4")

        result = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=150,
            estimated_output_tokens=150,
            circuit_registry=clean_circuit,
        )

        assert result.total_evaluated == 6
        assert result.eligible_count == 5
        assert "groq-tier_4" in result.ineligible_models
        assert "Circuit breaker tripped" in result.ineligible_models["groq-tier_4"]

        # Ensure all other 5 models are eligible
        eligible_ids = [m.model_id for m in result.eligible_models]
        assert "groq-tier_4" not in eligible_ids
        assert "gemini-tier_1" in eligible_ids
        assert "groq-tier_2" in eligible_ids
        assert "gemini-tier_3" in eligible_ids
        assert "groq-tier_5" in eligible_ids
        assert "gemini-tier_6" in eligible_ids

    def test_circuit_breaker_exception_fail_open_isolation(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """If circuit registry throws unexpected exception, filter fails open rather than crashing."""
        broken_circuit = MagicMock()
        broken_circuit.allow.side_effect = RuntimeError("Redis connection timeout")

        result = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
            circuit_registry=broken_circuit,
        )

        # Fail-open: all healthy models remain eligible
        assert result.eligible_count == 6
        assert result.total_evaluated == 6

    def test_request_budget_cap_excludes_expensive_retains_cheap(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """max_budget_usd = 0.0001 cleanly excludes Tier 5 / Tier 6 while retaining cheap Tier 1 / Tier 2."""
        result = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=200,
            estimated_output_tokens=100,
            max_budget_usd=0.0001,
        )

        eligible_ids = [m.model_id for m in result.eligible_models]
        assert "gemini-tier_1" in eligible_ids
        assert "groq-tier_2" in eligible_ids
        assert "groq-tier_5" not in eligible_ids
        assert "gemini-tier_6" not in eligible_ids

        assert "groq-tier_5" in result.ineligible_models
        assert "exceeds budget cap" in result.ineligible_models["groq-tier_5"]
        assert "gemini-tier_6" in result.ineligible_models
        assert "exceeds budget cap" in result.ineligible_models["gemini-tier_6"]

    def test_max_budget_usd_zero_boundary(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec], demo_free_model: ModelSpec
    ):
        """max_budget_usd = 0.0 cleanly excludes all paid models while permitting zero-cost models."""
        candidate_pool = [demo_free_model] + six_models

        result = clean_filter.filter(
            models=candidate_pool,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
            max_budget_usd=0.0,
        )

        assert result.eligible_count == 1
        assert result.eligible_models[0].model_id == "mock-free-tier"
        assert len(result.ineligible_models) == 6
        for m in six_models:
            assert m.model_id in result.ineligible_models
            assert "exceeds budget cap" in result.ineligible_models[m.model_id]

    def test_zero_ranking_verification_preserves_exact_input_order(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """Confirms eligible_models strictly preserves input order with NO scoring, sorting, or reordering."""
        reversed_models = list(reversed(six_models))
        result_rev = clean_filter.filter(
            models=reversed_models,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
        )
        assert [m.model_id for m in result_rev.eligible_models] == [m.model_id for m in reversed_models]

        permuted_models = [six_models[4], six_models[0], six_models[5], six_models[2], six_models[1], six_models[3]]
        result_perm = clean_filter.filter(
            models=permuted_models,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
        )
        assert [m.model_id for m in result_perm.eligible_models] == [m.model_id for m in permuted_models]

        for m in result_perm.eligible_models:
            assert not hasattr(m, "_heuristic_score")
            assert not hasattr(m, "_linucb_rank")

    def test_daily_spend_cap_exhaustion(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """When tracker shows daily spend limit reached, all models are cleanly disqualified."""
        mock_exhausted_tracker = MagicMock()
        mock_exhausted_tracker.budget_status.return_value = {
            "day_spend": 52.40,
            "daily_budget_usd": 50.00,
            "month_spend": 120.00,
            "monthly_budget_usd": 500.00,
        }

        result = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
            tracker=mock_exhausted_tracker,
        )

        assert result.eligible_count == 0
        assert len(result.eligible_models) == 0
        assert result.total_evaluated == 6
        assert len(result.ineligible_models) == 6
        for mid, reason in result.ineligible_models.items():
            assert "Daily spend cap exhausted" in reason

    def test_monthly_spend_cap_exhaustion(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """When tracker shows monthly spend limit reached, all models are cleanly disqualified."""
        mock_exhausted_tracker = MagicMock()
        mock_exhausted_tracker.budget_status.return_value = {
            "day_spend": 10.00,
            "daily_budget_usd": 50.00,
            "month_spend": 515.00,
            "monthly_budget_usd": 500.00,
        }

        result = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
            tracker=mock_exhausted_tracker,
        )

        assert result.eligible_count == 0
        assert len(result.eligible_models) == 0
        assert result.total_evaluated == 6
        assert len(result.ineligible_models) == 6
        for mid, reason in result.ineligible_models.items():
            assert "Monthly spend cap exhausted" in reason

    def test_tracker_exception_and_malformed_values_fail_open(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """Tracker exceptions and malformed spend status dictionaries must not crash the filter."""
        # 1. Tracker raises database exception
        crashing_tracker = MagicMock()
        crashing_tracker.budget_status.side_effect = sqlite3_err = RuntimeError("SQLite database locked")

        res_err = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
            tracker=crashing_tracker,
        )
        assert res_err.eligible_count == 6

        # 2. Tracker returns NaN / strings / corrupted dictionary
        malformed_tracker = MagicMock()
        malformed_tracker.budget_status.return_value = {
            "day_spend": "NaN",
            "daily_budget_usd": -10.0,
            "month_spend": float("nan"),
            "monthly_budget_usd": None,
        }
        res_malformed = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
            tracker=malformed_tracker,
        )
        assert res_malformed.eligible_count == 6

    def test_invalid_model_context_window(
        self, clean_filter: EligibilityFilter
    ):
        """Models with invalid context windows (<= 0 or None) are cleanly disqualified."""
        invalid_model = ModelSpec(
            model_id="corrupt-model",
            name="Corrupted Model",
            provider="mock",
            endpoint_model="mock-corrupt",
            api_key="",
            base_url="",
            input_price_per_mtok=0.1,
            output_price_per_mtok=0.2,
            expected_latency_ms=100.0,
            quality=0.5,
            reasoning=0.5,
            coding=0.5,
            context_window=0,  # Invalid context window <= 0
            tier="tier_1",
            demo_mode=True,
        )

        result = clean_filter.filter(
            models=[invalid_model],
            estimated_input_tokens=100,
            estimated_output_tokens=100,
        )
        assert result.eligible_count == 0
        assert "corrupt-model" in result.ineligible_models
        assert "Invalid context window" in result.ineligible_models["corrupt-model"]

    def test_extreme_and_non_finite_token_edge_cases(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """Comprehensive edge cases: non-finite tokens (Inf, NaN, sys.maxsize), strings, None."""
        # 1. float('inf') -> sanitized to sys.maxsize, cleanly exceeding all context windows
        res_inf = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=float("inf"),
            estimated_output_tokens=500,
        )
        assert res_inf.eligible_count == 0
        assert res_inf.total_evaluated == 6
        for mid, reason in res_inf.ineligible_models.items():
            assert "Context window exceeded" in reason

        # 2. float('nan') -> sanitized to 0
        res_nan = clean_filter.filter(
            models=six_models,
            estimated_input_tokens=float("nan"),
            estimated_output_tokens=float("nan"),
        )
        assert res_nan.eligible_count == 6

        # 3. String representations of numbers
        res_str = clean_filter.filter(
            models=six_models,
            estimated_input_tokens="250",
            estimated_output_tokens="150",
        )
        assert res_str.eligible_count == 6

        # 4. None models argument
        res_none = clean_filter.filter(
            models=None,
            estimated_input_tokens=100,
            estimated_output_tokens=100,
        )
        assert res_none.eligible_count == 0
        assert res_none.total_evaluated == 0
        assert res_none.eligible_models == []
        assert res_none.ineligible_models == {}

        # 5. Model list with None elements
        res_with_none = clean_filter.filter(
            models=[six_models[0], None, six_models[1], None],
            estimated_input_tokens=100,
            estimated_output_tokens=100,
        )
        assert res_with_none.eligible_count == 2
        assert res_with_none.total_evaluated == 2
        assert [m.model_id for m in res_with_none.eligible_models] == ["gemini-tier_1", "groq-tier_2"]

    def test_sub_millisecond_execution_performance(
        self, clean_filter: EligibilityFilter, six_models: List[ModelSpec]
    ):
        """Verifies sub-millisecond execution (< 0.1 ms average across 1,000 runs)."""
        for _ in range(50):
            clean_filter.filter(six_models, 250, 500)

        iterations = 1000
        t0 = time.perf_counter()
        for _ in range(iterations):
            clean_filter.filter(six_models, 250, 500)
        t1 = time.perf_counter()

        avg_latency_ms = ((t1 - t0) / iterations) * 1000.0
        assert avg_latency_ms < 0.1, (
            f"Average eligibility filtering took {avg_latency_ms:.4f} ms, exceeding 0.1 ms SLA"
        )
