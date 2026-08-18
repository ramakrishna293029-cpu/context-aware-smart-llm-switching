"""Pydantic schemas shared between API layer, engine, and frontend."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# --- Core Chat Messages ---
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000, description="User prompt")
    history: List[ChatMessage] = Field(default_factory=list, description="Prior conversational turns")
    strategy: Literal["balanced", "lowest_cost", "fastest", "highest_quality"] = Field(
        default="balanced", description="Routing strategy"
    )


# --- Candidate Scoring ---
class CandidateInfo(BaseModel):
    model_id: str
    name: str
    provider: str
    tier: str
    total: float
    expected_cost_usd: float
    expected_latency_ms: float
    selected: bool
    factors: Dict[str, float] = Field(default_factory=dict)


# --- Analyzer Decision Contract ---
class AnalyzerInfo(BaseModel):
    """Telemetry for the Analyzer LLM call + decision."""
    model_id: str
    model_name: str
    provider: str
    answer_mode: Literal["self", "switch"] = "switch"
    task_type: str
    complexity: Literal["low", "medium", "high"] = "medium"
    complexity_score: float
    reasoning_required: bool = False
    coding_required: bool = False
    context_required: bool = False
    target_tier: str = "fast"
    target_provider: str = "gemini"
    target_model: Optional[str] = None
    reason: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: float = 0.0
    cost_usd: Optional[float] = None


# --- Model Execution Info ---
class ModelInfo(BaseModel):
    model_id: str
    model_name: str
    provider: str
    tier: str
    mode: Literal["real", "demo"] = "real"
    strategy: str = "balanced"
    reason: str


# --- Full Response Schema ---
class ChatResponse(BaseModel):
    response: str
    answer_mode: Literal["self", "switch"] = "switch"
    model: ModelInfo
    analyzer: AnalyzerInfo
    context_relevant: bool = False
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    analyzer_cost_usd: Optional[float] = None
    total_cost_usd: Optional[float] = None
    baseline_cost_usd: Optional[float] = None
    savings_usd: Optional[float] = None
    savings_percent: Optional[float] = None
    latency_ms: float                     # generation latency
    analyzer_latency_ms: float            # analyzer latency
    total_latency_ms: float               # total end-to-end latency
    ttft_ms: Optional[float] = None       # time-to-first-token
    success: bool = True
    request_id: int
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    escalation_used: bool = False
    escalation_reason: Optional[str] = None
    candidates: List[CandidateInfo] = Field(default_factory=list)


# --- Analyze Only Schemas ---
class AnalyzeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    history: List[ChatMessage] = Field(default_factory=list)
    strategy: str = Field(default="balanced", max_length=32)


class AnalyzeResponse(BaseModel):
    analyzer: AnalyzerInfo
    candidates: List[CandidateInfo] = Field(default_factory=list)
    strategy: str = "balanced"


# --- Feedback Schemas ---
class FeedbackRequest(BaseModel):
    request_id: int
    rating: int = Field(ge=-1, le=1)  # 1 = good, -1 = poor


class FeedbackResponse(BaseModel):
    ok: bool
    message: str


# --- Telemetry History ---
class HistoryRow(BaseModel):
    id: int
    timestamp: str
    query: str
    task_type: str
    complexity: str
    selected_model: str
    provider: str
    answer_mode: Optional[str] = "switch"
    fallback_used: bool = False
    escalation_used: bool = False
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    total_cost_usd: Optional[float] = None
    latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    success: bool = True
    feedback: Optional[int] = None
    routing_reason: Optional[str] = None
    analyzer_model: Optional[str] = None


# --- Benchmark Schemas ---
class BenchmarkRunRequest(BaseModel):
    queries: Optional[List[str]] = None
    include_reasoning: bool = True
    include_coding: bool = True
    include_factual: bool = True


class BenchmarkComparisonItem(BaseModel):
    query: str
    task_type: str
    complexity: str

    # Baseline 1: Always Powerful Model
    baseline1_model: str
    baseline1_cost_usd: float
    baseline1_latency_ms: float

    # Baseline 2: Static Routing
    baseline2_model: str
    baseline2_cost_usd: float
    baseline2_latency_ms: float

    # Our System: Context-Aware Smart LLM Switching
    smart_model: str
    smart_cost_usd: float
    smart_latency_ms: float
    smart_savings_percent: float
    smart_speedup_percent: float


class BenchmarkResult(BaseModel):
    total_queries: int
    baseline1_total_cost_usd: float
    baseline1_avg_latency_ms: float
    baseline2_total_cost_usd: float
    baseline2_avg_latency_ms: float
    smart_total_cost_usd: float
    smart_avg_latency_ms: float
    total_cost_saved_usd: float
    overall_cost_savings_percent: float
    overall_speedup_percent: float
    items: List[BenchmarkComparisonItem] = Field(default_factory=list)


# --- Provider Health & Test Schemas ---
class ProviderStatusItem(BaseModel):
    status: Literal["connected", "error", "missing_api_key", "disabled"]
    latency_ms: Optional[float] = None
    model: Optional[str] = None
    error: Optional[str] = None


class ProviderHealthResponse(BaseModel):
    gemini: ProviderStatusItem
    groq: ProviderStatusItem
    openrouter: ProviderStatusItem
    openai: ProviderStatusItem
    custom: Optional[ProviderStatusItem] = None
    overall_status: str


class ProviderTestResponse(BaseModel):
    ok: bool
    message: str
    latency_ms: Optional[float] = None
    model: Optional[str] = None


# --- Public Model Item Schema ---
class ModelPublicItem(BaseModel):
    model_id: str
    name: str
    provider: str
    endpoint_model: str
    available: bool
    demo_mode: bool = False
    mode: str = "real"
    quality: float
    reasoning: float
    coding: float
    context_window: int
    input_price_per_mtok: float
    output_price_per_mtok: float
    expected_latency_ms: float
    tier: str