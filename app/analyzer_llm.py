"""Analyzer LLM: Evaluates query + context to produce a structured routing decision.

The Analyzer LLM is NOT a regular chatbot and does NOT answer the user's query directly.
Its sole role is to analyze:
- Current user query
- Relevant conversation history
- Complexity & difficulty level
- Task type (factual, general, coding, debugging, math, reasoning, system_architecture)
- Reasoning & coding requirements
- Context dependency
- Target tier (fast, coding, reasoning, powerful)
- Recommended provider (gemini, groq, openrouter)
- Human-readable routing reason ("Why this model?")
"""

import json
import re
from dataclasses import dataclass
from typing import List, Optional

from .adapters.base import LLMAdapterError, LLMResult, adapter_factory
from .config import settings
from .registry import ModelSpec, registry
from .schemas import ChatMessage

JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class AnalyzerDecisionError(RuntimeError):
    """The Analyzer LLM did not return a parseable structured decision."""


@dataclass
class AnalyzerDecision:
    task_type: str                  # "factual" | "general" | "coding" | "debugging" | "math" | "reasoning" | "system_architecture"
    complexity: str                 # "low" | "medium" | "high"
    complexity_score: float         # 0.0 - 1.0
    reasoning_required: bool
    coding_required: bool
    context_required: bool
    target_tier: str                # "fast" | "coding" | "reasoning" | "powerful" | "balanced"
    target_provider: str            # "gemini" | "groq" | "openrouter"
    target_model: Optional[str]     # model_id or endpoint_model
    reason: str                     # short explanation
    analyzer_model: ModelSpec       # model used for analysis
    analyzer_result: LLMResult      # usage and latency of analyzer call
    switch_required: bool = True    # always routes to target execution model


def _extract_json(text: str) -> dict:
    """Safely extracts JSON object from LLM output."""
    def try_parse(s: str):
        s = s.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    # 1. Code fence
    m = JSON_FENCE.search(text)
    if m:
        p = try_parse(m.group(1))
        if p:
            return p

    # 2. Raw JSON string
    p = try_parse(text)
    if p:
        return p

    # 3. Largest {...} block
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        p = try_parse(text[start:end + 1])
        if p:
            return p

    raise AnalyzerDecisionError("Analyzer output did not contain valid JSON: " + text[:200])


def _build_analyzer_messages(query: str, history: List[ChatMessage], available: List[ModelSpec]) -> List[ChatMessage]:
    """Builds prompt instructing the Analyzer LLM to classify and route."""
    models_summary = "\n".join([
        f"- {m.provider.upper()}: {m.name} [Tier: {m.tier}, Quality: {m.quality:.2f}, Reasoning: {m.reasoning:.2f}, Coding: {m.coding:.2f}]"
        for m in available if m.tier != "analyzer"
    ])

    system_prompt = f"""You are the QUERY & CONTEXT ANALYZER for an intelligent LLM switching router.
Your job is to analyze the incoming user query and conversation history, and output a structured routing decision.

DO NOT answer the user's question directly.
Output ONLY a valid JSON object describing what intelligence level the query requires.

AVAILABLE EXECUTION MODELS & PROVIDERS:
{models_summary}

ROUTING RULES:
1. FAST / LOW-COST TIER (Provider: "gemini", Tier: "fast"):
   - Greetings, general chit-chat, simple factual lookups, basic definitions, translations, simple math.
   - Example: "What is an API?", "Who invented C++?", "Hello", "Summarize in 2 sentences".
2. CODING TIER (Provider: "groq", Tier: "coding"):
   - Programming tasks, writing functions, debugging code, unit tests, SQL queries, algorithms, syntax fixes.
   - Example: "Write Python Dijkstra implementation", "Fix this React state loop", "Write a Dockerfile".
3. REASONING / ARCHITECTURE TIER (Provider: "groq", Tier: "reasoning"):
   - Complex reasoning, mathematical proofs, system architecture, distributed systems, deep trade-off analysis.
   - Example: "Design a fault-tolerant distributed cache", "Prove that sqrt(2) is irrational", "Multi-step logic puzzle".

REQUIRED JSON OUTPUT FORMAT (No markdown commentary, only valid JSON):
{{
  "task_type": "factual" | "general" | "coding" | "debugging" | "math" | "reasoning" | "system_architecture",
  "complexity": "low" | "medium" | "high",
  "complexity_score": 0.15,
  "reasoning_required": false,
  "coding_required": false,
  "context_required": false,
  "target_tier": "fast" | "coding" | "reasoning" | "powerful",
  "target_provider": "gemini" | "groq",
  "reason": "Concise sentence explaining why this tier/provider was selected."
}}"""

    messages = [ChatMessage(role="system", content=system_prompt)]

    if history:
        history_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in history])
        messages.append(ChatMessage(role="user", content=f"RECENT CONVERSATION CONTEXT:\n{history_text}\n\nCURRENT USER QUERY TO ANALYZE:\n{query}"))
    else:
        messages.append(ChatMessage(role="user", content=f"CURRENT USER QUERY TO ANALYZE:\n{query}"))

    return messages


