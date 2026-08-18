"""FastAPI Application: Context-Aware Smart LLM Switching for Cost & Performance Optimization.

Request Flow:
USER QUERY
  │
  ▼
LOAD RELEVANT CONVERSATION CONTEXT
  │
  ▼
OPENROUTER ANALYZER LLM (meta-llama/llama-3.2-3b-instruct)
  │ (Produces structured complexity, task type, & routing decision)
  ▼
SMART ORCHESTRATOR
  │ (Resolves target tier & provider with fallback ordering)
  ├──► GEMINI (Fast / Low-Cost Model: gemini-2.5-flash-lite / gemini-2.5-flash)
  ├──► GROQ (Coding Model: qwen3.6-27b)
  └──► GROQ (Reasoning Model: openai/gpt-oss-120b)
  │
  ▼
REAL LLM RESPONSE
  │ (If error -> Resilient fallback chain)
  │ (If low confidence -> Adaptive escalation)
  ▼
STORE REAL TELEMETRY (Tokens, Latency, Real Cost vs Baseline, Savings)
  │
  ▼
RETURN TRANSPARENT RESPONSE & DASHBOARD METRICS
"""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from .adapters.base import LLMAdapterError, LLMResult, adapter_factory
from .adapters.gemini import GeminiAdapter
from .adapters.mock import MockAdapter
from .adapters.openai import OpenAICompatibleAdapter
from .analyzer_llm import AnalyzerDecision, run_analyzer
from .config import settings
from .context import build_messages
from .registry import ModelRegistry, ModelSpec, registry
from .router import STRATEGIES, RoutingResult, router
from .schemas import (
    AnalyzerInfo,
    AnalyzeRequest,
    AnalyzeResponse,
    BenchmarkComparisonItem,
    BenchmarkResult,
    BenchmarkRunRequest,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
    FeedbackResponse,
    HistoryRow,
    ModelInfo,
)
from .tracker import estimate_cost_usd, tracker

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Context-Aware Smart LLM Router", version="2.5.0")
logger = logging.getLogger("smart-llm-router")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# CORS Setup
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Register Adapters
gemini_adapter = GeminiAdapter()
openai_adapter = OpenAICompatibleAdapter()
mock_adapter = MockAdapter()

adapter_factory.register(gemini_adapter)
adapter_factory.register(openai_adapter)
adapter_factory.register(mock_adapter)
adapter_factory.set_default(openai_adapter)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def _compute_cost(model: ModelSpec, result: Optional[LLMResult]) -> Optional[float]:
    if not result or result.input_tokens is None or result.output_tokens is None:
        return None
    return estimate_cost_usd(
        (model.input_price_per_mtok, model.output_price_per_mtok),
        result.input_tokens,
        result.output_tokens,
    )


def _compute_baseline_cost(tokens: Optional[tuple[int, int]]) -> Optional[float]:
    """Calculates what the request would have cost on the strongest available baseline model."""
    if not tokens or tokens[0] is None or tokens[1] is None:
        return None
    strongest = registry.strongest()
    if not strongest:
        return None
    return estimate_cost_usd(
        (strongest.input_price_per_mtok, strongest.output_price_per_mtok),
        tokens[0],
        tokens[1],
    )


def _filter_context(history: List[ChatMessage], context_required: bool) -> List[ChatMessage]:
    """Extracts only relevant conversation context when needed."""
    if not context_required or not history:
        return []
    return history[-settings.max_history_messages:]


async def _execute_with_fallback(
    messages: List[ChatMessage],
    chain: List[ModelSpec]
) -> tuple[ModelSpec, LLMResult, bool, Optional[str]]:
    """Tries primary model, falling back through chain on error. Returns (served_model, result, fallback_used, error)."""
    primary = chain[0]
    errors = []

    for model in chain:
        try:
            adapter = adapter_factory.get(model.provider)
            result = await adapter.generate(model, messages)
            fallback_used = (model.model_id != primary.model_id)
            err_msg = (" | ".join(errors)) if errors else None
            return model, result, fallback_used, err_msg
        except LLMAdapterError as exc:
            logger.warning("Model %s failed: %s", model.model_id, exc)
            errors.append(f"{model.model_id}: {exc}")

    raise LLMAdapterError("All candidate models failed in fallback chain: " + " | ".join(errors))


