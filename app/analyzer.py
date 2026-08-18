"""Context Analyzer: turns a raw query (plus optional conversation) into a
structured complexity profile and routing classification.

Deterministic scoring engine, fully transparent: every decision emits a
human-readable signal list. Provides instant heuristic classification and
reliable fallback for the analyzer brain.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .schemas import ChatMessage

# Keyword groups with per-keyword weight. Queries can match several
# groups; the strongest group drives the task type, all of them raise
# the complexity estimate.
TASK_GROUPS: Dict[str, List[str]] = {
    "coding": [
        "code", "function", "syntax", "python", "javascript", "java", "c++",
        "typescript", "html tag", "sql", "algorithm", "loop", "variable",
        "class", "module", "library", "framework", "regex", "compile",
        "refactor", "unit test", "docker", "git", "thread", "concurrency",
        "memory leak", "flask", "django", "react", "node", "pandas", "numpy",
        "implement", "write a program", "binary search", "sort", "dijkstra",
        "quicksort", "recursion", "asyncio", "decorator", "pointer", "rust",
        "golang", "backend", "frontend", "api endpoint", "json schema",
    ],
    "debugging": [
        "debug", "bug", "not working", "broken", "crash", "fails",
        "exception", "stack trace", "error message", "re-render",
        "re-renders", "infinite loop", "fix this", "why is this", "traceback",
        "segfault", "performance issue", "hang", "freeze", "unexpected output",
        "syntaxerror", "typeerror", "nullpointer", "undefined", "timeout",
    ],
    "mathematics": [
        "calculate", "equation", "solve", "integral", "derivative", "theorem",
        "proof", "prove", "matrix", "vector", "probability", "statistics",
        "algebra", "geometry", "sum", "average", "mean", "median", "percentage",
        "linear regression", "bayes", "gradient", "eigenvalue", "irrational",
        "calculus", "combinatorics", "permutation", "logarithm", "differential",
    ],
    "reasoning": [
        "why", "explain", "argue", "criticize", "justify", "hypothesis",
        "logical", "synthesize", "root cause", "implications", "consequences",
        "trade-off", "assess", "judge", "compare and contrast", "deduce",
        "inference", "counterfactual", "philosophical", "paradox",
    ],
    "analysis": [
        "analyze", "compare", "evaluate", "review", "critique", "identify",
        "interpret", "inspect", "profile", "benchmark", "impact",
    ],
    "planning": [
        "plan", "roadmap", "strategy", "schedule", "milestones", "steps to",
        "design", "architecture", "deploy plan", "rollout", "prioritize",
        "outline the approach", "distributed system", "microservices",
    ],
    "technical": [
        "api", "database", "server", "deployment", "protocol", "tcp", "udp",
        "http", "kubernetes", "distributed", "latency", "scalable", "cloud",
        "endpoint", "caching", "load balancer", "replication", "consistency",
        "partition", "networking", "raft", "paxos", "sharding",
    ],
    "summarization": [
        "summarize", "summary", "tl;dr", "condense", "key points", "brief",
        "short version", "in a nutshell", "abstract",
    ],
    "creative": [
        "write a story", "poem", "essay", "brainstorm", "ideas", "creative",
        "rewrite", "tone", "marketing", "ad copy", "tagline", "blog post",
        "social media", "dialogue", "novel", "script", "headline",
    ],
    "factual": [
        "what is", "define", "who", "when was", "where", "list", "name the",
        "history of", "capital of", "meaning of", "how many", "facts",
        "overview", "introduction", "what are",
    ],
}

# Greetings patterns
GREETING_PATTERNS = [
    r"^(?:hi|hello|hey|greetings|howdy|sup|yo|good morning|good afternoon|good evening|good day)(?:[\s!.,?]*)$",
    r"^(?:hi|hello|hey)\s+(?:there|ai|bot|assistant|friend)(?:[\s!.,?]*)$",
    r"^who are you(?:[\s!.,?]*)$",
    r"^what can you do(?:[\s!.,?]*)$",
    r"^how are you(?:[\s!.,?]*)$",
    r"^help(?:[\s!.,?]*)$",
]

# Simple arithmetic regex: e.g. "5 + 5", "what is 2 * 8", "100 / 4"
ARITHMETIC_PATTERN = re.compile(
    r"^(?:what is\s+|calculate\s+|solve\s+)?(\d+(?:\.\d+)?)\s*([\+\-\*\/])\s*(\d+(?:\.\d+)?)\s*\??$",
    re.IGNORECASE,
)

HIGH_REASON_PATTERNS = [
    r"explain.*in detail",
    r"step.?by.?step",
    r"\bprove\b",
    r"write.*code.*(?:that|to|which)",
    r"debug|fix.*error|fix.*bug",
    r"why.*fail",
    r"design.*(?:system|architecture|database|api)",
    r"compare and contrast",
    r"\b(?:complex|advanced|difficult|challenging)\b",
    r"\bdistributed\b",
    r"root cause",
]

LOW_REASON_PATTERNS = [
    r"^what is\b",
    r"^what are\b",
    r"^define\b",
    r"^who\b",
    r"^list\b",
    r"^name\b",
    r"^hi\b|^hello\b|^hey\b",
]

FOLLOWUP_WORD_LIMIT = 8
FOLLOWUP_HINTS = re.compile(
    r"\b(it|that|this|those|same|then|now|instead|above|below|first|second|"
    r"other|another|one|both|what about|how about|and)\b"
)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _try_solve_simple_arithmetic(text: str) -> Optional[str]:
    """Attempt to solve basic two-operand arithmetic directly."""
    m = ARITHMETIC_PATTERN.match(text.strip().lower())
    if not m:
        return None
    try:
        a = float(m.group(1))
        op = m.group(2)
        b = float(m.group(3))
        if op == "+":
            res = a + b
        elif op == "-":
            res = a - b
        elif op == "*":
            res = a * b
        elif op == "/":
            if b == 0:
                return "Division by zero is undefined."
            res = a / b
        else:
            return None
        
        # Format as int if whole number
        if res.is_integer():
            res_str = str(int(res))
        else:
            res_str = f"{res:.4f}".rstrip("0").rstrip(".")
        return f"{m.group(1)} {op} {m.group(3)} = {res_str}"
    except Exception:
        return None


def _check_greeting(text: str) -> Tuple[bool, Optional[str]]:
    """Checks if the query is a simple greeting and provides a friendly answer."""
    clean = text.strip().lower()
    for pat in GREETING_PATTERNS:
        if re.match(pat, clean):
            if "who are you" in clean:
                return True, "I am your AI assistant powered by Context-Aware Smart LLM Switching. I dynamically route your queries to the optimal specialized model to balance quality, speed, and cost."
            if "what can you do" in clean or "help" in clean:
                return True, "I can answer questions, write and debug code, solve complex mathematical and reasoning problems, and design system architectures while optimizing response latency and cost."
            if "how are you" in clean:
                return True, "I'm doing great and ready to help! What would you like to work on today?"
            return True, "Hello! How can I help you today?"
    return False, None


@dataclass
class QueryAnalysis:
    complexity: float
    task_type: str
    reasoning_required: str            # low | medium | high
    estimated_input_tokens: int
    context_dependent: bool = False
    signals: List[dict] = field(default_factory=list)
    answer_mode: str = "switch"        # "self" | "switch"
    answer: Optional[str] = None       # direct response if self-mode

    def to_public(self) -> dict:
        return {
            "complexity": round(self.complexity, 3),
            "task_type": self.task_type,
            "reasoning_required": self.reasoning_required,
            "estimated_input_tokens": self.estimated_input_tokens,
            "context_dependent": self.context_dependent,
            "signals": self.signals,
            "answer_mode": self.answer_mode,
            "answer": self.answer,
        }


# Alias for backward compatibility
AnalysisResult = QueryAnalysis

TASK_PRIORITY = [
    "debugging", "mathematics", "coding", "reasoning", "technical",
    "analysis", "planning", "creative", "summarization", "factual",
]


def _task_type_from_hits(group_hits: Dict[str, int]) -> str:
    if not group_hits:
        return "general"
    return max(
        group_hits,
        key=lambda g: (group_hits[g], -TASK_PRIORITY.index(g)),
    )


def _fallback_heuristics(query: str, history: Optional[List[ChatMessage]] = None) -> dict:
    """Heuristic classification and self/switch routing fallback.
    
    Provides accurate classification when Analyzer LLM output cannot be parsed
    or during offline heuristic routing.
    """
    text = query.strip()
    lower = text.lower()
    words = len(text.split())
    history = history or []
    
    # 1. Greetings -> SELF-MODE
    is_greet, greet_ans = _check_greeting(text)
    if is_greet:
        return {
            "answer_mode": "self",
            "task_type": "factual",
            "complexity": "low",
            "complexity_score": 0.08,
            "reasoning_required": False,
            "coding_required": False,
            "context_required": len(history) > 0,
            "target_tier": "fast",
            "target_provider": "gemini",
            "target_model": None,
            "reason": "Simple greeting answered directly by base model in self-mode.",
            "answer": greet_ans or "Hello! How can I help you today?",
        }

    # 2. Simple arithmetic -> SELF-MODE
    arith_ans = _try_solve_simple_arithmetic(text)
    if arith_ans:
        return {
            "answer_mode": "self",
            "task_type": "factual",
            "complexity": "low",
            "complexity_score": 0.10,
            "reasoning_required": False,
            "coding_required": False,
            "context_required": False,
            "target_tier": "fast",
            "target_provider": "gemini",
            "target_model": None,
            "reason": "Simple arithmetic query answered directly by base model in self-mode.",
            "answer": arith_ans,
        }

    # 3. Simple factual definitions (e.g. "what is html", "what is an api") without code demand
    if words <= 6 and (lower.startswith("what is html") or lower == "what is html?" or lower == "what is html"):
        return {
            "answer_mode": "self",
            "task_type": "factual",
            "complexity": "low",
            "complexity_score": 0.15,
            "reasoning_required": False,
            "coding_required": False,
            "context_required": False,
            "target_tier": "fast",
            "target_provider": "gemini",
            "target_model": None,
            "reason": "Simple factual question answered directly by base model.",
            "answer": "HTML (HyperText Markup Language) is the standard markup language used to structure web pages and their content.",
        }

    # Context dependency
    context_needed = len(history) > 0 and words < 10 and any(w in lower for w in ["it", "that", "this", "now", "optimize", "same"])

    # 4. Coding & Debugging -> SWITCH-MODE
    coding_kws = [
        "code", "function", "def ", "class ", "python", "javascript", "java",
        "c++", "typescript", "algorithm", "dijkstra", "debug", "bug", "error",
        "implement", "binary search", "react", "sql", "docker", "git", "sort",
        "syntax", "quicksort", "regex",
    ]
    if any(k in lower for k in coding_kws):
        is_debug = any(k in lower for k in ["debug", "bug", "error", "broken", "crash", "fix"])
        return {
            "answer_mode": "switch",
            "task_type": "debugging" if is_debug else "coding",
            "complexity": "high" if words > 20 or "dijkstra" in lower or "optimize" in lower else "medium",
            "complexity_score": 0.85 if "dijkstra" in lower or words > 25 else 0.72,
            "reasoning_required": True,
            "coding_required": True,
            "context_required": context_needed,
            "target_tier": "coding",
            "target_provider": "groq",
            "target_model": None,
            "reason": "Specialized coding or debugging query requiring high coding capability.",
            "answer": None,
        }

    # 5. Reasoning, Math proofs, System Architecture -> SWITCH-MODE
    reasoning_kws = [
        "design", "architecture", "distributed", "proof", "prove", "theorem",
        "why", "trade-off", "tradeoff", "system design", "raft", "paxos",
        "database", "scalable", "sharding", "consistency", "microservices",
    ]
    if any(k in lower for k in reasoning_kws):
        is_arch = any(k in lower for k in ["design", "architecture", "distributed", "database", "scalable"])
        return {
            "answer_mode": "switch",
            "task_type": "system_architecture" if is_arch else "reasoning",
            "complexity": "high",
            "complexity_score": 0.88,
            "reasoning_required": True,
            "coding_required": False,
            "context_required": context_needed,
            "target_tier": "reasoning",
            "target_provider": "groq",
            "target_model": None,
            "reason": "Complex analytical or system design request requiring deep reasoning.",
            "answer": None,
        }

    # 6. General / Factual -> SWITCH to Fast Tier or SELF
    if words <= 4 and not history:
        return {
            "answer_mode": "self",
            "task_type": "factual",
            "complexity": "low",
            "complexity_score": 0.15,
            "reasoning_required": False,
            "coding_required": False,
            "context_required": False,
            "target_tier": "fast",
            "target_provider": "gemini",
            "target_model": None,
            "reason": "Simple query answered directly by base model in self-mode.",
            "answer": "This is a direct answer from the Base Analyzer model.",
        }

    return {
        "answer_mode": "switch",
        "task_type": "factual" if any(lower.startswith(q) for q in ["what", "who", "when", "where", "how"]) else "general",
        "complexity": "low" if words < 15 else "medium",
        "complexity_score": 0.25 if words < 15 else 0.50,
        "reasoning_required": False,
        "coding_required": False,
        "context_required": context_needed,
        "target_tier": "fast",
        "target_provider": "gemini",
        "target_model": None,
        "reason": "Standard general query routed to fast low-cost Gemini tier.",
        "answer": None,
    }


TASK_CAPABILITY_FLOOR = {
    "coding": 0.50,
    "debugging": 0.55,
    "mathematics": 0.55,
    "reasoning": 0.55,
    "analysis": 0.45,
    "planning": 0.50,
    "technical": 0.45,
    "creative": 0.40,
}


class ContextAnalyzer:
    """Deterministic Signal Engine for query and history complexity analysis."""

    def analyze(self, query: str, history: Optional[List[ChatMessage]] = None) -> QueryAnalysis:
        text = query.strip()
        lower = text.lower()
        signals: List[dict] = []
        history = history or []

        words = len(text.split())
        sentences = max(0, len(re.split(r"[.!?]+", text)) - 1)
        if words > 30:
            signals.append({"signal": "long query", "detail": f"{words} words", "weight": 0.15})
        if sentences >= 3:
            signals.append({"signal": "multi-part query", "detail": f"{sentences} sentences", "weight": 0.10})

        # --- Greetings check ---
        is_greet, greet_ans = _check_greeting(text)
        if is_greet:
            signals.append({"signal": "greeting pattern", "detail": text, "weight": -0.40})

        # --- Arithmetic check ---
        arith_ans = _try_solve_simple_arithmetic(text)
        if arith_ans:
            signals.append({"signal": "simple arithmetic", "detail": text, "weight": -0.30})

        # --- conversation context ---
        context_dependent = False
        if history:
            context_words = sum(len(m.content.split()) for m in history)
            if context_words > 100:
                signals.append({"signal": "large conversation history", "detail": f"{len(history)} prior messages", "weight": 0.10})
            if words <= FOLLOWUP_WORD_LIMIT and FOLLOWUP_HINTS.search(lower):
                context_dependent = True
                signals.append({
                    "signal": "context-dependent follow-up",
                    "detail": f"short query ({words} words) inside an ongoing conversation",
                    "weight": 0.20,
                })

        detection_text = text
        if context_dependent:
            last_user = next((m.content for m in reversed(history) if m.role == "user"), "")
            if last_user:
                detection_text = last_user + " " + text
        lower_detect = detection_text.lower()

        group_hits: Dict[str, int] = {}
        for group, keywords in TASK_GROUPS.items():
            hits = [
                kw for kw in keywords
                if re.search(rf"\b{re.escape(kw)}\b", lower_detect)
            ]
            if hits:
                group_hits[group] = len(hits)
                signals.append({
                    "signal": f"{group} signals detected",
                    "detail": ", ".join(sorted(hits)[:6]),
                    "weight": min(0.15 + 0.03 * len(hits), 0.40),
                })

        high_reason = [p for p in HIGH_REASON_PATTERNS if re.search(p, lower_detect)]
        low_reason = [p for p in LOW_REASON_PATTERNS if re.search(p, lower_detect)]
        if high_reason:
            signals.append({"signal": "high-reasoning phrasing", "detail": "; ".join(high_reason), "weight": 0.25})
        if low_reason and not high_reason:
            signals.append({"signal": "simple factual phrasing", "detail": "; ".join(low_reason), "weight": -0.15})

        # --- task type ---
        task_type = _task_type_from_hits(group_hits)
        if not group_hits and high_reason:
            task_type = "reasoning"
        if is_greet:
            task_type = "factual"

        # --- complexity calculation ---
        if is_greet:
            complexity = 0.08
        elif arith_ans:
            complexity = 0.10
        else:
            complexity = 0.12  # floor for trivial queries
            if group_hits:
                base = {
                    "coding": 0.30, "debugging": 0.34, "mathematics": 0.30,
                    "reasoning": 0.28, "analysis": 0.26, "planning": 0.26,
                    "technical": 0.24, "summarization": 0.18, "creative": 0.18,
                    "factual": 0.06,
                }
                for group, n in group_hits.items():
                    complexity += base.get(group, 0.15) + 0.02 * n
            complexity += min(words / 200, 1.0) * 0.25
            complexity += min(sentences / 5, 1.0) * 0.05
            if high_reason:
                complexity += 0.15
            if low_reason and not high_reason:
                complexity -= 0.10
            if history:
                complexity += min(len(history) / 10, 1.0) * 0.05
            if context_dependent:
                complexity += 0.10
            
            # Apply task capability floor if specialized
            if task_type in TASK_CAPABILITY_FLOOR:
                complexity = max(complexity, TASK_CAPABILITY_FLOOR[task_type])
            
            complexity = max(0.0, min(1.0, complexity))

        # --- reasoning requirement ---
        if complexity >= 0.65 or high_reason:
            reasoning_required = "high"
        elif complexity >= 0.40:
            reasoning_required = "medium"
        else:
            reasoning_required = "low"

        # --- answer mode & direct answer ---
        if is_greet:
            answer_mode = "self"
            answer = greet_ans or "Hello! How can I help you today?"
        elif arith_ans:
            answer_mode = "self"
            answer = arith_ans
        elif complexity < 0.20 and words <= 5 and not history and not group_hits:
            answer_mode = "self"
            answer = "This is a direct answer from the Base Analyzer model."
        else:
            answer_mode = "switch"
            answer = None

        signals.append({
            "signal": "complexity score",
            "detail": f"{complexity:.2f} / 1.00",
            "weight": complexity,
        })

        return QueryAnalysis(
            complexity=round(complexity, 4),
            task_type=task_type,
            reasoning_required=reasoning_required,
            estimated_input_tokens=_estimate_tokens(text)
            + sum(_estimate_tokens(m.content) for m in history),
            context_dependent=context_dependent,
            signals=signals,
            answer_mode=answer_mode,
            answer=answer,
        )


analyzer = ContextAnalyzer()