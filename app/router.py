"""Smart Routing Engine: Multi-factor capability scoring, Bayesian updates,
hard eligibility constraints, statistical deadline handling, and resilient fallback ordering.

Routes requests across the 6 Response Model Tiers:
  - Tier 1: Gemini 3.5 Flash-Lite (Lightweight / Fast)
  - Tier 2: Groq GPT-OSS 20B (Fast General Purpose)
  - Tier 3: Gemini 3.6 Flash (Balanced)
  - Tier 4: Groq Qwen3.8 27B (Coding Specialist)
  - Tier 5: Groq GPT-OSS 120B (Advanced Reasoning)
  - Tier 6: Gemini 3.8 Flash (High-Capability Gemini)
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .analyzer_llm import AnalyzerDecision
from .bayesian import ModelHealthTracker, global_health_tracker
from .config import settings
from .registry import ModelRegistry, ModelSpec, registry as default_registry
from .schemas import CandidateInfo


STRATEGIES: Dict[str, Dict[str, float]] = {
    "balanced": {
        "quality_suitability": 1.0,
        "complexity_compatibility": 1.0,
        "reasoning_compatibility": 1.0,
        "coding_compatibility": 1.0,
        "cost_efficiency": 1.0,
        "latency_efficiency": 1.0,
    },
    "lowest_cost": {
        "quality_suitability": 0.5,
        "complexity_compatibility": 0.7,
        "reasoning_compatibility": 0.6,
        "coding_compatibility": 0.8,
        "cost_efficiency": 3.0,
        "latency_efficiency": 1.5,
    },
    "fastest": {
        "quality_suitability": 0.6,
        "complexity_compatibility": 0.8,
        "reasoning_compatibility": 0.7,
        "coding_compatibility": 0.8,
        "cost_efficiency": 1.0,
        "latency_efficiency": 3.0,
    },
    "highest_quality": {
        "quality_suitability": 2.5,
        "complexity_compatibility": 1.5,
        "reasoning_compatibility": 2.0,
        "coding_compatibility": 2.0,
        "cost_efficiency": 0.2,
        "latency_efficiency": 0.5,
    },
}


@dataclass
class ModelScore:
    model: ModelSpec
    quality_suitability: float
    complexity_compatibility: float
    reasoning_compatibility: float
    coding_compatibility: float
    cost_efficiency: float
    latency_efficiency: float
    total: float
    deadline_probability: float = 1.0
    bayesian_quality: float = 0.8
    bayesian_failure_rate: float = 0.05
    eligible: bool = True
    ineligibility_reason: Optional[str] = None

    def factors(self) -> Dict[str, float]:
        return {
            "quality_suitability": self.quality_suitability,
            "complexity_compatibility": self.complexity_compatibility,
            "reasoning_compatibility": self.reasoning_compatibility,
            "coding_compatibility": self.coding_compatibility,
            "cost_efficiency": self.cost_efficiency,
            "latency_efficiency": self.latency_efficiency,
            "total": self.total,
        }


@dataclass
class RoutingResult:
    primary_model: ModelSpec
    fallback_chain: List[ModelSpec]
    scores: Dict[str, ModelScore]
    reason: str
    strategy: str
    switched_by_hysteresis: bool = False
    retained_by_hysteresis: bool = False
    eligible_count: int = 0

    def candidates(self) -> List[dict]:
        """Returns candidate list formatted as raw dictionary rows for API/UI."""
        rows = []
        PREVIEW_IN_TOKENS, PREVIEW_OUT_TOKENS = 1000, 500
        for s in sorted(self.scores.values(), key=lambda s: -s.total):
            expected_cost = (
                PREVIEW_IN_TOKENS * s.model.input_price_per_mtok
                + PREVIEW_OUT_TOKENS * s.model.output_price_per_mtok
            ) / 1_000_000
            rows.append({
                "model_id": s.model.model_id,
                "name": s.model.name,
                "provider": s.model.provider,
                "tier": s.model.tier,
                "total": round(s.total, 3),
                "expected_cost_usd": round(expected_cost, 6),
                "expected_latency_ms": round(s.model.expected_latency_ms, 1),
                "selected": s.model.model_id == self.primary_model.model_id,
                "eligible": s.eligible,
                "deadline_probability": round(s.deadline_probability, 3),
                "factors": s.factors(),
            })
        return rows

    def to_candidate_infos(self) -> List[CandidateInfo]:
        """Returns candidate list formatted as Pydantic CandidateInfo objects."""
        return [
            CandidateInfo(
                model_id=row["model_id"],
                name=row["name"],
                provider=row["provider"],
                tier=row["tier"],
                total=row["total"],
                expected_cost_usd=row["expected_cost_usd"],
                expected_latency_ms=row["expected_latency_ms"],
                selected=row["selected"],
                factors=row["factors"],
            )
            for row in self.candidates()
        ]


class SmartRouter:
    """Context-aware multi-factor routing engine with Bayesian estimation and constraint verification."""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        w = weights or getattr(settings, "routing_weights", {})
        self.base_weights = {
            "quality_suitability": w.get("quality_suitability", 0.30),
            "complexity_compatibility": w.get("complexity_compatibility", 0.15),
            "reasoning_compatibility": w.get("reasoning_compatibility", 0.15),
            "coding_compatibility": w.get("task_compatibility", 0.15),
            "cost_efficiency": w.get("cost_efficiency", 0.15),
            "latency_efficiency": w.get("latency_efficiency", 0.10),
        }

    def effective_weights(self, strategy: str) -> Dict[str, float]:
        strat_key = strategy.lower().strip() if strategy else "balanced"
        strat_profile = STRATEGIES.get(strat_key, STRATEGIES["balanced"])
        scaled = {k: self.base_weights.get(k, 0.1) * strat_profile.get(k, 1.0) for k in self.base_weights}
        total = sum(scaled.values()) or 1.0
        return {k: v / total for k, v in scaled.items()}

    def _check_hard_eligibility(
        self,
        model: ModelSpec,
        decision: AnalyzerDecision,
        total_tokens: int,
        deadline_ms: Optional[float],
        max_budget_usd: Optional[float],
        health: ModelHealthTracker,
    ) -> Tuple[bool, Optional[str]]:
        """Applies hard constraints. A model failing ANY constraint is disqualified."""
        # 1. Availability check
        if not model.available:
            return False, "Model is not configured or missing API credentials."

        # 2. Context window constraint
        if total_tokens > model.context_window:
            return False, f"Required tokens ({total_tokens}) exceed model context window ({model.context_window})."

        # 3. Budget constraint (per-query cap)
        if max_budget_usd is not None and max_budget_usd > 0:
            est_cost = (
                total_tokens * 0.6 * model.input_price_per_mtok
                + total_tokens * 0.4 * model.output_price_per_mtok
            ) / 1_000_000
            if est_cost > max_budget_usd:
                return False, f"Estimated query cost (${est_cost:.6f}) exceeds budget cap (${max_budget_usd:.6f})."

        # 4. Model health & rate limit / quota block
        if health.is_in_cooldown(model.model_id) or health.is_in_cooldown(model.endpoint_model):
            return False, "Model is currently in temporary error cooldown / quota backoff."

        if health.failure_rate(model.model_id) > 0.45:
            return False, f"Model Bayesian failure rate ({health.failure_rate(model.model_id):.1%}) exceeds safety threshold."

        # 5. Statistical Deadline Constraint (Requirement 4)
        if deadline_ms is not None and deadline_ms > 0:
            prob = health.deadline_probability(model.model_id, deadline_ms)
            # Require at least 40% probability of deadline compliance under Log-Normal model
            if prob < 0.40:
                return False, f"Probability of meeting deadline {deadline_ms}ms is only {prob:.1%} (below 40% threshold)."

        # 6. Task capability floor for high complexity
        if decision.complexity == "high":
            if decision.coding_required and model.coding < 0.84:
                return False, f"Model coding capability ({model.coding:.2f}) is insufficient for high-complexity coding."
            if decision.reasoning_required and model.reasoning < 0.85:
                return False, f"Model reasoning capability ({model.reasoning:.2f}) is insufficient for high-complexity reasoning."

        return True, None

    def resolve(
        self,
        decision: AnalyzerDecision,
        strategy: str = "balanced",
        registry: Optional[ModelRegistry] = None,
        available: Optional[List[ModelSpec]] = None,
        latency_profile: Optional[Dict[str, float]] = None,
        feedback_modifiers: Optional[Dict[str, float]] = None,
        estimated_input_tokens: int = 1000,
        estimated_output_tokens: int = 500,
        deadline_ms: Optional[float] = None,
        max_budget_usd: Optional[float] = None,
        session_last_model_id: Optional[str] = None,
        health_tracker: Optional[ModelHealthTracker] = None,
        hysteresis_margin: float = 0.08,
    ) -> RoutingResult:
        """Context-aware multi-factor resolution enforcing hard eligibility and Bayesian health."""
        reg = registry or default_registry
        health = health_tracker or global_health_tracker
        total_tokens = max(10, estimated_input_tokens + estimated_output_tokens)

        # 1. Gather all candidates in registry (excluding analyzer)
        if available is not None:
            raw_pool = [m for m in available if m.tier != "analyzer"]
        else:
            raw_pool = [m for m in reg.all() if m.tier != "analyzer"]

        if not raw_pool:
            raise RuntimeError("No execution models available in registry for routing.")

        # Ensure health tracker has priors initialized
        for m in raw_pool:
            health.ensure_model(m.model_id, m.quality, m.expected_latency_ms)

        # 2. Hard Eligibility Filter (Requirement 3)
        eligible_models: List[ModelSpec] = []
        ineligible_reasons: Dict[str, str] = {}
        for m in raw_pool:
            is_ok, reason_str = self._check_hard_eligibility(
                m, decision, total_tokens, deadline_ms, max_budget_usd, health
            )
            if is_ok:
                eligible_models.append(m)
            else:
                ineligible_reasons[m.model_id] = reason_str or "Ineligible"

        # Safe relaxation fallback if over-constrained (e.g. strict deadline pruned all models)
        if not eligible_models:
            # Fallback to available models regardless of deadline/budget
            eligible_models = [m for m in raw_pool if m.available and not health.is_in_cooldown(m.model_id)]
            if not eligible_models:
                # Emergency fallback: any available model
                eligible_models = [m for m in raw_pool if m.available] or raw_pool

        # 3. Strategy filter on eligible pool
        candidate_pool = self._apply_strategy_pool(eligible_models, decision, strategy)
        if not candidate_pool:
            candidate_pool = eligible_models

        weights = self.effective_weights(strategy)
        profile = latency_profile or {}

        # Effective latency & price reference scales
        def get_model_lat(m: ModelSpec) -> float:
            meas = profile.get(m.endpoint_model)
            if meas and meas > 0:
                return meas
            return health.predictive_latency(m.model_id)

        min_price = min(m.price_per_1k for m in candidate_pool) if candidate_pool else 0.001
        min_lat = min(get_model_lat(m) for m in candidate_pool) if candidate_pool else 200.0

        scores: Dict[str, ModelScore] = {}

        # 4. Compute multi-factor Bayesian scores
        for m in raw_pool:
            is_elig = m in candidate_pool
            inelig_reason = ineligible_reasons.get(m.model_id)

            # Bayesian quality lower credible bound (Requirement 1 & 5)
            q_bayes = health.quality_lcb(m.model_id, z=1.0)
            p_fail = health.failure_rate(m.model_id)
            p_deadline = health.deadline_probability(m.model_id, deadline_ms)

            # 1. Quality suitability
            q_fit = 1.0 - abs(q_bayes - decision.complexity_score)
            if q_bayes < decision.complexity_score:
                q_fit *= 0.5

            # 2. Complexity compatibility
            if q_bayes >= decision.complexity_score:
                c_fit = 1.0
            else:
                c_fit = (q_bayes / max(0.01, decision.complexity_score)) * 0.8

            # 3. Reasoning compatibility
            r_fit = m.reasoning if decision.reasoning_required else (1.0 - 0.2 * m.reasoning)

            # 4. Coding compatibility
            cd_fit = m.coding if decision.coding_required else (1.0 - 0.1 * m.coding)

            # 5. Cost efficiency
            cost_fit = (min_price / m.price_per_1k) if m.price_per_1k > 0 else 1.0

            # 6. Latency efficiency & deadline compliance (Requirement 4)
            eff_lat = get_model_lat(m)
            lat_fit = (min_lat / eff_lat) if eff_lat > 0 else 1.0
            if deadline_ms is not None:
                lat_fit = 0.5 * lat_fit + 0.5 * p_deadline

            # Alignment bonus for exact required capability tier from triage
            wanted_tier = (decision.required_capability or decision.target_tier or "").lower()
            tier_match = (
                m.tier.lower() == wanted_tier
                or (wanted_tier == "tier_1" and "fast" in m.tier.lower())
                or (wanted_tier == "tier_4" and "coding" in m.tier.lower())
                or (wanted_tier == "tier_5" and "reasoning" in m.tier.lower())
                or (wanted_tier == "tier_6" and "powerful" in m.tier.lower())
                or (wanted_tier == "tier_3" and "balanced" in m.tier.lower())
            )
            tier_bonus = 0.35 if tier_match else 0.0

            wanted_provider = (decision.target_provider or "").lower()
            provider_bonus = 0.05 if wanted_provider and m.provider.lower() == wanted_provider else 0.0

            # Feedback bonus
            fb_mod = (feedback_modifiers or {}).get(m.endpoint_model) or (feedback_modifiers or {}).get(m.model_id) or 1.0
            feedback_bonus = round((fb_mod - 1.0) * 0.2, 3)

            # Reliability multiplier from Bayesian failure distribution
            reliability_weight = max(0.1, 1.0 - p_fail)

            total = (
                weights["quality_suitability"] * q_fit
                + weights["complexity_compatibility"] * c_fit
                + weights["reasoning_compatibility"] * r_fit
                + weights["coding_compatibility"] * cd_fit
                + weights["cost_efficiency"] * cost_fit
                + weights["latency_efficiency"] * lat_fit
                + tier_bonus
                + provider_bonus
                + feedback_bonus
            ) * reliability_weight

            # Ineligible models have their score penalized to zero so they cannot be selected
            if not is_elig:
                total = -1.0

            scores[m.model_id] = ModelScore(
                model=m,
                quality_suitability=round(q_fit, 3),
                complexity_compatibility=round(c_fit, 3),
                reasoning_compatibility=round(r_fit, 3),
                coding_compatibility=round(cd_fit, 3),
                cost_efficiency=round(cost_fit, 3),
                latency_efficiency=round(lat_fit, 3),
                total=round(total, 3),
                deadline_probability=round(p_deadline, 3),
                bayesian_quality=round(q_bayes, 3),
                bayesian_failure_rate=round(p_fail, 3),
                eligible=is_elig,
                ineligibility_reason=inelig_reason,
            )

        # 5. Model Selection with Hysteresis (Requirement 3)
        # Find best candidate among ELIGIBLE models only
        eligible_scores = [s for s in scores.values() if s.eligible]
        if not eligible_scores:
            eligible_scores = list(scores.values())

        best_score = max(eligible_scores, key=lambda s: s.total)
        chosen_model = best_score.model
        retained_by_hysteresis = False
        switched_by_hysteresis = False

        # Apply hysteresis only if previous model was specified and IS ELIGIBLE
        if session_last_model_id and session_last_model_id in scores:
            prev_score = scores[session_last_model_id]
            # HARD RULE: Hysteresis must NEVER retain an ineligible model!
            if prev_score.eligible:
                # If current best does not beat previous model by hysteresis margin, retain previous
                if best_score.total < (prev_score.total + hysteresis_margin):
                    chosen_model = prev_score.model
                    retained_by_hysteresis = True
                else:
                    switched_by_hysteresis = True

        # 6. Fallback Chain Ordering
        # Order remaining eligible models by score, then remaining backup models
        remaining_eligible = [
            s.model for s in sorted(eligible_scores, key=lambda s: -s.total)
            if s.model.model_id != chosen_model.model_id
        ]
        fallback_chain = [chosen_model] + remaining_eligible
        fallback_chain = fallback_chain[:6]

        return RoutingResult(
            primary_model=chosen_model,
            fallback_chain=fallback_chain,
            scores=scores,
            reason=decision.reason,
            strategy=strategy,
            switched_by_hysteresis=switched_by_hysteresis,
            retained_by_hysteresis=retained_by_hysteresis,
            eligible_count=len(eligible_scores),
        )

    @staticmethod
    def _apply_strategy_pool(
        pool: List[ModelSpec],
        decision: AnalyzerDecision,
        strategy: str,
    ) -> List[ModelSpec]:
        """Filters candidate pool according to selected optimization strategy."""
        key = (strategy or "balanced").lower()
        if key == "lowest_cost":
            if decision.reasoning_required and decision.complexity_score >= 0.85:
                return pool
            filtered = [m for m in pool if m.tier not in ("tier_6", "powerful")]
            if decision.coding_required:
                codingish = [
                    m for m in filtered
                    if m.tier in ("tier_4", "tier_1", "tier_2", "coding") or m.coding >= 0.6
                ]
                filtered = codingish or filtered
            return filtered or pool
        if key == "fastest":
            if decision.reasoning_required:
                return pool
            filtered = [m for m in pool if m.tier not in ("tier_5", "tier_6", "reasoning", "powerful")]
            return filtered or pool
        if key == "highest_quality":
            strong = [
                m for m in pool
                if m.quality >= 0.8 or m.tier in ("tier_4", "tier_5", "tier_6", "coding", "reasoning", "powerful")
            ]
            return strong or pool
        return pool


# Module-level default singleton
router = SmartRouter()


def route_decision(
    decision: AnalyzerDecision,
    strategy: str = "balanced",
    registry: Optional[ModelRegistry] = None,
    available: Optional[List[ModelSpec]] = None,
    latency_profile: Optional[Dict[str, float]] = None,
    feedback_modifiers: Optional[Dict[str, float]] = None,
    estimated_input_tokens: int = 1000,
    estimated_output_tokens: int = 500,
    deadline_ms: Optional[float] = None,
    max_budget_usd: Optional[float] = None,
    session_last_model_id: Optional[str] = None,
    health_tracker: Optional[ModelHealthTracker] = None,
    hysteresis_margin: float = 0.08,
) -> RoutingResult:
    """Convenience helper to route a decision using default router."""
    return router.resolve(
        decision,
        strategy=strategy,
        registry=registry,
        available=available,
        latency_profile=latency_profile,
        feedback_modifiers=feedback_modifiers,
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        deadline_ms=deadline_ms,
        max_budget_usd=max_budget_usd,
        session_last_model_id=session_last_model_id,
        health_tracker=health_tracker,
        hysteresis_margin=hysteresis_margin,
    )