"""Model Registry: declarative metadata for every available LLM.

Adding/removing models never touches the routing engine. Models whose
API credentials are missing are listed but marked unavailable and are
excluded from routing. Built-in "demo" models (clearly labelled) keep
the prototype functional without any API key.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from .config import settings


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    name: str
    provider: str            # "mock" or "openai" (adapter key)
    endpoint_model: str      # model name sent to the provider API
    api_key: str             # empty for mock models
    base_url: str            # provider API base
    input_price_per_mtok: float   # USD per 1M input tokens
    output_price_per_mtok: float  # USD per 1M output tokens
    expected_latency_ms: float
    quality: float           # 0..1 overall capability
    reasoning: float         # 0..1
    coding: float            # 0..1
    context_window: int
    demo_mode: bool = False

    @property
    def available(self) -> bool:
        if self.provider == "mock":
            return True
        return bool(self.api_key)

    @property
    def price_per_1k(self) -> float:
        """Blended price per 1K tokens (assumes ~3:1 input:output mix)."""
        return (3 * self.input_price_per_mtok + self.output_price_per_mtok) / 4 / 1000


def _openai_models() -> List[ModelSpec]:
    if not settings.has_openai:
        return []
    key = settings.openai_api_key
    base = settings.openai_base_url
    return [
        ModelSpec(
            model_id="openai-fast",
            name=f"{settings.openai_fast_model} (fast tier)",
            provider="openai",
            endpoint_model=settings.openai_fast_model,
            api_key=key,
            base_url=base,
            input_price_per_mtok=0.15,
            output_price_per_mtok=0.60,
            expected_latency_ms=450,
            quality=0.72,
            reasoning=0.60,
            coding=0.65,
            context_window=128_000,
        ),
        ModelSpec(
            model_id="openai-powerful",
            name=f"{settings.openai_powerful_model} (power tier)",
            provider="openai",
            endpoint_model=settings.openai_powerful_model,
            api_key=key,
            base_url=base,
            input_price_per_mtok=2.50,
            output_price_per_mtok=10.00,
            expected_latency_ms=1100,
            quality=0.95,
            reasoning=0.90,
            coding=0.90,
            context_window=128_000,
        ),
    ]


def _mock_models() -> List[ModelSpec]:
    return [
        ModelSpec(
            model_id="demo-fast",
            name="Demo Fast (cheap, quick)",
            provider="mock",
            endpoint_model="demo-fast",
            api_key="",
            base_url="",
            input_price_per_mtok=0.15,
            output_price_per_mtok=0.60,
            expected_latency_ms=250,
            quality=0.45,
            reasoning=0.30,
            coding=0.40,
            context_window=16_000,
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-balanced",
            name="Demo Balanced (mid tier)",
            provider="mock",
            endpoint_model="demo-balanced",
            api_key="",
            base_url="",
            input_price_per_mtok=1.00,
            output_price_per_mtok=3.00,
            expected_latency_ms=700,
            quality=0.70,
            reasoning=0.60,
            coding=0.65,
            context_window=128_000,
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-powerful",
            name="Demo Powerful (high tier)",
            provider="mock",
            endpoint_model="demo-powerful",
            api_key="",
            base_url="",
            input_price_per_mtok=5.00,
            output_price_per_mtok=15.00,
            expected_latency_ms=1800,
            quality=0.92,
            reasoning=0.90,
            coding=0.88,
            context_window=200_000,
            demo_mode=True,
        ),
    ]


class ModelRegistry:
    """Holds all ModelSpecs and answers routing queries."""

    def __init__(self, specs: List[ModelSpec]):
        self._specs: Dict[str, ModelSpec] = {s.model_id: s for s in specs}

    @classmethod
    def from_settings(cls) -> "ModelRegistry":
        specs: List[ModelSpec] = []
        if settings.mock_models_enabled:
            specs.extend(_mock_models())
        specs.extend(_openai_models())
        return cls(specs)

    def all(self) -> List[ModelSpec]:
        return list(self._specs.values())

    def available(self) -> List[ModelSpec]:
        return [s for s in self._specs.values() if s.available]

    def get(self, model_id: str) -> ModelSpec | None:
        return self._specs.get(model_id)

    def strongest(self) -> ModelSpec | None:
        """Highest-quality available model, used to compute the
        'no-routing' cost baseline."""
        avail = self.available()
        if not avail:
            return None
        return max(avail, key=lambda s: s.quality)

    def to_public_list(self) -> List[dict]:
        return [
            {
                "model_id": s.model_id,
                "name": s.name,
                "provider": s.provider,
                "available": s.available,
                "demo_mode": s.demo_mode,
                "quality": s.quality,
                "reasoning": s.reasoning,
                "coding": s.coding,
                "context_window": s.context_window,
                "input_price_per_mtok": s.input_price_per_mtok,
                "output_price_per_mtok": s.output_price_per_mtok,
                "expected_latency_ms": s.expected_latency_ms,
            }
            for s in self.all()
        ]


registry = ModelRegistry.from_settings()