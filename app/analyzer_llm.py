"""Analyzer LLM: Evaluates query + context to produce a structured routing decision.

Dual-Role First-Line Responder:
1. SELF-MODE (answer_mode = "self"):
   Answers simple queries (greetings, simple facts, basic math, short definitions) directly
   in 1 cheap call, emitting the complete answer in the `answer` field and bypassing downstream models.
2. SWITCH-MODE (answer_mode = "switch"):
   Classifies complex queries (coding, debugging, math proofs, system architecture, deep reasoning)
   and determines the optimal target tier, provider, and candidate sequence.
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .adapters.base import LLMResult, adapter_factory
from .analyzer import _fallback_heuristics, _check_greeting
from .registry import ModelRegistry, ModelSpec, registry
from .schemas import AnalyzerInfo, ChatMessage

JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


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
    target_provider: str            # "gemini" | "groq" | "openrouter" | "openai" | "custom" | "mock"
    target_model: Optional[str]     # model_id or endpoint_model
    reason: str                     # short explanation
    analyzer_model: ModelSpec       # model used for analysis
    analyzer_result: LLMResult      # usage and latency of analyzer call
    answer_mode: str = "switch"     # "self" | "switch"
    answer: Optional[str] = None    # direct answer if self-mode
    switch_required: bool = True    # False if self, True if switch

    def to_dict(self) -> dict:
        return {
            "answer_mode": self.answer_mode,
            "task_type": self.task_type,
            "complexity": self.complexity,
            "complexity_score": self.complexity_score,
            "reasoning_required": self.reasoning_required,
            "coding_required": self.coding_required,
            "context_required": self.context_required,
            "target_tier": self.target_tier,
            "target_provider": self.target_provider,
            "target_model": self.target_model,
            "reason": self.reason,
            "answer": self.answer,
            "switch_required": self.switch_required,
            "analyzer_model_id": self.analyzer_model.model_id,
            "latency_ms": self.analyzer_result.latency_ms,
        }

    def to_analyzer_info(self, cost_usd: Optional[float] = None) -> AnalyzerInfo:
        """Converts decision to standard telemetry AnalyzerInfo schema."""
        computed_cost = cost_usd
        if computed_cost is None:
            # Estimate cost based on analyzer model pricing
            tokens_in = self.analyzer_result.input_tokens or 0
            tokens_out = self.analyzer_result.output_tokens or 0
            in_cost = (tokens_in / 1_000_000.0) * self.analyzer_model.input_price_per_mtok
            out_cost = (tokens_out / 1_000_000.0) * self.analyzer_model.output_price_per_mtok
            computed_cost = round(in_cost + out_cost, 7)

        return AnalyzerInfo(
            model_id=self.analyzer_model.model_id,
            model_name=self.analyzer_model.name,
            provider=self.analyzer_model.provider,
            answer_mode="self" if self.answer_mode == "self" else "switch",
            task_type=self.task_type,
            complexity=self.complexity if self.complexity in ("low", "medium", "high") else "medium",  # type: ignore
            complexity_score=round(self.complexity_score, 3),
            reasoning_required=self.reasoning_required,
            coding_required=self.coding_required,
            context_required=self.context_required,
            target_tier=self.target_tier,
            target_provider=self.target_provider,
            target_model=self.target_model,
            reason=self.reason,
            input_tokens=self.analyzer_result.input_tokens,
            output_tokens=self.analyzer_result.output_tokens,
            latency_ms=round(self.analyzer_result.latency_ms, 2),
            cost_usd=computed_cost,
        )


def _extract_json(text: str) -> dict:
    """Safely extracts JSON object from LLM output handling fences, commentary, and balanced braces."""
    def try_parse(s: str) -> Optional[dict]:
        s = s.strip()
        if not s:
            return None
        try:
            res = json.loads(s)
            if isinstance(res, dict):
                return res
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    # 1. Code fence match
    for m in JSON_FENCE.finditer(text):
        p = try_parse(m.group(1))
        if p:
            return p

    # 2. Direct raw string
    p = try_parse(text)
    if p:
        return p

    # 3. Balanced outermost {...} extraction
    start = text.find("{")
    if start != -1:
        # Scan for balanced closing brace
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if not in_string:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : i + 1]
                        p = try_parse(candidate)
                        if p:
                            return p
                        break

    # 4. Fallback largest slice
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        p = try_parse(text[start : end + 1])
        if p:
            return p

    raise AnalyzerDecisionError("Analyzer output did not contain valid JSON: " + text[:200])


def _build_analyzer_messages(query: str, history: List[ChatMessage], available: List[ModelSpec]) -> List[ChatMessage]:
    """Builds prompt instructing the Analyzer LLM to classify, self-answer or route."""
    models_summary = "\n".join([
        f"- {m.provider.upper()}: {m.name} [Tier: {m.tier}, Quality: {m.quality:.2f}, Reasoning: {m.reasoning:.2f}, Coding: {m.coding:.2f}]"
        for m in available if m.tier != "analyzer"
    ])

    system_prompt = f"""You are the INTELLIGENT QUERY ANALYZER & FIRST-LINE RESPONDER for an AI Routing System.