# ---------------------------------------------------------------------------
# Public Endpoints
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mode": "real" if registry.has_real() else "demo",
        "models_count": len(registry.available()),
        "providers": {
            "openrouter": bool(settings.openrouter_api_key),
            "gemini": bool(settings.gemini_api_key),
            "groq": bool(settings.groq_api_key),
        },
        "configured_models": {
            "analyzer": settings.openrouter_analyzer_model,
            "fast_gemini": settings.gemini_fast_model,
            "coding_groq": settings.groq_coding_model,
            "reasoning_groq": settings.groq_reasoning_model,
        },
    }


@app.get("/api/providers/health")
async def provider_health():
    """Performs live connectivity check on each configured provider."""
    results = {}

    # OpenRouter check
    if settings.has_openrouter:
        analyzer_m = registry.get_analyzer()
        try:
            t0 = time.perf_counter()
            adapter = adapter_factory.get(analyzer_m.provider)
            res = await adapter.generate(analyzer_m, [ChatMessage(role="user", content="ping")])
            lat = (time.perf_counter() - t0) * 1000.0
            results["openrouter"] = {"status": "connected", "latency_ms": round(lat, 1), "model": analyzer_m.endpoint_model}
        except Exception as e:
            results["openrouter"] = {"status": "error", "error": str(e)}
    else:
        results["openrouter"] = {"status": "missing_api_key"}

    # Gemini check
    if settings.has_gemini:
        gemini_m = registry.get_by_tier("fast")
        if gemini_m:
            try:
                t0 = time.perf_counter()
                adapter = adapter_factory.get(gemini_m.provider)
                res = await adapter.generate(gemini_m, [ChatMessage(role="user", content="ping")])
                lat = (time.perf_counter() - t0) * 1000.0
                results["gemini"] = {"status": "connected", "latency_ms": round(lat, 1), "model": gemini_m.endpoint_model}
            except Exception as e:
                results["gemini"] = {"status": "error", "error": str(e)}
    else:
        results["gemini"] = {"status": "missing_api_key"}

    # Groq check
    if settings.has_groq:
        groq_m = registry.get_by_tier("coding")
        if groq_m:
            try:
                t0 = time.perf_counter()
                adapter = adapter_factory.get(groq_m.provider)
                res = await adapter.generate(groq_m, [ChatMessage(role="user", content="ping")])
                lat = (time.perf_counter() - t0) * 1000.0
                results["groq"] = {"status": "connected", "latency_ms": round(lat, 1), "model": groq_m.endpoint_model}
            except Exception as e:
                results["groq"] = {"status": "error", "error": str(e)}
    else:
        results["groq"] = {"status": "missing_api_key"}

    return results


