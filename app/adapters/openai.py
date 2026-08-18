"""OpenAI-compatible adapter (OpenRouter, Groq, OpenAI, Ollama, vLLM, Azure).

Speaks standard /chat/completions protocol over HTTP.
Supports unary generate() and streaming stream_chunks() / stream()
with reasoning token extraction and comprehensive error taxonomy.
"""

import json
import re
import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional

import httpx

from ..config import settings
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
    StreamChunk,
)

if TYPE_CHECKING:
    from ..registry import ModelSpec

_STATUS_ERRORS = {
    400: InvalidResponseError,
    401: InvalidApiKeyError,
    403: InvalidApiKeyError,
    404: ModelUnavailableError,
    408: ProviderTimeoutError,
    429: RateLimitError,
}

THINK_REGEX = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _build_url(model: "ModelSpec") -> str:
    base = (model.base_url or "").rstrip("/")
    if not base:
        base = "https://api.openai.com/v1"
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _build_headers(model: "ModelSpec") -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }
    if model.api_key:
        headers["Authorization"] = f"Bearer {model.api_key}"

    if "openrouter" in (model.base_url or "").lower() or model.provider == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:8000"
        headers["X-Title"] = "Context-Aware Smart LLM Switching"

    return headers


def _payload(
    model: "ModelSpec",
    messages: List[ChatMessage],
    stream: bool = False,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,
) -> dict:
    body: Dict[str, Any] = {
        "model": model.endpoint_model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "max_tokens": max_tokens or settings.default_max_output_tokens,
        "stream": stream,
        "temperature": 0.2 if json_mode else 0.7,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def _error_from_response(model: "ModelSpec", resp: httpx.Response) -> LLMAdapterError:
    body = ""
    try:
        data = resp.json()
        body = data.get("error", {}).get("message", "") or resp.text[:250]
    except Exception:
        body = resp.text[:250]

    error_cls = _STATUS_ERRORS.get(resp.status_code, ProviderUnavailableError)
    return error_cls(f"Provider '{model.provider}' ({model.endpoint_model}): HTTP {resp.status_code} - {body}")


def _extract_reasoning_and_content(raw_text: str) -> tuple[str, Optional[str]]:
    """Extract reasoning text if embedded in <think>...</think> tags."""
    if not raw_text:
        return "", None

    match = THINK_REGEX.search(raw_text)
    if match:
        reasoning = match.group(1).strip()
        cleaned_content = THINK_REGEX.sub("", raw_text).strip()
        return cleaned_content, reasoning
    return raw_text, None


class OpenAICompatibleAdapter(LLMAdapter):
    """Unified adapter for all OpenAI-compatible /chat/completions APIs."""
    provider = "openai"

    def __init__(self, provider_name: str = "openai"):
        self.provider = provider_name
        self._last_result: Optional[LLMResult] = None

    def last_result(self) -> Optional[LLMResult]:
        """Usage from the most recent call."""
        return self._last_result

    def supports_streaming(self) -> bool:
        return True

    async def generate(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        json_mode: bool = False,
        **kwargs: Any,
    ) -> LLMResult:
        url = _build_url(model)
        headers = _build_headers(model)
        max_tokens = kwargs.get("max_tokens")
        payload = _payload(model, messages, stream=False, json_mode=json_mode, max_tokens=max_tokens)
        t0 = time.perf_counter()

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
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
                raise InvalidResponseError(f"No choices in response from {model.provider}")

            msg = choices[0].get("message", {})
            raw_text = msg.get("content", "") or ""
            reasoning_field = msg.get("reasoning_content") or msg.get("reasoning")

            content, reasoning_from_tag = _extract_reasoning_and_content(raw_text)
            reasoning_content = reasoning_field or reasoning_from_tag

            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens") or 0
            output_tokens = usage.get("completion_tokens") or 0
            reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise InvalidResponseError(
                f"Provider '{model.provider}' returned unparseable response: {resp.text[:200]}"
            ) from exc

        usage_source = "provider" if (input_tokens or output_tokens) else "unavailable"
        result = LLMResult(
            content=content,
            text=content,
            reasoning_content=reasoning_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_in=input_tokens,
            tokens_out=output_tokens,
            reasoning_tokens=reasoning_tokens,
            latency_ms=latency_ms,
            model_id=model.model_id,
            raw_response=data,
            usage_source=usage_source,
            ttft_ms=latency_ms,
        )
        self._last_result = result
        return result

    async def stream_chunks(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream structured StreamChunk deltas capturing reasoning vs content."""
        url = _build_url(model)
        headers = _build_headers(model)
        max_tokens = kwargs.get("max_tokens")
        payload = _payload(model, messages, stream=True, max_tokens=max_tokens)

        t0 = time.perf_counter()
        ttft_ms: Optional[float] = None
        full_content_parts: List[str] = []
        full_reasoning_parts: List[str] = []
        usage: Dict[str, Any] = {}

        in_think_block = False

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        raise _error_from_response(model, resp)

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
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

                            # 1. Native reasoning_content field (Groq / DeepSeek / OpenAI)
                            reasoning_delta = delta.get("reasoning_content") or delta.get("reasoning")
                            if reasoning_delta:
                                if ttft_ms is None:
                                    ttft_ms = (time.perf_counter() - t0) * 1000.0
                                full_reasoning_parts.append(reasoning_delta)
                                yield StreamChunk(reasoning_text=reasoning_delta, raw_chunk=chunk)

                            # 2. Regular content delta
                            content_delta = delta.get("content")
                            if content_delta:
                                if ttft_ms is None:
                                    ttft_ms = (time.perf_counter() - t0) * 1000.0

                                # Handle inline <think> tags if model embeds them in content
                                if "<think>" in content_delta:
                                    in_think_block = True
                                    parts = content_delta.split("<think>", 1)
                                    if parts[0]:
                                        full_content_parts.append(parts[0])
                                        yield StreamChunk(text=parts[0], raw_chunk=chunk)
                                    content_delta = parts[1]

                                if in_think_block:
                                    if "</think>" in content_delta:
                                        think_parts = content_delta.split("</think>", 1)
                                        full_reasoning_parts.append(think_parts[0])
                                        yield StreamChunk(reasoning_text=think_parts[0], raw_chunk=chunk)
                                        in_think_block = False
                                        if think_parts[1]:
                                            full_content_parts.append(think_parts[1])
                                            yield StreamChunk(text=think_parts[1], raw_chunk=chunk)
                                    else:
                                        full_reasoning_parts.append(content_delta)
                                        yield StreamChunk(reasoning_text=content_delta, raw_chunk=chunk)
                                else:
                                    full_content_parts.append(content_delta)
                                    yield StreamChunk(text=content_delta, raw_chunk=chunk)

                        if "usage" in chunk and chunk["usage"]:
                            usage = chunk["usage"]

        except (httpx.HTTPError, ProviderUnavailableError, ProviderTimeoutError):
            # Fallback to non-streaming generate if stream connection fails midway
            res = await self.generate(model, messages, **kwargs)
            if res.reasoning_content:
                yield StreamChunk(reasoning_text=res.reasoning_content)
            if res.content:
                yield StreamChunk(text=res.content)
            yield StreamChunk(
                is_final=True,
                tokens_in=res.input_tokens,
                tokens_out=res.output_tokens,
                latency_ms=res.latency_ms,
            )
            return

        total_latency_ms = (time.perf_counter() - t0) * 1000.0
        final_text = "".join(full_content_parts)
        final_reasoning = "".join(full_reasoning_parts) if full_reasoning_parts else None

        input_tokens = usage.get("prompt_tokens") or max(1, sum(len(m.content) for m in messages) // 4)
        output_tokens = usage.get("completion_tokens") or max(1, (len(final_text) + (len(final_reasoning or ""))) // 4)
        reasoning_tokens = usage.get("completion_tokens_details", {}).get("reasoning_tokens")

        result = LLMResult(
            content=final_text,
            text=final_text,
            reasoning_content=final_reasoning,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_in=input_tokens,
            tokens_out=output_tokens,
            reasoning_tokens=reasoning_tokens,
            latency_ms=total_latency_ms,
            model_id=model.model_id,
            usage_source="provider" if usage.get("prompt_tokens") else "estimated",
            ttft_ms=ttft_ms or total_latency_ms,
        )
        self._last_result = result

        yield StreamChunk(
            text="",
            is_final=True,
            tokens_in=input_tokens,
            tokens_out=output_tokens,
            latency_ms=total_latency_ms,
        )

    async def stream(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream plain text deltas for backwards compatibility."""
        async for chunk in self.stream_chunks(model, messages, **kwargs):
            if chunk.text:
                yield chunk.text