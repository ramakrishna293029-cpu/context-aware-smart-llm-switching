"""Gemini adapter for Google Generative Language API (native v1beta).

Uses the official REST API: https://generativelanguage.googleapis.com/v1beta
Supports generateContent and streamGenerateContent with precise token metadata.
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
    return {
        "x-goog-api-key": model.api_key,
        "Content-Type": "application/json",
    }


def _to_gemini_payload(messages: List[ChatMessage]) -> tuple[dict, str]:
    """Convert ChatMessage list to Gemini contents payload and systemInstruction."""
    gemini_contents = []
    system_instruction = ""
    for m in messages:
        if m.role == "system":
            system_instruction = m.content
        else:
            role = "user" if m.role == "user" else "model"
            gemini_contents.append({"role": role, "parts": [{"text": m.content}]})

    if not gemini_contents:
        gemini_contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

    payload = {
        "contents": gemini_contents,
        "generationConfig": {
            "maxOutputTokens": settings.default_max_output_tokens,
            "temperature": 0.7,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    return payload, system_instruction


def _error_from_response(model: ModelSpec, resp: httpx.Response) -> LLMAdapterError:
    body = ""
    try:
        data = resp.json()
        body = data.get("error", {}).get("message", "") or resp.text[:200]
    except Exception:
        body = resp.text[:200]
    error_cls = _STATUS_ERRORS.get(resp.status_code, ProviderUnavailableError)
    return error_cls(f"Gemini API ({model.endpoint_model}): HTTP {resp.status_code} - {body}")


class GeminiAdapter(LLMAdapter):
    provider = "gemini"

    def __init__(self):
        self._last_result: LLMResult | None = None

    def last_result(self) -> LLMResult | None:
        return self._last_result

    async def _execute_generate(self, model: ModelSpec, endpoint_model: str, messages: List[ChatMessage]) -> LLMResult:
        payload, _ = _to_gemini_payload(messages)
        url = f"{model.base_url}/models/{endpoint_model}:generateContent?key={model.api_key}"
        headers = _build_headers(model)

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Gemini timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(f"Gemini unreachable: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"Gemini request failed: {exc}") from exc

        latency_ms = (time.perf_counter() - t0) * 1000.0

        if resp.status_code != 200:
            raise _error_from_response(model, resp)

        try:
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise InvalidResponseError("No candidates in Gemini response")

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()

            usage = data.get("usageMetadata", {})
            input_tokens = usage.get("promptTokenCount", 0)
            output_tokens = usage.get("candidatesTokenCount", 0)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise InvalidResponseError(
                f"Gemini returned unparseable JSON: {resp.text[:200]}"
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

    async def generate(self, model: ModelSpec, messages: List[ChatMessage]) -> LLMResult:
        try:
            return await self._execute_generate(model, model.endpoint_model, messages)
        except (ProviderUnavailableError, ModelUnavailableError):
            # If primary model is unavailable or overloaded (503), try fallback model
            if model.endpoint_model != "gemini-2.5-flash-lite":
                return await self._execute_generate(model, "gemini-2.5-flash-lite", messages)
            raise

    async def stream(self, model: ModelSpec, messages: List[ChatMessage]) -> AsyncIterator[str]:
        """Stream chunks via Gemini streamGenerateContent SSE endpoint."""
        payload, _ = _to_gemini_payload(messages)
        endpoint = model.endpoint_model
        url = f"{model.base_url}/models/{endpoint}:streamGenerateContent?alt=sse&key={model.api_key}"
        headers = _build_headers(model)

        t0 = time.perf_counter()
        ttft_ms: float | None = None
        full_text_parts: list[str] = []
        usage = {}

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
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        candidates = chunk.get("candidates", [])
                        if candidates:
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            for p in parts:
                                piece = p.get("text", "")
                                if piece:
                                    if ttft_ms is None:
                                        ttft_ms = (time.perf_counter() - t0) * 1000.0
                                    full_text_parts.append(piece)
                                    yield piece

                        usage = chunk.get("usageMetadata", usage)
        except (httpx.HTTPError, ProviderUnavailableError) as exc:
            # Fallback to non-streaming generate if stream fails
            gen_res = await self.generate(model, messages)
            yield gen_res.text
            return

        text = "".join(full_text_parts)
        input_tokens = usage.get("promptTokenCount", 0)
        output_tokens = usage.get("candidatesTokenCount", 0)
        usage_source = "provider" if (input_tokens or output_tokens) else "unavailable"
        result = LLMResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage_source=usage_source,
            ttft_ms=ttft_ms,
        )
        self._last_result = result

    def supports_streaming(self) -> bool:
        return True