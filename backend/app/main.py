"""FastAPI Application: Context-Aware Smart LLM Switching for Cost & Performance Optimization.

System Architecture:
  Analyzer: Gemini 3.1 Flash-Lite
  6 Response Model Tiers:
    - Tier 1: Gemini 3.5 Flash-Lite
    - Tier 2: Groq GPT-OSS 20B
    - Tier 3: Gemini 3.6 Flash
    - Tier 4: Groq Qwen3.8 27B
    - Tier 5: Groq GPT-OSS 120B
    - Tier 6: Gemini 3.8 Flash (resilient fallback: gemini-3.5-flash)
"""

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from .adapters.base import (
    LLMAdapterError,
    LLMResult,
    adapter_factory,
)
from .adapters.gemini import GeminiAdapter
from .adapters.mock import MockAdapter
from .adapters.openai import OpenAICompatibleAdapter
from .analyzer_llm import AnalyzerDecision
from .config import settings
from .context import build_messages, estimate_tokens
from .eligibility import eligibility_filter
from .features import feature_extractor
from .linucb import linucb_router
from .pipeline import (
    _get_local_decision,
    check_spend_budgets,
    clear_completion_cache,
    compute_cost as _compute_cost,
    compute_baseline_cost as _compute_baseline_cost,
    execute_with_fallback as _execute_with_fallback,
    expected_request_cost,
    iter_chat_sse,
    run_unary_chat,
)
from .registry import ModelRegistry, ModelSpec, registry as default_registry
from .router import STRATEGIES
from .schemas import (
    AnalyzerInfo,
    AnalyzeRequest,
    AnalyzeResponse,
    BenchmarkComparisonItem,
    BenchmarkResult,
    BenchmarkRunRequest,
    CandidateInfo,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
    FeedbackResponse,
    ModelInfo,
    ProviderHealthResponse,
    ProviderStatusItem,
    ProviderTestResponse,
    RoutePreviewRequest,
)
from .security import (
    ResolvedCredentials,
    resolve_request_credentials,
)
from .tracker import estimate_cost_usd, tracker

STATIC_DIR = Path(settings.static_dir)

app = FastAPI(
    title="Context-Aware Smart LLM Router",
    version="3.0.0",
    description="Context-Aware Smart LLM Switching: Gemini 3.1 Flash-Lite Analyzer + 6 Response Model Tiers",
)
logger = logging.getLogger("smart-llm-router")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Register CORS Middleware
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )


# Security headers for browser hardening
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    return response

# Register Adapters in Factory
gemini_adapter = GeminiAdapter()
openai_adapter = OpenAICompatibleAdapter("openai")
openrouter_adapter = OpenAICompatibleAdapter("openrouter")
groq_adapter = OpenAICompatibleAdapter("groq")
custom_adapter = OpenAICompatibleAdapter("custom")
mock_adapter = MockAdapter()

adapter_factory.register(gemini_adapter)
adapter_factory.register(openai_adapter)
adapter_factory.register(openrouter_adapter)
adapter_factory.register(groq_adapter)
adapter_factory.register(custom_adapter)
adapter_factory.register(mock_adapter)
adapter_factory.set_default(gemini_adapter)

# Initialize LinUCB state & warm-start priors
@app.on_event("startup")
async def startup_event():
    try:
        linucb_router.load_state()
    except Exception as exc:
        logger.warning(f"Could not load LinUCB state: {exc}")
    total_pulls = sum(a.pull_count for a in linucb_router.arms.values())
    if total_pulls == 0:
        logger.info("Initializing LinUCB router with warm-start priors across core tiers...")
        linucb_router.warm_start_defaults()
        try:
            linucb_router.save_state()
        except Exception as exc:
            logger.warning(f"Could not persist initial warm-start state: {exc}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down adapters and releasing HTTP connection pools...")
    await adapter_factory.aclose()

# Rate Limiting State
_rate_hits: Dict[str, List[float]] = defaultdict(list)
_rate_hits_lock = threading.Lock()
_RATE_MAX = 60  # max requests per minute per IP
_RATE_WINDOW = 60.0


