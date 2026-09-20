"""Model Registry: Declarative metadata and dynamic catalog for all LLM models.

Providers supported:
  - Gemini: Fast / low-cost and high-context models
  - Groq: Ultra-low latency coding and reasoning models
  - OpenRouter: Unified gateway analyzer and backup tiers
  - OpenAI: Direct GPT-4o, GPT-4o-mini, o1/o3-mini models
  - Custom: User-provided OpenAI-compatible endpoints (Ollama, vLLM, Azure)
  - Mock: Deterministic offline demo mode
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import Settings, settings as default_settings
from .security import ResolvedCredentials, resolve_credentials_from_headers

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
    "gemini:gemini-1.5-pro":            (0.92, 0.90, 0.88, 1.250, 5.00, 1200, 2000000),

    # Groq models
    "groq:groq/compound-mini":         (0.84, 0.82, 0.84, 0.08, 0.15, 200, 128000),
    "groq:qwen/qwen3.8-27b":            (0.90, 0.86, 0.96, 0.20, 0.60, 350, 32768),
    "groq:qwen/qwen3.6-27b":            (0.90, 0.86, 0.96, 0.20, 0.60, 350, 32768),
    "groq:openai/gpt-oss-120b":         (0.95, 0.97, 0.92, 0.59, 0.79, 500, 8192),
    "groq:openai/gpt-oss-20b":          (0.82, 0.78, 0.84, 0.10, 0.20, 250, 8192),
    "groq:llama-3.3-70b-versatile":     (0.91, 0.88, 0.86, 0.59, 0.79, 450, 128000),
    "groq:llama-3.1-8b-instant":        (0.75, 0.70, 0.72, 0.05, 0.08, 200, 128000),
    "groq:deepseek-r1-distill-llama-70b": (0.94, 0.96, 0.90, 0.59, 0.79, 700, 128000),

    # Direct OpenAI models
    "openai:gpt-4o-mini":               (0.82, 0.80, 0.82, 0.15, 0.60, 500, 128000),
    "openai:gpt-4o":                    (0.95, 0.94, 0.93, 2.50, 10.00, 900, 128000),
    "openai:o1-mini":                   (0.93, 0.96, 0.92, 1.10, 4.40, 800, 128000),
    "openai:o3-mini":                   (0.95, 0.97, 0.94, 1.10, 4.40, 750, 200000),
    "openai:gpt-3.5-turbo":             (0.70, 0.65, 0.65, 0.50, 1.50, 600, 16385),

    # OpenRouter models
    "openrouter:meta-llama/llama-3.2-3b-instruct":        (0.68, 0.58, 0.60, 0.06, 0.06, 300, 131072),
    "openrouter:google/gemma-2-9b-it":                   (0.76, 0.72, 0.74, 0.08, 0.08, 600, 8192),
    "openrouter:google/gemma-2-27b-it":                  (0.82, 0.78, 0.80, 0.27, 0.27, 800, 8192),
    "openrouter:qwen/qwen-2.5-coder-32b-instruct":       (0.92, 0.88, 0.97, 0.18, 0.18, 800, 32768),
    "openrouter:meta-llama/llama-3.1-70b-instruct":       (0.92, 0.90, 0.88, 0.52, 0.75, 900, 131072),
    "openrouter:deepseek/deepseek-r1":                   (0.98, 0.99, 0.95, 0.55, 2.19, 1400, 64000),
    "openrouter:deepseek/deepseek-r1-distill-llama-70b":  (0.94, 0.96, 0.90, 0.23, 0.69, 900, 16384),
    "openrouter:anthropic/claude-3.5-sonnet":            (0.97, 0.96, 0.98, 3.00, 15.00, 1100, 200000),

    # Demo / Mock models
    "mock:demo-analyzer":               (0.70, 0.60, 0.60, 0.00, 0.00, 150, 32768),
    "mock:demo-fast":                   (0.80, 0.75, 0.75, 0.00, 0.00, 250, 32768),
    "mock:demo-balanced":               (0.85, 0.82, 0.84, 0.00, 0.00, 400, 32768),
    "mock:demo-coding":                 (0.92, 0.88, 0.96, 0.00, 0.00, 350, 32768),
    "mock:demo-reasoning":              (0.95, 0.97, 0.92, 0.00, 0.00, 500, 32768),
    "mock:demo-powerful":               (0.98, 0.96, 0.95, 0.00, 0.00, 800, 64000),
}

# Fallback tier defaults
ANALYZER_DEFAULTS = (0.68, 0.58, 0.60, 0.06, 0.06, 300, 131072)
FAST_DEFAULTS = (0.80, 0.72, 0.75, 0.075, 0.30, 400, 1000000)
BALANCED_DEFAULTS = (0.76, 0.72, 0.74, 0.08, 0.08, 600, 8192)
CODING_DEFAULTS = (0.90, 0.86, 0.96, 0.20, 0.60, 350, 32768)
POWERFUL_DEFAULTS = (0.95, 0.94, 0.92, 1.25, 5.00, 1200, 2000000)
REASONING_DEFAULTS = (0.95, 0.97, 0.92, 0.59, 0.79, 500, 8192)
CUSTOM_DEFAULTS = (0.85, 0.80, 0.80, 0.10, 0.20, 400, 32768)


@dataclass(frozen=True)
class ModelSpec:
    model_id: str                 # Internal ID: "gemini-fast", "groq-coding", "openai-fast", etc.
    name: str                     # Display name
    provider: str                 # "gemini" | "groq" | "openrouter" | "openai" | "custom" | "mock"
    endpoint_model: str           # Model identifier sent to provider API
    api_key: str                  # Provider API key
    base_url: str                 # Provider API base URL
    input_price_per_mtok: float   # USD per 1M input tokens
    output_price_per_mtok: float  # USD per 1M output tokens
    expected_latency_ms: float
    quality: float                # 0..1 overall capability
    reasoning: float              # 0..1
    coding: float                 # 0..1
    context_window: int
    tier: str                     # "analyzer", "fast", "balanced", "coding", "powerful", "reasoning", "custom"
    demo_mode: bool = False
    custom_endpoint: bool = False

    @property
    def available(self) -> bool:
        return bool(self.api_key or self.custom_endpoint or self.demo_mode)

    @property
    def price_per_1k(self) -> float:
        """Blended price per 1K tokens (assumes ~3:1 input:output mix)."""
        return (3 * self.input_price_per_mtok + self.output_price_per_mtok) / 4 / 1000

    @property
    def mode(self) -> str:
        return "demo" if self.demo_mode else "real"


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
    demo_mode: bool = False,
    custom_endpoint: bool = False,
) -> Optional[ModelSpec]:
    """Build a single ModelSpec for a given tier and provider."""
    if not model_name:
        return None
    if not api_key and not demo_mode and not custom_endpoint:
        return None

    quality, reasoning, coding, in_price, out_price, latency, ctx = _model_metadata(provider, model_name, tier_defaults)
    return ModelSpec(
        model_id=f"{provider}-{tier}",
        name=f"{model_name} ({tier_label})",
        provider=provider,
        endpoint_model=model_name,
        api_key=api_key or "",
        base_url=base_url or "",
        input_price_per_mtok=in_price,
        output_price_per_mtok=out_price,
        expected_latency_ms=latency,
        quality=quality,
        reasoning=reasoning,
        coding=coding,
        context_window=ctx,
        tier=tier,
        demo_mode=demo_mode,
        custom_endpoint=custom_endpoint,
    )


def _build_demo_models() -> List[ModelSpec]:
    """Build standard offline simulation models."""
    return [
        ModelSpec(
            model_id="demo-analyzer",
            name="Demo Analyzer LLM (Simulation)",
            provider="mock",
            endpoint_model="demo-analyzer",
            api_key="",
            base_url="",
            input_price_per_mtok=0.0,
            output_price_per_mtok=0.0,
            expected_latency_ms=150,
            quality=0.70,
            reasoning=0.60,
            coding=0.60,
            context_window=32768,
            tier="analyzer",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-fast",
            name="Demo Fast Tier (Simulation)",
            provider="mock",
            endpoint_model="demo-fast",
            api_key="",
            base_url="",
            input_price_per_mtok=0.075,
            output_price_per_mtok=0.30,
            expected_latency_ms=250,
            quality=0.80,
            reasoning=0.75,
            coding=0.75,
            context_window=32768,
            tier="fast",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-balanced",
            name="Demo Balanced Tier (Simulation)",
            provider="mock",
            endpoint_model="demo-balanced",
            api_key="",
            base_url="",
            input_price_per_mtok=0.15,
            output_price_per_mtok=0.60,
            expected_latency_ms=400,
            quality=0.85,
            reasoning=0.82,
            coding=0.84,
            context_window=32768,
            tier="balanced",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-coding",
            name="Demo Coding Specialist (Simulation)",
            provider="mock",
            endpoint_model="demo-coding",
            api_key="",
            base_url="",
            input_price_per_mtok=0.20,
            output_price_per_mtok=0.60,
            expected_latency_ms=350,
            quality=0.92,
            reasoning=0.88,
            coding=0.96,
            context_window=32768,
            tier="coding",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-reasoning",
            name="Demo Deep Reasoning (Simulation)",
            provider="mock",
            endpoint_model="demo-reasoning",
            api_key="",
            base_url="",
            input_price_per_mtok=0.59,
            output_price_per_mtok=0.79,
            expected_latency_ms=500,
            quality=0.95,
            reasoning=0.97,
            coding=0.92,
            context_window=32768,
            tier="reasoning",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-powerful",
            name="Demo Ultra Powerful Baseline (Simulation)",
            provider="mock",
            endpoint_model="demo-powerful",
            api_key="",
            base_url="",
            input_price_per_mtok=1.25,
            output_price_per_mtok=5.00,
            expected_latency_ms=800,
            quality=0.98,
            reasoning=0.96,
            coding=0.95,
            context_window=64000,
            tier="powerful",
            demo_mode=True,
        ),
    ]


def build_models_from_credentials(
    creds: ResolvedCredentials,
    settings: Optional[Settings] = None,
) -> List[ModelSpec]:
    """Dynamically construct model catalog from resolved credentials and overrides."""
    cfg = settings or default_settings
    specs: List[ModelSpec] = []

    # If force mock mode or zero credentials exist, return demo suite
    if cfg.mock_models_mode in ("true", "1", "yes") or not creds.has_real_providers:
        return _build_demo_models()

    # 1. Base / Analyzer Tier
    # Priority: OpenRouter > Gemini > Groq > OpenAI > Custom
    analyzer_model_name = creds.base_model or cfg.analyzer_model
    if creds.has_openrouter:
        m = _build_model(
            "analyzer", analyzer_model_name,
            creds.openrouter_api_key or "", cfg.openrouter_base_url,
            ANALYZER_DEFAULTS, "Analyzer", "openrouter"
        )
        if m: specs.append(m)
    elif creds.has_gemini:
        m = _build_model(
            "analyzer", creds.fast_model or cfg.gemini_fast_model,
            creds.gemini_api_key or "", cfg.gemini_base_url,
            ANALYZER_DEFAULTS, "Analyzer", "gemini"
        )
        if m: specs.append(m)
    elif creds.has_groq:
        m = _build_model(
            "analyzer", "llama-3.1-8b-instant",
            creds.groq_api_key or "", cfg.groq_base_url,
            ANALYZER_DEFAULTS, "Analyzer", "groq"
        )
        if m: specs.append(m)
    elif creds.has_openai:
        m = _build_model(
            "analyzer", cfg.openai_model,
            creds.openai_api_key or "", cfg.openai_base_url,
            ANALYZER_DEFAULTS, "Analyzer", "openai"
        )
        if m: specs.append(m)
    elif creds.has_custom:
        m = _build_model(
            "analyzer", creds.custom_model or cfg.custom_model,
            creds.custom_api_key or "", creds.custom_base_url or "",
            ANALYZER_DEFAULTS, "Analyzer", "custom", custom_endpoint=True
        )
        if m: specs.append(m)

    # 2. Google Gemini Models
    if creds.has_gemini:
        fast_model_name = creds.fast_model or cfg.gemini_fast_model
        fast_gemini = _build_model(
            "fast", fast_model_name,
            creds.gemini_api_key or "", cfg.gemini_base_url,
            FAST_DEFAULTS, "Fast Tier", "gemini"
        )
        if fast_gemini: specs.append(fast_gemini)

        # Also register Gemini 2.5 Flash / Pro if available
        pro_gemini = _build_model(
            "powerful", "gemini-2.5-pro",
            creds.gemini_api_key or "", cfg.gemini_base_url,
            POWERFUL_DEFAULTS, "Pro Tier", "gemini"
        )
        if pro_gemini: specs.append(pro_gemini)

    # 3. Groq Models (Coding + Reasoning)
    if creds.has_groq:
        coding_model_name = creds.coding_model or cfg.groq_coding_model
        groq_coding = _build_model(
            "coding", coding_model_name,
            creds.groq_api_key or "", cfg.groq_base_url,
            CODING_DEFAULTS, "Coding Tier", "groq"
        )
        if groq_coding: specs.append(groq_coding)

        reasoning_model_name = creds.reasoning_model or cfg.groq_reasoning_model
        groq_reasoning = _build_model(
            "reasoning", reasoning_model_name,
            creds.groq_api_key or "", cfg.groq_base_url,
            REASONING_DEFAULTS, "Reasoning Tier", "groq"
        )
        if groq_reasoning: specs.append(groq_reasoning)

        groq_fast = _build_model(
            "fast-backup", "groq/compound-mini",
            creds.groq_api_key or "", cfg.groq_base_url,
            FAST_DEFAULTS, "Fast Backup", "groq"
        )
        if groq_fast: specs.append(groq_fast)

    # 4. Direct OpenAI Models
    if creds.has_openai:
        openai_fast = _build_model(
            "fast-backup", "gpt-4o-mini",
            creds.openai_api_key or "", cfg.openai_base_url,
            FAST_DEFAULTS, "Fast Tier", "openai"
        )
        if openai_fast: specs.append(openai_fast)

        openai_powerful = _build_model(
            "powerful", "gpt-4o",
            creds.openai_api_key or "", cfg.openai_base_url,
            POWERFUL_DEFAULTS, "Powerful Tier", "openai"
        )
        if openai_powerful: specs.append(openai_powerful)

        openai_reasoning = _build_model(
            "reasoning-backup", "o3-mini",
            creds.openai_api_key or "", cfg.openai_base_url,
            REASONING_DEFAULTS, "Reasoning Backup", "openai"
        )
        if openai_reasoning: specs.append(openai_reasoning)

    # 5. OpenRouter Models (Backup & Powerful baseline)
    if creds.has_openrouter:
        op_fast = _build_model(
            "fast-backup", cfg.openrouter_fast_model,
            creds.openrouter_api_key or "", cfg.openrouter_base_url,
            FAST_DEFAULTS, "Fast Backup", "openrouter"
        )
        if op_fast: specs.append(op_fast)

        op_coding = _build_model(
            "coding-backup", cfg.openrouter_coding_model,
            creds.openrouter_api_key or "", cfg.openrouter_base_url,
            CODING_DEFAULTS, "Coding Backup", "openrouter"
        )
        if op_coding: specs.append(op_coding)

        op_reasoning = _build_model(
            "reasoning-backup", cfg.openrouter_reasoning_model,
            creds.openrouter_api_key or "", cfg.openrouter_base_url,
            REASONING_DEFAULTS, "Reasoning Backup", "openrouter"
        )
        if op_reasoning: specs.append(op_reasoning)

        powerful_model_name = creds.powerful_model or cfg.openrouter_powerful_model
        op_powerful = _build_model(
            "powerful", powerful_model_name,
            creds.openrouter_api_key or "", cfg.openrouter_base_url,
            POWERFUL_DEFAULTS, "Powerful Baseline", "openrouter"
        )
        if op_powerful: specs.append(op_powerful)

    # 6. Custom OpenAI-Compatible Endpoint
    if creds.has_custom:
        custom_spec = _build_model(
            "custom", creds.custom_model or cfg.custom_model,
            creds.custom_api_key or "custom-key", creds.custom_base_url or "",
            CUSTOM_DEFAULTS, "Custom Endpoint", "custom", custom_endpoint=True
        )
        if custom_spec: specs.append(custom_spec)

    # Fallback to demo models if somehow zero models were instantiated
    if not specs:
        return _build_demo_models()

    return specs


class ModelRegistry:
    """Holds all ModelSpecs for routing, candidate scoring, and fallback chains."""

    def __init__(self, specs: List[ModelSpec]):
        self._specs: Dict[str, ModelSpec] = {s.model_id: s for s in specs}

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None) -> "ModelRegistry":
        cfg = settings or default_settings
        creds = resolve_credentials_from_headers({}, cfg)
        specs = build_models_from_credentials(creds, cfg)
        return cls(specs)

    @classmethod
    def from_credentials(
        cls,
        creds: ResolvedCredentials,
        settings: Optional[Settings] = None,
    ) -> "ModelRegistry":
        specs = build_models_from_credentials(creds, settings or default_settings)
        return cls(specs)

    def all(self) -> List[ModelSpec]:
        return list(self._specs.values())

    def available(self) -> List[ModelSpec]:
        return [s for s in self._specs.values() if s.available]

    def get(self, model_id: str) -> Optional[ModelSpec]:
        return self._specs.get(model_id)

    def get_by_provider_and_tier(self, provider: str, tier: str) -> Optional[ModelSpec]:
        p = provider.lower()
        for s in self._specs.values():
            if s.provider.lower() == p and s.tier == tier and s.available:
                return s
        return None

    def get_by_tier(self, tier: str) -> Optional[ModelSpec]:
        preferred_provider = {
            "fast": "gemini",
            "coding": "groq",
            "reasoning": "groq",
            "powerful": "openrouter",
            "balanced": "gemini",
            "custom": "custom",
        }.get(tier, "gemini")

        match = self.get_by_provider_and_tier(preferred_provider, tier)
        if match:
            return match

        # Fallback to any available model in that tier
        for s in self._specs.values():
            if tier in s.tier and s.available and s.tier != "analyzer":
                return s

        # General fallback to any available non-analyzer model
        candidates = [s for s in self.available() if s.tier != "analyzer"]
        return candidates[0] if candidates else None

    def get_analyzer(self) -> ModelSpec:
        for s in self._specs.values():
            if s.tier == "analyzer" and s.available:
                return s
        avail = self.available()
        if not avail:
            # Fallback to demo analyzer
            demo_models = _build_demo_models()
            return demo_models[0]
        return avail[0]

    def strongest(self) -> Optional[ModelSpec]:
        """Highest-quality available model (used for baseline cost comparisons)."""
        avail = [m for m in self.available() if m.tier != "analyzer"]
        if not avail:
            return None
        return max(avail, key=lambda s: s.quality)

    def has_real(self) -> bool:
        return any(s.available and not s.demo_mode for s in self._specs.values())

    def to_public_list(self) -> List[dict]:
        return [
            {
                "model_id": s.model_id,
                "name": s.name,
                "provider": s.provider,
                "endpoint_model": s.endpoint_model,
                "available": s.available,
                "demo_mode": s.demo_mode,
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