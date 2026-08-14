"""Context Analyzer: turns a raw query into a structured complexity profile.

Rule-based and fully transparent for the first prototype: every decision
emits a human-readable signal list. The `analyze()` interface is stable so
this component can later be swapped for an ML classifier without touching
the router.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List

from .schemas import ChatMessage

# Keyword groups with per-keyword weight. Queries can match multiple
# groups; the strongest group drives the task type, all of them raise
# the complexity estimate.
TASK_GROUPS: Dict[str, List[str]] = {
    "coding": [
        "code", "function", "bug", "debug", "error", "exception", "syntax",
        "python", "javascript", "java", "c++", "typescript", "html tag",
        "sql", "api", "endpoint", "request", "database", "algorithm", "loop",
        "variable", "class", "module", "library", "framework", "regex",
        "compile", "deploy", "refactor", "test", "unit test", "docker",
        "git", "thread", "concurrency", "performance issue", "memory leak",
        "stack trace", "flask", "django", "react", "node", "pandas", "numpy",
    ],
    "math": [
        "calculate", "equation", "solve", "integral", "derivative", "theorem",
        "proof", "prove", "matrix", "vector", "probability", "statistics", "algebra",
        "geometry", "sum", "average", "mean", "median", "percentage",
        "linear regression", "bayes", "gradient", "eigenvalue",
    ],
    "reasoning": [
        "why", "explain", "analyze", "compare", "contrast", "evaluate",
        "argue", "criticize", "justify", "implications", "consequences",
        "trade-off", "root cause", "hypothesis", "logical", "synthesize",
        "strategy", "recommend", "optimize", "design", "architecture",
        "review", "debug this", "refactor this", "assess", "judge",
    ],
    "creative": [
        "write a story", "poem", "essay", "brainstorm", "ideas", "creative",
        "rewrite", "tone", "marketing", "ad copy", "tagline", "blog post",
        "social media", "dialogue", "novel", "script",
    ],
    "factual": [
        "what is", "define", "who", "when was", "where", "list", "name the",
        "history of", "capital of", "meaning of", "how many", "facts",
        "summary", "overview", "introduction",
    ],
}

# Phrases that signal high reasoning demand beyond raw keyword counts.
HIGH_REASON_PATTERNS = [
    r"explain.*in detail",
    r"step.?by.?step",
    r"prove",
    r"write.*code.*(?:that|to|which)",
    r"debug|fix.*error|fix.*bug",
    r"why.*fail",
    r"design.*(?:system|architecture|database|api)",
    r"compare and contrast",
    r"complex|advanced|difficult|challenging",
]

LOW_REASON_PATTERNS = [
    r"^what is\b",
    r"^define\b",
    r"^who\b",
    r"^list\b",
    r"^name\b",
    r"^hi\b|^hello\b|^hey\b",
]


@dataclass
class QueryAnalysis:
    complexity: float
    task_type: str
    reasoning_required: str            # low | medium | high
    estimated_input_tokens: int
    signals: List[dict] = field(default_factory=list)

    def to_public(self) -> dict:
        return {
            "complexity": round(self.complexity, 3),
            "task_type": self.task_type,
            "reasoning_required": self.reasoning_required,
            "estimated_input_tokens": self.estimated_input_tokens,
            "signals": self.signals,
        }


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ContextAnalyzer:
    def analyze(self, query: str, history: List[ChatMessage] | None = None) -> QueryAnalysis:
        text = query.strip()
        lower = text.lower()
        signals: List[dict] = []

        group_hits: Dict[str, int] = {}
        for group, keywords in TASK_GROUPS.items():
            hits = [kw for kw in keywords if kw in lower]
            if hits:
                group_hits[group] = len(hits)
                signals.append({
                    "signal": f"{group} signals detected",
                    "detail": ", ".join(sorted(hits)[:6]),
                    "weight": min(0.15 + 0.03 * len(hits), 0.40),
                })

        words = len(text.split())
        sentences = len(re.split(r"[.!?]+", text)) - 1
        if words > 30:
            signals.append({"signal": "long query", "detail": f"{words} words", "weight": 0.15})
        if sentences >= 3:
            signals.append({"signal": "multi-part query", "detail": f"{sentences} sentences", "weight": 0.10})

        high_reason = [p for p in HIGH_REASON_PATTERNS if re.search(p, lower)]
        low_reason = [p for p in LOW_REASON_PATTERNS if re.search(p, lower)]
        if high_reason:
            signals.append({"signal": "high-reasoning phrasing", "detail": "; ".join(high_reason), "weight": 0.25})
        if low_reason and not high_reason:
            signals.append({"signal": "simple factual phrasing", "detail": "; ".join(low_reason), "weight": -0.15})

        if history:
            context_words = sum(len(m.content.split()) for m in history)
            if context_words > 100:
                signals.append({"signal": "large conversation history", "detail": f"{len(history)} prior messages", "weight": 0.10})

        complexity = 0.12  # floor for trivial queries
        if group_hits:
            for group, n in group_hits.items():
                base = {"coding": 0.30, "math": 0.30, "reasoning": 0.28,
                        "creative": 0.18, "factual": 0.06}[group]
                complexity += base + 0.02 * n
        complexity += min(words / 200, 1.0) * 0.25
        complexity += min(sentences / 5, 1.0) * 0.05
        if high_reason:
            complexity += 0.15
        if low_reason and not high_reason:
            complexity -= 0.10
        if history:
            complexity += min(len(history) / 10, 1.0) * 0.05
        complexity = max(0.0, min(1.0, complexity))

        if group_hits:
            task_type = max(group_hits, key=lambda g: (group_hits[g], g))
        elif high_reason:
            task_type = "reasoning"
        else:
            task_type = "general"

        if complexity >= 0.65 or high_reason:
            reasoning_required = "high"
        elif complexity >= 0.40:
            reasoning_required = "medium"
        else:
            reasoning_required = "low"

        signals.append({
            "signal": "complexity score",
            "detail": f"{complexity:.2f} / 1.00",
            "weight": complexity,
        })

        return QueryAnalysis(
            complexity=round(complexity, 4),
            task_type=task_type,
            reasoning_required=reasoning_required,
            estimated_input_tokens=_estimate_tokens(text) + sum(_estimate_tokens(m.content) for m in (history or [])),
            signals=signals,
        )


analyzer = ContextAnalyzer()