"""Pydantic schemas shared between the API layer and internal modules."""

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    history: List[ChatMessage] = Field(default_factory=list)


class ContextAnalysisOut(BaseModel):
    complexity: float
    task_type: str
    reasoning_required: str
    estimated_input_tokens: int
    signals: List[Dict[str, Any]]


class ScoreBreakdown(BaseModel):
    quality_suitability: float
    complexity_compatibility: float
    cost_efficiency: float
    latency_efficiency: float
    historical_performance: float
    total: float


class RoutingInfo(BaseModel):
    model_id: str
    model_name: str
    provider: str
    demo_mode: bool
    reason: str
    analysis: ContextAnalysisOut
    scores: ScoreBreakdown


class ChatResponse(BaseModel):
    response: str
    model: RoutingInfo
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    success: bool
    request_id: int


class FeedbackRequest(BaseModel):
    request_id: int
    rating: int = Field(ge=-1, le=1)  # 1 = good, -1 = poor


class FeedbackResponse(BaseModel):
    ok: bool
    message: str


class ModelInfo(BaseModel):
    model_id: str
    name: str
    provider: str
    available: bool
    demo_mode: bool
    quality: float
    reasoning: float
    coding: float
    context_window: int
    input_price_per_mtok: float
    output_price_per_mtok: float
    expected_latency_ms: float


class HistoryRow(BaseModel):
    id: int
    timestamp: str
    query: str
    task_type: str
    complexity: float
    selected_model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    success: bool
    feedback: int | None


class StatsOut(BaseModel):
    total_requests: int
    successful_requests: int
    success_rate: float
    average_latency_ms: float
    average_complexity: float
    total_estimated_cost_usd: float
    baseline_cost_usd: float
    estimated_savings_usd: float
    savings_percent: float
    model_distribution: List[Dict[str, Any]]
    feedback_good: int
    feedback_poor: int
    recent_requests: List[HistoryRow]