@app.get("/api/models")
async def list_models():
    return {"models": registry.to_public_list()}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    strategy = req.strategy if req.strategy in STRATEGIES else "balanced"
    available = registry.available()

    t0 = time.perf_counter()
    decision = await run_analyzer(req.query, req.history[-settings.max_history_messages:], available, strategy=strategy)
    analyzer_lat = (time.perf_counter() - t0) * 1000.0
    analyzer_cost = _compute_cost(decision.analyzer_model, decision.analyzer_result)

    routing_res = router.resolve(decision, strategy=strategy)

    analyzer_info = AnalyzerInfo(
        model_id=decision.analyzer_model.model_id,
        model_name=decision.analyzer_model.name,
        provider=decision.analyzer_model.provider,
        task_type=decision.task_type,
        complexity=decision.complexity,
        complexity_score=decision.complexity_score,
        reasoning_required=decision.reasoning_required,
        coding_required=decision.coding_required,
        context_required=decision.context_required,
        target_tier=decision.target_tier,
        target_provider=decision.target_provider,
        target_model=decision.target_model,
        reason=decision.reason,
        input_tokens=decision.analyzer_result.input_tokens,
        output_tokens=decision.analyzer_result.output_tokens,
        latency_ms=round(analyzer_lat, 1),
        cost_usd=round(analyzer_cost, 6) if analyzer_cost is not None else None,
    )

    return AnalyzeResponse(
        analyzer=analyzer_info,
        candidates=routing_res.candidates(),
        strategy=strategy,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    strategy = req.strategy if req.strategy in STRATEGIES else "balanced"
    available = registry.available()

    # 1. Run OpenRouter Analyzer LLM
    t_start = time.perf_counter()
    decision = await run_analyzer(req.query, req.history, available, strategy=strategy)
    analyzer_lat = (time.perf_counter() - t_start) * 1000.0
    analyzer_cost = _compute_cost(decision.analyzer_model, decision.analyzer_result)

    # 2. Smart Router resolves target model & fallback chain
    routing_res = router.resolve(decision, strategy=strategy)
    primary_model = routing_res.primary_model
    fallback_chain = routing_res.fallback_chain

    # 3. Build filtered context messages
    context_msgs = _filter_context(req.history, decision.context_required)
    messages = build_messages(context_msgs, req.query)

    # 4. Execute with fallback resilience
    t_gen = time.perf_counter()
    fallback_used = False
    fallback_reason = None
    served_model = primary_model
    result = None
    success = True
    error_text = None

    try:
        served_model, result, fallback_used, fallback_reason = await _execute_with_fallback(messages, fallback_chain)
    except LLMAdapterError as exc:
        success = False
        error_text = str(exc)
        logger.error("Chat execution error: %s", exc)

    gen_lat = (time.perf_counter() - t_gen) * 1000.0
    total_lat = (time.perf_counter() - t_start) * 1000.0

    # 5. Token metrics and cost calculations
    in_tok = result.input_tokens if result else None
    out_tok = result.output_tokens if result else None
    tot_tok = ((in_tok or 0) + (out_tok or 0) + (decision.analyzer_result.input_tokens or 0) + (decision.analyzer_result.output_tokens or 0)) if result else None

    model_cost = _compute_cost(served_model, result) if result else 0.0
    total_cost = ((model_cost or 0.0) + (analyzer_cost or 0.0)) if result else 0.0
    baseline_cost = _compute_baseline_cost((in_tok, out_tok)) if result else 0.0
    savings_usd = max(0.0, baseline_cost - total_cost) if baseline_cost > 0 else 0.0
    savings_pct = (savings_usd / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

    # 6. Record real telemetry in SQLite
    req_id = tracker.record_request(
        query=req.query,
        task_type=decision.task_type,
        complexity=decision.complexity,
        complexity_score=decision.complexity_score,
        analyzer_provider=decision.analyzer_model.provider,
        analyzer_model=decision.analyzer_model.endpoint_model,
        analyzer_latency_ms=analyzer_lat,
        analyzer_input_tokens=decision.analyzer_result.input_tokens,
        analyzer_output_tokens=decision.analyzer_result.output_tokens,
        analyzer_cost=analyzer_cost,
        target_tier=decision.target_tier,
        target_provider=decision.target_provider,
        selected_model=served_model.endpoint_model,
        selected_provider=served_model.provider,
        routing_reason=decision.reason,
        context_relevant=decision.context_required,
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=tot_tok,
        latency_ms=gen_lat,
        total_latency_ms=total_lat,
        ttft_ms=result.ttft_ms if result else None,
        estimated_cost=model_cost,
        baseline_cost=baseline_cost,
        savings_usd=savings_usd,
        savings_percent=savings_pct,
        success=success,
        error=error_text,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        strategy=strategy,
        candidates_json=json.dumps(routing_res.candidates()),
    )

    response_text = result.text if result else f"Error: {error_text or 'Generation failed'}"

    return ChatResponse(
        response=response_text,
        model=ModelInfo(
            model_id=served_model.model_id,
            model_name=served_model.name,
            provider=served_model.provider,
            tier=served_model.tier,
            mode=served_model.mode,
            strategy=strategy,
            reason=decision.reason,
        ),
        analyzer=AnalyzerInfo(
            model_id=decision.analyzer_model.model_id,
            model_name=decision.analyzer_model.name,
            provider=decision.analyzer_model.provider,
            task_type=decision.task_type,
            complexity=decision.complexity,
            complexity_score=decision.complexity_score,
            reasoning_required=decision.reasoning_required,
            coding_required=decision.coding_required,
            context_required=decision.context_required,
            target_tier=decision.target_tier,
            target_provider=decision.target_provider,
            target_model=decision.target_model,
            reason=decision.reason,
            input_tokens=decision.analyzer_result.input_tokens,
            output_tokens=decision.analyzer_result.output_tokens,
            latency_ms=round(analyzer_lat, 1),
            cost_usd=round(analyzer_cost, 6) if analyzer_cost is not None else None,
        ),
        context_relevant=decision.context_required,
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=tot_tok,
        estimated_cost_usd=round(model_cost, 6) if model_cost is not None else None,
        analyzer_cost_usd=round(analyzer_cost, 6) if analyzer_cost is not None else None,
        total_cost_usd=round(total_cost, 6) if total_cost is not None else None,
        baseline_cost_usd=round(baseline_cost, 6) if baseline_cost is not None else None,
        savings_usd=round(savings_usd, 6) if savings_usd is not None else None,
        savings_percent=round(savings_pct, 1) if savings_pct is not None else None,
        latency_ms=round(gen_lat, 1),
        analyzer_latency_ms=round(analyzer_lat, 1),
        total_latency_ms=round(total_lat, 1),
        ttft_ms=round(result.ttft_ms, 1) if (result and result.ttft_ms) else None,
        success=success,
        request_id=req_id,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        candidates=routing_res.candidates(),
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE Streaming endpoint with real-time routing transparency."""
    strategy = req.strategy if req.strategy in STRATEGIES else "balanced"
    available = registry.available()

    async def event_generator():
        t_start = time.perf_counter()

        # Step 1: OpenRouter Analyzer
        try:
            decision = await run_analyzer(req.query, req.history, available, strategy=strategy)
        except Exception as exc:
            yield "data: " + json.dumps({"event": "error", "detail": f"Analyzer error: {exc}"}) + "\n\n"
            return

        analyzer_lat = (time.perf_counter() - t_start) * 1000.0
        analyzer_cost = _compute_cost(decision.analyzer_model, decision.analyzer_result)

        # Emit Analyzer Event
        yield "data: " + json.dumps({
            "event": "analyzer",
            "info": {
                "model_id": decision.analyzer_model.model_id,
                "model_name": decision.analyzer_model.name,
                "provider": decision.analyzer_model.provider,
                "task_type": decision.task_type,
                "complexity": decision.complexity,
                "complexity_score": decision.complexity_score,
                "reasoning_required": decision.reasoning_required,
                "coding_required": decision.coding_required,
                "context_required": decision.context_required,
                "target_tier": decision.target_tier,
                "target_provider": decision.target_provider,
                "reason": decision.reason,
                "latency_ms": round(analyzer_lat, 1),
                "cost_usd": round(analyzer_cost, 6) if analyzer_cost else None,
            }
        }) + "\n\n"

        # Step 2: Routing Decision
        routing_res = router.resolve(decision, strategy=strategy)
        target_model = routing_res.primary_model
        fallback_chain = routing_res.fallback_chain

        yield "data: " + json.dumps({
            "event": "routing",
            "target_model": target_model.endpoint_model,
            "target_name": target_model.name,
            "target_provider": target_model.provider,
            "target_tier": target_model.tier,
            "reason": decision.reason,
            "context_relevant": decision.context_required,
            "candidates": routing_res.candidates(),
        }) + "\n\n"

        # Step 3: Stream Execution
        context_msgs = _filter_context(req.history, decision.context_required)
        messages = build_messages(context_msgs, req.query)

        served_model = target_model
        full_text = []
        fallback_used = False
        t_gen = time.perf_counter()
        ttft_ms = None
        result = None

        for cand in fallback_chain:
            served_model = cand
            fallback_used = (cand.model_id != target_model.model_id)
            adapter = adapter_factory.get(cand.provider)
            try:
                if adapter.supports_streaming():
                    async for chunk in adapter.stream(cand, messages):
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - t_gen) * 1000.0
                        full_text.append(chunk)
                        yield "data: " + json.dumps({"event": "delta", "text": chunk}) + "\n\n"
                    result = getattr(adapter, "last_result", lambda: None)()
                else:
                    result = await adapter.generate(cand, messages)
                    yield "data: " + json.dumps({"event": "delta", "text": result.text}) + "\n\n"
                    full_text.append(result.text)
                break
            except LLMAdapterError as exc:
                logger.warning("Streaming failed for %s: %s", cand.model_id, exc)
                continue
        else:
            yield "data: " + json.dumps({"event": "error", "detail": "All candidate models in fallback chain failed."}) + "\n\n"
            return

        gen_lat = (time.perf_counter() - t_gen) * 1000.0
        total_lat = (time.perf_counter() - t_start) * 1000.0
        resp_text = "".join(full_text)

        in_tok = result.input_tokens if result else len(req.query) // 4
        out_tok = result.output_tokens if result else len(resp_text) // 4
        tot_tok = (in_tok + out_tok + (decision.analyzer_result.input_tokens or 0) + (decision.analyzer_result.output_tokens or 0))

        model_cost = _compute_cost(served_model, result) if result else 0.0
        total_cost = ((model_cost or 0.0) + (analyzer_cost or 0.0))
        baseline_cost = _compute_baseline_cost((in_tok, out_tok)) or 0.0
        savings_usd = max(0.0, baseline_cost - total_cost)
        savings_pct = (savings_usd / baseline_cost * 100.0) if baseline_cost > 0 else 0.0

        req_id = tracker.record_request(
            query=req.query,
            task_type=decision.task_type,
            complexity=decision.complexity,
            complexity_score=decision.complexity_score,
            analyzer_provider=decision.analyzer_model.provider,
            analyzer_model=decision.analyzer_model.endpoint_model,
            analyzer_latency_ms=analyzer_lat,
            analyzer_input_tokens=decision.analyzer_result.input_tokens,
            analyzer_output_tokens=decision.analyzer_result.output_tokens,
            analyzer_cost=analyzer_cost,
            target_tier=decision.target_tier,
            target_provider=decision.target_provider,
            selected_model=served_model.endpoint_model,
            selected_provider=served_model.provider,
            routing_reason=decision.reason,
            context_relevant=decision.context_required,
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=tot_tok,
            latency_ms=gen_lat,
            total_latency_ms=total_lat,
            ttft_ms=ttft_ms,
            estimated_cost=model_cost,
            baseline_cost=baseline_cost,
            savings_usd=savings_usd,
            savings_percent=savings_pct,
            success=True,
            fallback_used=fallback_used,
            strategy=strategy,
            candidates_json=json.dumps(routing_res.candidates()),
        )

        yield "data: " + json.dumps({
            "event": "done",
            "success": True,
            "request_id": req_id,
            "response": resp_text,
            "model": {
                "model_id": served_model.model_id,
                "model_name": served_model.name,
                "provider": served_model.provider,
                "tier": served_model.tier,
                "reason": decision.reason,
            },
            "analyzer": {
                "model_name": decision.analyzer_model.name,
                "provider": decision.analyzer_model.provider,
                "task_type": decision.task_type,
                "complexity": decision.complexity,
                "latency_ms": round(analyzer_lat, 1),
                "cost_usd": round(analyzer_cost, 6) if analyzer_cost else None,
            },
            "context_relevant": decision.context_required,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": tot_tok,
            "estimated_cost_usd": round(model_cost, 6) if model_cost else None,
            "analyzer_cost_usd": round(analyzer_cost, 6) if analyzer_cost else None,
            "total_cost_usd": round(total_cost, 6),
            "baseline_cost_usd": round(baseline_cost, 6),
            "savings_usd": round(savings_usd, 6),
            "savings_percent": round(savings_pct, 1),
            "latency_ms": round(gen_lat, 1),
            "analyzer_latency_ms": round(analyzer_lat, 1),
            "total_latency_ms": round(total_lat, 1),
            "ttft_ms": round(ttft_ms, 1) if ttft_ms else None,
            "fallback_used": fallback_used,
            "candidates": routing_res.candidates(),
        }) + "\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/feedback", response_model=FeedbackResponse)
async def feedback(req: FeedbackRequest):
    ok = tracker.record_feedback(req.request_id, req.rating)
    if not ok:
        raise HTTPException(status_code=404, detail="Request not found.")
    return FeedbackResponse(ok=True, message="Feedback recorded.")


@app.get("/api/stats")
async def stats():
    return tracker.dashboard_stats()


@app.get("/api/requests/{request_id}")
async def request_detail(request_id: int):
    detail = tracker.request_detail(request_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    return detail


@app.get("/api/history")
async def history(limit: int = 20):
    return tracker.recent_requests(limit=min(max(limit, 1), 100))


@app.post("/api/benchmark/run", response_model=BenchmarkResult)
async def run_benchmark(req: BenchmarkRunRequest):
    """Research Experiment (Section 27): Compares Baseline 1, Baseline 2, and Smart Router across queries."""
    sample_queries = req.queries or [
        "What is an HTTP request header?",
        "Write a Python function to implement binary search with recursion.",
        "Design a high-throughput, fault-tolerant distributed message broker like Apache Kafka.",
        "Explain the time complexity differences between QuickSort and MergeSort in 2 sentences.",
        "Write a SQL query with window functions to calculate 7-day rolling revenue per customer.",
    ]

    items = []
    powerful_model = registry.strongest() or registry.get_by_tier("reasoning")
    fast_model = registry.get_by_tier("fast")
    available = registry.available()

    baseline1_total_cost = 0.0
    baseline1_lat_sum = 0.0
    baseline2_total_cost = 0.0
    baseline2_lat_sum = 0.0
    smart_total_cost = 0.0
    smart_lat_sum = 0.0

    for query in sample_queries:
        # 1. Run Analyzer
        decision = await run_analyzer(query, [], available)
        routing_res = router.resolve(decision)
        smart_model = routing_res.primary_model

        # Estimate tokens
        q_len = len(query) // 4
        ans_len = 300 if decision.complexity == "low" else 800

        # Baseline 1 (Always Powerful)
        b1_in_cost = (q_len * powerful_model.input_price_per_mtok) / 1_000_000
        b1_out_cost = (ans_len * powerful_model.output_price_per_mtok) / 1_000_000
        b1_cost = b1_in_cost + b1_out_cost
        b1_lat = powerful_model.expected_latency_ms

        # Baseline 2 (Static Routing: Fast for everything unless code keyword)
        is_code = "python" in query.lower() or "function" in query.lower() or "sql" in query.lower()
        b2_model = registry.get_by_tier("coding") if is_code else fast_model
        b2_cost = (q_len * b2_model.input_price_per_mtok + ans_len * b2_model.output_price_per_mtok) / 1_000_000
        b2_lat = b2_model.expected_latency_ms

        # Smart Router: Analyzer Cost + Selected Model Cost
        analyzer_c = (decision.analyzer_result.input_tokens * decision.analyzer_model.input_price_per_mtok + decision.analyzer_result.output_tokens * decision.analyzer_model.output_price_per_mtok) / 1_000_000
        smart_m_cost = (q_len * smart_model.input_price_per_mtok + ans_len * smart_model.output_price_per_mtok) / 1_000_000
        smart_cost = analyzer_c + smart_m_cost
        smart_lat = decision.analyzer_model.expected_latency_ms + smart_model.expected_latency_ms

        savings_pct = max(0.0, ((b1_cost - smart_cost) / b1_cost * 100.0)) if b1_cost > 0 else 0.0
        speedup_pct = max(0.0, ((b1_lat - smart_lat) / b1_lat * 100.0)) if b1_lat > smart_lat else 0.0

        baseline1_total_cost += b1_cost
        baseline1_lat_sum += b1_lat
        baseline2_total_cost += b2_cost
        baseline2_lat_sum += b2_lat
        smart_total_cost += smart_cost
        smart_lat_sum += smart_lat

        items.append(BenchmarkComparisonItem(
            query=query,
            task_type=decision.task_type,
            complexity=decision.complexity,
            baseline1_model=powerful_model.name,
            baseline1_cost_usd=round(b1_cost, 6),
            baseline1_latency_ms=b1_lat,
            baseline2_model=b2_model.name,
            baseline2_cost_usd=round(b2_cost, 6),
            baseline2_latency_ms=b2_lat,
            smart_model=smart_model.name,
            smart_cost_usd=round(smart_cost, 6),
            smart_latency_ms=smart_lat,
            smart_savings_percent=round(savings_pct, 1),
            smart_speedup_percent=round(speedup_pct, 1),
        ))

    n = len(sample_queries)
    saved_cost = max(0.0, baseline1_total_cost - smart_total_cost)
    overall_savings_pct = (saved_cost / baseline1_total_cost * 100.0) if baseline1_total_cost > 0 else 0.0
    overall_speedup_pct = ((baseline1_lat_sum - smart_lat_sum) / baseline1_lat_sum * 100.0) if baseline1_lat_sum > smart_lat_sum else 0.0

    return BenchmarkResult(
        total_queries=n,
        baseline1_total_cost_usd=round(baseline1_total_cost, 6),
        baseline1_avg_latency_ms=round(baseline1_lat_sum / n, 1),
        baseline2_total_cost_usd=round(baseline2_total_cost, 6),
        baseline2_avg_latency_ms=round(baseline2_lat_sum / n, 1),
        smart_total_cost_usd=round(smart_total_cost, 6),
        smart_avg_latency_ms=round(smart_lat_sum / n, 1),
        total_cost_saved_usd=round(saved_cost, 6),
        overall_cost_savings_percent=round(overall_savings_pct, 1),
        overall_speedup_percent=round(overall_speedup_pct, 1),
        items=items,
    )


@app.get("/api/settings")
async def get_settings():
    return {
        "analyzer_model": settings.openrouter_analyzer_model,
        "gemini_fast_model": settings.gemini_fast_model,
        "groq_coding_model": settings.groq_coding_model,
        "groq_reasoning_model": settings.groq_reasoning_model,
        "openrouter_fast_model": settings.openrouter_fast_model,
        "openrouter_coding_model": settings.openrouter_coding_model,
        "openrouter_reasoning_model": settings.openrouter_reasoning_model,
        "daily_budget_usd": settings.daily_budget_usd,
        "request_timeout_seconds": settings.request_timeout_seconds,
        "has_openrouter_key": bool(settings.openrouter_api_key),
        "has_gemini_key": bool(settings.gemini_api_key),
        "has_groq_key": bool(settings.groq_api_key),
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")