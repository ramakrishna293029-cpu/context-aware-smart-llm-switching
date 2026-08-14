"""FastAPI application: wires analyzer -> router -> adapters -> tracker."""

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .adapters.base import LLMAdapterError, adapter_factory
from .adapters.mock import MockAdapter
from .adapters.openai import OpenAICompatibleAdapter
from .analyzer import analyzer
from .config import settings
from .registry import registry
from .router import compute_history_stats, router
from .schemas import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ContextAnalysisOut,
    FeedbackRequest,
    FeedbackResponse,
    RoutingInfo,
    ScoreBreakdown,
    StatsOut,
)
from .tracker import estimate_cost_usd, tracker

adapter_factory.register(MockAdapter())
adapter_factory.register(OpenAICompatibleAdapter())

app = FastAPI(
    title="Context-Aware Smart LLM Switching",
    description="Intelligent LLM orchestration: understand the query first, then decide which model answers it.",
    version="0.1.0",
)

STATIC_DIR: Path = settings.static_dir


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "demo_mode": registry.get("demo-fast") is not None,
            "models": len(registry.available())}


@app.get("/api/models")
async def list_models():
    return {"models": registry.to_public_list()}


async def _generate_with_fallback(messages, analysis, decision, latency_start):
    """Try the winner, then remaining models by score; collect errors."""
    chain = router.ranking(decision)
    errors: list[str] = []
    for model in chain:
        try:
            adapter = adapter_factory.get(model.provider)
            result = await adapter.generate(model, messages)
            return model, result, errors
        except LLMAdapterError as exc:
            errors.append(f"{model.model_id}: {exc}")
    raise LLMAdapterError("All models failed. " + " | ".join(errors))


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    history = req.history[-settings.max_history_messages:]
    analysis = analyzer.analyze(req.query, history)
    history_stats = compute_history_stats()
    decision = router.route(analysis, history_stats)

    messages = [*history, ChatMessage(role="user", content=req.query)]
    start = time.perf_counter()

    try:
        model, result, errors = await _generate_with_fallback(messages, analysis, decision, start)
        success = True
        error_text = None
    except LLMAdapterError as exc:
        model = decision.model
        result = None
        success = False
        error_text = str(exc)

    latency_ms = (time.perf_counter() - start) * 1000.0

    if success:
        input_tokens = result.input_tokens
        output_tokens = result.output_tokens
        cost = estimate_cost_usd(
            (model.input_price_per_mtok, model.output_price_per_mtok),
            input_tokens, output_tokens,
        )
        strongest = registry.strongest()
        baseline_cost = (
            estimate_cost_usd(
                (strongest.input_price_per_mtok, strongest.output_price_per_mtok),
                input_tokens, output_tokens,
            )
            if strongest else 0.0
        )
        response_text = result.text
    else:
        input_tokens = analysis.estimated_input_tokens
        output_tokens = 0
        cost = 0.0
        baseline_cost = 0.0
        response_text = f"All candidate models failed: {error_text}"

    request_id = tracker.record_request(
        query=req.query,
        task_type=analysis.task_type,
        complexity=analysis.complexity,
        selected_model=model.model_id,
        provider=model.provider,
        demo_mode=model.demo_mode,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=cost,
        baseline_cost=baseline_cost,
        latency_ms=latency_ms,
        success=success,
        error=error_text,
    )

    return ChatResponse(
        response=response_text,
        model=RoutingInfo(
            model_id=model.model_id,
            model_name=model.name,
            provider=model.provider,
            demo_mode=model.demo_mode,
            reason=decision.reason,
            analysis=ContextAnalysisOut(**analysis.to_public()),
            scores=ScoreBreakdown(**{
                k: getattr(decision.winner, k)
                for k in ("quality_suitability", "complexity_compatibility",
                          "cost_efficiency", "latency_efficiency",
                          "historical_performance", "total")
            }),
        ),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=round(cost, 6),
        latency_ms=round(latency_ms, 1),
        success=success,
        request_id=request_id,
    )


@app.post("/api/feedback", response_model=FeedbackResponse)
async def feedback(req: FeedbackRequest):
    updated = tracker.record_feedback(req.request_id, req.rating)
    if not updated:
        raise HTTPException(status_code=404, detail="Request not found or already resolved.")
    return FeedbackResponse(ok=True, message="Thanks for your feedback!")


@app.get("/api/stats", response_model=StatsOut)
async def stats():
    return StatsOut(**tracker.dashboard_stats())


@app.get("/api/history", response_model=list)
async def history(limit: int = 20):
    return tracker.recent_requests(limit=min(max(limit, 1), 100))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
