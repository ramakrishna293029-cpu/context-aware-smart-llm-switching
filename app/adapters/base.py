"""LLM adapter contract. The router never talks to providers directly."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

from ..registry import ModelSpec
from ..schemas import ChatMessage


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int


class LLMAdapterError(RuntimeError):
    pass


class LLMAdapter(ABC):
    provider: str = "base"

    @abstractmethod
    async def generate(self, model: ModelSpec, messages: List[ChatMessage]) -> LLMResult:
        """Run the conversation through `model` and return the result."""
        raise NotImplementedError


class AdapterFactory:
    """Registers and hands out adapters by provider name."""

    def __init__(self):
        self._adapters = {}

    def register(self, adapter: LLMAdapter):
        self._adapters[adapter.provider] = adapter

    def get(self, provider: str) -> LLMAdapter:
        if provider not in self._adapters:
            raise LLMAdapterError(f"No adapter registered for provider '{provider}'")
        return self._adapters[provider]

    def providers(self) -> List[str]:
        return list(self._adapters.keys())


adapter_factory = AdapterFactory()