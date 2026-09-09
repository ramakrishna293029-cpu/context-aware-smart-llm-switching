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
    hits = _rate_hits[client_ip]
    _rate_hits[client_ip] = [t for t in hits if now - t < _RATE_WINDOW]
    if len(_rate_hits[client_ip]) >= _RATE_MAX:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")
    _rate_hits[client_ip].append(now)


def _check_daily_budget():
    """Enforces daily spending cap if configured."""
    if getattr(settings, "daily_budget_usd", 0.0) > 0:
        status = tracker.budget_status()
        if status["day_spend"] >= settings.daily_budget_usd:
            raise HTTPException(status_code=429, detail="Daily budget exceeded. Request rejected.")


def _get_request_context(request: Request) -> tuple[ResolvedCredentials, ModelRegistry]:
    """Extracts credentials and builds dynamic request-scoped ModelRegistry."""
    creds = resolve_request_credentials(request, settings)
    reg = ModelRegistry.from_credentials(creds, settings)
    return creds, reg


def _compute_cost(model: ModelSpec, result: Optional[LLMResult]) -> Optional[float]:
    if not result or result.input_tokens is None or result.output_tokens is None:
        return None
    return estimate_cost_usd(
        (model.input_price_per_mtok, model.output_price_per_mtok),
        result.input_tokens,
        result.output_tokens,
    )


def _compute_baseline_cost(reg: ModelRegistry, tokens: Optional[tuple[Optional[int], Optional[int]]]) -> Optional[float]:
    """Calculates what the request would have cost on the strongest available baseline model."""
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


