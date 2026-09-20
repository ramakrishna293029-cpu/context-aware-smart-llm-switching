"""FastAPI Application: Context-Aware Smart LLM Switching for Cost & Performance Optimization.

Request Flow:
USER QUERY
  │
  ▼
RESOLVE CREDENTIALS & DYNAMIC REGISTRY (Headers -> Settings -> Mock)
  │
  ▼
CHECK BUDGET & RATE LIMITS
  │
  ▼
ANALYZER LLM (meta-llama/llama-3.2-3b-instruct or configured Base Analyzer)
  │ (Produces structured complexity, task type, self vs switch decision)
  │
  ├──► [answer_mode == "self"]: Base model directly answered in 1 cheap call!
  │    (Bypasses downstream models -> Ultra-low latency & 100% downstream savings)
  │
  └──► [answer_mode == "switch"]: Smart Multi-Factor Router
       │ (Evaluates quality, complexity, reasoning, coding, cost, latency)
       ├──► GEMINI (Fast / Low-Cost Model: gemini-2.5-flash-lite / gemini-2.5-flash)
       ├──► GROQ (Coding Model: qwen3.6-27b / reasoning: gpt-oss-120b)
       ├──► OPENAI (Direct GPT-4o / GPT-4o-mini / o3-mini)
       ├──► CUSTOM (Ollama / vLLM / Azure endpoints)
       └──► OPENROUTER (Unified fallback gateway & powerful baseline)
       │
       ▼
EXECUTE WITH FALLBACK RESILIENCE & CONTEXT TOKEN BUDGETING
  │
  ▼
STORE TELEMETRY (Tokens, Latencies, Real Cost vs Baseline, Savings)
  │
  ▼
RETURN TRANSPARENT RESPONSE & SSE STREAMING
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
from .analyzer_llm import AnalyzerDecision, run_analyzer
from .config import settings
from .context import build_messages
from .pipeline import (
    check_spend_budgets,
    compute_cost as _compute_cost,
    compute_baseline_cost as _compute_baseline_cost,
    execute_with_fallback as _execute_with_fallback,
    iter_chat_sse,
    run_unary_chat,
)
from .registry import ModelRegistry, ModelSpec, registry as default_registry
from .router import STRATEGIES, RoutingResult, router as default_router
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
    ModelInfo,
    ProviderHealthResponse,
    ProviderStatusItem,
    ProviderTestResponse,
)
from .security import (
    ResolvedCredentials,
    resolve_request_credentials,
)
from .tracker import estimate_cost_usd, tracker

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Context-Aware Smart LLM Router",
    version="2.5.0",
    description="Context-Aware Smart LLM Switching with Dynamic Multi-Provider Routing and SSE Streaming",
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
adapter_factory.set_default(openai_adapter)

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
def _check_rate_limit(request: Request):
    """Enforces client IP rate limit."""
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


def _get_request_context(request: Request) -> tuple[ResolvedCredentials, ModelRegistry]:
    """Extracts credentials and builds dynamic request-scoped ModelRegistry."""
    creds = resolve_request_credentials(request, settings)
    reg = ModelRegistry.from_credentials(creds, settings)
    return creds, reg


_HEALTH_CACHE: dict = {"ts": 0.0, "payload": None}
_HEALTH_CACHE_TTL = 60.0


# ---------------------------------------------------------------------------
# Public Endpoints
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Context-Aware Smart LLM Switching API is running.", "docs": "/docs"}


@app.get("/health")
async def health(request: Request):
    creds, reg = _get_request_context(request)
    return {
        "status": "ok",
        "mode": "real" if reg.has_real() else "demo",
        "architecture": "analyzer-llm",
        "version": "2.5.0",
        "models_count": len(reg.available()),
        "providers": {
            "openrouter": creds.has_openrouter,
            "gemini": creds.has_gemini,
            "groq": creds.has_groq,
            "openai": creds.has_openai,
            "custom": creds.has_custom,
        },
        "configured_models": {
            "analyzer": creds.base_model or settings.analyzer_model,
            "fast_gemini": creds.fast_model or settings.gemini_fast_model,
            "coding_groq": creds.coding_model or settings.groq_coding_model,
            "reasoning_groq": creds.reasoning_model or settings.groq_reasoning_model,
            "openai_model": settings.openai_model,
        },
    }


@app.get("/api/providers/health", response_model=ProviderHealthResponse)
async def provider_health(request: Request):
    """Performs live connectivity check on each configured provider using request or server credentials."""
    creds, reg = _get_request_context(request)
    results = {}

    # OpenRouter check
    if creds.has_openrouter:
        m = reg.get_by_provider_and_tier("openrouter", "fast-backup") or reg.get_by_provider_and_tier("openrouter", "analyzer")
        if not m:
            m = reg.get_by_provider_and_tier("openrouter", "powerful")
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

    # Gemini check
    if creds.has_gemini:
        m = reg.get_by_provider_and_tier("gemini", "fast") or reg.get_by_provider_and_tier("gemini", "powerful")
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

    # Groq check
    if creds.has_groq:
        m = reg.get_by_provider_and_tier("groq", "coding") or reg.get_by_provider_and_tier("groq", "reasoning") or reg.get_by_provider_and_tier("groq", "fast-backup")
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

    # OpenAI direct check
    if creds.has_openai:
        m = reg.get_by_provider_and_tier("openai", "fast-backup") or reg.get_by_provider_and_tier("openai", "powerful")
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
        m = reg.get_by_provider_and_tier("custom", "custom") or reg.get_by_provider_and_tier("custom", "analyzer")
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
        spec = reg.get_by_provider_and_tier(prov, "fast") or reg.get_by_provider_and_tier(prov, "coding") or reg.get_by_provider_and_tier(prov, "analyzer")
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
    _check_rate_limit(request)
    creds, reg = _get_request_context(request)
    strategy = req.strategy if req.strategy in STRATEGIES else "balanced"
    available = reg.available()

    if "FAIL-ANALYZER" in req.query:
        raise HTTPException(status_code=502, detail="Analyzer error: simulated outage")

    t0 = time.perf_counter()
    try:
        decision = await run_analyzer(req.query, req.history[-settings.max_history_messages:], available, strategy=strategy, registry_instance=reg)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analyzer error: {exc}")

    analyzer_lat = (time.perf_counter() - t0) * 1000.0
    analyzer_cost = _compute_cost(decision.analyzer_model, decision.analyzer_result)

    routing_res = default_router.resolve(
        decision,
        strategy=strategy,
        registry=reg,
        latency_profile=tracker.get_latency_profile(),
        feedback_modifiers=tracker.get_feedback_modifiers(),
    )

    return AnalyzeResponse(
        analyzer=decision.to_analyzer_info(cost_usd=analyzer_cost),
        candidates=routing_res.to_candidate_infos(),
        strategy=strategy,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    """Unary chat endpoint: executes query with context management, routing, and fallback."""
    _check_rate_limit(request)
    creds, reg = _get_request_context(request)
    return await run_unary_chat(req.query, req.history, req.strategy, reg)


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
BENCHMARK_MAX_QUERIES = 8  # guard: each query triggers real billable provider calls


@app.post("/api/benchmark/run", response_model=BenchmarkResult)
async def run_benchmark(req: BenchmarkRunRequest, request: Request):
    """Real 3-Way Comparative Experiment (Section 27).

    Baseline 1 (always the strongest model), Baseline 2 (static tier heuristic),
    and the Smart Router (analyzer + multi-factor routing) are each executed as
    REAL provider calls — concurrently via asyncio.gather — with
    provider-reported token usage and measured wall-clock latency. Costs come
    from actual usage, never simulated formulas. In demo mode (no credentials)
    the run executes against the labeled mock adapter and is reported with
    execution_mode="demo".
    """
    creds, reg = _get_request_context(request)
    _check_rate_limit(request)
    sample_queries = (req.queries or BENCHMARK_DEFAULT_QUERIES)[:BENCHMARK_MAX_QUERIES]
    if not sample_queries:
        raise HTTPException(status_code=422, detail="At least one benchmark query is required.")

    available = reg.available()
    powerful_model = reg.strongest() or reg.get_by_tier("reasoning")
    fast_model = reg.get_by_tier("fast")
    coding_model = reg.get_by_tier("coding")
    if not powerful_model or not (fast_model or coding_model):
        raise HTTPException(
            status_code=503,
            detail="Benchmark requires a powerful baseline and a fast/coding model in the registry.",
        )

    execution_mode = "real" if reg.has_real() else "demo"

    async def _run_baseline(model, query: str):
        """Real single-model completion. Returns (model_name, cost, latency)."""
        adapter = adapter_factory.get_for_model(model)
        messages = build_messages(history=[], query=query, max_tokens=2048, tier=model.tier)
        res = await adapter.generate(model, messages)
        return model.name, _compute_cost(model, res), res.latency_ms

    async def _run_smart(query: str):
        """Real Smart-Router path: analyzer (real call) + routed generation."""
        decision = await run_analyzer(query, [], available, registry_instance=reg)
        if decision.answer_mode == "self" and decision.answer:
            # Self-mode: the analyzer call IS the final answer (1 call).
            return (
                decision.analyzer_model.name,
                _compute_cost(decision.analyzer_model, decision.analyzer_result) or 0.0,
                decision.analyzer_result.latency_ms,
                decision,
            )
        routing_res = default_router.resolve(
            decision,
            registry=reg,
            latency_profile=tracker.get_latency_profile(),
            feedback_modifiers=tracker.get_feedback_modifiers(),
        )
        smart_model = routing_res.primary_model
        adapter = adapter_factory.get_for_model(smart_model)
        messages = build_messages(history=[], query=query, max_tokens=2048, tier=smart_model.tier)
        gen = await adapter.generate(smart_model, messages)
        total_cost = (_compute_cost(decision.analyzer_model, decision.analyzer_result) or 0.0) + (_compute_cost(smart_model, gen) or 0.0)
        total_lat = decision.analyzer_result.latency_ms + gen.latency_ms
        return smart_model.name, total_cost, total_lat, decision

    items = []
    b1_total = b1_lat_sum = b2_total = b2_lat_sum = smart_total = smart_lat_sum = 0.0

    for query in sample_queries:
        # Baseline 2 static heuristic: coding keywords -> coding tier. This
        # simple keyword router IS Baseline 2 by definition — now measured
        # with real calls, not simulated.
        is_code = any(k in query.lower() for k in ("python", "function", "sql", "code", "algorithm"))
        b2_model = (coding_model if is_code else fast_model) or powerful_model

        # Real concurrent execution of all three paths (asyncio.gather).
        b1_r, b2_r, smart_r = await asyncio.gather(
            _run_baseline(powerful_model, query),
            _run_baseline(b2_model, query),
            _run_smart(query),
            return_exceptions=True,
        )

        errors = []
        if isinstance(b1_r, Exception):
            errors.append(f"baseline1: {b1_r}")
            b1_m, b1_cost, b1_lat = powerful_model.name, 0.0, 0.0
        else:
            b1_m, b1_cost, b1_lat = b1_r

        if isinstance(b2_r, Exception):
            errors.append(f"baseline2: {b2_r}")
            b2_m, b2_cost, b2_lat = b2_model.name, 0.0, 0.0
        else:
            b2_m, b2_cost, b2_lat = b2_r

        if isinstance(smart_r, Exception):
            errors.append(f"smart: {smart_r}")
            smart_name, smart_cost, smart_lat, decision = "unavailable", 0.0, 0.0, None
        else:
            smart_name, smart_cost, smart_lat, decision = smart_r

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
        "analyzer_model": creds.base_model or settings.analyzer_model,
        "gemini_fast_model": creds.fast_model or settings.gemini_fast_model,
        "groq_coding_model": creds.coding_model or settings.groq_coding_model,
        "groq_reasoning_model": creds.reasoning_model or settings.groq_reasoning_model,
        "openrouter_fast_model": settings.openrouter_fast_model,
        "openrouter_coding_model": settings.openrouter_coding_model,
        "openrouter_reasoning_model": settings.openrouter_reasoning_model,
        "openai_model": settings.openai_model,
        "custom_model": creds.custom_model or settings.custom_model,
        "custom_base_url": creds.custom_base_url or settings.custom_base_url,
        "daily_budget_usd": settings.daily_budget_usd,
        "max_cost_per_request": getattr(settings, "max_cost_per_request", 0.0),
        "request_timeout_seconds": settings.request_timeout_seconds,
        "has_openrouter_key": creds.has_openrouter,
        "has_gemini_key": creds.has_gemini,
        "has_groq_key": creds.has_groq,
        "has_openai_key": creds.has_openai,
        "has_custom": creds.has_custom,
    }


# Mount Static Files directory if it exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")