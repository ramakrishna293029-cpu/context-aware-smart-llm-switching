"""OpenAI-compatible adapter (OpenAI, Azure, OpenRouter, Groq, Ollama...).

Speaks the standard /chat/completions protocol over HTTP so any
compatible endpoint works without code changes.
"""

from typing import List

import httpx

from ..config import settings
from ..registry import ModelSpec
from ..schemas import ChatMessage
from .base import LLMAdapter, LLMAdapterError, LLMResult


class OpenAICompatibleAdapter(LLMAdapter):
    provider = "openai"

    async def generate(self, model: ModelSpec, messages: List[ChatMessage]) -> LLMResult:
        url = f"{model.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {model.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model.endpoint_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": 2048,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise LLMAdapterError(f"Provider request failed: {exc}") from exc

        try:
            text = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens") or 0
            output_tokens = usage.get("completion_tokens") or 0
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMAdapterError(f"Unexpected provider response: {data}") from exc

        return LLMResult(text=text, input_tokens=input_tokens, output_tokens=output_tokens)