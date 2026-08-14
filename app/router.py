"""Smart Routing Engine: multi-factor scoring over the model registry.

For every query the router scores each available model on five axes:
quality suitability, complexity compatibility, cost efficiency, latency
efficiency and historical performance. Weights are configurable via
`routing_weights` in Settings.

The decision record keeps the full score breakdown so the UI (and the
user) can see exactly why a model was chosen. No hard-coded
simple/medium/complex rules — the winner emerges from the scoring.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from .analyzer import QueryAnalysis
from .config import settings
from .registry import ModelSpec, registry


@dataclass
class ModelScore:
    model: ModelSpec
    quality_suitability: float
    complexity_compatibility: float
    cost_efficiency: float
    latency_efficiency: float
    historical_performance: float
    total: float


@dataclass
class RoutingDecision:
    model: ModelSpec
    scores: Dict[str, ModelScore]
    reason: str

    @property
    def winner(self) -> ModelScore:
        return self.scores[self.model.model_id]


def _capability_fit(capability: float, required: float) -> float:
    """Fitness of a model's capability for a required level.

    Underpowered models are penalised heavily; overpowered models get a
    mild 'overkill' penalty so the router avoids wasting money.
    """
    if required <= 0:
        return 1.0
    if capability >= required:
        surplus = (capability - required) / required
        return max(0.0, 1.0 - 0.25 * surplus)
    deficit = (required - capability) / required
    return max(0.0, 1.0 - 2.0 * deficit)


def _requirements(analysis: QueryAnalysis) -> Dict[str, float]:
    """Map an analysis to required capability levels in 0..1."""
    task_floor = {
        "coding": {"coding": 0.55},
        "math": {"reasoning": 0.60},
        "reasoning": {"reasoning": 0.60},
        "creative": {"quality": 0.55},
        "factual": {},
        "general": {},
    }.get(analysis.task_type, {})
    required = {
        "quality": analysis.complexity,
        "reasoning": analysis.complexity,
        "coding": analysis.complexity,
    }
    for cap, floor in task_floor.items():
        required[cap] = max(required[cap], floor)
    if analysis.reasoning_required == "high":
        required["reasoning"] = max(required["reasoning"], 0.72)
        required["quality"] = max(required["quality"], 0.68)
    elif analysis.reasoning_required == "medium":
        required["reasoning"] = max(required["reasoning"], 0.45)
    return required


class SmartRouter:
    def __init__(self, weights: Optional[Dict[str, float]] = None):
        w = weights or settings.routing_weights
        total = sum(w.values()) or 1.0
        self.weights = {k: v / total for k, v in w.items()}

    def _history_score(self, model: ModelSpec, task_type: str,
                       history_stats: Dict[str, Dict[str, float]]) -> float:
        """Blend of the model's average feedback for this task type and its
        reliability, toward a neutral 0.5 when there is no data."""
        stats = history_stats.get(task_type, {}).get(model.model_id)
        if not stats:
            return 0.5
        n = stats.get("n", 0)
        avg_rating = stats.get("avg_feedback", 0.0)  # -1..1
        success_rate = stats.get("success_rate", 1.0)
        confidence = min(n / 20.0, 1.0)
        quality_signal = 0.5 + 0.5 * avg_rating  # -1..1 -> 0..1
        return 0.5 + (quality_signal * success_rate - 0.5) * confidence

    def route(self, analysis: QueryAnalysis,
              history_stats: Optional[Dict[str, Dict[str, float]]] = None) -> RoutingDecision:
        history_stats = history_stats or {}
        models = registry.available()
        if not models:
            raise RuntimeError("No models available. Configure an API key or enable mock models.")

        required = _requirements(analysis)

        # Hard eligibility gate: a model that is clearly underpowered for
        # the query must never win on cost/latency alone. Below the gate a
        # model is excluded from contention (still usable as fallback).
        gate = required["quality"] * 0.8 if required["quality"] > 0.35 else 0.0
        contenders = [m for m in models if m.quality >= gate] or models

        cheapest = min(m.price_per_1k for m in contenders)
        fastest = min(m.expected_latency_ms for m in contenders)

        scored: Dict[str, ModelScore] = {}
        for m in contenders:
            quality_fit = _capability_fit(m.quality, required["quality"])
            complexity_fit = 1.0 - min(0.8 * abs(m.quality - analysis.complexity), 0.8)
            if m.quality < analysis.complexity:
                complexity_fit = max(0.0, complexity_fit - 0.5 * (analysis.complexity - m.quality))
            cost_fit = min(1.0, cheapest / m.price_per_1k) if m.price_per_1k > 0 else 1.0
            latency_fit = min(1.0, fastest / m.expected_latency_ms) if m.expected_latency_ms > 0 else 1.0
            history_fit = self._history_score(m, analysis.task_type, history_stats)

            total = (
                self.weights["quality_suitability"] * quality_fit
                + self.weights["complexity_compatibility"] * complexity_fit
                + self.weights["cost_efficiency"] * cost_fit
                + self.weights["latency_efficiency"] * latency_fit
                + self.weights["historical_performance"] * history_fit
            )
            scored[m.model_id] = ModelScore(
                model=m,
                quality_suitability=round(quality_fit, 4),
                complexity_compatibility=round(complexity_fit, 4),
                cost_efficiency=round(cost_fit, 4),
                latency_efficiency=round(latency_fit, 4),
                historical_performance=round(history_fit, 4),
                total=round(total, 4),
            )

        winner_id = max(scored, key=lambda k: (scored[k].total, -scored[k].model.price_per_1k))
        winner = scored[winner_id].model
        reason = self._build_reason(analysis, scored[winner_id], required)
        return RoutingDecision(model=winner, scores=scored, reason=reason)

    def ranking(self, decision: RoutingDecision) -> List[ModelSpec]:
        """Fallback chain: best model first."""
        return [s.model for s in sorted(decision.scores.values(), key=lambda s: -s.total)]

    def _build_reason(self, analysis: QueryAnalysis, winner: ModelScore, required: Dict[str, float]) -> str:
        parts = [f"Query classified as '{analysis.task_type}' with complexity {analysis.complexity:.2f}"]
        if required["reasoning"] >= 0.72:
            parts.append("high reasoning needs")
        elif required["reasoning"] >= 0.45:
            parts.append("moderate reasoning needs")
        else:
            parts.append("low reasoning needs")
        parts.append(
            f"'{winner.model.name}' scored best at {winner.total:.3f} "
            f"(quality {winner.quality_suitability:.2f}, complexity-fit {winner.complexity_compatibility:.2f}, "
            f"cost {winner.cost_efficiency:.2f}, latency {winner.latency_efficiency:.2f}, "
            f"history {winner.historical_performance:.2f})"
        )
        return ". ".join(parts) + "."


def compute_history_stats() -> Dict[str, Dict[str, Dict[str, float]]]:
    """Aggregate stored request/feedback data for the router.

    Shape: {task_type: {model_id: {n, avg_feedback, success_rate}}}
    """
    from .tracker import tracker
    return tracker.history_stats()


router = SmartRouter()