"""OpenAI-compatible adapter (OpenRouter, Groq, OpenAI, Ollama, etc.).

Speaks the standard /chat/completions protocol over HTTP.
Supports one-shot generate() and token stream() with precise token and TTFT metrics.
"""

import json
import time
from typing import AsyncIterator, List

import httpx

from ..config import settings
from ..registry import ModelSpec
from ..schemas import ChatMessage
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
)

_STATUS_ERRORS = {
    400: InvalidResponseError,
    401: InvalidApiKeyError,
    403: InvalidApiKeyError,
    404: ModelUnavailableError,
    408: ProviderTimeoutError,
    429: RateLimitError,
}


def _build_headers(model: ModelSpec) -> dict:
    headers = {
        "Authorization": f"Bearer {model.api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter" in model.base_url:
        headers["HTTP-Referer"] = "http://localhost:8000"
        headers["X-Title"] = "Context-Aware Smart LLM Switching"
    return headers


def _payload(model: ModelSpec, messages: List[ChatMessage], stream: bool = False, json_mode: bool = False) -> dict:
    body = {
        "model": model.endpoint_model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "max_tokens": settings.default_max_output_tokens,
        "stream": stream,
        "temperature": 0.2 if json_mode else 0.7,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def _error_from_response(model: ModelSpec, resp: httpx.Response) -> LLMAdapterError:
    body = ""
    try:
        data = resp.json()
        body = data.get("error", {}).get("message", "") or resp.text[:200]
    except Exception:
        body = resp.text[:200]
    error_cls = _STATUS_ERRORS.get(resp.status_code, ProviderUnavailableError)
    return error_cls(f"Provider '{model.provider}' ({model.endpoint_model}): HTTP {resp.status_code} - {body}")


class OpenAICompatibleAdapter(LLMAdapter):
    provider = "openai"

    def __init__(self):
        self._last_result: LLMResult | None = None

    def last_result(self) -> LLMResult | None:
        """Usage from the most recent call."""
        return self._last_result

    async def generate(self, model: ModelSpec, messages: List[ChatMessage], json_mode: bool = False) -> LLMResult:
        url = f"{model.base_url}/chat/completions"
        headers = _build_headers(model)
        t0 = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=_payload(model, messages, stream=False, json_mode=json_mode))
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Provider '{model.provider}' timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(f"Provider '{model.provider}' unreachable: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Provider request failed: {exc}") from exc

        latency_ms = (time.perf_counter() - t0) * 1000.0

        if resp.status_code != 200:
            raise _error_from_response(model, resp)

        try:
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise InvalidResponseError("No choices in response")
            text = choices[0].get("message", {}).get("content", "").strip()
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens") or 0
            output_tokens = usage.get("completion_tokens") or 0
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise InvalidResponseError(
                f"Provider '{model.provider}' returned an unparseable response: {resp.text[:200]}"
            ) from exc

        usage_source = "provider" if (input_tokens or output_tokens) else "unavailable"
        result = LLMResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage_source=usage_source,
            ttft_ms=latency_ms,
        )
        self._last_result = result
        return result

    async def stream(self, model: ModelSpec, messages: List[ChatMessage]) -> AsyncIterator[str]:
        """Stream tokens via SSE, capturing usage from the final chunk."""
        url = f"{model.base_url}/chat/completions"
        headers = _build_headers(model)
        full_text_parts: list[str] = []
        usage: dict = {}
        t0 = time.perf_counter()
        ttft_ms: float | None = None

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers,
                                         json=_payload(model, messages, stream=True)) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        raise _error_from_response(model, resp)

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[len("data:"):].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            piece = delta.get("content")
                            if piece:
                                if ttft_ms is None:
                                    ttft_ms = (time.perf_counter() - t0) * 1000.0
                                full_text_parts.append(piece)
                                yield piece

                        if "usage" in chunk and chunk["usage"]:
                            usage = chunk["usage"]
        except (httpx.HTTPError, ProviderUnavailableError) as exc:
            # Fallback to non-streaming generate if stream fails
            gen_res = await self.generate(model, messages)
            yield gen_res.text
            return

        text = "".join(full_text_parts)
        input_tokens = usage.get("prompt_tokens") or max(1, sum(len(m.content) for m in messages) // 4)
        output_tokens = usage.get("completion_tokens") or max(1, len(text) // 4)
        usage_source = "provider" if usage.get("prompt_tokens") else "estimated"
        result = LLMResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage_source=usage_source,
            ttft_ms=ttft_ms or (time.perf_counter() - t0) * 1000.0,
        )
        self._last_result = result

    def supports_streaming(self) -> bool:
        return True