# ---------------------------------------------------------------------------
# Request Payloads
# ---------------------------------------------------------------------------
class ProviderTestPayload(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def _check_rate_limit(request: Optional[Request] = None):
    """Enforces client IP rate limit."""
    if request is None:
        return
    client_ip = (request.client.host if request.client else "testclient") or "testclient"
    now = time.monotonic()
    with _rate_hits_lock:
        hits = _rate_hits[client_ip]
        _rate_hits[client_ip] = [t for t in hits if now - t < _RATE_WINDOW]
        if len(_rate_hits[client_ip]) >= _RATE_MAX:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")
        _rate_hits[client_ip].append(now)


def _check_daily_budget():
    """Enforces daily and monthly spending caps if configured."""
    check_spend_budgets()


def _get_request_context(request: Optional[Request] = None) -> tuple[ResolvedCredentials, ModelRegistry]:
    """Extracts credentials and builds dynamic request-scoped ModelRegistry."""
    creds = resolve_request_credentials(request, settings)
    reg = ModelRegistry.from_credentials(creds, settings)
    return creds, reg


# ---------------------------------------------------------------------------
# Public Endpoints
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Context-Aware Smart LLM Switching API is running.", "docs": "/docs"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def health(request: Request):
    creds, reg = _get_request_context(request)
    return {
        "status": "ok",
        "mode": "real" if reg.has_real() else "demo",
        "architecture": "Context-Aware Smart LLM Switching (Disjoint LinUCB Contextual Router + 6 Response Model Tiers)",
        "version": "3.0.0",
        "models_count": len([m for m in reg.available() if m.tier != "analyzer"]),
        "providers": {
            "gemini": creds.has_gemini,
            "groq": creds.has_groq,
            "openrouter": creds.has_openrouter,
            "openai": creds.has_openai,
            "custom": creds.has_custom,
        },
        "tiers": {
            "analyzer": settings.gemini_analyzer_model,
            "tier_1": settings.gemini_tier1_model,
            "tier_2": settings.groq_tier2_model,
            "tier_3": settings.gemini_tier3_model,
            "tier_4": settings.groq_tier4_model,
            "tier_5": settings.groq_tier5_model,
            "tier_6": settings.gemini_tier6_model,
            "tier_6_fallback": settings.gemini_tier6_fallback_model,
        },
    }


@app.get("/api/providers/health", response_model=ProviderHealthResponse)
async def provider_health(request: Request):
    """Performs live connectivity check on each configured provider using request or server credentials."""
    creds, reg = _get_request_context(request)
    results = {}

    # Gemini check (Tier 1 or Analyzer)
    if creds.has_gemini:
        m = reg.get_by_tier("tier_1") or reg.get_analyzer()
        if m:
            try:
                t0 = time.perf_counter()
                adapter = adapter_factory.get("gemini")
                res = await adapter.generate(m, [ChatMessage(role="user", content="ping")])
                lat = (time.perf_counter() - t0) * 1000.0
                results["gemini"] = ProviderStatusItem(status="connected", latency_ms=round(lat, 1), model=m.endpoint_model)
            except Exception as e:
                results["gemini"] = ProviderStatusItem(status="error", error=str(e), model=m.endpoint_model)
        else:
            results["gemini"] = ProviderStatusItem(status="disabled")
    else:
        results["gemini"] = ProviderStatusItem(status="missing_api_key")

    # Groq check (Tier 2 or Tier 4)
    if creds.has_groq:
        m = reg.get_by_tier("tier_2") or reg.get_by_tier("tier_4") or reg.get_by_tier("tier_5")
        if m:
            try:
                t0 = time.perf_counter()
                adapter = adapter_factory.get("groq")
                res = await adapter.generate(m, [ChatMessage(role="user", content="ping")])
                lat = (time.perf_counter() - t0) * 1000.0
                results["groq"] = ProviderStatusItem(status="connected", latency_ms=round(lat, 1), model=m.endpoint_model)
            except Exception as e:
                results["groq"] = ProviderStatusItem(status="error", error=str(e), model=m.endpoint_model)
        else:
            results["groq"] = ProviderStatusItem(status="disabled")
    else:
        results["groq"] = ProviderStatusItem(status="missing_api_key")

    # OpenRouter check (optional)
    if creds.has_openrouter:
        m = reg.get_by_provider_and_tier("openrouter", "fast-backup") or reg.get_by_provider_and_tier("openrouter", "powerful")
        if m:
            try:
                t0 = time.perf_counter()
                adapter = adapter_factory.get("openrouter")
                res = await adapter.generate(m, [ChatMessage(role="user", content="ping")])
                lat = (time.perf_counter() - t0) * 1000.0
                results["openrouter"] = ProviderStatusItem(status="connected", latency_ms=round(lat, 1), model=m.endpoint_model)
            except Exception as e:
                results["openrouter"] = ProviderStatusItem(status="error", error=str(e), model=m.endpoint_model)
        else:
            results["openrouter"] = ProviderStatusItem(status="disabled")
    else:
        results["openrouter"] = ProviderStatusItem(status="missing_api_key")

    # OpenAI direct check (optional)
    if creds.has_openai:
        m = reg.get_by_provider_and_tier("openai", "tier_1") or reg.get_by_provider_and_tier("openai", "fast-backup")
        if m:
            try:
                t0 = time.perf_counter()
                adapter = adapter_factory.get("openai")
                res = await adapter.generate(m, [ChatMessage(role="user", content="ping")])
                lat = (time.perf_counter() - t0) * 1000.0
                results["openai"] = ProviderStatusItem(status="connected", latency_ms=round(lat, 1), model=m.endpoint_model)
            except Exception as e:
                results["openai"] = ProviderStatusItem(status="error", error=str(e), model=m.endpoint_model)
        else:
            results["openai"] = ProviderStatusItem(status="disabled")
    else:
        results["openai"] = ProviderStatusItem(status="missing_api_key")

    # Custom check (optional)
    if creds.has_custom:
        m = reg.get_by_provider_and_tier("custom", "custom")
        if m:
            try:
                t0 = time.perf_counter()
                adapter = adapter_factory.get("custom")
                res = await adapter.generate(m, [ChatMessage(role="user", content="ping")])
                lat = (time.perf_counter() - t0) * 1000.0
                results["custom"] = ProviderStatusItem(status="connected", latency_ms=round(lat, 1), model=m.endpoint_model)
            except Exception as e:
                results["custom"] = ProviderStatusItem(status="error", error=str(e), model=m.endpoint_model)
        else:
            results["custom"] = ProviderStatusItem(status="disabled")

    overall = "connected" if any(v.status == "connected" for v in results.values()) else ("missing_api_key" if not creds.has_real_providers else "degraded")

    return ProviderHealthResponse(
        gemini=results.get("gemini", ProviderStatusItem(status="missing_api_key")),
        groq=results.get("groq", ProviderStatusItem(status="missing_api_key")),
        openrouter=results.get("openrouter", ProviderStatusItem(status="missing_api_key")),
        openai=results.get("openai", ProviderStatusItem(status="missing_api_key")),
        custom=results.get("custom"),
        overall_status=overall,
    )


@app.post("/api/providers/test/{provider}", response_model=ProviderTestResponse)
async def test_single_provider(provider: str, request: Request, req: Optional[ProviderTestPayload] = None):
    """Tests a single provider connectivity with optional custom credentials."""
    prov = provider.lower().strip()
    creds, reg = _get_request_context(request)

    api_key = (req.api_key if (req and req.api_key) else None) or creds.get_key_for_provider(prov)
    base_url = (req.base_url if (req and req.base_url) else None) or getattr(settings, f"{prov}_base_url", "")
    model_name = (req.model if (req and req.model) else None)

    if not model_name:
        spec = reg.get_by_provider_and_tier(prov, "tier_1") or reg.get_by_provider_and_tier(prov, "tier_2") or reg.get_analyzer()
        model_name = spec.endpoint_model if spec else "default"

    test_spec = ModelSpec(
        model_id=f"{prov}-test",
        name=f"Test {prov}",
        provider=prov,
        endpoint_model=model_name,
        api_key=api_key or "",
        base_url=base_url or "",
        input_price_per_mtok=0.1,
        output_price_per_mtok=0.1,
        expected_latency_ms=300,
        quality=0.8,
        reasoning=0.8,
        coding=0.8,
        context_window=32768,
        tier="test",
        demo_mode=(not api_key and prov != "custom"),
        custom_endpoint=(prov == "custom"),
    )

    t0 = time.perf_counter()
    try:
        adapter = adapter_factory.get(prov)
        res = await adapter.generate(test_spec, [ChatMessage(role="user", content="Ping")])
        lat = (time.perf_counter() - t0) * 1000.0
        return ProviderTestResponse(ok=True, message=f"Connected successfully to {prov} ({model_name})", latency_ms=round(lat, 1), model=model_name)
    except Exception as exc:
        lat = (time.perf_counter() - t0) * 1000.0
        return ProviderTestResponse(ok=False, message=f"Failed to connect to {prov}: {exc}", latency_ms=round(lat, 1), model=model_name)


@app.get("/api/models")
async def list_models(request: Request):
    creds, reg = _get_request_context(request)
    return {"models": reg.to_public_list()}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, request: Request):
    """Analyze query and preview routing candidates using LinUCB & hard constraints."""
    _check_rate_limit(request)
    creds, reg = _get_request_context(request)
    strategy = req.strategy if req.strategy in STRATEGIES else "balanced"
    available = reg.available()

    if "FAIL-ANALYZER" in req.query:
        raise HTTPException(status_code=502, detail="Analyzer error: simulated outage")

    t0 = time.perf_counter()
    decision = _get_local_decision(req.query, history=req.history, available=available)
    x_t = feature_extractor.extract(req.query, history=req.history if decision.context_required else None)

    in_tok = estimate_tokens(req.query) + (
        sum(estimate_tokens(m.content if hasattr(m, "content") else str(m)) for m in (req.history or []))
        if decision.context_required
        else 0
    )
    out_tok = min(512, getattr(settings, "default_max_output_tokens", 512))
    candidate_models = [m for m in available if m.tier != "analyzer"] or available
    eligible_set = eligibility_filter.filter(
        models=candidate_models,
        estimated_input_tokens=in_tok,
        estimated_output_tokens=out_tok,
    )
    if eligible_set.eligible_count == 0:
        raise HTTPException(status_code=503, detail="No eligible models available.")

    bandit_decision = linucb_router.route(
        x_t,
        eligible_set.eligible_models,
        strategy=strategy,
        task_type=decision.task_type,
        complexity=decision.complexity,
    )
    primary_model = bandit_decision.selected_model
    candidates_list = [
        CandidateInfo(
            model_id=m.model_id,
            name=m.name,
            provider=m.provider,
            tier=m.tier,
            total=round(bandit_decision.scores[m.model_id].ucb_score, 4),
            expected_cost_usd=round(expected_request_cost(m, in_tok), 6),
            expected_latency_ms=round(m.expected_latency_ms, 1),
            selected=(m.model_id == primary_model.model_id),
            factors={
                "ucb_score": bandit_decision.scores[m.model_id].ucb_score,
                "expected_reward": bandit_decision.scores[m.model_id].expected_reward,
                "uncertainty": bandit_decision.scores[m.model_id].uncertainty,
                "pull_count": float(bandit_decision.scores[m.model_id].pull_count),
                "quality_suitability": m.quality,
                "reasoning_compatibility": m.reasoning,
                "coding_compatibility": m.coding,
            },
        )
        for m in [primary_model] + bandit_decision.fallback_chain
    ]
    analyzer_lat = (time.perf_counter() - t0) * 1000.0

    return AnalyzeResponse(
        analyzer=decision.to_analyzer_info(cost_usd=0.0),
        candidates=candidates_list,
        strategy=strategy,
    )


