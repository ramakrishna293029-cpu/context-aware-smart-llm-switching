"""Model Registry: declarative metadata for every available LLM.

Providers:
  - OpenRouter: Analyzer LLM (fast/cheap model for routing decisions) + backup tiers
  - Gemini: Fast / low-cost model for simple queries
  - Groq: Coding + Reasoning models for specialized software & deep reasoning

All API keys from server-side .env only.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import settings

# ---------------------------------------------------------------------------
# Known-model metadata: provider:model_id -> (quality, reasoning, coding,
#                               in$/Mtok, out$/Mtok, latency_ms, context_window)
# ---------------------------------------------------------------------------
KNOWN_MODELS: Dict[str, tuple] = {
    # Gemini models (Google AI API)
    "gemini:gemini-2.5-flash-lite":     (0.80, 0.72, 0.75, 0.075, 0.30, 400, 1000000),
    "gemini:gemini-2.5-flash":          (0.86, 0.80, 0.82, 0.150, 0.60, 600, 1000000),
    "gemini:gemini-flash-latest":       (0.86, 0.80, 0.82, 0.150, 0.60, 600, 1000000),
    "gemini:gemini-1.5-flash":          (0.80, 0.72, 0.75, 0.075, 0.30, 700, 1000000),
    "gemini:gemini-2.5-pro":            (0.95, 0.94, 0.92, 1.250, 5.00, 1200, 2000000),

    # Groq models
    "groq:qwen/qwen3.6-27b":            (0.90, 0.86, 0.96, 0.20, 0.60, 350, 32768),
    "groq:openai/gpt-oss-120b":         (0.95, 0.97, 0.92, 0.59, 0.79, 500, 8192),
    "groq:openai/gpt-oss-20b":          (0.82, 0.78, 0.84, 0.10, 0.20, 250, 8192),
    "groq:allam-2-7b":                  (0.75, 0.70, 0.70, 0.10, 0.10, 200, 4096),

    # OpenRouter models
    "openrouter:meta-llama/llama-3.2-3b-instruct":        (0.68, 0.58, 0.60, 0.06, 0.06, 300, 131072),
    "openrouter:google/gemma-2-9b-it":                   (0.76, 0.72, 0.74, 0.08, 0.08, 600, 8192),
    "openrouter:google/gemma-2-27b-it":                  (0.82, 0.78, 0.80, 0.27, 0.27, 800, 8192),
    "openrouter:qwen/qwen-2.5-coder-32b-instruct":       (0.92, 0.88, 0.97, 0.18, 0.18, 800, 32768),
    "openrouter:meta-llama/llama-3.1-70b-instruct":       (0.92, 0.90, 0.88, 0.52, 0.75, 900, 131072),
    "openrouter:deepseek/deepseek-r1":                   (0.98, 0.99, 0.95, 0.55, 2.19, 1400, 64000),
    "openrouter:deepseek/deepseek-r1-distill-llama-70b":  (0.94, 0.96, 0.90, 0.23, 0.69, 900, 16384),
}

# Fallback tier defaults
ANALYZER_DEFAULTS = (0.68, 0.58, 0.60, 0.06, 0.06, 300, 131072)
FAST_DEFAULTS = (0.80, 0.72, 0.75, 0.075, 0.30, 400, 1000000)
BALANCED_DEFAULTS = (0.76, 0.72, 0.74, 0.08, 0.08, 600, 8192)
CODING_DEFAULTS = (0.90, 0.86, 0.96, 0.20, 0.60, 350, 32768)
POWERFUL_DEFAULTS = (0.95, 0.94, 0.92, 1.25, 5.00, 1200, 2000000)
REASONING_DEFAULTS = (0.95, 0.97, 0.92, 0.59, 0.79, 500, 8192)


@dataclass(frozen=True)
class ModelSpec:
    model_id: str                 # Internal ID: "gemini-fast", "groq-coding", "groq-reasoning", etc.
    name: str                     # Display name
    provider: str                 # "gemini" | "groq" | "openrouter"
    endpoint_model: str           # Model name sent to provider API
    api_key: str                  # Provider API key
    base_url: str                 # Provider API base
    input_price_per_mtok: float   # USD per 1M input tokens
    output_price_per_mtok: float  # USD per 1M output tokens
    expected_latency_ms: float
    quality: float                # 0..1 overall capability
    reasoning: float              # 0..1
    coding: float                 # 0..1
    context_window: int
    tier: str                     # "analyzer", "fast", "balanced", "coding", "powerful", "reasoning"
    demo_mode: bool = False

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def price_per_1k(self) -> float:
        """Blended price per 1K tokens (assumes ~3:1 input:output mix)."""
        return (3 * self.input_price_per_mtok + self.output_price_per_mtok) / 4 / 1000

    @property
    def mode(self) -> str:
        return "real" if not self.demo_mode else "demo"


def _model_metadata(provider: str, endpoint_model: str, tier_defaults: tuple) -> tuple:
    key = f"{provider}:{endpoint_model}"
    meta = KNOWN_MODELS.get(key)
    if meta is None:
        meta = tier_defaults
    return meta


def _build_model(
    tier: str,
    model_name: str,
    api_key: str,
    base_url: str,
    tier_defaults: tuple,
    tier_label: str,
    provider: str,
) -> Optional[ModelSpec]:
    """Build a single ModelSpec for a given tier and provider."""
    if not model_name or not api_key:
        return None
    quality, reasoning, coding, in_price, out_price, latency, ctx = _model_metadata(provider, model_name, tier_defaults)
    return ModelSpec(
        model_id=f"{provider}-{tier}",
        name=f"{model_name} ({tier_label})",
        provider=provider,
        endpoint_model=model_name,
        api_key=api_key,
        base_url=base_url,
        input_price_per_mtok=in_price,
        output_price_per_mtok=out_price,
        expected_latency_ms=latency,
        quality=quality,
        reasoning=reasoning,
        coding=coding,
        context_window=ctx,
        tier=tier,
    )


def _build_all_models() -> List[ModelSpec]:
    """Build all models from all configured providers."""
    specs: List[ModelSpec] = []

    # 1. OpenRouter Analyzer
    if settings.has_openrouter:
        analyzer = _build_model(
            "analyzer", settings.openrouter_analyzer_model,
            settings.openrouter_api_key, settings.openrouter_base_url,
            ANALYZER_DEFAULTS, "Analyzer", "openrouter"
        )
        if analyzer:
            specs.append(analyzer)

    # 2. Google Gemini (Fast / Low-Cost Model)
    if settings.has_gemini:
        fast_gemini = _build_model(
            "fast", settings.gemini_fast_model,
            settings.gemini_api_key, settings.gemini_base_url,
            FAST_DEFAULTS, "Fast Tier", "gemini"
        )
        if fast_gemini:
            specs.append(fast_gemini)

    # 3. Groq (Coding & Reasoning Models)
    if settings.has_groq:
        groq_coding = _build_model(
            "coding", settings.groq_coding_model,
            settings.groq_api_key, settings.groq_base_url,
            CODING_DEFAULTS, "Coding Tier", "groq"
        )
        if groq_coding:
            specs.append(groq_coding)

        groq_reasoning = _build_model(
            "reasoning", settings.groq_reasoning_model,
            settings.groq_api_key, settings.groq_base_url,
            REASONING_DEFAULTS, "Reasoning Tier", "groq"
        )
        if groq_reasoning:
            specs.append(groq_reasoning)

    # 4. OpenRouter Fallback Models (Backup when primary providers fail)
    if settings.has_openrouter:
        op_fast = _build_model(
            "fast-backup", settings.openrouter_fast_model,
            settings.openrouter_api_key, settings.openrouter_base_url,
            FAST_DEFAULTS, "Fast Backup", "openrouter"
        )
        if op_fast:
            specs.append(op_fast)

        op_coding = _build_model(
            "coding-backup", settings.openrouter_coding_model,
            settings.openrouter_api_key, settings.openrouter_base_url,
            CODING_DEFAULTS, "Coding Backup", "openrouter"
        )
        if op_coding:
            specs.append(op_coding)

        op_reasoning = _build_model(
            "reasoning-backup", settings.openrouter_reasoning_model,
            settings.openrouter_api_key, settings.openrouter_base_url,
            REASONING_DEFAULTS, "Reasoning Backup", "openrouter"
        )
        if op_reasoning:
            specs.append(op_reasoning)

        op_powerful = _build_model(
            "powerful", settings.openrouter_powerful_model,
            settings.openrouter_api_key, settings.openrouter_base_url,
            POWERFUL_DEFAULTS, "Powerful Baseline", "openrouter"
        )
        if op_powerful:
            specs.append(op_powerful)

    return specs


class ModelRegistry:
    """Holds all ModelSpecs and answers routing and fallback queries."""

    def __init__(self, specs: List[ModelSpec]):
        self._specs: Dict[str, ModelSpec] = {s.model_id: s for s in specs}

    @classmethod
    def from_settings(cls) -> "ModelRegistry":
        specs = _build_all_models()
        if not specs:
            raise RuntimeError(
                "No models configured. Set at least one provider API key in .env"
            )
        return cls(specs)

    def all(self) -> List[ModelSpec]:
        return list(self._specs.values())

    def available(self) -> List[ModelSpec]:
        return [s for s in self._specs.values() if s.available]

    def get(self, model_id: str) -> Optional[ModelSpec]:
        return self._specs.get(model_id)

    def get_by_provider_and_tier(self, provider: str, tier: str) -> Optional[ModelSpec]:
        for s in self._specs.values():
            if s.provider == provider and s.tier == tier and s.available:
                return s
        return None

    def get_by_tier(self, tier: str) -> Optional[ModelSpec]:
        # Preference: Gemini for fast, Groq for coding/reasoning, OpenRouter for powerful
        preferred_provider = {
            "fast": "gemini",
            "coding": "groq",
            "reasoning": "groq",
            "powerful": "openrouter",
            "balanced": "gemini",
        }.get(tier, "gemini")

        match = self.get_by_provider_and_tier(preferred_provider, tier)
        if match:
            return match

        # Fallback to any model in that tier
        for s in self._specs.values():
            if tier in s.tier and s.available and s.tier != "analyzer":
                return s
        return None

    def get_analyzer(self) -> ModelSpec:
        for s in self._specs.values():
            if s.tier == "analyzer" and s.available:
                return s
        avail = self.available()
        if not avail:
            raise RuntimeError("No available model to serve as Analyzer.")
        return avail[0]

    def strongest(self) -> Optional[ModelSpec]:
        """Highest-quality available model (used for baseline cost calculations)."""
        avail = [m for m in self.available() if m.tier != "analyzer"]
        if not avail:
            return None
        return max(avail, key=lambda s: s.quality)

    def has_real(self) -> bool:
        return any(s.available for s in self._specs.values())

    def to_public_list(self) -> List[dict]:
        return [
            {
                "model_id": s.model_id,
                "name": s.name,
                "provider": s.provider,
                "endpoint_model": s.endpoint_model,
                "available": s.available,
                "demo_mode": False,
                "mode": s.mode,
                "quality": s.quality,
                "reasoning": s.reasoning,
                "coding": s.coding,
                "context_window": s.context_window,
                "input_price_per_mtok": s.input_price_per_mtok,
                "output_price_per_mtok": s.output_price_per_mtok,
                "expected_latency_ms": s.expected_latency_ms,
                "tier": s.tier,
            }
            for s in self.all()
        ]


registry = ModelRegistry.from_settings()