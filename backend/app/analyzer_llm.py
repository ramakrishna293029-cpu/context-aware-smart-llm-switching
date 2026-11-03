"""Analyzer LLM: Gemini 3.1 Flash-Lite Structured Decision Engine.

Analyzes query + context to produce structured JSON matching Box 3:
{
  "task_type": "coding" | "general" | "reasoning" | "factual" | "math",
  "complexity": "low" | "medium" | "high",
  "required_capability": "tier_1" | "tier_2" | "tier_3" | "tier_4" | "tier_5" | "tier_6",
  "reason": "..."
}
"""

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional

from .adapters.base import LLMResult, adapter_factory
from .analyzer import _check_greeting, _fallback_heuristics, _try_solve_simple_arithmetic
from .registry import ModelRegistry, ModelSpec, registry
from .schemas import AnalyzerInfo, ChatMessage

JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# ---------------------------------------------------------------------------
# Semantic routing cache
# ---------------------------------------------------------------------------
_ROUTING_CACHE: "OrderedDict[str, tuple[float, AnalyzerDecision]]" = OrderedDict()
_ROUTING_CACHE_MAX = 256
_ROUTING_CACHE_TTL = 600.0  # seconds


def _routing_cache_key(
    query: str,
    history: List[ChatMessage],
    strategy: str,
    active_analyzer: ModelSpec,
    avail_models: List[ModelSpec],
) -> str:
    h = hashlib.sha1()
    h.update(query.strip().lower().encode("utf-8"))
    h.update(b"\x00")
    h.update("\n".join(m.content for m in history[-10:]).encode("utf-8"))
    h.update(f"\x00{strategy}\x00{active_analyzer.model_id}\x00".encode("utf-8"))
    h.update(",".join(m.model_id for m in avail_models).encode("utf-8"))
    return h.hexdigest()


def _routing_cache_get(key: str) -> Optional["AnalyzerDecision"]:
    entry = _ROUTING_CACHE.get(key)
    if not entry:
        return None
    ts, dec = entry
    if time.monotonic() - ts > _ROUTING_CACHE_TTL:
        _ROUTING_CACHE.pop(key, None)
        return None
    _ROUTING_CACHE.move_to_end(key)
    return dec


def _routing_cache_put(key: str, dec: "AnalyzerDecision") -> None:
    _ROUTING_CACHE[key] = (time.monotonic(), dec)
    _ROUTING_CACHE.move_to_end(key)
    while len(_ROUTING_CACHE) > _ROUTING_CACHE_MAX:
        _ROUTING_CACHE.popitem(last=False)


def clear_routing_cache() -> None:
    """Called on registry changes / tests to drop cached routing decisions."""
    _ROUTING_CACHE.clear()


class AnalyzerDecisionError(RuntimeError):
    """The Analyzer LLM did not return a parseable structured decision."""


@dataclass
class AnalyzerDecision:
    task_type: str                  # "coding" | "general" | "reasoning" | "factual" | "math"
    complexity: str                 # "low" | "medium" | "high"
    required_capability: str        # "tier_1" | "tier_2" | "tier_3" | "tier_4" | "tier_5" | "tier_6"
    reason: str                     # structured reasoning explanation
    analyzer_model: ModelSpec       # model used for analysis (Gemini 3.1 Flash-Lite)
    analyzer_result: LLMResult      # usage and latency of analyzer call
    complexity_score: float = 0.5   # 0.0 - 1.0 numeric score
    reasoning_required: bool = False
    coding_required: bool = False
    context_required: bool = False
    target_tier: str = "tier_1"
    target_provider: str = "gemini"
    target_model: Optional[str] = None
    answer_mode: str = "switch"     # "switch" | "self"
    answer: Optional[str] = None    # direct answer if self-mode
    switch_required: bool = True

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "complexity": self.complexity,
            "required_capability": self.required_capability,
            "reason": self.reason,
            "complexity_score": self.complexity_score,
            "reasoning_required": self.reasoning_required,
            "coding_required": self.coding_required,
            "context_required": self.context_required,
            "target_tier": self.target_tier,
            "target_provider": self.target_provider,
            "target_model": self.target_model,
            "answer_mode": self.answer_mode,
            "answer": self.answer,
            "switch_required": self.switch_required,
            "analyzer_model_id": self.analyzer_model.model_id,
            "latency_ms": self.analyzer_result.latency_ms,
        }

    def to_analyzer_info(self, cost_usd: Optional[float] = None) -> AnalyzerInfo:
        """Converts decision to standard telemetry AnalyzerInfo schema (Box 3)."""
        computed_cost = cost_usd
        if computed_cost is None:
            tokens_in = self.analyzer_result.input_tokens or 0
            tokens_out = self.analyzer_result.output_tokens or 0
            in_cost = (tokens_in / 1_000_000.0) * self.analyzer_model.input_price_per_mtok
            out_cost = (tokens_out / 1_000_000.0) * self.analyzer_model.output_price_per_mtok
            computed_cost = round(in_cost + out_cost, 7)

        return AnalyzerInfo(
            model_id=self.analyzer_model.model_id,
            model_name=self.analyzer_model.name,
            provider=self.analyzer_model.provider,
            task_type=self.task_type,
            complexity=self.complexity if self.complexity in ("low", "medium", "high") else "medium",  # type: ignore
            required_capability=self.required_capability,
            reason=self.reason,
            input_tokens=self.analyzer_result.input_tokens,
            output_tokens=self.analyzer_result.output_tokens,
            latency_ms=round(self.analyzer_result.latency_ms, 2),
            cost_usd=computed_cost,
            complexity_score=round(self.complexity_score, 3),
            answer_mode="self" if self.answer_mode == "self" else "switch",
            target_tier=self.target_tier,
            target_provider=self.target_provider,
            target_model=self.target_model,
            reasoning_required=self.reasoning_required,
            coding_required=self.coding_required,
            context_required=self.context_required,
        )


