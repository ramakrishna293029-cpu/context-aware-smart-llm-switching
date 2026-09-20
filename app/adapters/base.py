"""LLM Adapter Base Interface & Exception Taxonomy."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

if TYPE_CHECKING:
    from ..registry import ModelSpec
from ..schemas import ChatMessage


# ---------------------------------------------------------------------------
# Typed Adapter Exception Hierarchy
# ---------------------------------------------------------------------------
class LLMAdapterError(RuntimeError):
    """Base exception for all provider adapter failures."""


class InvalidApiKeyError(LLMAdapterError):
    """HTTP 401 / 403: Provider API key missing, invalid, or unauthorized."""


class RateLimitError(LLMAdapterError):
    """HTTP 429: Provider quota or rate limit exceeded."""


class ProviderTimeoutError(LLMAdapterError):
    """HTTP 408 / 504 / Connection Timeout."""


class ProviderUnavailableError(LLMAdapterError):
    """HTTP 500 / 502 / 503 / DNS / Network failure."""


class ModelUnavailableError(LLMAdapterError):
    """HTTP 404: Requested model identifier not found or unsupported."""


class InvalidResponseError(LLMAdapterError):
    """Provider response body was corrupted or could not be parsed."""


# ---------------------------------------------------------------------------
# Data Transfer Objects
# ---------------------------------------------------------------------------
@dataclass
class LLMResult:
    """Standardized response from an LLM adapter completion call."""
    content: str = ""
    text: str = ""
    reasoning_content: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    reasoning_tokens: Optional[int] = None
    latency_ms: float = 0.0
    cost_usd: Optional[float] = None
    model_id: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None
    usage_source: str = "provider"  # "provider" | "unavailable" | "demo" | "estimated"
    ttft_ms: Optional[float] = None  # time to first token in milliseconds

    def __post_init__(self):
        if not self.content and self.text:
            self.content = self.text
        elif not self.text and self.content:
            self.text = self.content

        if not self.input_tokens and self.tokens_in:
            self.input_tokens = self.tokens_in
        elif not self.tokens_in and self.input_tokens:
            self.tokens_in = self.input_tokens

        if not self.output_tokens and self.tokens_out:
            self.output_tokens = self.tokens_out
        elif not self.tokens_out and self.output_tokens:
            self.tokens_out = self.output_tokens


@dataclass
class StreamChunk:
    """Standardized streaming chunk containing text deltas and metrics."""
    text: str = ""
    reasoning_text: str = ""
    is_final: bool = False
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: Optional[float] = None
    raw_chunk: Optional[Dict[str, Any]] = None
    usage_source: Optional[str] = None
    reasoning_tokens: Optional[int] = None
    ttft_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# Abstract Adapter Interface
# ---------------------------------------------------------------------------
class LLMAdapter(ABC):
    """Abstract base class for all provider-specific adapters."""
    provider: str = "base"

    @abstractmethod
    async def generate(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        json_mode: bool = False,
        **kwargs: Any,
    ) -> LLMResult:
        """Run the prompt/history through `model` and return LLMResult."""
        raise NotImplementedError

    async def complete(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> LLMResult:
        """Alias for generate with optional system prompt injection."""
        msgs = list(messages)
        if system_prompt and not any(m.role == "system" for m in msgs):
            msgs.insert(0, ChatMessage(role="system", content=system_prompt))
        return await self.generate(model, msgs, json_mode=json_mode, **kwargs)

    async def stream_chunks(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Yield structured StreamChunk objects (content and/or reasoning)."""
        res = await self.generate(model, messages, **kwargs)
        if res.reasoning_content:
            yield StreamChunk(reasoning_text=res.reasoning_content)
        if res.content:
            yield StreamChunk(text=res.content)
        yield StreamChunk(
            text="",
            is_final=True,
            tokens_in=res.input_tokens,
            tokens_out=res.output_tokens,
            latency_ms=res.latency_ms,
        )

    async def stream(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield raw response text chunks as they arrive."""
        async for chunk in self.stream_chunks(model, messages, **kwargs):
            if chunk.text:
                yield chunk.text

    def supports_streaming(self) -> bool:
        """Whether this adapter supports incremental streaming."""
        return False

    async def health_check(self, model: "ModelSpec") -> bool:
        """Test provider connectivity and credentials."""
        try:
            res = await self.generate(
                model,
                [ChatMessage(role="user", content="Ping")]
            )
            return bool(res.content or res.text)
        except Exception:
            return False


# Re-export factory symbols for backwards compatibility
from .factory import AdapterFactory, adapter_factory