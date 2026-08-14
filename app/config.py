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


@dataclass(frozen=True)
class Settings:
    """Typed access to configuration. Frozen: loaded once at startup."""

    database_path: Path = field(
        default_factory=lambda: BASE_DIR / "data" / "metrics.db"
    )
    static_dir: Path = field(default_factory=lambda: BASE_DIR / "static")

    mock_models_enabled: bool = field(
        default_factory=lambda: _env_bool("MOCK_MODELS_ENABLED", True)
    )

    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip()
    )
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    )
    openai_fast_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini").strip()
    )
    openai_powerful_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_POWERFUL_MODEL", "gpt-4o").strip()
    )

    request_timeout_seconds: float = field(
        default_factory=lambda: _env_float("REQUEST_TIMEOUT_SECONDS", 60.0)
    )
    max_history_messages: int = field(
        default_factory=lambda: max(1, int(os.getenv("MAX_HISTORY_MESSAGES", "10")))
    )

    routing_weights: dict = field(default_factory=lambda: {
        "quality_suitability": _env_float("W_QUALITY", 0.30),
        "complexity_compatibility": _env_float("W_COMPLEXITY", 0.15),
        "cost_efficiency": _env_float("W_COST", 0.25),
        "latency_efficiency": _env_float("W_LATENCY", 0.15),
        "historical_performance": _env_float("W_HISTORY", 0.15),
    })

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()