def _extract_json(text: str) -> dict:
    """Safely extracts JSON object from LLM output handling fences and commentary."""
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
    """Builds prompt instructing Gemini 3.1 Flash-Lite Analyzer to return structured Box 3 JSON."""
    system_prompt = """You are the Analyzer LLM for Context-Aware Smart LLM Switching.
Your job is to analyze the incoming user query and conversation context, determine the task type, complexity, and required capability tier, and output a strictly valid JSON object matching Box 3:
{
  "task_type": "coding" | "general" | "reasoning" | "factual" | "math",
  "complexity": "low" | "medium" | "high",
  "required_capability": "tier_1" | "tier_2" | "tier_3" | "tier_4" | "tier_5" | "tier_6",
  "reason": "Concise justification for the capability and tier selection."
}

MODEL TIER ARCHITECTURE & CAPABILITIES:
- tier_1: Gemini 3.5 Flash-Lite (Lightweight / Fast) - Simple factual queries, short definitions, greetings, basic translations, low complexity.
- tier_2: Groq GPT-OSS 20B (Fast General Purpose) - Fast conversational text generation, general drafting, medium-low complexity.
- tier_3: Gemini 3.6 Flash (Balanced) - Balanced general queries, structured explanations, moderate complexity factual & analytical questions.
- tier_4: Groq Qwen3.8 27B (Coding Specialist) - Programming, debugging, SQL queries, algorithms (quicksort, binary search, dijkstra), syntax, code refactoring.
- tier_5: Groq GPT-OSS 120B (Advanced Reasoning) - Complex multi-step reasoning, mathematical proofs, logic puzzles, deep architecture trade-offs.
- tier_6: Gemini 3.8 Flash (High-Capability Gemini) - Frontier multi-domain problems, comprehensive synthesis, critical complex systems analysis.

RULES:
1. Programming/coding/debugging/algorithms MUST select "tier_4" (or "tier_5"/"tier_6" for massive system architectures).
2. Advanced reasoning/math proofs/logic puzzles MUST select "tier_5" (or "tier_6" for high complexity).
3. Simple greetings, basic facts, short definitions MUST select "tier_1" or "tier_2".
4. Moderate complexity general/factual tasks MUST select "tier_3".
5. Highly complex synthesis and critical architecture design MUST select "tier_6".

Return ONLY the strictly valid JSON object."""

    messages = [ChatMessage(role="system", content=system_prompt)]

    if history:
        history_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in history[-10:]])
        messages.append(ChatMessage(role="user", content=f"CONVERSATION HISTORY:\n{history_text}\n\nUSER QUERY:\n{query}"))
    else:
        messages.append(ChatMessage(role="user", content=f"USER QUERY:\n{query}"))

    return messages


