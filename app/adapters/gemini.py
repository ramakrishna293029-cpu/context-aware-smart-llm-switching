"""Gemini adapter for Google Generative Language API (REST v1beta).

Uses official REST API: https://generativelanguage.googleapis.com/v1beta
Supports unary generateContent and streaming streamGenerateContent with metadata.
"""

import json
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


def _build_headers(model: "ModelSpec") -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
    }
    if model.api_key:
        headers["x-goog-api-key"] = model.api_key
    return headers


def _to_gemini_payload(
    messages: List[ChatMessage],
    max_tokens: Optional[int] = None,
    temperature: float = 0.7,
) -> tuple[dict, str]:
    """Convert ChatMessage list to Gemini contents payload and systemInstruction."""
    gemini_contents: List[Dict[str, Any]] = []
    system_instruction = ""
    for m in messages:
        if m.role == "system":
            if system_instruction:
                system_instruction += "\n\n" + m.content
            else:
                system_instruction = m.content
        else:
            role = "user" if m.role == "user" else "model"
            if gemini_contents and gemini_contents[-1]["role"] == role:
                gemini_contents[-1]["parts"].append({"text": m.content})
            else:
                gemini_contents.append({"role": role, "parts": [{"text": m.content}]})

    if not gemini_contents:
        gemini_contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

    payload: Dict[str, Any] = {
        "contents": gemini_contents,
        "generationConfig": {
            "maxOutputTokens": max_tokens or settings.default_max_output_tokens,
            "temperature": temperature,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    return payload, system_instruction


def _error_from_response(model: "ModelSpec", resp: httpx.Response) -> LLMAdapterError:
    body = ""
    try:
        data = resp.json()
        body = data.get("error", {}).get("message", "") or resp.text[:250]
    except Exception:
        body = resp.text[:250]
    error_cls = _STATUS_ERRORS.get(resp.status_code, ProviderUnavailableError)
    return error_cls(f"Gemini API ({model.endpoint_model}): HTTP {resp.status_code} - {body}")


class GeminiAdapter(LLMAdapter):
    """Adapter for Google Gemini models via Generative Language v1beta REST API."""
    provider = "gemini"

    def __init__(self):
        self._last_result: Optional[LLMResult] = None

    def last_result(self) -> Optional[LLMResult]:
        return self._last_result

    def supports_streaming(self) -> bool:
        return True

    async def _execute_generate(
        self,
        model: "ModelSpec",
        endpoint_model: str,
        messages: List[ChatMessage],
        **kwargs: Any,
    ) -> LLMResult:
        max_tokens = kwargs.get("max_tokens")
        payload, _ = _to_gemini_payload(messages, max_tokens=max_tokens)
        base = (model.base_url or "").rstrip("/") or "https://generativelanguage.googleapis.com/v1beta"
        url = f"{base}/models/{endpoint_model}:generateContent"
        if model.api_key:
            url += f"?key={model.api_key}"
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

            content_obj = candidates[0].get("content", {})
            parts = content_obj.get("parts", [])
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
            content=text,
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_in=input_tokens,
            tokens_out=output_tokens,
            latency_ms=latency_ms,
            model_id=model.model_id,
            raw_response=data,
            usage_source=usage_source,
            ttft_ms=latency_ms,
        )
        self._last_result = result
        return result

    async def generate(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        json_mode: bool = False,
        **kwargs: Any,
    ) -> LLMResult:
        try:
            return await self._execute_generate(model, model.endpoint_model, messages, **kwargs)
        except (ProviderUnavailableError, ModelUnavailableError):
            # If primary model is unavailable (e.g. 503 overloaded), attempt flash-lite fallback
            if model.endpoint_model != "gemini-2.5-flash-lite":
                return await self._execute_generate(model, "gemini-2.5-flash-lite", messages, **kwargs)
            raise

    async def stream_chunks(
        self,
        model: "ModelSpec",
        messages: List[ChatMessage],
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chunks via Gemini streamGenerateContent SSE endpoint."""
        max_tokens = kwargs.get("max_tokens")
        payload, _ = _to_gemini_payload(messages, max_tokens=max_tokens)
        endpoint = model.endpoint_model
        base = (model.base_url or "").rstrip("/") or "https://generativelanguage.googleapis.com/v1beta"
        url = f"{base}/models/{endpoint}:streamGenerateContent?alt=sse"
        if model.api_key:
            url += f"&key={model.api_key}"
        headers = _build_headers(model)

        t0 = time.perf_counter()
        ttft_ms: Optional[float] = None
        full_text_parts: List[str] = []
        usage: Dict[str, Any] = {}

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
                            content_obj = candidates[0].get("content", {})
                            parts = content_obj.get("parts", [])
                            for p in parts:
                                piece = p.get("text", "")
                                if piece:
                                    if ttft_ms is None:
                                        ttft_ms = (time.perf_counter() - t0) * 1000.0
                                    full_text_parts.append(piece)
                                    yield StreamChunk(text=piece, raw_chunk=chunk)

                        if "usageMetadata" in chunk and chunk["usageMetadata"]:
                            usage = chunk["usageMetadata"]

        except (httpx.HTTPError, ProviderUnavailableError, ProviderTimeoutError):
            # Fallback to non-streaming generate if stream fails midway
            res = await self.generate(model, messages, **kwargs)
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
        final_text = "".join(full_text_parts)
        input_tokens = usage.get("promptTokenCount", 0) or max(1, sum(len(m.content) for m in messages) // 4)
        output_tokens = usage.get("candidatesTokenCount", 0) or max(1, len(final_text) // 4)

        result = LLMResult(
            content=final_text,
            text=final_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tokens_in=input_tokens,
            tokens_out=output_tokens,
            latency_ms=total_latency_ms,
            model_id=model.model_id,
            usage_source="provider" if usage.get("promptTokenCount") else "estimated",
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
        """Stream plain text deltas."""
        async for chunk in self.stream_chunks(model, messages, **kwargs):
            if chunk.text:
                yield chunk.text