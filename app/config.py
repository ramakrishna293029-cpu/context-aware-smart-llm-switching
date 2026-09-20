"""Application configuration loaded from environment variables / .env."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Typed access to configuration. Loaded once at startup or reloaded on changes."""

    database_path: Path = field(
        default_factory=lambda: Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "metrics.db")))
    )
    static_dir: Path = field(default_factory=lambda: BASE_DIR / "static")

    mock_models_mode: str = field(
        default_factory=lambda: os.getenv("MOCK_MODELS_ENABLED", "false").strip().lower()
    )

    # OpenRouter (Unified Gateway - Analyzer + Fallbacks)
    openrouter_api_key: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_API_KEY", "").strip()
    )
    openrouter_base_url: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    )
    openrouter_analyzer_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_ANALYZER_MODEL", "meta-llama/llama-3.2-3b-instruct").strip()
    )

    # Google Gemini (Fast / Low-Cost Model)
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip()
    )
    gemini_base_url: str = field(
        default_factory=lambda: os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/")
    )
    gemini_fast_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_FAST_MODEL", "gemini-2.5-flash-lite").strip()
    )

    # Groq (Coding + Reasoning Models)
    groq_api_key: str = field(
        default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip()
    )
    groq_base_url: str = field(
        default_factory=lambda: os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip().rstrip("/")
    )
    groq_coding_model: str = field(
        default_factory=lambda: os.getenv("GROQ_CODING_MODEL", "qwen/qwen3.8-27b").strip()
    )
    groq_reasoning_model: str = field(
        default_factory=lambda: os.getenv("GROQ_REASONING_MODEL", "openai/gpt-oss-120b").strip()
    )

    # Direct OpenAI Provider
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip()
    )
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    )
    openai_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    )

    # Custom OpenAI-Compatible Endpoints (Ollama, LocalAI, vLLM, Azure OpenAI)
    custom_base_url: str = field(
        default_factory=lambda: os.getenv("CUSTOM_BASE_URL", "").strip().rstrip("/")
    )
    custom_api_key: str = field(
        default_factory=lambda: os.getenv("CUSTOM_API_KEY", "").strip()
    )
    custom_model: str = field(
        default_factory=lambda: os.getenv("CUSTOM_MODEL", "default").strip()
    )

    # OpenRouter fallback models (backup tiers)
    openrouter_fast_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_FAST_MODEL", "meta-llama/llama-3.2-3b-instruct").strip()
    )
    openrouter_balanced_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_BALANCED_MODEL", "google/gemma-2-9b-it").strip()
    )
    openrouter_coding_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_CODING_MODEL", "qwen/qwen-2.5-coder-32b-instruct").strip()
    )
    openrouter_powerful_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_POWERFUL_MODEL", "meta-llama/llama-3.1-70b-instruct").strip()
    )
    openrouter_reasoning_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_REASONING_MODEL", "deepseek/deepseek-r1").strip()
    )

    system_prompt: str = field(
        default_factory=lambda: os.getenv(
            "SYSTEM_PROMPT",
            "You are a helpful, expert AI assistant. Provide accurate, clear, and direct responses."
        ).strip()
    )

    # --- Runtime ----------------------------------------------------
    default_strategy: str = field(
        default_factory=lambda: os.getenv("DEFAULT_STRATEGY", "balanced").strip().lower()
    )
    max_cost_per_request: float = field(
        default_factory=lambda: _env_float("MAX_COST_PER_REQUEST", 0.10)
    )
    daily_budget_usd: float = field(
        default_factory=lambda: _env_float("DAILY_BUDGET_USD", 10.00)
    )
    monthly_budget_usd: float = field(
        default_factory=lambda: _env_float("MONTHLY_BUDGET_USD", 100.00)
    )
    max_context_tokens: int = field(
        default_factory=lambda: max(256, _env_int("MAX_CONTEXT_TOKENS", 131072))
    )
    default_max_output_tokens: int = field(
        default_factory=lambda: max(128, _env_int("DEFAULT_MAX_OUTPUT_TOKENS", 4096))
    )
    cors_origins: str = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "*").strip()
    )
    request_timeout_seconds: float = field(
        default_factory=lambda: _env_float("REQUEST_TIMEOUT_SECONDS", 60.0)
    )
    max_history_messages: int = field(
        default_factory=lambda: max(1, _env_int("MAX_HISTORY_MESSAGES", 10))
    )

    # Analyzer model settings
    analyzer_model: str = field(
        default_factory=lambda: os.getenv("OPENROUTER_ANALYZER_MODEL", "meta-llama/llama-3.2-3b-instruct").strip()
    )
    analyzer_max_output_tokens: int = field(
        default_factory=lambda: max(128, _env_int("ANALYZER_MAX_OUTPUT_TOKENS", 1024))
    )

    # Feature flags
    enable_fallback: bool = field(
        default_factory=lambda: _env_bool("ENABLE_FALLBACK", True)
    )
    enable_escalation: bool = field(
        default_factory=lambda: _env_bool("ENABLE_ESCALATION", True)
    )
    enable_telemetry: bool = field(
        default_factory=lambda: _env_bool("ENABLE_TELEMETRY", True)
    )

    # Routing weights
    routing_weights: dict = field(default_factory=lambda: {
        "quality_suitability": _env_float("W_QUALITY", 0.30),
        "complexity_compatibility": _env_float("W_COMPLEXITY", 0.15),
        "reasoning_compatibility": _env_float("W_REASONING", 0.15),
        "task_compatibility": _env_float("W_TASK", 0.10),
        "cost_efficiency": _env_float("W_COST", 0.25),
        "latency_efficiency": _env_float("W_LATENCY", 0.15),
        "historical_performance": _env_float("W_HISTORY", 0.15),
    })

    @property
    def has_openrouter(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_custom(self) -> bool:
        return bool(self.custom_base_url)

    @property
    def has_real_providers(self) -> bool:
        return (
            self.has_openrouter
            or self.has_gemini
            or self.has_groq
            or self.has_openai
            or self.has_custom
        )


settings = Settings()