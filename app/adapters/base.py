"""LLM adapter contract. The router never talks to providers directly."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, List, Optional

from ..registry import ModelSpec
from ..schemas import ChatMessage


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    usage_source: str = "provider"  # "provider" | "unavailable" | "demo"
    ttft_ms: Optional[float] = None  # measured time-to-first-token


class LLMAdapterError(RuntimeError):
    """Base class for provider failures."""


class InvalidApiKeyError(LLMAdapterError):
    """401/403: credentials missing or rejected."""


class RateLimitError(LLMAdapterError):
    """429: provider rate limit / quota exceeded."""


class ProviderTimeoutError(LLMAdapterError):
    """408/504/connect timeout: provider too slow or unreachable."""


class ProviderUnavailableError(LLMAdapterError):
    """5xx/network: provider down or unreachable."""


class ModelUnavailableError(LLMAdapterError):
    """404: requested model does not exist on the provider."""


class InvalidResponseError(LLMAdapterError):
    """Provider returned data that could not be parsed."""


class LLMAdapter(ABC):
    provider: str = "base"

    @abstractmethod
    async def generate(self, model: ModelSpec, messages: List[ChatMessage]) -> LLMResult:
        """Run the conversation through `model` and return the result."""
        raise NotImplementedError

    async def stream(self, model: ModelSpec, messages: List[ChatMessage]) -> AsyncIterator[str]:
        """Yield response text chunks as they arrive."""
        result = await self.generate(model, messages)
        yield result.text

    def supports_streaming(self) -> bool:
        return False

    async def health_check(self, model: ModelSpec) -> bool:
        """Quick ping test to check provider availability."""
        try:
            res = await self.generate(model, [ChatMessage(role="user", content="ping")])
            return bool(res.text)
        except Exception:
            return False


class AdapterFactory:
    """Registers and hands out adapters by provider name."""

    def __init__(self):
        self._adapters = {}
        self._default = None

    def register(self, adapter: LLMAdapter):
        self._adapters[adapter.provider] = adapter

    def set_default(self, adapter: LLMAdapter):
        self._default = adapter

    def get(self, provider: str) -> LLMAdapter:
        # Handle provider aliases
        if provider in ("gemini", "google"):
            if "gemini" in self._adapters:
                return self._adapters["gemini"]
            if "google" in self._adapters:
                return self._adapters["google"]
        if provider in self._adapters:
            return self._adapters[provider]
        if self._default is not None:
            return self._default
        raise LLMAdapterError(f"No adapter registered for provider '{provider}'")

    def providers(self) -> List[str]:
        return list(self._adapters.keys())


adapter_factory = AdapterFactory()