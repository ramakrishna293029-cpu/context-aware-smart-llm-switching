"""Context Analyzer: turns a raw query (plus optional conversation) into a
structured complexity profile.

Deterministic scoring engine, fully transparent: every decision emits a
human-readable signal list. The public `analyze()` contract is stable so
this component can later be swapped or supplemented with an ML
classifier without touching the router.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List

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
        "implement", "write a program", "binary search", "sort",
    ],
    "debugging": [
        "debug", "bug", "not working", "broken", "crash", "fails",
        "exception", "stack trace", "error message", "re-render",
        "re-renders", "infinite loop", "fix this", "why is this", "traceback",
        "segfault", "performance issue", "hang", "freeze", "unexpected output",
    ],
    "mathematics": [
        "calculate", "equation", "solve", "integral", "derivative", "theorem",
        "proof", "prove", "matrix", "vector", "probability", "statistics",
        "algebra", "geometry", "sum", "average", "mean", "median", "percentage",
        "linear regression", "bayes", "gradient", "eigenvalue", "irrational",
    ],
    "reasoning": [
        "why", "explain", "argue", "criticize", "justify", "hypothesis",
        "logical", "synthesize", "root cause", "implications", "consequences",
        "trade-off", "assess", "judge", "compare and contrast",
    ],
    "analysis": [
        "analyze", "compare", "evaluate", "review", "critique", "identify",
        "interpret", "inspect", "profile", "benchmark", "impact",
    ],
    "planning": [
        "plan", "roadmap", "strategy", "schedule", "milestones", "steps to",
        "design", "architecture", "deploy plan", "rollout", "prioritize",
        "outline the approach",
    ],
    "technical": [
        "api", "database", "server", "deployment", "protocol", "tcp", "udp",
        "http", "kubernetes", "distributed", "latency", "scalable", "cloud",
        "endpoint", "caching", "load balancer", "replication", "consistency",
        "partition", "networking",
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

# Phrases that signal high reasoning demand beyond raw keyword counts.
# Single-word patterns use word boundaries so "complexity" does not
# trigger the "complex" rule.
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

# Task types that intrinsically need more capability even at low length.
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

# Short queries following a conversation are usually follow-ups whose
# meaning depends on prior turns ("now optimize it").
FOLLOWUP_WORD_LIMIT = 8
FOLLOWUP_HINTS = re.compile(
    r"\b(it|that|this|those|same|then|now|instead|above|below|first|second|"
    r"other|another|one|both|what about|how about|and)\b"
)


@dataclass
class QueryAnalysis:
    complexity: float
    task_type: str
    reasoning_required: str            # low | medium | high
    estimated_input_tokens: int
    context_dependent: bool = False
    signals: List[dict] = field(default_factory=list)

    def to_public(self) -> dict:
        return {
            "complexity": round(self.complexity, 3),
            "task_type": self.task_type,
            "reasoning_required": self.reasoning_required,
            "estimated_input_tokens": self.estimated_input_tokens,
            "context_dependent": self.context_dependent,
            "signals": self.signals,
        }


# Ties between keyword groups prefer the more specialized task type.
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


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ContextAnalyzer:
    def analyze(self, query: str, history: List[ChatMessage] | None = None) -> QueryAnalysis:
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

        # --- conversation context -----------------------------------------
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

        # Follow-ups inherit the subject of the previous user turn so a
        # short "now optimize it" keeps its coding task type.
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

        # --- conversation context -----------------------------------------
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

        # --- complexity -----------------------------------------------------
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
        complexity = max(0.0, min(1.0, complexity))

        # --- task type ------------------------------------------------------
        task_type = _task_type_from_hits(group_hits)
        if not group_hits and high_reason:
            task_type = "reasoning"

        # --- reasoning requirement -----------------------------------------
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
            estimated_input_tokens=_estimate_tokens(text)
            + sum(_estimate_tokens(m.content) for m in history),
            context_dependent=context_dependent,
            signals=signals,
        )


analyzer = ContextAnalyzer()