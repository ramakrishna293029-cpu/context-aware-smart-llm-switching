"""Adapter Factory: Dynamic registry and lookup for LLM adapters."""

from typing import TYPE_CHECKING, Dict, List, Optional

from .base import LLMAdapter, LLMAdapterError

if TYPE_CHECKING:
    from ..registry import ModelSpec


class AdapterFactory:
    """Registers and provides adapters by provider name or model spec."""

    def __init__(self):
        self._adapters: Dict[str, LLMAdapter] = {}
        self._default: Optional[LLMAdapter] = None

    def register(self, adapter: LLMAdapter) -> None:
        """Register an adapter instance for its primary provider name."""
        self._adapters[adapter.provider.lower()] = adapter

    def set_default(self, adapter: LLMAdapter) -> None:
        """Set fallback adapter when a provider is not explicitly mapped."""
        self._default = adapter

    def get(self, provider: str) -> LLMAdapter:
        """Resolve adapter by provider name or alias."""
        p = provider.lower()
        if p in ("gemini", "google"):
            if "gemini" in self._adapters:
                return self._adapters["gemini"]
            if "google" in self._adapters:
                return self._adapters["google"]

        if p in ("groq", "openrouter", "openai", "custom"):
            # Check for direct registration first, then openai-compatible
            if p in self._adapters:
                return self._adapters[p]
            if "openai" in self._adapters:
                return self._adapters["openai"]

        if p in ("mock", "demo"):
            if "mock" in self._adapters:
                return self._adapters["mock"]
            if "demo" in self._adapters:
                return self._adapters["demo"]

        if p in self._adapters:
            return self._adapters[p]

        if self._default is not None:
            return self._default

        raise LLMAdapterError(f"No adapter registered for provider '{provider}'")

    def get_for_model(self, model: "ModelSpec") -> LLMAdapter:
        """Resolve adapter for a specific ModelSpec, respecting demo mode."""
        if getattr(model, "demo_mode", False) or model.provider in ("mock", "demo"):
            return self.get("mock")
        return self.get(model.provider)

    def providers(self) -> List[str]:
        """List all registered provider names."""
        return list(self._adapters.keys())


adapter_factory = AdapterFactory()