Your job is to analyze the incoming user query and conversation context, decide whether you can answer it accurately yourself (SELF-MODE) or if it requires switching to a specialized heavy model (SWITCH-MODE), and output a strictly valid JSON object.

DECISION CRITERIA:
1. SELF-MODE (answer_mode = "self"):
   - Use ONLY for: Simple greetings ("hi", "hello", "good morning"), casual dialogue, simple factual questions, short definitions, straightforward translations, simple arithmetic ("5 + 7").
   - Action: Set answer_mode to "self", provide the direct complete answer in the "answer" field, and set target_tier to "fast".
   - Example queries: "Hi", "Hello", "What is HTML?", "Capital of France", "Who wrote Hamlet?", "5 + 7".

2. SWITCH-MODE (answer_mode = "switch"):
   - MANDATORY for: ANY programming, coding, algorithms (e.g. Dijkstra, sorting, search), debugging, math proofs, system architecture, distributed systems, deep reasoning, large code refactoring.
   - Action: Set answer_mode to "switch", set "answer" to null, and select the optimal target tier and provider.
   - NEVER use self-mode for coding or algorithms.
   - Target tiers:
     * "coding": Programming, debugging, SQL, syntax, Docker, scripts, algorithms, code implementation.
     * "reasoning": System architecture, mathematical proofs, logic puzzles, trade-off analysis.
     * "powerful": Deep comprehensive synthesis, massive context reasoning.
     * "fast": General heavy factual lookups.

AVAILABLE PROVIDERS & TIERS:
{models_summary}

