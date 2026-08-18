"""Smart Routing Engine: Multi-factor scoring, model resolution, and fallback ordering.

Scores candidate models along:
- Quality suitability
- Complexity compatibility
- Reasoning requirement
- Coding requirement
- Cost efficiency
- Latency efficiency
- Historical reliability and provider/tier affinity
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from .analyzer_llm import AnalyzerDecision
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
        "quality_suitability": 0.6,
        "complexity_compatibility": 0.8,
        "reasoning_compatibility": 0.7,
        "coding_compatibility": 0.8,
        "cost_efficiency": 3.0,
        "latency_efficiency": 1.5,
    },
    "fastest": {
        "quality_suitability": 0.7,
        "complexity_compatibility": 0.9,
        "reasoning_compatibility": 0.8,
        "coding_compatibility": 0.8,
        "cost_efficiency": 1.0,
        "latency_efficiency": 3.0,
    },
    "highest_quality": {
        "quality_suitability": 2.5,
        "complexity_compatibility": 1.2,
        "reasoning_compatibility": 2.0,
        "coding_compatibility": 2.0,
        "cost_efficiency": 0.3,
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

    def candidates(self) -> List[dict]:
        """Returns candidate list formatted as raw dictionary rows."""
        rows = []
        for s in sorted(self.scores.values(), key=lambda s: -s.total):
            expected_cost = s.model.price_per_1k * 1.5  # ~1.5K tokens
            rows.append({
                "model_id": s.model.model_id,
                "name": s.model.name,
                "provider": s.model.provider,
                "tier": s.model.tier,
                "total": round(s.total, 3),
                "expected_cost_usd": round(expected_cost, 6),
                "expected_latency_ms": s.model.expected_latency_ms,
                "selected": s.model.model_id == self.primary_model.model_id,
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
    """Multi-factor scoring and model resolution engine."""

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

    def resolve(
        self,
        decision: AnalyzerDecision,
        strategy: str = "balanced",
        registry: Optional[ModelRegistry] = None,
        available: Optional[List[ModelSpec]] = None,
    ) -> RoutingResult:
        """Evaluates all candidate execution models against analyzer decision and strategy."""
        reg = registry or default_registry
        if available is not None:
            candidate_pool = [m for m in available if m.tier != "analyzer" and m.available]
        else:
            candidate_pool = [m for m in reg.available() if m.tier != "analyzer"]

        if not candidate_pool:
            raise RuntimeError("No execution models available in registry for routing.")

        weights = self.effective_weights(strategy)
        min_price = min(m.price_per_1k for m in candidate_pool)
        min_latency = min(m.expected_latency_ms for m in candidate_pool)

        scores: Dict[str, ModelScore] = {}
        for m in candidate_pool:
            # 1. Quality suitability
            q_fit = 1.0 - abs(m.quality - decision.complexity_score)
            if m.quality < decision.complexity_score:
                q_fit *= 0.6  # penalize underpowered models

            # 2. Complexity compatibility
            c_fit = 1.0 if m.quality >= decision.complexity_score else (m.quality / max(0.01, decision.complexity_score))

            # 3. Reasoning compatibility
            r_fit = m.reasoning if decision.reasoning_required else (1.0 - 0.2 * m.reasoning)

            # 4. Coding compatibility
            cd_fit = m.coding if decision.coding_required else (1.0 - 0.1 * m.coding)

            # 5. Cost efficiency
            cost_fit = (min_price / m.price_per_1k) if m.price_per_1k > 0 else 1.0

            # 6. Latency efficiency
            lat_fit = (min_latency / m.expected_latency_ms) if m.expected_latency_ms > 0 else 1.0

            # Bonus for matching target provider and tier
            provider_bonus = 0.20 if m.provider.lower() == decision.target_provider.lower() else 0.0
            tier_bonus = 0.25 if decision.target_tier.lower() in m.tier.lower() else 0.0

            total = (
                weights["quality_suitability"] * q_fit
                + weights["complexity_compatibility"] * c_fit
                + weights["reasoning_compatibility"] * r_fit
                + weights["coding_compatibility"] * cd_fit
                + weights["cost_efficiency"] * cost_fit
                + weights["latency_efficiency"] * lat_fit
                + provider_bonus
                + tier_bonus
            )

            scores[m.model_id] = ModelScore(
                model=m,
                quality_suitability=round(q_fit, 3),
                complexity_compatibility=round(c_fit, 3),
                reasoning_compatibility=round(r_fit, 3),
                coding_compatibility=round(cd_fit, 3),
                cost_efficiency=round(cost_fit, 3),
                latency_efficiency=round(lat_fit, 3),
                total=round(total, 3),
            )

        # Primary selection:
        # Priority 1: Match target provider + tier
        target_model = None
        for m in candidate_pool:
            if m.provider.lower() == decision.target_provider.lower() and decision.target_tier.lower() in m.tier.lower():
                target_model = m
                break

        # Priority 2: Match target tier on any provider
        if not target_model:
            for m in candidate_pool:
                if decision.target_tier.lower() in m.tier.lower():
                    target_model = m
                    break

        # Priority 3: Highest total score candidate
        if not target_model:
            target_model = max(scores.values(), key=lambda s: s.total).model

        # Build fallback chain: primary model first, then remaining sorted by total score
        fallback_chain = [target_model]
        for s in sorted(scores.values(), key=lambda s: -s.total):
            if s.model.model_id != target_model.model_id:
                fallback_chain.append(s.model)

        return RoutingResult(
            primary_model=target_model,
            fallback_chain=fallback_chain,
            scores=scores,
            reason=decision.reason,
            strategy=strategy,
        )


# Module-level default singleton
router = SmartRouter()


def route_decision(
    decision: AnalyzerDecision,
    strategy: str = "balanced",
    registry: Optional[ModelRegistry] = None,
    available: Optional[List[ModelSpec]] = None,
) -> RoutingResult:
    """Convenience helper to route a decision using default router."""
    return router.resolve(decision, strategy=strategy, registry=registry, available=available)