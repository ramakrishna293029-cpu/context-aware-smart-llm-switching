"""Model Registry: Declarative metadata and dynamic catalog for all LLM models.

Architecture:
  - Analyzer LLM: Gemini 3.1 Flash-Lite
  - Tier 1: Gemini 3.5 Flash-Lite (Lightweight / Fast)
  - Tier 2: Groq GPT-OSS 20B (Fast General Purpose)
  - Tier 3: Gemini 3.6 Flash (Balanced)
  - Tier 4: Groq Qwen3.8 27B (Coding Specialist)
  - Tier 5: Groq GPT-OSS 120B (Advanced Reasoning)
  - Tier 6: Gemini 3.8 Flash (High-Capability Gemini, with resilient fallback to gemini-3.5-flash)
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
    # 6 Core Architecture Tiers + Analyzer
    "gemini:gemini-3.1-flash-lite":     (0.82, 0.80, 0.80, 0.050, 0.20, 250, 1000000),
    "gemini:gemini-3.5-flash-lite":     (0.82, 0.78, 0.78, 0.075, 0.30, 300, 1000000),
    "groq:openai/gpt-oss-20b":          (0.84, 0.80, 0.82, 0.100, 0.20, 200, 8192),
    "gemini:gemini-3.6-flash":          (0.88, 0.85, 0.86, 0.150, 0.60, 450, 1000000),
    "groq:qwen/qwen3.8-27b":            (0.92, 0.88, 0.96, 0.200, 0.60, 320, 32768),
    "groq:openai/gpt-oss-120b":         (0.96, 0.97, 0.92, 0.590, 0.79, 480, 8192),
    "gemini:gemini-3.8-flash":          (0.97, 0.95, 0.94, 0.300, 1.20, 600, 1000000),
    "gemini:gemini-3.5-flash":          (0.86, 0.82, 0.82, 0.150, 0.60, 400, 1000000),

    # Legacy Gemini models
    "gemini:gemini-2.5-flash-lite":     (0.80, 0.72, 0.75, 0.075, 0.30, 400, 1000000),
    "gemini:gemini-2.5-flash":          (0.86, 0.80, 0.82, 0.150, 0.60, 600, 1000000),
    "gemini:gemini-flash-latest":       (0.86, 0.80, 0.82, 0.150, 0.60, 600, 1000000),
    "gemini:gemini-1.5-flash":          (0.80, 0.72, 0.75, 0.075, 0.30, 700, 1000000),
    "gemini:gemini-2.5-pro":            (0.95, 0.94, 0.92, 1.250, 5.00, 1200, 2000000),
    "gemini:gemini-1.5-pro":            (0.92, 0.90, 0.88, 1.250, 5.00, 1200, 2000000),

    # Legacy Groq models
    "groq:groq/compound-mini":         (0.84, 0.82, 0.84, 0.08, 0.15, 200, 128000),
    "groq:qwen/qwen3.6-27b":            (0.90, 0.86, 0.96, 0.20, 0.60, 350, 32768),
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
ANALYZER_DEFAULTS = (0.82, 0.80, 0.80, 0.05, 0.20, 250, 1000000)
TIER1_DEFAULTS = (0.82, 0.78, 0.78, 0.075, 0.30, 300, 1000000)
TIER2_DEFAULTS = (0.84, 0.80, 0.82, 0.10, 0.20, 200, 8192)
TIER3_DEFAULTS = (0.88, 0.85, 0.86, 0.15, 0.60, 450, 1000000)
TIER4_DEFAULTS = (0.92, 0.88, 0.96, 0.20, 0.60, 320, 32768)
TIER5_DEFAULTS = (0.96, 0.97, 0.92, 0.59, 0.79, 480, 8192)
TIER6_DEFAULTS = (0.97, 0.95, 0.94, 0.30, 1.20, 600, 1000000)
CUSTOM_DEFAULTS = (0.85, 0.80, 0.80, 0.10, 0.20, 400, 32768)


@dataclass(frozen=True)
class ModelSpec:
    model_id: str                 # Internal ID: "gemini-tier_1", "groq-tier_2", etc.
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
    tier: str                     # "analyzer", "tier_1", "tier_2", "tier_3", "tier_4", "tier_5", "tier_6"
    fallback_model: Optional[str] = None  # Resilient fallback endpoint for this model
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
    fallback_model: Optional[str] = None,
    demo_mode: bool = False,
    custom_endpoint: bool = False,
    model_id_override: Optional[str] = None,
) -> Optional[ModelSpec]:
    """Build a single ModelSpec for a given tier and provider."""
    if not model_name:
        return None
    if not api_key and not demo_mode and not custom_endpoint:
        return None

    quality, reasoning, coding, in_price, out_price, latency, ctx = _model_metadata(provider, model_name, tier_defaults)
    mid = model_id_override or f"{provider}-{tier}"
    return ModelSpec(
        model_id=mid,
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
        fallback_model=fallback_model,
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
            model_id="demo-tier_1",
            name="Demo Tier 1 - Fast (Simulation)",
            provider="mock",
            endpoint_model="demo-tier_1",
            api_key="",
            base_url="",
            input_price_per_mtok=0.075,
            output_price_per_mtok=0.30,
            expected_latency_ms=250,
            quality=0.80,
            reasoning=0.75,
            coding=0.75,
            context_window=32768,
            tier="tier_1",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-tier_2",
            name="Demo Tier 2 - Fast General (Simulation)",
            provider="mock",
            endpoint_model="demo-tier_2",
            api_key="",
            base_url="",
            input_price_per_mtok=0.10,
            output_price_per_mtok=0.20,
            expected_latency_ms=200,
            quality=0.84,
            reasoning=0.80,
            coding=0.82,
            context_window=8192,
            tier="tier_2",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-tier_3",
            name="Demo Tier 3 - Balanced (Simulation)",
            provider="mock",
            endpoint_model="demo-tier_3",
            api_key="",
            base_url="",
            input_price_per_mtok=0.15,
            output_price_per_mtok=0.60,
            expected_latency_ms=400,
            quality=0.85,
            reasoning=0.82,
            coding=0.84,
            context_window=32768,
            tier="tier_3",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-tier_4",
            name="Demo Tier 4 - Coding (Simulation)",
            provider="mock",
            endpoint_model="demo-tier_4",
            api_key="",
            base_url="",
            input_price_per_mtok=0.20,
            output_price_per_mtok=0.60,
            expected_latency_ms=350,
            quality=0.92,
            reasoning=0.88,
            coding=0.96,
            context_window=32768,
            tier="tier_4",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-tier_5",
            name="Demo Tier 5 - Reasoning (Simulation)",
            provider="mock",
            endpoint_model="demo-tier_5",
            api_key="",
            base_url="",
            input_price_per_mtok=0.59,
            output_price_per_mtok=0.79,
            expected_latency_ms=500,
            quality=0.95,
            reasoning=0.97,
            coding=0.92,
            context_window=32768,
            tier="tier_5",
            demo_mode=True,
        ),
        ModelSpec(
            model_id="demo-tier_6",
            name="Demo Tier 6 - High Capability (Simulation)",
            provider="mock",
            endpoint_model="demo-tier_6",
            api_key="",
            base_url="",
            input_price_per_mtok=1.25,
            output_price_per_mtok=5.00,
            expected_latency_ms=800,
            quality=0.98,
            reasoning=0.96,
            coding=0.95,
            context_window=64000,
            tier="tier_6",
            demo_mode=True,
        ),
    ]


def build_models_from_credentials(
    creds: ResolvedCredentials,
    settings: Optional[Settings] = None,
) -> List[ModelSpec]:
    """Dynamically construct model catalog from resolved credentials and environment."""
    cfg = settings or default_settings
    specs: List[ModelSpec] = []

    # If force mock mode or zero credentials exist, return demo suite
    if cfg.mock_models_mode in ("true", "1", "yes") or not creds.has_real_providers:
        return _build_demo_models()

    # 1. Analyzer LLM: Gemini 3.1 Flash-Lite
    analyzer_key = (
        creds.gemini_analyzer_api_key
        or cfg.gemini_analyzer_api_key
        or creds.gemini_api_key
        or cfg.gemini_api_key
    )
    analyzer_model_name = creds.gemini_analyzer_model or cfg.gemini_analyzer_model
    if analyzer_key and analyzer_model_name:
        m_analyzer = _build_model(
            "analyzer",
            analyzer_model_name,
            analyzer_key,
            cfg.gemini_base_url,
            ANALYZER_DEFAULTS,
            "Analyzer LLM",
            "gemini",
            model_id_override="gemini-analyzer",
        )
        if m_analyzer:
            specs.append(m_analyzer)

    # 2. Tier 1: Gemini 3.5 Flash-Lite
    t1_key = (
        creds.gemini_tier1_api_key
        or cfg.gemini_tier1_api_key
        or creds.gemini_api_key
        or cfg.gemini_api_key
    )
    t1_model = creds.gemini_tier1_model or cfg.gemini_tier1_model
    if t1_key and t1_model:
        m_t1 = _build_model(
            "tier_1",
            t1_model,
            t1_key,
            cfg.gemini_base_url,
            TIER1_DEFAULTS,
            "Tier 1: Lightweight / Fast",
            "gemini",
            model_id_override="gemini-tier_1",
        )
        if m_t1:
            specs.append(m_t1)

    # 3. Tier 2: Groq GPT-OSS 20B
    t2_key = (
        creds.groq_tier2_api_key
        or cfg.groq_tier2_api_key
        or creds.groq_api_key
        or cfg.groq_api_key
    )
    t2_model = creds.groq_tier2_model or cfg.groq_tier2_model
    if t2_key and t2_model:
        m_t2 = _build_model(
            "tier_2",
            t2_model,
            t2_key,
            cfg.groq_base_url,
            TIER2_DEFAULTS,
            "Tier 2: Fast General Purpose",
            "groq",
            model_id_override="groq-tier_2",
        )
        if m_t2:
            specs.append(m_t2)

    # 4. Tier 3: Gemini 3.6 Flash
    t3_key = (
        creds.gemini_tier3_api_key
        or cfg.gemini_tier3_api_key
        or creds.gemini_api_key
        or cfg.gemini_api_key
    )
    t3_model = creds.gemini_tier3_model or cfg.gemini_tier3_model
    if t3_key and t3_model:
        m_t3 = _build_model(
            "tier_3",
            t3_model,
            t3_key,
            cfg.gemini_base_url,
            TIER3_DEFAULTS,
            "Tier 3: Balanced",
            "gemini",
            model_id_override="gemini-tier_3",
        )
        if m_t3:
            specs.append(m_t3)

    # 5. Tier 4: Groq Qwen3.8 27B
    t4_key = (
        creds.groq_tier4_api_key
        or cfg.groq_tier4_api_key
        or creds.groq_api_key
        or cfg.groq_api_key
    )
    t4_model = creds.groq_tier4_model or cfg.groq_tier4_model
    if t4_key and t4_model:
        m_t4 = _build_model(
            "tier_4",
            t4_model,
            t4_key,
            cfg.groq_base_url,
            TIER4_DEFAULTS,
            "Tier 4: Coding Specialist",
            "groq",
            model_id_override="groq-tier_4",
        )
        if m_t4:
            specs.append(m_t4)

    # 6. Tier 5: Groq GPT-OSS 120B
    t5_key = (
        creds.groq_tier5_api_key
        or cfg.groq_tier5_api_key
        or creds.groq_api_key
        or cfg.groq_api_key
    )
    t5_model = creds.groq_tier5_model or cfg.groq_tier5_model
    if t5_key and t5_model:
        m_t5 = _build_model(
            "tier_5",
            t5_model,
            t5_key,
            cfg.groq_base_url,
            TIER5_DEFAULTS,
            "Tier 5: Advanced Reasoning",
            "groq",
            model_id_override="groq-tier_5",
        )
        if m_t5:
            specs.append(m_t5)

    # 7. Tier 6: Gemini 3.8 Flash (with resilient fallback to gemini-3.5-flash)
    t6_key = (
        creds.gemini_tier6_api_key
        or cfg.gemini_tier6_api_key
        or creds.gemini_api_key
        or cfg.gemini_api_key
    )
    t6_model = creds.gemini_tier6_model or cfg.gemini_tier6_model
    t6_fallback = (
        creds.gemini_tier6_fallback_model
        or cfg.gemini_tier6_fallback_model
        or "gemini-3.5-flash"
    )
    if t6_key and t6_model:
        m_t6 = _build_model(
            "tier_6",
            t6_model,
            t6_key,
            cfg.gemini_base_url,
            TIER6_DEFAULTS,
            "Tier 6: High-Capability Gemini",
            "gemini",
            fallback_model=t6_fallback,
            model_id_override="gemini-tier_6",
        )
        if m_t6:
            specs.append(m_t6)

    # 8. Extra / Test Providers (OpenAI, Custom, OpenRouter if configured)
    if creds.has_openai:
        op_fast = _build_model(
            "tier_1", creds.fast_model or cfg.openai_model,
            creds.openai_api_key or "", cfg.openai_base_url,
            TIER1_DEFAULTS, "OpenAI Tier", "openai",
            model_id_override="openai-tier_1",
        )
        if op_fast and not any(s.model_id == "openai-tier_1" for s in specs):
            specs.append(op_fast)

        if not any(s.tier == "analyzer" for s in specs):
            op_an = _build_model(
                "analyzer", cfg.openai_model,
                creds.openai_api_key or "", cfg.openai_base_url,
                ANALYZER_DEFAULTS, "Analyzer", "openai",
                model_id_override="openai-analyzer",
            )
            if op_an:
                specs.append(op_an)

    if creds.has_custom:
        custom_spec = _build_model(
            "custom", creds.custom_model or cfg.custom_model,
            creds.custom_api_key or "custom-key", creds.custom_base_url or "",
            CUSTOM_DEFAULTS, "Custom Endpoint", "custom", custom_endpoint=True
        )
        if custom_spec:
            specs.append(custom_spec)

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
        t = tier.lower()
        for s in self._specs.values():
            if s.provider.lower() == p and s.tier.lower() == t and s.available:
                return s
        return None

    def get_by_tier(self, tier: str) -> Optional[ModelSpec]:
        """Resolves model by tier name ('tier_1'..'tier_6' or legacy aliases)."""
        t = tier.lower().strip()
        tier_alias = {
            "tier_1": "tier_1",
            "tier1": "tier_1",
            "fast": "tier_1",
            "fast-backup": "tier_1",
            "tier_2": "tier_2",
            "tier2": "tier_2",
            "tier_3": "tier_3",
            "tier3": "tier_3",
            "balanced": "tier_3",
            "tier_4": "tier_4",
            "tier4": "tier_4",
            "coding": "tier_4",
            "coding-backup": "tier_4",
            "tier_5": "tier_5",
            "tier5": "tier_5",
            "reasoning": "tier_5",
            "reasoning-backup": "tier_5",
            "tier_6": "tier_6",
            "tier6": "tier_6",
            "powerful": "tier_6",
        }.get(t, t)

        # 1. Exact match on normalized tier
        for s in self._specs.values():
            if s.tier.lower() == tier_alias and s.available and s.tier != "analyzer":
                return s

        # 2. Match substring in tier
        for s in self._specs.values():
            if (t in s.tier.lower() or tier_alias in s.tier.lower()) and s.available and s.tier != "analyzer":
                return s

        return None

    def get_analyzer(self) -> ModelSpec:
        for s in self._specs.values():
            if s.tier == "analyzer" and s.available:
                return s
        avail = self.available()
        if not avail:
            demo_models = _build_demo_models()
            return demo_models[0]
        return avail[0]

    def strongest(self) -> Optional[ModelSpec]:
        """Highest-quality available model (used for baseline cost comparisons)."""
        avail = [m for m in self.available() if m.tier != "analyzer"]
        if not avail:
            return None
        # Prefer Tier 6 if available
        t6 = self.get_by_tier("tier_6")
        if t6 and t6.available:
            return t6
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
                "fallback_model": s.fallback_model,
            }
            for s in self.all()
        ]


registry = ModelRegistry.from_settings()