def _fallback_heuristics(query: str, history: List[ChatMessage]) -> dict:
    """Heuristic fallback in case Analyzer LLM output cannot be parsed."""
    lower = query.lower()
    coding_kws = ["code", "function", "def ", "class ", "python", "javascript", "java", "c++", "algorithm", "dijkstra", "debug", "bug", "error", "implement"]
    reasoning_kws = ["design", "architecture", "distributed", "proof", "prove", "theorem", "why", "trade-off", "system design"]

    context_needed = len(history) > 0 and len(query.split()) < 10 and any(w in lower for w in ["it", "that", "this", "now", "optimize", "same"])

    if any(k in lower for k in coding_kws):
        return {
            "task_type": "coding",
            "complexity": "medium",
            "complexity_score": 0.65,
            "reasoning_required": True,
            "coding_required": True,
            "context_required": context_needed,
            "target_tier": "coding",
            "target_provider": "groq",
            "reason": "Software engineering or coding request requiring specialized code generation.",
        }
    elif any(k in lower for k in reasoning_kws):
        return {
            "task_type": "system_architecture" if "design" in lower or "architecture" in lower else "reasoning",
            "complexity": "high",
            "complexity_score": 0.85,
            "reasoning_required": True,
            "coding_required": False,
            "context_required": context_needed,
            "target_tier": "reasoning",
            "target_provider": "groq",
            "reason": "Complex analytical or system design request requiring deep reasoning.",
        }
    else:
        return {
            "task_type": "factual" if "what" in lower or "who" in lower or "how" in lower else "general",
            "complexity": "low",
            "complexity_score": 0.20,
            "reasoning_required": False,
            "coding_required": False,
            "context_required": context_needed,
            "target_tier": "fast",
            "target_provider": "gemini",
            "reason": "Standard query routed to fast low-cost Gemini model.",
        }


async def run_analyzer(query: str, history: List[ChatMessage], available: List[ModelSpec], strategy: str = "balanced") -> AnalyzerDecision:
    """Executes the OpenRouter Analyzer LLM and extracts the routing decision."""
    analyzer_model = registry.get_analyzer()
    messages = _build_analyzer_messages(query, history, available)

    try:
        adapter = adapter_factory.get(analyzer_model.provider)
        result = await adapter.generate(analyzer_model, messages, json_mode=True)
        decision_dict = _extract_json(result.text)
    except Exception as exc:
        # If the analyzer API call fails or produces malformed JSON, use heuristic classification
        fallback_data = _fallback_heuristics(query, history)
        result = LLMResult(
            text=json.dumps(fallback_data),
            input_tokens=max(1, len(query) // 4),
            output_tokens=60,
            usage_source="fallback",
            ttft_ms=50.0,
        )
        decision_dict = fallback_data

    # Parse and normalize fields
    task_type = str(decision_dict.get("task_type", "general")).lower()
    complexity_raw = str(decision_dict.get("complexity", "medium")).lower()
    if complexity_raw not in ("low", "medium", "high"):
        complexity_raw = "medium"

    complexity_score = decision_dict.get("complexity_score")
    if complexity_score is None:
        complexity_score = 0.2 if complexity_raw == "low" else 0.6 if complexity_raw == "medium" else 0.9
    else:
        try:
            complexity_score = float(complexity_score)
        except (ValueError, TypeError):
            complexity_score = 0.5

    reasoning_required = bool(decision_dict.get("reasoning_required", complexity_raw == "high"))
    coding_required = bool(decision_dict.get("coding_required", task_type in ("coding", "debugging")))
    context_required = bool(decision_dict.get("context_required", False))

    target_tier = str(decision_dict.get("target_tier", "fast")).lower()
    if target_tier not in ("fast", "coding", "reasoning", "powerful", "balanced"):
        target_tier = "coding" if coding_required else "reasoning" if reasoning_required else "fast"

    target_provider = str(decision_dict.get("target_provider", "gemini" if target_tier == "fast" else "groq")).lower()
    if target_provider not in ("gemini", "groq", "openrouter"):
        target_provider = "gemini" if target_tier == "fast" else "groq"

    reason = str(decision_dict.get("reason", f"Routed to {target_tier} tier ({target_provider})")).strip()

    return AnalyzerDecision(
        task_type=task_type,
        complexity=complexity_raw,
        complexity_score=round(complexity_score, 3),
        reasoning_required=reasoning_required,
        coding_required=coding_required,
        context_required=context_required,
        target_tier=target_tier,
        target_provider=target_provider,
        target_model=decision_dict.get("target_model"),
        reason=reason,
        analyzer_model=analyzer_model,
        analyzer_result=result,
    )