REQUIRED JSON OUTPUT FORMAT (Strictly valid JSON with no conversational prefix/suffix):
{{
  "answer_mode": "self" | "switch",
  "task_type": "factual" | "general" | "coding" | "debugging" | "math" | "reasoning" | "system_architecture",
  "complexity": "low" | "medium" | "high",
  "complexity_score": 0.15,
  "reasoning_required": false,
  "coding_required": false,
  "context_required": false,
  "target_tier": "fast" | "coding" | "reasoning" | "powerful",
  "target_provider": "gemini" | "groq" | "openrouter" | "openai" | "custom",
  "target_model": null,
  "reason": "Concise sentence explaining why this mode and tier were selected.",
  "answer": "Direct answer text if answer_mode is self, otherwise null"
}}"""

    messages = [ChatMessage(role="system", content=system_prompt)]

    if history:
        history_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in history[-6:]])
        messages.append(ChatMessage(role="user", content=f"CONVERSATION HISTORY:\n{history_text}\n\nUSER QUERY:\n{query}"))
    else:
        messages.append(ChatMessage(role="user", content=f"USER QUERY:\n{query}"))

    return messages



async def run_analyzer(
    query: str,
    history: Optional[List[ChatMessage]] = None,
    available: Optional[List[ModelSpec]] = None,
    strategy: str = "balanced",
    analyzer_model: Optional[ModelSpec] = None,
    registry_instance: Optional[ModelRegistry] = None,
) -> AnalyzerDecision:
    """Executes the Base/Analyzer model, parses the output, and produces an AnalyzerDecision."""
    history = history or []
    
    # 1. Resolve analyzer model and candidate models
    reg = registry_instance or registry
    active_analyzer = analyzer_model or reg.get_analyzer()
    avail_models = available if available is not None else [m for m in reg.available() if m.tier != "analyzer"]

    messages = _build_analyzer_messages(query, history, avail_models)

    # 2. Invoke analyzer model via adapter
    t0 = time.perf_counter()
    try:
        adapter = adapter_factory.get(active_analyzer.provider)
        result = await adapter.generate(active_analyzer, messages, json_mode=True)
        decision_dict = _extract_json(result.text)
    except Exception:
        # Fallback to deterministic heuristic engine
        decision_dict = _fallback_heuristics(query, history)
        lat_ms = (time.perf_counter() - t0) * 1000.0
        result = LLMResult(
            content=json.dumps(decision_dict),
            text=json.dumps(decision_dict),
            input_tokens=max(1, len(query) // 4 + 10),
            output_tokens=max(1, len(json.dumps(decision_dict)) // 4),
            tokens_in=max(1, len(query) // 4 + 10),
            tokens_out=max(1, len(json.dumps(decision_dict)) // 4),
            usage_source="fallback",
            latency_ms=lat_ms,
            ttft_ms=lat_ms,
        )

    # 3. Parse and normalize answer_mode & direct answer
    answer_mode = str(decision_dict.get("answer_mode", "switch")).lower().strip()
    if answer_mode not in ("self", "switch"):
        answer_mode = "self" if decision_dict.get("answer") else "switch"

    direct_answer = decision_dict.get("answer")
    if answer_mode == "self":
        switch_required = False
        if not direct_answer or not str(direct_answer).strip():
            is_greet, greet_ans = _check_greeting(query)
            direct_answer = greet_ans or "Hello! How can I help you today?"
        else:
            direct_answer = str(direct_answer).strip()
    else:
        switch_required = True
        direct_answer = None

    # 4. Parse and normalize task classification & routing metrics
    task_type = str(decision_dict.get("task_type", "general")).lower().strip()
    complexity_raw = str(decision_dict.get("complexity", "medium")).lower().strip()
    if complexity_raw not in ("low", "medium", "high"):
        complexity_raw = "low" if answer_mode == "self" else "medium"

    complexity_score_raw = decision_dict.get("complexity_score")
    if complexity_score_raw is None:
        complexity_score = 0.1 if complexity_raw == "low" else 0.6 if complexity_raw == "medium" else 0.9
    else:
        try:
            complexity_score = max(0.0, min(1.0, float(complexity_score_raw)))
        except (ValueError, TypeError):
            complexity_score = 0.5

    reasoning_required = bool(decision_dict.get("reasoning_required", complexity_raw == "high"))
    coding_required = bool(decision_dict.get("coding_required", task_type in ("coding", "debugging")))
    context_required = bool(decision_dict.get("context_required", len(history) > 0))

    # Safety Guardrail: Coding, debugging, and complex system architecture queries MUST use switch mode
    q_lower = query.lower()
    has_code_intent = coding_required or task_type in ("coding", "debugging", "system_architecture") or any(k in q_lower for k in ("algorithm", "dijkstra", "quicksort", "binary search", "function", "debug", "refactor", "unit test", "distributed"))
    if has_code_intent:
        answer_mode = "switch"
        switch_required = True
        direct_answer = None
        if task_type not in ("coding", "debugging", "system_architecture", "reasoning"):
            task_type = "coding"
        coding_required = True

    target_tier = str(decision_dict.get("target_tier", "fast")).lower().strip()
    if target_tier not in ("fast", "coding", "reasoning", "powerful", "balanced", "custom"):
        target_tier = "coding" if coding_required else "reasoning" if reasoning_required else "fast"


    target_provider = str(decision_dict.get("target_provider", "gemini" if target_tier == "fast" else "groq")).lower().strip()
    if target_provider not in ("gemini", "groq", "openrouter", "openai", "custom", "mock"):
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
        analyzer_model=active_analyzer,
        analyzer_result=result,
        answer_mode=answer_mode,
        answer=direct_answer,
        switch_required=switch_required,
    )


# Alias for unified calling convention
analyze_and_route = run_analyzer