def _normalize_required_capability(raw_tier: Optional[str], task_type: str, complexity: str) -> str:
    """Normalizes any tier string to standard tier_1 .. tier_6."""
    raw = str(raw_tier or "").lower().strip()
    tier_map = {
        "tier_1": "tier_1", "tier1": "tier_1", "fast": "tier_1", "fast-backup": "tier_1",
        "tier_2": "tier_2", "tier2": "tier_2",
        "tier_3": "tier_3", "tier3": "tier_3", "balanced": "tier_3",
        "tier_4": "tier_4", "tier4": "tier_4", "coding": "tier_4", "coding-backup": "tier_4",
        "tier_5": "tier_5", "tier5": "tier_5", "reasoning": "tier_5", "reasoning-backup": "tier_5",
        "tier_6": "tier_6", "tier6": "tier_6", "powerful": "tier_6",
    }
    if raw in tier_map:
        return tier_map[raw]

    # Deduce from task_type and complexity if unrecognized
    if task_type == "coding":
        return "tier_4"
    if task_type in ("reasoning", "math"):
        return "tier_6" if complexity == "high" else "tier_5"
    if complexity == "high":
        return "tier_6"
    if complexity == "medium":
        return "tier_3"
    return "tier_1"


async def run_analyzer(
    query: str,
    history: Optional[List[ChatMessage]] = None,
    available: Optional[List[ModelSpec]] = None,
    strategy: str = "balanced",
    analyzer_model: Optional[ModelSpec] = None,
    registry_instance: Optional[ModelRegistry] = None,
) -> AnalyzerDecision:
    """Executes Gemini 3.1 Flash-Lite Analyzer LLM, returning structured Box 3 decision."""
    history = history or []

    # 1. Resolve analyzer model and candidate models
    reg = registry_instance or registry
    active_analyzer = analyzer_model or reg.get_analyzer()
    avail_models = available if available is not None else [m for m in reg.available() if m.tier != "analyzer"]

    # 2. Fast-path heuristic gate + routing cache
    cache_key = _routing_cache_key(query, history, strategy, active_analyzer, avail_models)
    cached = _routing_cache_get(cache_key)
    if cached is not None:
        return cached

    # Fast-path for exact arithmetic
    t_start_fast = time.perf_counter()
    arith_ans = _try_solve_simple_arithmetic(query.strip())
    if arith_ans and not history:
        lat_ms = (time.perf_counter() - t_start_fast) * 1000.0
        fastpath_result = LLMResult(
            content=arith_ans, text=arith_ans,
            input_tokens=0, output_tokens=0, tokens_in=0, tokens_out=0,
            usage_source="fastpath", latency_ms=lat_ms,
        )
        decision = AnalyzerDecision(
            task_type="math",
            complexity="low",
            required_capability="tier_1",
            reason="Exact arithmetic computed locally by the fast-path gate.",
            analyzer_model=active_analyzer,
            analyzer_result=fastpath_result,
            complexity_score=0.10,
            reasoning_required=False,
            coding_required=False,
            context_required=False,
            target_tier="tier_1",
            target_provider="gemini",
            target_model=None,
            answer_mode="self",
            answer=arith_ans,
            switch_required=False,
        )
        _routing_cache_put(cache_key, decision)
        return decision

    # Fast-path for greetings & conversational pleasantries (Requirement 7)
    # Eliminates serial 22+ second remote analyzer latency for simple queries
    t_greet_start = time.perf_counter()
    is_greet, greet_ans = _check_greeting(query.strip())
    if is_greet:
        ans_text = greet_ans or "Hello! How can I help you today?"
        lat_ms = (time.perf_counter() - t_greet_start) * 1000.0
        fastpath_result = LLMResult(
            content=ans_text, text=ans_text,
            input_tokens=0, output_tokens=0, tokens_in=0, tokens_out=0,
            usage_source="fastpath", latency_ms=lat_ms,
        )
        decision = AnalyzerDecision(
            task_type="general",
            complexity="low",
            required_capability="tier_1",
            reason="Simple greeting answered directly by base model in self-mode.",
            analyzer_model=active_analyzer,
            analyzer_result=fastpath_result,
            complexity_score=0.08,
            reasoning_required=False,
            coding_required=False,
            context_required=len(history) > 0,
            target_tier="tier_1",
            target_provider=active_analyzer.provider if active_analyzer else "gemini",
            target_model=None,
            answer_mode="self",
            answer=ans_text,
            switch_required=False,
        )
        _routing_cache_put(cache_key, decision)
        return decision

    messages = _build_analyzer_messages(query, history, avail_models)

    # 3. Invoke Analyzer model (Gemini 3.1 Flash-Lite)
    t0 = time.perf_counter()
    try:
        adapter = adapter_factory.get(active_analyzer.provider)
        result = await adapter.generate(active_analyzer, messages, json_mode=True)
        decision_dict = _extract_json(result.text)
    except Exception:
        # Fallback to deterministic heuristics
        decision_dict = _fallback_heuristics(query, history)
        lat_ms = (time.perf_counter() - t0) * 1000.0
        result = LLMResult(
            content=json.dumps(decision_dict),
            text=json.dumps(decision_dict),
            input_tokens=0,
            output_tokens=0,
            tokens_in=0,
            tokens_out=0,
            usage_source="unavailable",
            latency_ms=lat_ms,
            ttft_ms=lat_ms,
        )

    # 4. Parse & Normalize Box 3 fields
    raw_task = str(decision_dict.get("task_type", "general")).lower().strip()
    if raw_task in ("coding", "general", "reasoning", "factual", "math"):
        task_type = raw_task
    elif "code" in raw_task or "debug" in raw_task:
        task_type = "coding"
    elif "math" in raw_task or "calc" in raw_task:
        task_type = "math"
    elif "reason" in raw_task:
        task_type = "reasoning"
    elif "fact" in raw_task:
        task_type = "factual"
    else:
        task_type = "general"

    raw_comp = str(decision_dict.get("complexity", "medium")).lower().strip()
    if raw_comp in ("low", "medium", "high"):
        complexity = raw_comp
    else:
        complexity = "medium"

    raw_req_cap = decision_dict.get("required_capability") or decision_dict.get("target_tier")
    required_capability = _normalize_required_capability(raw_req_cap, task_type, complexity)

    reason = str(decision_dict.get("reason") or f"Routed to {required_capability} based on task analysis.").strip()

    # Safety overrides for explicit code/reasoning prompts
    q_lower = query.lower()
    has_code_intent = (
        task_type == "coding"
        or "```" in query
        or any(k in q_lower for k in ("write a function", "implement ", "algorithm", "quicksort", "binary search", "dijkstra", "unit test", "def ", "class "))
    )
    if has_code_intent:
        task_type = "coding"
        if required_capability in ("tier_1", "tier_2", "tier_3"):
            required_capability = "tier_4"

    # Numeric complexity score
    if complexity == "low":
        complexity_score = 0.20
    elif complexity == "high":
        complexity_score = 0.90
    else:
        complexity_score = 0.55

    if "complexity_score" in decision_dict:
        try:
            complexity_score = float(decision_dict["complexity_score"])
        except (ValueError, TypeError):
            pass

    coding_required = task_type == "coding" or required_capability == "tier_4"
    reasoning_required = task_type in ("reasoning", "math") or required_capability in ("tier_5", "tier_6")
    context_required = bool(decision_dict.get("context_required", len(history) > 0))
    if len(history) > 0 and any(k in q_lower for k in ("history", "above", "earlier", "previous", "context", "before", "last turn", "we discussed", "you said")):
        context_required = True

    # Provider map for the 6 tiers
    provider_map = {
        "tier_1": "gemini",
        "tier_2": "groq",
        "tier_3": "gemini",
        "tier_4": "groq",
        "tier_5": "groq",
        "tier_6": "gemini",
    }
    target_provider = provider_map.get(required_capability, "gemini")

    # In demo simulation mode, check if answer was provided
    answer_mode = str(decision_dict.get("answer_mode", "switch")).lower().strip()
    direct_answer = decision_dict.get("answer")
    if answer_mode == "self" and direct_answer and str(direct_answer).strip():
        direct_answer = str(direct_answer).strip()
        switch_required = False
    else:
        answer_mode = "switch"
        direct_answer = None
        switch_required = True

    decision = AnalyzerDecision(
        task_type=task_type,
        complexity=complexity,
        required_capability=required_capability,
        reason=reason,
        analyzer_model=active_analyzer,
        analyzer_result=result,
        complexity_score=round(complexity_score, 3),
        reasoning_required=reasoning_required,
        coding_required=coding_required,
        context_required=context_required,
        target_tier=required_capability,
        target_provider=target_provider,
        target_model=decision_dict.get("target_model"),
        answer_mode=answer_mode,
        answer=direct_answer,
        switch_required=switch_required,
    )
    _routing_cache_put(cache_key, decision)
    return decision


# Alias for unified calling convention
analyze_and_route = run_analyzer