async def _execute_with_fallback(
    messages: List[ChatMessage],
    chain: List[ModelSpec],
) -> tuple[ModelSpec, LLMResult, bool, Optional[str]]:
    """Tries primary model, falling back through candidate chain on error."""
    if not chain:
        raise LLMAdapterError("No candidate models available in fallback chain.")

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
    _check_rate_limit(request)
    _check_daily_budget()

    if "FAIL-ANALYZER" in req.query:
        raise HTTPException(status_code=502, detail="Analyzer execution failed: simulated outage")

    creds, reg = _get_request_context(request)
    strategy = req.strategy if req.strategy in STRATEGIES else "balanced"
    available = reg.available()

    # Step 1: Run Analyzer LLM
    t_start = time.perf_counter()
    try:
        decision = await run_analyzer(req.query, req.history, available, strategy=strategy, registry_instance=reg)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analyzer execution failed: {exc}")

    analyzer_lat = (time.perf_counter() - t_start) * 1000.0
    analyzer_cost = _compute_cost(decision.analyzer_model, decision.analyzer_result) or 0.0

    # Step 2: Route & Resolve
    routing_res = default_router.resolve(
        decision,
        strategy=strategy,
        registry=reg,
        latency_profile=tracker.get_latency_profile(),
        feedback_modifiers=tracker.get_feedback_modifiers(),
    )
    primary_model = routing_res.primary_model
    fallback_chain = routing_res.fallback_chain

    # Filter candidate models by max_cost_per_request if configured
    max_cost_cap = getattr(settings, "max_cost_per_request", 0.0)
    if max_cost_cap > 0:
        filtered_chain = [m for m in fallback_chain if (m.price_per_1k * 1.5) <= max_cost_cap]
        if not filtered_chain:
            raise HTTPException(status_code=429, detail="Cost per request budget exceeded. No candidate fits cap.")
        fallback_chain = filtered_chain
        primary_model = filtered_chain[0]

    # Step 3: Self-Mode vs Switch-Mode Execution
    # Guard: self-mode requires a real analyzer-produced answer. If absent
    # (canned text is prohibited), fall through to switch-mode so a real
    # provider generates the response.
    if decision.answer_mode == "self" and decision.answer:
        # SELF-MODE: Direct base answer without extra downstream call!
        response_text = decision.answer
        served_model = decision.analyzer_model
        fallback_used = False
        fallback_reason = None
        success = True
        error_text = None
        gen_lat = 0.0
        total_lat = (time.perf_counter() - t_start) * 1000.0

        in_tok = decision.analyzer_result.input_tokens
        out_tok = decision.analyzer_result.output_tokens
        tot_tok = (in_tok or 0) + (out_tok or 0)
        model_cost = analyzer_cost
        total_cost = analyzer_cost
        # Honest baseline: genuine strongest-model pricing at the request's
        # actual token usage — or None when no real provider is configured.
        # Never fabricate savings with invented multipliers.
        baseline_cost = _compute_baseline_cost(reg, (in_tok, out_tok))
        savings_usd = max(0.0, baseline_cost - total_cost) if baseline_cost else 0.0
        savings_pct = (savings_usd / baseline_cost * 100.0) if baseline_cost else 0.0
        candidates_list = routing_res.to_candidate_infos()

        req_id = tracker.record_request(
            query=req.query,
            task_type=decision.task_type,
            complexity=decision.complexity,
            complexity_score=decision.complexity_score,
            answer_mode="self",
            analyzer_provider=decision.analyzer_model.provider,
            analyzer_model=decision.analyzer_model.endpoint_model,
            analyzer_latency_ms=analyzer_lat,
            analyzer_input_tokens=in_tok,
            analyzer_output_tokens=out_tok,
            analyzer_cost=analyzer_cost,
            target_tier="fast",
            target_provider=decision.analyzer_model.provider,
            selected_model=served_model.endpoint_model,
            selected_provider=served_model.provider,
            routing_reason=decision.reason,
            context_relevant=decision.context_required,
            input_tokens=None,
            output_tokens=None,
            reasoning_tokens=0,
            total_tokens=tot_tok,
            latency_ms=gen_lat,
            total_latency_ms=total_lat,
            ttft_ms=analyzer_lat,
            estimated_cost=analyzer_cost,
            analyzer_cost_usd=analyzer_cost,
            total_cost_usd=total_cost,
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

        return ChatResponse(
            response=response_text,
            answer_mode="self",
            model=ModelInfo(
                model_id=served_model.model_id,
                model_name=served_model.name,
                provider=served_model.provider,
                tier=served_model.tier,
                mode=served_model.mode,
                strategy=strategy,
                reason=decision.reason,
            ),
            analyzer=decision.to_analyzer_info(cost_usd=analyzer_cost),
            context_relevant=decision.context_required,
            input_tokens=None,
            output_tokens=None,
            reasoning_tokens=0,
            total_tokens=tot_tok,
            estimated_cost_usd=round(analyzer_cost, 6),
            analyzer_cost_usd=round(analyzer_cost, 6),
            total_cost_usd=round(total_cost, 6),
            baseline_cost_usd=round(baseline_cost, 6) if baseline_cost is not None else None,
            savings_usd=round(savings_usd, 6),
            savings_percent=round(savings_pct, 1),
            latency_ms=round(gen_lat, 1),
            analyzer_latency_ms=round(analyzer_lat, 1),
            total_latency_ms=round(total_lat, 1),
            ttft_ms=round(analyzer_lat, 1),
            success=success,
            request_id=req_id,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            candidates=candidates_list,
        )

    # SWITCH-MODE: Prune context with ContextManager & execute specialized model with fallback
    messages = build_messages(
        history=req.history,
        query=req.query,
        max_tokens=primary_model.context_window,
        tier=primary_model.tier,
    )

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

    in_tok = result.input_tokens if result else None
    out_tok = result.output_tokens if result else None
    reasoning_toks = result.reasoning_tokens if result else 0
    tot_tok = ((in_tok or 0) + (out_tok or 0) + (decision.analyzer_result.input_tokens or 0) + (decision.analyzer_result.output_tokens or 0)) if result else None

    model_cost = _compute_cost(served_model, result) if result else 0.0
    total_cost = ((model_cost or 0.0) + analyzer_cost) if result else 0.0
    baseline_cost = _compute_baseline_cost(reg, (in_tok, out_tok)) if result else 0.0
    savings_usd = max(0.0, (baseline_cost or 0.0) - total_cost) if (baseline_cost and baseline_cost > 0) else 0.0
    savings_pct = (savings_usd / baseline_cost * 100.0) if (baseline_cost and baseline_cost > 0) else 0.0

    req_id = tracker.record_request(
        query=req.query,
        task_type=decision.task_type,
        complexity=decision.complexity,
        complexity_score=decision.complexity_score,
        answer_mode="switch",
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
        reasoning_tokens=reasoning_toks,
        total_tokens=tot_tok,
        latency_ms=gen_lat,
        total_latency_ms=total_lat,
        ttft_ms=result.ttft_ms if result else None,
        estimated_cost=model_cost,
        analyzer_cost_usd=analyzer_cost,
        total_cost_usd=total_cost,
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
        answer_mode="switch",
        model=ModelInfo(
            model_id=served_model.model_id,
            model_name=served_model.name,
            provider=served_model.provider,
            tier=served_model.tier,
            mode=served_model.mode,
            strategy=strategy,
            reason=decision.reason,
        ),
        analyzer=decision.to_analyzer_info(cost_usd=analyzer_cost),
        context_relevant=decision.context_required,
        input_tokens=in_tok,
        output_tokens=out_tok,
        reasoning_tokens=reasoning_toks,
        total_tokens=tot_tok,
        estimated_cost_usd=round(model_cost, 6) if model_cost is not None else None,
        analyzer_cost_usd=round(analyzer_cost, 6),
        total_cost_usd=round(total_cost, 6),
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
        candidates=routing_res.to_candidate_infos(),
    )


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE Streaming endpoint emitting typed events: analyzer -> routing -> reasoning_delta -> content_delta -> done."""
    _check_rate_limit(request)
    creds, reg = _get_request_context(request)
    strategy = req.strategy if req.strategy in STRATEGIES else "balanced"
    available = reg.available()

    async def event_generator():
        t_start = time.perf_counter()

        if "FAIL-ANALYZER" in req.query:
            yield "data: " + json.dumps({"event": "error", "detail": "Analyzer error: simulated outage"}) + "\n\n"
            return

        # Step 1: Run Analyzer LLM
        try:
            decision = await run_analyzer(req.query, req.history, available, strategy=strategy, registry_instance=reg)
        except Exception as exc:
            yield "data: " + json.dumps({"event": "error", "detail": f"Analyzer error: {exc}"}) + "\n\n"
            return

        analyzer_lat = (time.perf_counter() - t_start) * 1000.0
        analyzer_cost = _compute_cost(decision.analyzer_model, decision.analyzer_result) or 0.0

        # Emit typed Analyzer Event
        yield "data: " + json.dumps({
            "event": "analyzer",
            "info": decision.to_analyzer_info(cost_usd=analyzer_cost).model_dump(),
        }) + "\n\n"

        # Step 2: Self-Mode vs Switch-Mode
        # Guard: self-mode must carry a real analyzer answer (no canned text).
        if decision.answer_mode == "self" and decision.answer:
            ans_text = decision.answer
            words = ans_text.split(" ")
            for i in range(0, len(words), 3):
                chunk = " ".join(words[i:i + 3])
                if i + 3 < len(words):
                    chunk += " "
                yield "data: " + json.dumps({"event": "content_delta", "text": chunk}) + "\n\n"
                yield "data: " + json.dumps({"event": "delta", "text": chunk}) + "\n\n"

            gen_lat = 0.0
            total_lat = (time.perf_counter() - t_start) * 1000.0
            in_tok = decision.analyzer_result.input_tokens
            out_tok = decision.analyzer_result.output_tokens
            tot_tok = (in_tok or 0) + (out_tok or 0)
            baseline_cost = _compute_baseline_cost(reg, (in_tok, out_tok))
            savings_usd = max(0.0, baseline_cost - analyzer_cost) if baseline_cost else 0.0
            savings_pct = (savings_usd / baseline_cost * 100.0) if baseline_cost else 0.0

            req_id = tracker.record_request(
                query=req.query,
                task_type=decision.task_type,
                complexity=decision.complexity,
                complexity_score=decision.complexity_score,
                answer_mode="self",
                analyzer_provider=decision.analyzer_model.provider,
                analyzer_model=decision.analyzer_model.endpoint_model,
                analyzer_latency_ms=analyzer_lat,
                analyzer_input_tokens=in_tok,
                analyzer_output_tokens=out_tok,
                analyzer_cost=analyzer_cost,
                target_tier="fast",
                target_provider=decision.analyzer_model.provider,
                selected_model=decision.analyzer_model.endpoint_model,
                selected_provider=decision.analyzer_model.provider,
                routing_reason=decision.reason,
                context_relevant=decision.context_required,
                input_tokens=None,
                output_tokens=None,
                reasoning_tokens=0,
                total_tokens=tot_tok,
                latency_ms=gen_lat,
                total_latency_ms=total_lat,
                ttft_ms=analyzer_lat,
                estimated_cost=analyzer_cost,
                analyzer_cost_usd=analyzer_cost,
                total_cost_usd=analyzer_cost,
                baseline_cost=baseline_cost,
                savings_usd=savings_usd,
                savings_percent=savings_pct,
                success=True,
                fallback_used=False,
                strategy=strategy,
            )

            yield "data: " + json.dumps({
                "event": "done",
                "success": True,
                "request_id": req_id,
                "response": ans_text,
                "answer_mode": "self",
                "model": {
                    "model_id": decision.analyzer_model.model_id,
                    "model_name": decision.analyzer_model.name,
                    "provider": decision.analyzer_model.provider,
                    "tier": decision.analyzer_model.tier,
                    "reason": decision.reason,
                },
                "analyzer": decision.to_analyzer_info(cost_usd=analyzer_cost).model_dump(),
                "context_relevant": decision.context_required,
                "input_tokens": None,
                "output_tokens": None,
                "reasoning_tokens": 0,
                "total_tokens": tot_tok,
                "estimated_cost_usd": round(analyzer_cost, 6),
                "analyzer_cost_usd": round(analyzer_cost, 6),
                "total_cost_usd": round(analyzer_cost, 6),
                "baseline_cost_usd": round(baseline_cost, 6) if baseline_cost is not None else None,
                "savings_usd": round(savings_usd, 6),
                "savings_percent": round(savings_pct, 1),
                "latency_ms": round(gen_lat, 1),
                "analyzer_latency_ms": round(analyzer_lat, 1),
                "total_latency_ms": round(total_lat, 1),
                "ttft_ms": round(analyzer_lat, 1),
                "fallback_used": False,
                "candidates": [],
            }) + "\n\n"
            return

        # SWITCH-MODE: Routing Event + Target Streaming
        routing_res = default_router.resolve(
            decision,
            strategy=strategy,
            registry=reg,
            latency_profile=tracker.get_latency_profile(),
            feedback_modifiers=tracker.get_feedback_modifiers(),
        )
        target_model = routing_res.primary_model
        fallback_chain = routing_res.fallback_chain

        yield "data: " + json.dumps({
            "event": "routing",
            "target_model": target_model.endpoint_model,
            "target_name": target_model.name,
            "target_provider": target_model.provider,
            "target_tier": target_model.tier,
            "reason": decision.reason,
            "answer_mode": "switch",
            "context_relevant": decision.context_required,
            "candidates": routing_res.candidates(),
        }) + "\n\n"

        messages = build_messages(
            history=req.history,
            query=req.query,
            max_tokens=target_model.context_window,
            tier=target_model.tier,
        )

        served_model = target_model
        full_text = []
        full_reasoning = []
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
                    async for chunk in adapter.stream_chunks(cand, messages):
                        if chunk.is_final:
                            continue
                        if ttft_ms is None:
                            ttft_ms = (time.perf_counter() - t_gen) * 1000.0

                        if chunk.reasoning_text:
                            full_reasoning.append(chunk.reasoning_text)
                            yield "data: " + json.dumps({"event": "reasoning_delta", "text": chunk.reasoning_text}) + "\n\n"

                        if chunk.text:
                            full_text.append(chunk.text)
                            yield "data: " + json.dumps({"event": "content_delta", "text": chunk.text}) + "\n\n"
                            yield "data: " + json.dumps({"event": "delta", "text": chunk.text}) + "\n\n"

                    result = getattr(adapter, "last_result", lambda: None)()
                else:
                    result = await adapter.generate(cand, messages)
                    if result.reasoning_content:
                        full_reasoning.append(result.reasoning_content)
                        yield "data: " + json.dumps({"event": "reasoning_delta", "text": result.reasoning_content}) + "\n\n"
                    if result.content:
                        full_text.append(result.content)
                        yield "data: " + json.dumps({"event": "content_delta", "text": result.content}) + "\n\n"
                        yield "data: " + json.dumps({"event": "delta", "text": result.content}) + "\n\n"
                break
            except Exception as exc:
                logger.warning("Streaming failed for %s: %s", cand.model_id, exc)
                continue
        else:
            yield "data: " + json.dumps({"event": "error", "detail": "All candidate models in fallback chain failed."}) + "\n\n"
            return

        gen_lat = (time.perf_counter() - t_gen) * 1000.0
        total_lat = (time.perf_counter() - t_start) * 1000.0
        resp_text = "".join(full_text)

        in_tok = result.input_tokens if result else max(1, len(req.query) // 4)
        out_tok = result.output_tokens if result else max(1, len(resp_text) // 4)
        reasoning_toks = result.reasoning_tokens if result else len("".join(full_reasoning)) // 4
        tot_tok = (in_tok + out_tok + (decision.analyzer_result.input_tokens or 0) + (decision.analyzer_result.output_tokens or 0))

        model_cost = _compute_cost(served_model, result) if result else 0.0
        total_cost = ((model_cost or 0.0) + analyzer_cost)
        baseline_cost = _compute_baseline_cost(reg, (in_tok, out_tok))
        savings_usd = max(0.0, baseline_cost - total_cost) if baseline_cost else 0.0
        savings_pct = (savings_usd / baseline_cost * 100.0) if baseline_cost else 0.0

        req_id = tracker.record_request(
            query=req.query,
            task_type=decision.task_type,
            complexity=decision.complexity,
            complexity_score=decision.complexity_score,
            answer_mode="switch",
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
            reasoning_tokens=reasoning_toks,
            total_tokens=tot_tok,
            latency_ms=gen_lat,
            total_latency_ms=total_lat,
            ttft_ms=ttft_ms,
            estimated_cost=model_cost,
            analyzer_cost_usd=analyzer_cost,
            total_cost_usd=total_cost,
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
            "answer_mode": "switch",
            "model": {
                "model_id": served_model.model_id,
                "model_name": served_model.name,
                "provider": served_model.provider,
                "tier": served_model.tier,
                "reason": decision.reason,
            },
            "analyzer": decision.to_analyzer_info(cost_usd=analyzer_cost).model_dump(),
            "context_relevant": decision.context_required,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "reasoning_tokens": reasoning_toks,
            "total_tokens": tot_tok,
            "estimated_cost_usd": round(model_cost, 6) if model_cost else None,
            "analyzer_cost_usd": round(analyzer_cost, 6),
            "total_cost_usd": round(total_cost, 6),
            "baseline_cost_usd": round(baseline_cost, 6) if baseline_cost is not None else None,
            "savings_usd": round(savings_usd, 6),
            "savings_percent": round(savings_pct, 1),
            "latency_ms": round(gen_lat, 1),
            "analyzer_latency_ms": round(analyzer_lat, 1),
            "total_latency_ms": round(total_lat, 1),
            "ttft_ms": round(ttft_ms, 1) if ttft_ms else None,
            "fallback_used": fallback_used,
            "candidates": routing_res.candidates(),
        }) + "\n\n"

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