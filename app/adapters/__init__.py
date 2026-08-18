"""Multi-provider LLM Adapters package."""

from .base import (
    InvalidApiKeyError,
    InvalidResponseError,
    LLMAdapter,
    LLMAdapterError,
    LLMResult,
    ModelUnavailableError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
    StreamChunk,
)
from .factory import AdapterFactory, adapter_factory
from .gemini import GeminiAdapter
from .mock import MockAdapter
from .openai import OpenAICompatibleAdapter

# Initialize and register default adapters in the factory
_gemini = GeminiAdapter()
_openai = OpenAICompatibleAdapter("openai")
_groq = OpenAICompatibleAdapter("groq")
_openrouter = OpenAICompatibleAdapter("openrouter")
_custom = OpenAICompatibleAdapter("custom")
_mock = MockAdapter()

adapter_factory.register(_gemini)
adapter_factory.register(_openai)
adapter_factory.register(_groq)
adapter_factory.register(_openrouter)
adapter_factory.register(_custom)
adapter_factory.register(_mock)
adapter_factory.set_default(_openai)

__all__ = [
    "LLMAdapter",
    "LLMResult",
    "StreamChunk",
    "LLMAdapterError",
    "InvalidApiKeyError",
    "RateLimitError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "ModelUnavailableError",
    "InvalidResponseError",
    "GeminiAdapter",
    "OpenAICompatibleAdapter",
    "MockAdapter",
    "AdapterFactory",
    "adapter_factory",
]
