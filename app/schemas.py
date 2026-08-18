"""Pydantic schemas shared between API layer, engine, and frontend."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    history: List[ChatMessage] = Field(default_factory=list)
    strategy: str = Field(default="balanced", max_length=32)


class CandidateInfo(BaseModel):
    model_id: str
    name: str
    provider: str
    tier: str
    total: float
    expected_cost_usd: float
    expected_latency_ms: float
    selected: bool
    factors: Dict[str, float]


class AnalyzerInfo(BaseModel):
    """Telemetry for the OpenRouter Analyzer LLM call + decision."""
    model_id: str
    model_name: str
    provider: str
    task_type: str
    complexity: str
    complexity_score: float
    reasoning_required: bool
    coding_required: bool
    context_required: bool
    target_tier: str
    target_provider: str
    target_model: Optional[str] = None
    reason: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: float
    cost_usd: Optional[float] = None


class ModelInfo(BaseModel):
    model_id: str
    model_name: str
    provider: str
    tier: str
    mode: str = "real"
    strategy: str = "balanced"
    reason: str


class ChatResponse(BaseModel):
    response: str
    model: ModelInfo
    analyzer: AnalyzerInfo
    context_relevant: bool
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    analyzer_cost_usd: Optional[float] = None
    total_cost_usd: Optional[float] = None
    baseline_cost_usd: Optional[float] = None
    savings_usd: Optional[float] = None
    savings_percent: Optional[float] = None
    latency_ms: float                     # generation latency
    analyzer_latency_ms: float            # analyzer latency
    total_latency_ms: float               # analyzer + generation
    ttft_ms: Optional[float] = None
    success: bool
    request_id: int
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    escalation_used: bool = False
    escalation_reason: Optional[str] = None
    candidates: List[CandidateInfo] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    history: List[ChatMessage] = Field(default_factory=list)
    strategy: str = Field(default="balanced", max_length=32)


class AnalyzeResponse(BaseModel):
    analyzer: AnalyzerInfo
    candidates: List[CandidateInfo]
    strategy: str


class FeedbackRequest(BaseModel):
    request_id: int
    rating: int = Field(ge=-1, le=1)  # 1 = good, -1 = poor


class FeedbackResponse(BaseModel):
    ok: bool
    message: str


class HistoryRow(BaseModel):
    id: int
    timestamp: str
    query: str
    task_type: str
    complexity: str
    selected_model: str
    provider: str
    fallback_used: bool
    escalation_used: bool
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    total_cost_usd: Optional[float] = None
    latency_ms: float
    total_latency_ms: float
    success: bool
    feedback: Optional[int] = None
    routing_reason: Optional[str] = None
    analyzer_model: Optional[str] = None


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
    items: List[BenchmarkComparisonItem]