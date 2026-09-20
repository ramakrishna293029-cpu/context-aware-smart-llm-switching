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
        # Stated token assumption for candidate cost previews: 1K in / 0.5K out.
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
        latency_profile: Optional[Dict[str, float]] = None,
        feedback_modifiers: Optional[Dict[str, float]] = None,
    ) -> RoutingResult:
        """Evaluates all candidate execution models against analyzer decision and strategy.

        `latency_profile` maps endpoint_model -> EWMA of measured latency (ms).
        `feedback_modifiers` maps model_id -> user approval multiplier (0.85-1.15)."""
        reg = registry or default_registry
        if available is not None:
            candidate_pool = [m for m in available if m.tier != "analyzer" and m.available]
        else:
            candidate_pool = [m for m in reg.available() if m.tier != "analyzer"]

        if not candidate_pool:
            raise RuntimeError("No execution models available in registry for routing.")

        candidate_pool = self._apply_strategy_pool(candidate_pool, decision, strategy)
        if not candidate_pool:
            raise RuntimeError("No execution models left after strategy filter.")

        weights = self.effective_weights(strategy)
        profile = latency_profile or {}

        def effective_latency(m: ModelSpec) -> float:
            measured = profile.get(m.endpoint_model)
            return measured if (measured and measured > 0) else m.expected_latency_ms

        min_price = min(m.price_per_1k for m in candidate_pool)
        min_latency = min(effective_latency(m) for m in candidate_pool)

        scores: Dict[str, ModelScore] = {}
        for m in candidate_pool:
            # 1. Quality suitability
            q_fit = 1.0 - abs(m.quality - decision.complexity_score)
            if m.quality < decision.complexity_score:
                q_fit *= 0.5  # penalize underpowered models for complex queries

            # 2. Complexity compatibility
            if m.quality >= decision.complexity_score:
                c_fit = 1.0
            else:
                c_fit = (m.quality / max(0.01, decision.complexity_score)) * 0.8

            # 3. Reasoning compatibility
            r_fit = m.reasoning if decision.reasoning_required else (1.0 - 0.2 * m.reasoning)

            # 4. Coding compatibility
            cd_fit = m.coding if decision.coding_required else (1.0 - 0.1 * m.coding)

            # 5. Cost efficiency
            cost_fit = (min_price / m.price_per_1k) if m.price_per_1k > 0 else 1.0

            # 6. Latency efficiency (measured EWMA when available, static prior otherwise)
            eff_lat = effective_latency(m)
            lat_fit = (min_latency / eff_lat) if eff_lat > 0 else 1.0

            # Small affinity only — capability + strategy scores pick the primary.
            wanted_provider = (decision.target_provider or "").lower()
            provider_bonus = 0.05 if wanted_provider and m.provider.lower() == wanted_provider else 0.0
            tier_bonus = 0.12 if decision.target_tier.lower() in m.tier.lower() else 0.0

            # Dynamic feedback modifier (user rating reward/penalty)
            fb_mod = (feedback_modifiers or {}).get(m.endpoint_model) or (feedback_modifiers or {}).get(m.model_id) or 1.0
            feedback_bonus = round((fb_mod - 1.0) * 0.3, 3)

            total = (
                weights["quality_suitability"] * q_fit
                + weights["complexity_compatibility"] * c_fit
                + weights["reasoning_compatibility"] * r_fit
                + weights["coding_compatibility"] * cd_fit
                + weights["cost_efficiency"] * cost_fit
                + weights["latency_efficiency"] * lat_fit
                + provider_bonus
                + tier_bonus
                + feedback_bonus
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

        # Primary = highest score among the strategy-filtered, capability-aware pool.
        target_model = max(scores.values(), key=lambda s: s.total).model

        # Fallback: same capability / next provider first, then remaining scores. Cap length.
        same_cap: List[ModelSpec] = []
        rest: List[ModelSpec] = []
        for s in sorted(scores.values(), key=lambda s: -s.total):
            if s.model.model_id == target_model.model_id:
                continue
            if self._same_capability(s.model, decision):
                same_cap.append(s.model)
            else:
                rest.append(s.model)
        fallback_chain = [target_model] + same_cap + rest
        fallback_chain = fallback_chain[:4]

        return RoutingResult(
            primary_model=target_model,
            fallback_chain=fallback_chain,
            scores=scores,
            reason=decision.reason,
            strategy=strategy,
        )

    @staticmethod
    def _same_capability(model: ModelSpec, decision: AnalyzerDecision) -> bool:
        if decision.coding_required:
            return model.coding >= 0.55 or "coding" in model.tier.lower()
        if decision.reasoning_required:
            return model.reasoning >= 0.55 or any(
                t in model.tier.lower() for t in ("reasoning", "powerful")
            )
        return "fast" in model.tier.lower() or model.tier.lower() in ("custom", "balanced")

    @staticmethod
    def _apply_strategy_pool(
        pool: List[ModelSpec],
        decision: AnalyzerDecision,
        strategy: str,
    ) -> List[ModelSpec]:
        """Strategy must change the candidate *set*, not only score weights."""
        key = (strategy or "balanced").lower()
        if key == "lowest_cost":
            if decision.reasoning_required and decision.complexity_score >= 0.85:
                return pool
            filtered = [m for m in pool if m.tier not in ("powerful",)]
            if decision.coding_required:
                codingish = [
                    m for m in filtered
                    if m.tier in ("coding", "fast", "fast-backup", "custom") or m.coding >= 0.6
                ]
                filtered = codingish or filtered
            return filtered or pool
        if key == "fastest":
            if decision.reasoning_required:
                return pool
            filtered = [m for m in pool if m.tier not in ("reasoning", "powerful")]
            return filtered or pool
        if key == "highest_quality":
            strong = [
                m for m in pool
                if m.quality >= 0.7 or m.tier in ("reasoning", "powerful", "coding")
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
) -> RoutingResult:
    """Convenience helper to route a decision using default router."""
    return router.resolve(
        decision,
        strategy=strategy,
        registry=registry,
        available=available,
        latency_profile=latency_profile,
        feedback_modifiers=feedback_modifiers,
    )