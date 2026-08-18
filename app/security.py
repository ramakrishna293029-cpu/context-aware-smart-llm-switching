"""Security and Request Credential Resolution.

Extracts dynamic provider API keys, custom endpoints, and tier model overrides
from incoming request headers with fallback to server .env / settings.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from fastapi import Request

from .config import Settings, settings as default_settings


@dataclass(frozen=True)
class ResolvedCredentials:
    """Request-scoped credentials and model configuration."""

    gemini_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    custom_base_url: Optional[str] = None
    custom_api_key: Optional[str] = None
    custom_model: Optional[str] = None

    # Tier model overrides
    base_model: Optional[str] = None
    fast_model: Optional[str] = None
    coding_model: Optional[str] = None
    reasoning_model: Optional[str] = None
    powerful_model: Optional[str] = None

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def has_openrouter(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_custom(self) -> bool:
        return bool(self.custom_base_url)

    @property
    def has_real_providers(self) -> bool:
        return (
            self.has_gemini
            or self.has_groq
            or self.has_openrouter
            or self.has_openai
            or self.has_custom
        )

    def get_key_for_provider(self, provider: str) -> Optional[str]:
        p = provider.lower()
        if p in ("gemini", "google"):
            return self.gemini_api_key
        elif p == "groq":
            return self.groq_api_key
        elif p == "openrouter":
            return self.openrouter_api_key
        elif p == "openai":
            return self.openai_api_key
        elif p == "custom":
            return self.custom_api_key or "custom-key"
        return None

    def active_providers(self) -> List[str]:
        providers = []
        if self.has_gemini:
            providers.append("gemini")
        if self.has_groq:
            providers.append("groq")
        if self.has_openrouter:
            providers.append("openrouter")
        if self.has_openai:
            providers.append("openai")
        if self.has_custom:
            providers.append("custom")
        return providers


def resolve_credentials_from_headers(
    headers: Dict[str, str],
    settings: Optional[Settings] = None,
) -> ResolvedCredentials:
    """Extract credentials and model overrides from a headers dictionary.
    
    Resolution order:
    1. Header value (if present and non-empty)
    2. Server settings / .env value
    3. None
    """
    cfg = settings or default_settings

    # Normalize header keys to lowercase
    norm = {k.lower(): v.strip() for k, v in headers.items() if v and v.strip()}

    def _pick(header_name: str, server_val: Optional[str]) -> Optional[str]:
        h_val = norm.get(header_name.lower())
        if h_val:
            return h_val
        return server_val if server_val else None

    gemini_key = _pick("x-gemini-key", cfg.gemini_api_key)
    groq_key = _pick("x-groq-key", cfg.groq_api_key)
    openrouter_key = _pick("x-openrouter-key", cfg.openrouter_api_key)
    openai_key = _pick("x-openai-key", cfg.openai_api_key)

    custom_url = _pick("x-custom-endpoint", cfg.custom_base_url)
    custom_key = _pick("x-custom-key", cfg.custom_api_key)
    custom_model = _pick("x-custom-model", cfg.custom_model)

    base_model = _pick("x-base-model", cfg.analyzer_model)
    fast_model = _pick("x-fast-model", cfg.gemini_fast_model)
    coding_model = _pick("x-coding-model", cfg.groq_coding_model)
    reasoning_model = _pick("x-reasoning-model", cfg.groq_reasoning_model)
    powerful_model = _pick("x-powerful-model", cfg.openrouter_powerful_model)

    return ResolvedCredentials(
        gemini_api_key=gemini_key,
        groq_api_key=groq_key,
        openrouter_api_key=openrouter_key,
        openai_api_key=openai_key,
        custom_base_url=custom_url,
        custom_api_key=custom_key,
        custom_model=custom_model,
        base_model=base_model,
        fast_model=fast_model,
        coding_model=coding_model,
        reasoning_model=reasoning_model,
        powerful_model=powerful_model,
    )


def resolve_request_credentials(
    request: Optional[Request] = None,
    settings: Optional[Settings] = None,
) -> ResolvedCredentials:
    """Extract credentials and model overrides from a FastAPI Request or fallback to server settings."""
    if request is not None:
        return resolve_credentials_from_headers(dict(request.headers), settings)
    return resolve_credentials_from_headers({}, settings)
