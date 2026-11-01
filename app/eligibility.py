"""MCDA Hard-Constraint Eligibility Filter for the LinUCB Router.

Strictly evaluates 4 hard constraints ONLY:
  1. Provider Health & Circuit Breaker: Is the model's circuit breaker tripped/OPEN or cooling down?
  2. Context Window Limit: Does (estimated_input_tokens + estimated_output_tokens) > model.context_window?
  3. Request Cost Budget Cap: Does estimated request cost exceed max_budget_usd / max_cost_per_request?
  4. Daily/Monthly Spend Cap: Has daily or monthly budget been exhausted?

ZERO SCORING, ZERO RANKING, NO HEURISTIC WEIGHTS!
Binary hard-constraint filtering with sub-millisecond execution (< 0.1 ms).
"""

from dataclasses import dataclass
import math
import sys
import time
from typing import Any, Dict, List, Optional

from .circuit import ProviderCircuit, circuits as default_circuits
from .config import Settings, settings as default_settings
from .registry import ModelSpec
from .tracker import Tracker, tracker as default_tracker


@dataclass
class EligibleSet:
    """Immutable result of hard-constraint filtering."""
    eligible_models: List[ModelSpec]
    ineligible_models: Dict[str, str]  # model_id -> human-readable rejection reason
    total_evaluated: int
    eligible_count: int


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely extract finite non-negative float, handling NaN/Inf/strings gracefully."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f) or f < 0.0:
            return default
        return f
    except (ValueError, TypeError, OverflowError):
        return default


def _sanitize_token_count(val: Any) -> int:
    """Sanitize token inputs, defensively handling non-finite floats, strings, and negatives."""
    if val is None:
        return 0
    try:
        if isinstance(val, (int, float)):
            if math.isnan(val):
                return 0
            if math.isinf(val):
                return sys.maxsize if val > 0 else 0
            return max(0, int(val))
        num = float(val)
        if math.isnan(num):
            return 0
        if math.isinf(num):
            return sys.maxsize if num > 0 else 0
        return max(0, int(num))
    except (ValueError, TypeError, OverflowError):
        return 0


def _is_circuit_open(circuit_reg: Any, model_id: str) -> bool:
    """Check if circuit breaker is open or in cooldown for the given model_id.

    Fails open (returns False) on unexpected exceptions to ensure circuit telemetry
    failures never crash request routing.
    """
    if circuit_reg is None:
        return False
    try:
        # ProviderCircuit instance or duck-typed object with allow()
        if hasattr(circuit_reg, "allow"):
            return not bool(circuit_reg.allow(model_id))
        # Object with is_open()
        if hasattr(circuit_reg, "is_open"):
            return bool(circuit_reg.is_open(model_id))
        # Object with is_tripped()
        if hasattr(circuit_reg, "is_tripped"):
            return bool(circuit_reg.is_tripped(model_id))
        # Object with is_available()
        if hasattr(circuit_reg, "is_available"):
            return not bool(circuit_reg.is_available(model_id))
        # Callable predicate: allow_fn(model_id) -> bool
        if callable(circuit_reg):
            return not bool(circuit_reg(model_id))
        # Collection of open/tripped model IDs
        if isinstance(circuit_reg, (set, frozenset, list, tuple)):
            return model_id in circuit_reg
        return False
    except Exception:
        # Secondary circuit telemetry failure: fail-open to preserve routing availability
        return False


