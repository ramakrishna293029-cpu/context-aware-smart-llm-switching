"""Shared chat pipeline: analyze → route → execute → persist.

Unary `/api/chat` and SSE `/api/chat/stream` both call these helpers so
token honesty, budgets, fallback, and telemetry stay in one place.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException

from .adapters.base import LLMAdapterError, LLMResult, StreamChunk, adapter_factory
from .analyzer_llm import AnalyzerDecision, run_analyzer
from .circuit import circuits
from .config import settings
from .context import build_messages
from .registry import ModelRegistry, ModelSpec
from .router import STRATEGIES, RoutingResult, router as default_router
from .schemas import ChatMessage, ChatResponse, ModelInfo
from .tracker import estimate_cost_usd, tracker

_COMPLETION_CACHE: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_COMPLETION_CACHE_MAX = 64
_COMPLETION_CACHE_TTL = 300.0


def clear_completion_cache() -> None:
    _COMPLETION_CACHE.clear()


def check_spend_budgets() -> None:
    status = tracker.budget_status()
    daily = getattr(settings, "daily_budget_usd", 0.0) or 0.0
    monthly = getattr(settings, "monthly_budget_usd", 0.0) or 0.0
    if daily > 0 and (status.get("day_spend") or 0) >= daily:
        raise HTTPException(status_code=429, detail="Daily budget exceeded. Request rejected.")
    if monthly > 0 and (status.get("month_spend") or 0) >= monthly:
        raise HTTPException(status_code=429, detail="Monthly budget exceeded. Request rejected.")


def compute_cost(model: ModelSpec, result: Optional[LLMResult]) -> Optional[float]:
    if not result:
        return None
    if result.usage_source in ("unavailable", "estimated", "cache"):
        return None
    if result.input_tokens is None or result.output_tokens is None:
        return None
    return estimate_cost_usd(
        (model.input_price_per_mtok, model.output_price_per_mtok),
        result.input_tokens,
        result.output_tokens,
    )


def compute_baseline_cost(
    reg: ModelRegistry,
    tokens: Optional[Tuple[Optional[int], Optional[int]]],
) -> Optional[float]:
    if not tokens or tokens[0] is None or tokens[1] is None:
        return None
    strongest = reg.strongest()
    if not strongest:
        return None
    return estimate_cost_usd(
        (strongest.input_price_per_mtok, strongest.output_price_per_mtok),
        tokens[0],
        tokens[1],
    )


def expected_request_cost(model: ModelSpec, analyzer_input_tokens: Optional[int]) -> float:
    """Projected USD for a switch call, using measured analyzer input size."""
    in_tok = analyzer_input_tokens if analyzer_input_tokens is not None else 800
    out_tok = min(512, getattr(settings, "default_max_output_tokens", 512))
    return (
        in_tok * model.input_price_per_mtok + out_tok * model.output_price_per_mtok
    ) / 1_000_000


def apply_cost_cap(chain: List[ModelSpec], analyzer_input_tokens: Optional[int]) -> List[ModelSpec]:
    cap = getattr(settings, "max_cost_per_request", 0.0) or 0.0
    if cap <= 0:
        return chain
    filtered = [m for m in chain if expected_request_cost(m, analyzer_input_tokens) <= cap]
    if not filtered:
        raise HTTPException(
            status_code=429,
            detail="Cost per request budget exceeded. No candidate fits cap.",
        )
    return filtered


def route_decision(
    decision: AnalyzerDecision,
    strategy: str,
    reg: ModelRegistry,
) -> RoutingResult:
    return default_router.resolve(
        decision,
        strategy=strategy,
        registry=reg,
        latency_profile=tracker.get_latency_profile(),
        feedback_modifiers=tracker.get_feedback_modifiers(),
    )


async def execute_with_fallback(
    messages: List[ChatMessage],
    chain: List[ModelSpec],
) -> Tuple[ModelSpec, LLMResult, bool, Optional[str]]:
    if not chain:
        raise LLMAdapterError("No candidate models available in fallback chain.")

    primary = chain[0]
    errors: List[str] = []

    for model in chain:
        if not circuits.allow(model.model_id):
            errors.append(f"{model.model_id}: circuit open")
            continue
        try:
            adapter = adapter_factory.get(model.provider)
            result = await adapter.generate(model, messages)
            circuits.success(model.model_id)
            fallback_used = model.model_id != primary.model_id
            err_msg = " | ".join(errors) if errors else None
            return model, result, fallback_used, err_msg
        except LLMAdapterError as exc:
            circuits.failure(model.model_id)
            errors.append(f"{model.model_id}: {exc}")

    raise LLMAdapterError("All candidate models failed in fallback chain: " + " | ".join(errors))


async def stream_with_fallback(
    messages: List[ChatMessage],
    chain: List[ModelSpec],
    disconnected: Optional[Callable[[], Any]] = None,
) -> AsyncIterator[Tuple[str, Any]]:
    """Yields ('chunk', StreamChunk) then ('complete', (model, result, fallback, reason))."""
    if not chain:
        raise LLMAdapterError("No candidate models available in fallback chain.")

    primary = chain[0]
    errors: List[str] = []

    for cand in chain:
        if not circuits.allow(cand.model_id):
            errors.append(f"{cand.model_id}: circuit open")
            continue
        adapter = adapter_factory.get(cand.provider)
        full_text: List[str] = []
        full_reasoning: List[str] = []
        result: Optional[LLMResult] = None
        try:
            if adapter.supports_streaming():
                async for chunk in adapter.stream_chunks(cand, messages):
                    if disconnected is not None and await disconnected():
                        return
                    if chunk.is_final:
                        usage_src = chunk.usage_source or "unavailable"
                        in_tok = chunk.tokens_in
                        out_tok = chunk.tokens_out
                        if usage_src in ("unavailable", "estimated"):
                            in_tok = None if usage_src == "unavailable" else in_tok
                            out_tok = None if usage_src == "unavailable" else out_tok
                        result = LLMResult(
                            content="".join(full_text),
                            text="".join(full_text),
                            reasoning_content="".join(full_reasoning) or None,
                            input_tokens=in_tok or 0,
                            output_tokens=out_tok or 0,
                            tokens_in=in_tok or 0,
                            tokens_out=out_tok or 0,
                            reasoning_tokens=chunk.reasoning_tokens,
                            latency_ms=chunk.latency_ms or 0.0,
                            usage_source=usage_src,
                            ttft_ms=chunk.ttft_ms,
                            model_id=cand.model_id,
                        )
                        if usage_src == "unavailable":
                            result.input_tokens = 0
                            result.output_tokens = 0
                        continue
                    if chunk.reasoning_text:
                        full_reasoning.append(chunk.reasoning_text)
                    if chunk.text:
                        full_text.append(chunk.text)
                    yield ("chunk", chunk)
            else:
                result = await adapter.generate(cand, messages)
                if result.reasoning_content:
                    yield ("chunk", StreamChunk(reasoning_text=result.reasoning_content))
                if result.content:
                    yield ("chunk", StreamChunk(text=result.content))

            if result is None:
                result = LLMResult(
                    content="".join(full_text),
                    text="".join(full_text),
                    usage_source="unavailable",
                )
            circuits.success(cand.model_id)
            fallback_used = cand.model_id != primary.model_id
            err_msg = " | ".join(errors) if errors else None
            yield ("complete", (cand, result, fallback_used, err_msg))
            return
        except Exception as exc:
            circuits.failure(cand.model_id)
            errors.append(f"{cand.model_id}: {exc}")
            continue

    raise LLMAdapterError("All candidate models failed in fallback chain: " + " | ".join(errors))


def _completion_key(query: str, history: List[ChatMessage], strategy: str, model_ids: str) -> str:
    h = hashlib.sha1()
    h.update(query.strip().encode("utf-8"))
    h.update(b"\x00")
    h.update("\n".join(m.content for m in history[-10:]).encode("utf-8"))
    h.update(f"\x00{strategy}\x00{model_ids}".encode("utf-8"))
    return h.hexdigest()


def completion_cache_get(key: str) -> Optional[dict]:
    entry = _COMPLETION_CACHE.get(key)
    if not entry:
        return None
    ts, payload = entry
    if time.monotonic() - ts > _COMPLETION_CACHE_TTL:
        _COMPLETION_CACHE.pop(key, None)
        return None
    _COMPLETION_CACHE.move_to_end(key)
    return payload


def completion_cache_put(key: str, payload: dict) -> None:
    _COMPLETION_CACHE[key] = (time.monotonic(), payload)
    _COMPLETION_CACHE.move_to_end(key)
    while len(_COMPLETION_CACHE) > _COMPLETION_CACHE_MAX:
        _COMPLETION_CACHE.popitem(last=False)


@dataclass
class ChatOutcome:
    decision: AnalyzerDecision
    routing: Optional[RoutingResult]
    served_model: ModelSpec
    result: Optional[LLMResult]
    answer_mode: str
    response_text: str
    analyzer_lat: float
    gen_lat: float
    total_lat: float
    ttft_ms: Optional[float]
    fallback_used: bool
    fallback_reason: Optional[str]
    success: bool
    error_text: Optional[str]
    analyzer_cost: float
    model_cost: Optional[float]
    total_cost: float
    baseline_cost: Optional[float]
    savings_usd: float
    savings_pct: float
    in_tok: Optional[int]
    out_tok: Optional[int]
    reasoning_toks: Optional[int]
    tot_tok: Optional[int]
    cached: bool = False
    request_id: Optional[int] = None
    strategy: str = "balanced"
    extra: Dict[str, Any] = field(default_factory=dict)


def _assemble_costs(
    *,
    answer_mode: str,
    decision: AnalyzerDecision,
    served: ModelSpec,
    result: Optional[LLMResult],
    analyzer_cost: float,
    reg: ModelRegistry,
) -> Tuple[Optional[float], float, Optional[float], float, float, Optional[int], Optional[int], Optional[int], Optional[int]]:
    if answer_mode == "self":
        in_tok = decision.analyzer_result.input_tokens
        out_tok = decision.analyzer_result.output_tokens
        tot_tok = (in_tok or 0) + (out_tok or 0)
        baseline = compute_baseline_cost(reg, (in_tok, out_tok))
        total = analyzer_cost
        savings = max(0.0, baseline - total) if baseline else 0.0
        pct = (savings / baseline * 100.0) if baseline else 0.0
        return None, total, baseline, savings, pct, None, None, 0, tot_tok

    in_tok = result.input_tokens if result else None
    out_tok = result.output_tokens if result else None
    reasoning_toks = result.reasoning_tokens if result else 0
    if result and result.usage_source in ("unavailable", "estimated"):
        in_tok = None
        out_tok = None
        model_cost = None
    elif result and result.usage_source == "cache":
        model_cost = 0.0
    else:
        model_cost = compute_cost(served, result) if result else None

    a_in = decision.analyzer_result.input_tokens or 0
    a_out = decision.analyzer_result.output_tokens or 0
    tot_tok = ((in_tok or 0) + (out_tok or 0) + a_in + a_out) if result else None
    total = ((model_cost or 0.0) + analyzer_cost) if result else 0.0
    baseline = compute_baseline_cost(reg, (in_tok, out_tok)) if result and in_tok is not None else None
    savings = max(0.0, (baseline or 0.0) - total) if baseline else 0.0
    pct = (savings / baseline * 100.0) if baseline else 0.0
    return model_cost, total, baseline, savings, pct, in_tok, out_tok, reasoning_toks, tot_tok


def persist_outcome(query: str, outcome: ChatOutcome) -> int:
    d = outcome.decision
    served = outcome.served_model
    routing = outcome.routing
    req_id = tracker.record_request(
        query=query,
        task_type=d.task_type,
        complexity=d.complexity,
        complexity_score=d.complexity_score,
        answer_mode=outcome.answer_mode,
        analyzer_provider=d.analyzer_model.provider,
        analyzer_model=d.analyzer_model.endpoint_model,
        analyzer_latency_ms=outcome.analyzer_lat,
        analyzer_input_tokens=d.analyzer_result.input_tokens,
        analyzer_output_tokens=d.analyzer_result.output_tokens,
        analyzer_cost=outcome.analyzer_cost,
        target_tier=d.target_tier if outcome.answer_mode == "switch" else "fast",
        target_provider=d.target_provider or served.provider,
        selected_model=served.endpoint_model,
        selected_provider=served.provider,
        routing_reason=d.reason,
        context_relevant=d.context_required,
        input_tokens=outcome.in_tok,
        output_tokens=outcome.out_tok,
        reasoning_tokens=outcome.reasoning_toks or 0,
        total_tokens=outcome.tot_tok,
        latency_ms=outcome.gen_lat,
        total_latency_ms=outcome.total_lat,
        ttft_ms=outcome.ttft_ms,
        estimated_cost=outcome.model_cost if outcome.answer_mode == "switch" else outcome.analyzer_cost,
        analyzer_cost_usd=outcome.analyzer_cost,
        total_cost_usd=outcome.total_cost,
        baseline_cost=outcome.baseline_cost,
        savings_usd=outcome.savings_usd,
        savings_percent=outcome.savings_pct,
        success=outcome.success,
        error=outcome.error_text,
        fallback_used=outcome.fallback_used,
        fallback_reason=outcome.fallback_reason,
        strategy=outcome.strategy,
        candidates_json=json.dumps(routing.candidates()) if routing else None,
    )
    outcome.request_id = req_id
    return req_id


def to_chat_response(outcome: ChatOutcome) -> ChatResponse:
    served = outcome.served_model
    d = outcome.decision
    routing = outcome.routing
    return ChatResponse(
        response=outcome.response_text,
        answer_mode=outcome.answer_mode,  # type: ignore[arg-type]
        model=ModelInfo(
            model_id=served.model_id,
            model_name=served.name,
            provider=served.provider,
            tier=served.tier,
            mode=served.mode,
            strategy=outcome.strategy,
            reason=d.reason,
        ),
        analyzer=d.to_analyzer_info(cost_usd=outcome.analyzer_cost),
        context_relevant=d.context_required,
        input_tokens=outcome.in_tok,
        output_tokens=outcome.out_tok,
        reasoning_tokens=outcome.reasoning_toks or 0,
        total_tokens=outcome.tot_tok,
        estimated_cost_usd=round(outcome.model_cost, 6) if outcome.model_cost is not None else (
            round(outcome.analyzer_cost, 6) if outcome.answer_mode == "self" else None
        ),
        analyzer_cost_usd=round(outcome.analyzer_cost, 6),
        total_cost_usd=round(outcome.total_cost, 6),
        baseline_cost_usd=round(outcome.baseline_cost, 6) if outcome.baseline_cost is not None else None,
        savings_usd=round(outcome.savings_usd, 6),
        savings_percent=round(outcome.savings_pct, 1),
        latency_ms=round(outcome.gen_lat, 1),
        analyzer_latency_ms=round(outcome.analyzer_lat, 1),
        total_latency_ms=round(outcome.total_lat, 1),
        ttft_ms=round(outcome.ttft_ms, 1) if outcome.ttft_ms else None,
        success=outcome.success,
        request_id=outcome.request_id or 0,
        fallback_used=outcome.fallback_used,
        fallback_reason=outcome.fallback_reason,
        candidates=routing.to_candidate_infos() if routing else [],
    )


def done_event_payload(outcome: ChatOutcome) -> dict:
    served = outcome.served_model
    d = outcome.decision
    routing = outcome.routing
    return {
        "event": "done",
        "success": outcome.success,
        "request_id": outcome.request_id,
        "response": outcome.response_text,
        "answer_mode": outcome.answer_mode,
        "model": {
            "model_id": served.model_id,
            "model_name": served.name,
            "provider": served.provider,
            "tier": served.tier,
            "reason": d.reason,
        },
        "analyzer": d.to_analyzer_info(cost_usd=outcome.analyzer_cost).model_dump(),
        "context_relevant": d.context_required,
        "input_tokens": outcome.in_tok,
        "output_tokens": outcome.out_tok,
        "reasoning_tokens": outcome.reasoning_toks or 0,
        "total_tokens": outcome.tot_tok,
        "estimated_cost_usd": round(outcome.model_cost, 6) if outcome.model_cost is not None else (
            round(outcome.analyzer_cost, 6) if outcome.answer_mode == "self" else None
        ),
        "analyzer_cost_usd": round(outcome.analyzer_cost, 6),
        "total_cost_usd": round(outcome.total_cost, 6),
        "baseline_cost_usd": round(outcome.baseline_cost, 6) if outcome.baseline_cost is not None else None,
        "savings_usd": round(outcome.savings_usd, 6),
        "savings_percent": round(outcome.savings_pct, 1),
        "latency_ms": round(outcome.gen_lat, 1),
        "analyzer_latency_ms": round(outcome.analyzer_lat, 1),
        "total_latency_ms": round(outcome.total_lat, 1),
        "ttft_ms": round(outcome.ttft_ms, 1) if outcome.ttft_ms else None,
        "fallback_used": outcome.fallback_used,
        "candidates": routing.candidates() if routing else [],
    }


def build_self_outcome(
    *,
    decision: AnalyzerDecision,
    analyzer_lat: float,
    t_start: float,
    analyzer_cost: float,
    reg: ModelRegistry,
    strategy: str,
) -> ChatOutcome:
    served = decision.analyzer_model
    total_lat = (time.perf_counter() - t_start) * 1000.0
    model_cost, total, baseline, savings, pct, in_tok, out_tok, reasoning, tot = _assemble_costs(
        answer_mode="self",
        decision=decision,
        served=served,
        result=decision.analyzer_result,
        analyzer_cost=analyzer_cost,
        reg=reg,
    )
    return ChatOutcome(
        decision=decision,
        routing=None,
        served_model=served,
        result=decision.analyzer_result,
        answer_mode="self",
        response_text=decision.answer or "",
        analyzer_lat=analyzer_lat,
        gen_lat=0.0,
        total_lat=total_lat,
        ttft_ms=analyzer_lat,
        fallback_used=False,
        fallback_reason=None,
        success=True,
        error_text=None,
        analyzer_cost=analyzer_cost,
        model_cost=model_cost,
        total_cost=total,
        baseline_cost=baseline,
        savings_usd=savings,
        savings_pct=pct,
        in_tok=in_tok,
        out_tok=out_tok,
        reasoning_toks=reasoning,
        tot_tok=tot,
        strategy=strategy,
    )


def build_switch_outcome(
    *,
    decision: AnalyzerDecision,
    routing: RoutingResult,
    served: ModelSpec,
    result: Optional[LLMResult],
    analyzer_lat: float,
    gen_lat: float,
    t_start: float,
    ttft_ms: Optional[float],
    analyzer_cost: float,
    fallback_used: bool,
    fallback_reason: Optional[str],
    success: bool,
    error_text: Optional[str],
    reg: ModelRegistry,
    strategy: str,
) -> ChatOutcome:
    total_lat = (time.perf_counter() - t_start) * 1000.0
    model_cost, total, baseline, savings, pct, in_tok, out_tok, reasoning, tot = _assemble_costs(
        answer_mode="switch",
        decision=decision,
        served=served,
        result=result,
        analyzer_cost=analyzer_cost,
        reg=reg,
    )
    text = result.text if result else f"Error: {error_text or 'Generation failed'}"
    return ChatOutcome(
        decision=decision,
        routing=routing,
        served_model=served,
        result=result,
        answer_mode="switch",
        response_text=text,
        analyzer_lat=analyzer_lat,
        gen_lat=gen_lat,
        total_lat=total_lat,
        ttft_ms=ttft_ms,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        success=success,
        error_text=error_text,
        analyzer_cost=analyzer_cost,
        model_cost=model_cost,
        total_cost=total,
        baseline_cost=baseline,
        savings_usd=savings,
        savings_pct=pct,
        in_tok=in_tok,
        out_tok=out_tok,
        reasoning_toks=reasoning,
        tot_tok=tot,
        strategy=strategy,
    )


async def run_unary_chat(
    query: str,
    history: List[ChatMessage],
    strategy: str,
    reg: ModelRegistry,
) -> ChatResponse:
    check_spend_budgets()
    if "FAIL-ANALYZER" in query:
        raise HTTPException(status_code=502, detail="Analyzer execution failed: simulated outage")
    strategy = strategy if strategy in STRATEGIES else "balanced"
    available = reg.available()
    t_start = time.perf_counter()

    cache_key = _completion_key(query, history, strategy, ",".join(m.model_id for m in available))
    cached = completion_cache_get(cache_key)
    # Replay only switch completions; self answers are already a single cheap call.

    try:
        decision = await run_analyzer(
            query, history, available, strategy=strategy, registry_instance=reg
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analyzer execution failed: {exc}") from exc

    analyzer_lat = (time.perf_counter() - t_start) * 1000.0
    analyzer_cost = compute_cost(decision.analyzer_model, decision.analyzer_result) or 0.0

    if decision.answer_mode == "self" and decision.answer:
        outcome = build_self_outcome(
            decision=decision,
            analyzer_lat=analyzer_lat,
            t_start=t_start,
            analyzer_cost=analyzer_cost,
            reg=reg,
            strategy=strategy,
        )
        persist_outcome(query, outcome)
        return to_chat_response(outcome)

    routing = route_decision(decision, strategy, reg)
    chain = apply_cost_cap(
        routing.fallback_chain,
        decision.analyzer_result.input_tokens,
    )
    primary = chain[0]

    if cached and cached.get("answer_mode") == "switch" and cached.get("response"):
        # Exact repeat of a switch query: skip the second provider call.
        served = primary
        fake = LLMResult(
            content=cached["response"],
            text=cached["response"],
            input_tokens=cached.get("input_tokens") or 0,
            output_tokens=cached.get("output_tokens") or 0,
            usage_source="cache",
            latency_ms=0.0,
        )
        outcome = build_switch_outcome(
            decision=decision,
            routing=routing,
            served=served,
            result=fake,
            analyzer_lat=analyzer_lat,
            gen_lat=0.0,
            t_start=t_start,
            ttft_ms=0.0,
            analyzer_cost=analyzer_cost,
            fallback_used=False,
            fallback_reason="exact_cache",
            success=True,
            error_text=None,
            reg=reg,
            strategy=strategy,
        )
        outcome.cached = True
        outcome.response_text = cached["response"]
        persist_outcome(query, outcome)
        return to_chat_response(outcome)
    messages = build_messages(
        history=history,
        query=query,
        max_tokens=primary.context_window,
        tier=primary.tier,
    )

    t_gen = time.perf_counter()
    fallback_used = False
    fallback_reason = None
    served = primary
    result = None
    success = True
    error_text = None
    try:
        served, result, fallback_used, fallback_reason = await execute_with_fallback(messages, chain)
    except LLMAdapterError as exc:
        success = False
        error_text = str(exc)

    gen_lat = (time.perf_counter() - t_gen) * 1000.0
    outcome = build_switch_outcome(
        decision=decision,
        routing=routing,
        served=served,
        result=result,
        analyzer_lat=analyzer_lat,
        gen_lat=gen_lat,
        t_start=t_start,
        ttft_ms=result.ttft_ms if result else None,
        analyzer_cost=analyzer_cost,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        success=success,
        error_text=error_text,
        reg=reg,
        strategy=strategy,
    )
    persist_outcome(query, outcome)
    if success and result:
        completion_cache_put(cache_key, {
            "answer_mode": "switch",
            "response": outcome.response_text,
            "input_tokens": outcome.in_tok,
            "output_tokens": outcome.out_tok,
        })
    return to_chat_response(outcome)


def _sse(event: dict) -> dict:
    return event


async def iter_chat_sse(
    query: str,
    history: List[ChatMessage],
    strategy: str,
    reg: ModelRegistry,
    disconnected: Optional[Callable[[], Any]] = None,
) -> AsyncIterator[dict]:
    """Yield typed SSE event dicts for `/api/chat/stream`."""
    check_spend_budgets()
    if "FAIL-ANALYZER" in query:
        yield {"event": "error", "detail": "Analyzer error: simulated outage"}
        return

    strategy = strategy if strategy in STRATEGIES else "balanced"
    available = reg.available()
    t_start = time.perf_counter()
    cache_key = _completion_key(query, history, strategy, ",".join(m.model_id for m in available))
    cached = completion_cache_get(cache_key)

    try:
        decision = await run_analyzer(
            query, history, available, strategy=strategy, registry_instance=reg
        )
    except Exception as exc:
        yield {"event": "error", "detail": f"Analyzer error: {exc}"}
        return

    analyzer_lat = (time.perf_counter() - t_start) * 1000.0
    analyzer_cost = compute_cost(decision.analyzer_model, decision.analyzer_result) or 0.0

    yield {
        "event": "analyzer",
        "info": decision.to_analyzer_info(cost_usd=analyzer_cost).model_dump(),
    }

    if decision.answer_mode == "self" and decision.answer:
        outcome = build_self_outcome(
            decision=decision,
            analyzer_lat=analyzer_lat,
            t_start=t_start,
            analyzer_cost=analyzer_cost,
            reg=reg,
            strategy=strategy,
        )
        persist_outcome(query, outcome)
        # One honest delta (the analyzer already produced the full answer).
        yield {"event": "content_delta", "text": outcome.response_text}
        yield {"event": "delta", "text": outcome.response_text}
        yield done_event_payload(outcome)
        return

    routing = route_decision(decision, strategy, reg)
    chain = apply_cost_cap(routing.fallback_chain, decision.analyzer_result.input_tokens)
    primary = chain[0]

    yield {
        "event": "routing",
        "target_model": primary.endpoint_model,
        "target_name": primary.name,
        "target_provider": primary.provider,
        "target_tier": primary.tier,
        "reason": decision.reason,
        "answer_mode": "switch",
        "context_relevant": decision.context_required,
        "candidates": routing.candidates(),
    }

    if cached and cached.get("answer_mode") == "switch" and cached.get("response"):
        text = cached["response"]
        yield {"event": "content_delta", "text": text}
        yield {"event": "delta", "text": text}
        fake = LLMResult(
            content=text,
            text=text,
            input_tokens=cached.get("input_tokens") or 0,
            output_tokens=cached.get("output_tokens") or 0,
            usage_source="cache",
            latency_ms=0.0,
        )
        outcome = build_switch_outcome(
            decision=decision,
            routing=routing,
            served=primary,
            result=fake,
            analyzer_lat=analyzer_lat,
            gen_lat=0.0,
            t_start=t_start,
            ttft_ms=0.0,
            analyzer_cost=analyzer_cost,
            fallback_used=False,
            fallback_reason="exact_cache",
            success=True,
            error_text=None,
            reg=reg,
            strategy=strategy,
        )
        outcome.cached = True
        outcome.response_text = text
        persist_outcome(query, outcome)
        yield done_event_payload(outcome)
        return

    messages = build_messages(
        history=history,
        query=query,
        max_tokens=primary.context_window,
        tier=primary.tier,
    )
    t_gen = time.perf_counter()
    served = primary
    result = None
    fallback_used = False
    fallback_reason = None
    success = True
    error_text = None
    completed = False

    try:
        async for kind, payload in stream_with_fallback(messages, chain, disconnected=disconnected):
            if kind == "chunk":
                chunk: StreamChunk = payload
                if chunk.reasoning_text:
                    yield {"event": "reasoning_delta", "text": chunk.reasoning_text}
                if chunk.text:
                    yield {"event": "content_delta", "text": chunk.text}
                    yield {"event": "delta", "text": chunk.text}
            elif kind == "complete":
                served, result, fallback_used, fallback_reason = payload
                completed = True
    except LLMAdapterError as exc:
        success = False
        error_text = str(exc)
        yield {"event": "error", "detail": error_text}

    if disconnected is not None and await disconnected():
        return

    if not completed and success:
        success = False
        error_text = error_text or "Generation interrupted or all candidates failed."
        if not error_text.startswith("All"):
            yield {"event": "error", "detail": error_text}

    gen_lat = (time.perf_counter() - t_gen) * 1000.0
    outcome = build_switch_outcome(
        decision=decision,
        routing=routing,
        served=served,
        result=result,
        analyzer_lat=analyzer_lat,
        gen_lat=gen_lat,
        t_start=t_start,
        ttft_ms=result.ttft_ms if result else None,
        analyzer_cost=analyzer_cost,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        success=success and bool(result),
        error_text=error_text,
        reg=reg,
        strategy=strategy,
    )
    persist_outcome(query, outcome)
    if outcome.success and result:
        completion_cache_put(cache_key, {
            "answer_mode": "switch",
            "response": outcome.response_text,
            "input_tokens": outcome.in_tok,
            "output_tokens": outcome.out_tok,
        })
    yield done_event_payload(outcome)