@app.post("/api/route/preview")
@app.get("/api/route/preview")
async def route_preview(
    request: Request,
    req: Optional[RoutePreviewRequest] = None,
    query: Optional[str] = None,
    strategy: Optional[str] = "balanced",
    max_budget_usd: Optional[float] = None,
    alpha: Optional[float] = None,
):
    """LinUCB route preview: evaluates hard constraints and upper confidence bounds without invoking model."""
    _check_rate_limit(request)
    creds, reg = _get_request_context(request)

    prompt_query = req.query if (req and req.query) else (query or "")
    if not prompt_query:
        raise HTTPException(status_code=422, detail="query parameter is required")

    prompt_history = req.history if req else []
    budget_cap = req.max_budget_usd if req else max_budget_usd
    alpha_override = req.alpha if req else alpha

    # 1. Feature extraction
    x_t = feature_extractor.extract(prompt_query, history=prompt_history)

    # 2. Token estimation
    in_tok = (
        req.estimated_input_tokens
        if (req and req.estimated_input_tokens is not None)
        else (estimate_tokens(prompt_query) + sum(estimate_tokens(m.content if hasattr(m, "content") else str(m)) for m in prompt_history))
    )
    out_tok = (
        req.estimated_output_tokens
        if (req and req.estimated_output_tokens is not None)
        else min(512, getattr(settings, "default_max_output_tokens", 512))
    )

    # 3. Hard-constraint eligibility filter
    available = reg.available()
    candidate_models = [m for m in available if m.tier != "analyzer"] or available
    eligible_set = eligibility_filter.filter(
        models=candidate_models,
        estimated_input_tokens=in_tok,
        estimated_output_tokens=out_tok,
        max_budget_usd=budget_cap,
    )

    if eligible_set.eligible_count == 0:
        reasons = "; ".join(
            f"{mid}: {reason}" for mid, reason in eligible_set.ineligible_models.items()
        ) or "No eligible models available."
        is_budget = any(
            "budget" in r.lower() or "cost" in r.lower() or "spend" in r.lower()
            for r in eligible_set.ineligible_models.values()
        )
        status_code = 429 if is_budget else 503
        raise HTTPException(
            status_code=status_code,
            detail={
                "message": f"No eligible models available: {reasons}",
                "eligibility": {
                    "total_evaluated": eligible_set.total_evaluated,
                    "eligible_count": 0,
                    "eligible_models": [],
                    "ineligible_models": eligible_set.ineligible_models,
                },
            },
        )

    # 4. LinUCB Contextual Router
    decision = linucb_router.route(
        x_t,
        eligible_set.eligible_models,
        alpha=alpha_override,
        strategy=strategy,
    )

    scores_dict = {
        mid: {
            "model_id": mid,
            "ucb_score": round(score.ucb_score, 4),
            "expected_reward": round(score.expected_reward, 4),
            "uncertainty": round(score.uncertainty, 4),
            "pull_count": score.pull_count,
        }
        for mid, score in decision.scores.items()
    }

    candidate_arm_scores = [
        {
            "model_id": mid,
            "ucb_score": round(score.ucb_score, 4),
            "expected_reward": round(score.expected_reward, 4),
            "uncertainty": round(score.uncertainty, 4),
            "pull_count": score.pull_count,
            "selected": mid == decision.selected_model.model_id,
        }
        for mid, score in decision.scores.items()
    ]

    return {
        "feature_vector": x_t.tolist(),
        "selected_model": {
            "model_id": decision.selected_model.model_id,
            "name": decision.selected_model.name,
            "provider": decision.selected_model.provider,
            "tier": decision.selected_model.tier,
        },
        "fallback_chain": [
            {
                "model_id": m.model_id,
                "name": m.name,
                "provider": m.provider,
                "tier": m.tier,
            }
            for m in decision.fallback_chain
        ],
        "bandit_score": decision.scores[decision.selected_model.model_id].ucb_score,
        "expected_reward": decision.scores[decision.selected_model.model_id].expected_reward,
        "uncertainty": decision.scores[decision.selected_model.model_id].uncertainty,
        "scores": scores_dict,
        "candidate_arm_scores": candidate_arm_scores,
        "eligibility": {
            "total_evaluated": eligible_set.total_evaluated,
            "eligible_count": eligible_set.eligible_count,
            "eligible_models": [m.model_id for m in eligible_set.eligible_models],
            "ineligible_models": eligible_set.ineligible_models,
        },
        "estimated_tokens": {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
        },
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    """Unary chat endpoint: executes query with context management, routing, Box 6 quality check & escalation."""
    _check_rate_limit(request)
    creds, reg = _get_request_context(request)
    return await run_unary_chat(
        req.query,
        req.history,
        req.strategy,
        reg,
        deadline_ms=getattr(req, "deadline_ms", None),
        max_budget_usd=getattr(req, "max_budget_usd", None),
        session_last_model_id=getattr(req, "session_last_model_id", None),
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE Streaming endpoint emitting typed events: analyzer -> routing -> reasoning_delta -> delta -> done."""
    _check_rate_limit(request)
    creds, reg = _get_request_context(request)

    async def event_generator():
        async for evt in iter_chat_sse(
            req.query,
            req.history,
            req.strategy,
            reg,
            disconnected=request.is_disconnected,
            deadline_ms=getattr(req, "deadline_ms", None),
            max_budget_usd=getattr(req, "max_budget_usd", None),
            session_last_model_id=getattr(req, "session_last_model_id", None),
        ):
            yield f"data: {json.dumps(evt)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/feedback", response_model=FeedbackResponse)
async def feedback(req: FeedbackRequest):
    ok = tracker.record_feedback(req.request_id, req.rating)
    if not ok:
        raise HTTPException(status_code=404, detail="Request not found.")
    return FeedbackResponse(ok=True, message="Feedback recorded.")


@app.get("/api/stats")
@app.get("/api/metrics")
async def stats():
    stats_data = tracker.dashboard_stats()
    bandit_arms = {
        mid: {
            "model_id": mid,
            "pull_count": arm.pull_count,
            "total_reward": round(arm.total_reward, 4),
            "mean_reward": round(arm.total_reward / arm.pull_count, 4) if arm.pull_count > 0 else 0.0,
            "alpha": arm.alpha,
        }
        for mid, arm in linucb_router.arms.items()
    }
    stats_data["bandit_arms"] = bandit_arms
    stats_data["bandit"] = {
        "total_arms": len(bandit_arms),
        "arms": bandit_arms,
        "total_pulls": sum(a.pull_count for a in linucb_router.arms.values()),
    }
    return stats_data


@app.get("/api/requests/{request_id}")
async def request_detail(request_id: int):
    detail = tracker.request_detail(request_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Request not found.")
    return detail


@app.get("/api/history")
async def history(limit: int = 20):
    return tracker.recent_requests(limit=min(max(limit, 1), 100))


@app.get("/api/benchmark/matrix")
async def benchmark_matrix(request: Request):
    """Returns dynamic model comparison matrix with capabilities, latency, and costs."""
    creds, reg = _get_request_context(request)
    models = reg.available()
    return {
        "matrix": [
            {
                "model_id": m.model_id,
                "name": m.name,
                "provider": m.provider,
                "tier": m.tier,
                "quality": m.quality,
                "reasoning": m.reasoning,
                "coding": m.coding,
                "input_price_per_mtok": m.input_price_per_mtok,
                "output_price_per_mtok": m.output_price_per_mtok,
                "expected_latency_ms": m.expected_latency_ms,
                "context_window": m.context_window,
                "fallback_model": m.fallback_model,
            }
            for m in models
        ]
    }


BENCHMARK_DEFAULT_QUERIES = [
    "What is an HTTP request header?",
    "Write a Python function to implement binary search with recursion.",
    "Design a high-throughput, fault-tolerant distributed message broker like Apache Kafka.",
    "Explain the time complexity differences between QuickSort and MergeSort in 2 sentences.",
    "Write a SQL query with window functions to calculate 7-day rolling revenue per customer.",
]
BENCHMARK_MAX_QUERIES = 8


@app.post("/api/benchmark/run", response_model=BenchmarkResult)
async def run_benchmark(req: BenchmarkRunRequest, request: Request):
    """Comparative Experiment: Baseline 1 (Tier 6), Baseline 2 (Static Routing), Smart Router."""
    creds, reg = _get_request_context(request)
    _check_rate_limit(request)
    sample_queries = (req.queries or BENCHMARK_DEFAULT_QUERIES)[:BENCHMARK_MAX_QUERIES]
    if not sample_queries:
        raise HTTPException(status_code=422, detail="At least one benchmark query is required.")

    available = reg.available()
    powerful_model = reg.get_by_tier("tier_6") or reg.strongest()
    fast_model = reg.get_by_tier("tier_1") or reg.get_by_tier("tier_2")
    coding_model = reg.get_by_tier("tier_4")
    if not powerful_model or not (fast_model or coding_model):
        raise HTTPException(
            status_code=503,
            detail="Benchmark requires Tier 6 baseline and response models in the registry.",
        )

    execution_mode = "real" if reg.has_real() else "demo"

    async def _run_baseline(model, query: str):
        adapter = adapter_factory.get_for_model(model)
        messages = build_messages(history=[], query=query, max_tokens=2048, tier=model.tier)
        res = await adapter.generate(model, messages)
        in_tok = res.input_tokens or 0
        out_tok = res.output_tokens or 0
        in_p = model.input_price_per_mtok or 0.0
        out_p = model.output_price_per_mtok or 0.0
        cost = (in_tok * in_p + out_tok * out_p) / 1_000_000.0
        return model.name, cost, res.latency_ms

    async def _run_smart(query: str):
        chat_resp = await run_unary_chat(query, [], "balanced", reg)
        model_name = (
            chat_resp.selected_model
            or (chat_resp.model.model_name if chat_resp.model else "LinUCB Router")
        )
        cost = chat_resp.total_cost_usd or 0.0
        lat = chat_resp.total_latency_ms or 0.0
        return model_name, cost, lat, chat_resp.analyzer

    items = []
    b1_total = b1_lat_sum = b2_total = b2_lat_sum = smart_total = smart_lat_sum = 0.0

    for query in sample_queries:
        is_code = any(k in query.lower() for k in ("python", "function", "sql", "code", "algorithm"))
        b2_model = (coding_model if is_code else fast_model) or powerful_model

        b1_r, b2_r, smart_r = await asyncio.gather(
            _run_baseline(powerful_model, query),
            _run_baseline(b2_model, query),
            _run_smart(query),
            return_exceptions=True,
        )

        errors = []
        if isinstance(b1_r, Exception):
            errors.append(f"baseline1: {b1_r}")
            b1_m = powerful_model.name
            b1_cost = 0.0
            b1_lat = 0.0
        else:
            b1_m, b1_cost, b1_lat = b1_r
            b1_cost = b1_cost or 0.0
            b1_lat = b1_lat or 0.0

        if isinstance(b2_r, Exception):
            errors.append(f"baseline2: {b2_r}")
            b2_m = b2_model.name
            b2_cost = 0.0
            b2_lat = 0.0
        else:
            b2_m, b2_cost, b2_lat = b2_r
            b2_cost = b2_cost or 0.0
            b2_lat = b2_lat or 0.0

        if isinstance(smart_r, Exception):
            errors.append(f"smart: {smart_r}")
            smart_name, smart_cost, smart_lat, decision = "Smart Router (Error)", 0.0, 0.0, None
        else:
            smart_name, smart_cost, smart_lat, decision = smart_r
            smart_cost = smart_cost or 0.0
            smart_lat = smart_lat or 0.0

        task_type = decision.task_type if decision else "unknown"
        complexity = decision.complexity if decision else "unknown"

        savings_pct = max(0.0, ((b1_cost - smart_cost) / b1_cost * 100.0)) if b1_cost > 0 else 0.0
        speedup_pct = max(0.0, ((b1_lat - smart_lat) / b1_lat * 100.0)) if b1_lat > smart_lat else 0.0

        b1_total += b1_cost
        b1_lat_sum += b1_lat
        b2_total += b2_cost
        b2_lat_sum += b2_lat
        smart_total += smart_cost
        smart_lat_sum += smart_lat

        items.append(BenchmarkComparisonItem(
            query=query,
            task_type=task_type,
            complexity=complexity,
            baseline1_model=b1_m,
            baseline1_cost_usd=round(b1_cost, 6),
            baseline1_latency_ms=round(b1_lat, 1),
            baseline2_model=b2_m,
            baseline2_cost_usd=round(b2_cost, 6),
            baseline2_latency_ms=round(b2_lat, 1),
            smart_model=smart_name,
            smart_cost_usd=round(smart_cost, 6),
            smart_latency_ms=round(smart_lat, 1),
            smart_savings_percent=round(savings_pct, 1),
            smart_speedup_percent=round(speedup_pct, 1),
            error="; ".join(errors) if errors else None,
        ))

    n = len(items) or 1
    saved_cost = max(0.0, b1_total - smart_total)
    overall_savings_pct = (saved_cost / b1_total * 100.0) if b1_total > 0 else 0.0
    overall_speedup_pct = ((b1_lat_sum - smart_lat_sum) / b1_lat_sum * 100.0) if b1_lat_sum > smart_lat_sum else 0.0

    res = BenchmarkResult(
        total_queries=n,
        baseline1_total_cost_usd=round(b1_total, 6),
        baseline1_avg_latency_ms=round(b1_lat_sum / n, 1),
        baseline2_total_cost_usd=round(b2_total, 6),
        baseline2_avg_latency_ms=round(b2_lat_sum / n, 1),
        smart_total_cost_usd=round(smart_total, 6),
        smart_avg_latency_ms=round(smart_lat_sum / n, 1),
        total_cost_saved_usd=round(saved_cost, 6),
        overall_cost_savings_percent=round(overall_savings_pct, 1),
        overall_speedup_percent=round(overall_speedup_pct, 1),
        items=items,
        execution_mode=execution_mode,
    )

    tracker.record_benchmark(res.model_dump())
    return res


@app.get("/api/settings")
async def get_settings(request: Request):
    creds, reg = _get_request_context(request)
    return {
        "analyzer_model": creds.gemini_analyzer_model or settings.gemini_analyzer_model,
        "tier_1_model": creds.gemini_tier1_model or settings.gemini_tier1_model,
        "tier_2_model": creds.groq_tier2_model or settings.groq_tier2_model,
        "tier_3_model": creds.gemini_tier3_model or settings.gemini_tier3_model,
        "tier_4_model": creds.groq_tier4_model or settings.groq_tier4_model,
        "tier_5_model": creds.groq_tier5_model or settings.groq_tier5_model,
        "tier_6_model": creds.gemini_tier6_model or settings.gemini_tier6_model,
        "tier_6_fallback": settings.gemini_tier6_fallback_model,
        "daily_budget_usd": settings.daily_budget_usd,
        "max_cost_per_request": getattr(settings, "max_cost_per_request", 0.0),
        "request_timeout_seconds": settings.request_timeout_seconds,
        "has_gemini_key": creds.has_gemini,
        "has_groq_key": creds.has_groq,
        "has_openai_key": creds.has_openai,
        "has_custom": creds.has_custom,
    }


# Mount Frontend / Static Files directory if it exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/frontend", StaticFiles(directory=STATIC_DIR), name="frontend")