class EligibilityFilter:
    """MCDA Hard-Constraint Eligibility Filter for LinUCB Router candidate selection."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        circuit_registry: Any = None,
        tracker: Any = None,
        budget_cache_ttl_s: float = 1.0,
    ) -> None:
        self.settings = settings or default_settings
        self.circuit_registry = circuit_registry if circuit_registry is not None else default_circuits
        self.tracker = tracker if tracker is not None else default_tracker
        self.budget_cache_ttl_s = budget_cache_ttl_s
        self._cached_spend_status: Optional[Dict[str, Any]] = None
        self._cached_spend_time: float = 0.0

    def invalidate_budget_cache(self) -> None:
        """Invalidate spend cap cache."""
        self._cached_spend_status = None
        self._cached_spend_time = 0.0

    def _get_spend_cap_status(self, tracker: Any = None) -> Optional[Dict[str, Any]]:
        """Retrieve current spend status, caching default tracker calls for sub-millisecond latency."""
        active_tracker = tracker if tracker is not None else self.tracker
        if active_tracker is None:
            return None

        # Custom tracker instance (e.g. In unit tests or request overrides) is evaluated fresh
        if tracker is not None:
            try:
                if hasattr(active_tracker, "budget_status"):
                    return active_tracker.budget_status()
            except Exception:
                pass
            return None

        now = time.monotonic()
        current_daily = getattr(self.settings, "daily_budget_usd", 0.0)
        if (
            self._cached_spend_status is not None
            and (now - self._cached_spend_time) < self.budget_cache_ttl_s
            and self._cached_spend_status.get("daily_budget_usd") == current_daily
        ):
            return self._cached_spend_status

        try:
            if hasattr(active_tracker, "budget_status"):
                status = active_tracker.budget_status()
                self._cached_spend_status = status
                self._cached_spend_time = now
                return status
        except Exception:
            pass
        return None

    def _check_spend_caps(self, status: Optional[Dict[str, Any]]) -> Optional[str]:
        """Check if daily or monthly spend caps are exhausted."""
        if not status or not isinstance(status, dict):
            return None

        day_spend = _safe_float(status.get("day_spend", 0.0))
        month_spend = _safe_float(status.get("month_spend", 0.0))
        daily_budget = _safe_float(status.get("daily_budget_usd", 0.0))
        monthly_budget = _safe_float(status.get("monthly_budget_usd", 0.0))

        if daily_budget > 0 and day_spend >= daily_budget:
            return f"Daily spend cap exhausted: spent ${day_spend:.2f} >= budget ${daily_budget:.2f}"
        if monthly_budget > 0 and month_spend >= monthly_budget:
            return f"Monthly spend cap exhausted: spent ${month_spend:.2f} >= budget ${monthly_budget:.2f}"

        return None

    def filter(
        self,
        models: Optional[List[ModelSpec]],
        estimated_input_tokens: Any,
        estimated_output_tokens: Any = 500,
        max_budget_usd: Optional[float] = None,
        circuit_registry: Any = None,
        tracker: Any = None,
    ) -> EligibleSet:
        """Filter candidate models through 4 hard constraints strictly.

        Args:
            models: Candidate model specifications to evaluate.
            estimated_input_tokens: Estimated or actual input token count.
            estimated_output_tokens: Estimated output token count (defaults to 500).
            max_budget_usd: Optional max USD budget cap per request. If >= 0.0, overrides settings.
            circuit_registry: Optional circuit breaker registry override.
            tracker: Optional performance tracker override for spend caps.

        Returns:
            EligibleSet containing eligible models, ineligible models map with reasons,
            total evaluated count, and eligible count.
        """
        if models is None:
            return EligibleSet(
                eligible_models=[],
                ineligible_models={},
                total_evaluated=0,
                eligible_count=0,
            )

        # Defensively sanitize token counts against NaN, Inf, strings, and negatives
        in_tok = _sanitize_token_count(estimated_input_tokens)
        out_tok = _sanitize_token_count(estimated_output_tokens)
        total_tokens = in_tok + out_tok

        # Effective request cost cap: distinguish explicit limit (>= 0.0) from unset (None)
        effective_cost_cap: Optional[float] = None
        if max_budget_usd is not None and max_budget_usd >= 0.0:
            effective_cost_cap = float(max_budget_usd)
        elif (
            getattr(self.settings, "max_cost_per_request", None) is not None
            and self.settings.max_cost_per_request > 0.0
        ):
            effective_cost_cap = float(self.settings.max_cost_per_request)

        # Circuit breaker registry to use
        circuit_reg = circuit_registry if circuit_registry is not None else self.circuit_registry

        # Constraint 4: Daily / Monthly spend cap status check
        spend_status = self._get_spend_cap_status(tracker=tracker)
        spend_exhausted_reason = self._check_spend_caps(spend_status)

        eligible_models: List[ModelSpec] = []
        ineligible_models: Dict[str, str] = {}
        total_evaluated = 0

        for model in models:
            if model is None:
                continue

            total_evaluated += 1
            model_id = getattr(model, "model_id", str(model))

            # 1. Provider Health & Circuit Breaker
            if _is_circuit_open(circuit_reg, model_id):
                ineligible_models[model_id] = (
                    f"Circuit breaker tripped / cooling down for model '{model_id}'"
                )
                continue

            # 2. Context Window Limit (Validate context_window > 0 and within capacity)
            raw_context_window = getattr(model, "context_window", None)
            try:
                context_window = int(raw_context_window) if raw_context_window is not None else 0
            except (ValueError, TypeError, OverflowError):
                context_window = 0

            if context_window <= 0:
                ineligible_models[model_id] = (
                    f"Invalid context window ({raw_context_window}) for model '{model_id}'"
                )
                continue

            if total_tokens > context_window:
                ineligible_models[model_id] = (
                    f"Context window exceeded: requested {total_tokens} tokens "
                    f"(in={in_tok}, out={out_tok}) > context window {context_window}"
                )
                continue

            # 3. Request Cost Budget Cap
            in_price = getattr(model, "input_price_per_mtok", 0.0) or 0.0
            out_price = getattr(model, "output_price_per_mtok", 0.0) or 0.0
            estimated_cost = (in_tok * in_price + out_tok * out_price) / 1_000_000.0

            if effective_cost_cap is not None and estimated_cost > effective_cost_cap:
                ineligible_models[model_id] = (
                    f"Estimated request cost ${estimated_cost:.6f} "
                    f"exceeds budget cap ${effective_cost_cap:.6f}"
                )
                continue

            # 4. Daily / Monthly Spend Cap
            if spend_exhausted_reason is not None:
                ineligible_models[model_id] = spend_exhausted_reason
                continue

            # Model passed all 4 hard constraints
            eligible_models.append(model)

        return EligibleSet(
            eligible_models=eligible_models,
            ineligible_models=ineligible_models,
            total_evaluated=total_evaluated,
            eligible_count=len(eligible_models),
        )


# Global singleton instance
eligibility_filter = EligibilityFilter()
