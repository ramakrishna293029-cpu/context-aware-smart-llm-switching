"""Cost-aware conversation context management and token budgeting.

Intelligently builds the message list sent to a model from conversation history,
trimming old turns so the token budget (MAX_CONTEXT_TOKENS) is strictly respected.
Preserves system prompts, retains conversation anchor when possible, and maintains
chronological ordering.
"""

from typing import Dict, List, Optional

from .config import settings
from .schemas import ChatMessage


# ---------------------------------------------------------------------------
# Tier-Specific Production Personas & Response Formatting Standards
# ---------------------------------------------------------------------------
MODEL_TIER_PERSONAS: Dict[str, str] = {
    "analyzer": (
        "You are an expert, instant AI assistant. "
        "Provide direct, accurate, and crisp responses. "
        "Format your answer with clean bullet points where appropriate. "
        "Maintain a concise, medium-to-short length with zero conversational filler."
    ),
    "fast": (
        "You are a high-speed factual and general intelligence assistant. "
        "Deliver clear, well-structured, and concise information. "
        "Group key takeaways into clean bullet bunches. "
        "Keep responses focused, informative, and medium-to-short in length."
    ),
    "coding": (
        "You are a principal software engineer and expert coding specialist. "
        "Provide clean, production-grade, bug-free code with syntax highlighting. "
        "Structure explanations with concise bullet bunches covering key design choices, time/space complexity, and edge cases. "
        "Keep non-code explanations concise and tightly focused."
    ),
    "reasoning": (
        "You are an advanced analytical reasoning and systems architecture specialist. "
        "Break down complex problems, proofs, logic, and trade-offs into structured steps. "
        "Organize deductions and conclusions into clean, bullet-bunched sections. "
        "Deliver sharp, rigorous, medium-to-short explanations without unnecessary fluff."
    ),
    "powerful": (
        "You are a comprehensive multi-domain AI problem solver. "
        "Synthesize high-depth answers with structured clarity. "
        "Use bullet bunches for key concepts, actionable steps, and trade-offs. "
        "Maintain an authoritative, elegant, and concise tone."
    ),
    "balanced": (
        "You are a versatile, well-rounded AI assistant. "
        "Provide clear, accurate, and structured responses with bullet-bunched key points. "
        "Keep answers medium-to-short, highly informative, and easy to read."
    ),
    "custom": (
        "You are an expert AI assistant. "
        "Provide direct, well-structured responses formatted with clean bullet bunches. "
        "Keep response length medium-to-short with high information density."
    ),
}

DEFAULT_SYSTEM_PERSONA = (
    "You are a helpful, expert AI assistant. Provide accurate, clear, and direct responses "
    "formatted with concise bullet bunches and structured sections where appropriate. "
    "Keep responses medium-to-short in length."
)


def get_tier_persona(tier: str, custom_system_prompt: Optional[str] = None) -> str:
    """Returns the production persona tailored to the model's tier.
    
    If a custom_system_prompt is provided by the user/session, appends formatting guidelines.
    """
    if custom_system_prompt and custom_system_prompt.strip():
        base = custom_system_prompt.strip()
        formatting = (
            "\n\nResponse formatting guidelines:\n"
            "- Structure your response with clean bullet bunches where applicable.\n"
            "- Keep answers medium-to-short in length, crisp, and informative.\n"
            "- For code, provide clean syntax-highlighted code blocks with brief explanations."
        )
        return base + formatting

    return MODEL_TIER_PERSONAS.get(tier.lower(), DEFAULT_SYSTEM_PERSONA)


def estimate_tokens(text: str) -> int:
    """Estimates token count from text using standard character heuristic (~4 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# Backward-compatibility alias
_estimate_tokens = estimate_tokens


class ContextManager:
    """Manages token budgeting and conversation history pruning up to 128K tokens."""

    def __init__(self, max_context_tokens: Optional[int] = None):
        self.default_max_tokens = max_context_tokens or getattr(settings, "max_context_tokens", 131072)

    def estimate_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def get_token_count(self, messages: List[ChatMessage]) -> int:
        """Calculates total estimated tokens for a list of ChatMessages including framing."""
        total = 0
        for msg in messages:
            total += self.estimate_tokens(msg.content) + 4  # 4 tokens per message framing overhead
        return total

    def build_context(
        self,
        query: str,
        history: Optional[List[ChatMessage]] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[ChatMessage]:
        """Trims history to stay within `max_tokens` (default 128K) and appends the user query.
        
        Preserves:
        1. System prompt / Tier persona (if specified or configured)
        2. Anchor message (the initial conversation context) if it fits
        3. Most recent turns in chronological order
        4. Current user query
        """
        budget = max(max_tokens or self.default_max_tokens, 256)
        history = list(history or [])
        
        # Determine system persona
        if system_prompt is not None and system_prompt != "":
            sys_text = system_prompt.strip()
        elif tier:
            sys_text = get_tier_persona(tier)
        else:
            base_prompt = getattr(settings, "system_prompt", "") or ""
            sys_text = base_prompt.strip()

        sys_tokens = self.estimate_tokens(sys_text) + 4 if sys_text else 0
        query_tokens = self.estimate_tokens(query) + 4

        # Reserve headroom for query processing & generation buffer (at least 256 tokens or 25% of budget, capped at 4096)
        reserved_headroom = min(4096, max(256, budget // 8))
        history_budget = budget - reserved_headroom - query_tokens - sys_tokens
        if history_budget < 0:
            history_budget = 0

        kept: List[ChatMessage] = []
        used = 0

        # Traverse backwards from newest to oldest
        for msg in reversed(history):
            cost = self.estimate_tokens(msg.content) + 4
            if used + cost > history_budget:
                break
            kept.append(msg)
            used += cost

        # Retain original conversation anchor (first message) if it fits and isn't already included
        if kept and history and kept[-1] is not history[0]:
            anchor = history[0]
            anchor_cost = self.estimate_tokens(anchor.content) + 4
            if used + anchor_cost <= history_budget:
                kept.append(anchor)
                used += anchor_cost

        # Re-order chronologically
        ordered = list(reversed(kept))

        # Insert system prompt at index 0 if present
        if sys_text:
            ordered.insert(0, ChatMessage(role="system", content=sys_text))

        # Append current user query
        ordered.append(ChatMessage(role="user", content=query))

        return ordered

    def prune(
        self,
        query: str,
        history: Optional[List[ChatMessage]] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> List[ChatMessage]:
        """Convenience alias for build_context."""
        return self.build_context(
            query,
            history=history,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            tier=tier,
        )


# Module-level default singleton
context_manager = ContextManager()


def build_messages(
    history: List[ChatMessage],
    query: str,
    max_tokens: Optional[int] = None,
    system_prompt: Optional[str] = None,
    tier: Optional[str] = None,
) -> List[ChatMessage]:
    """Trim history to `max_tokens` (default 128K) and append the user query with tier persona."""
    return context_manager.build_context(
        query=query,
        history=history,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        tier=tier,
    )


def build_context(
    query: str,
    history: Optional[List[ChatMessage]] = None,
    max_tokens: Optional[int] = None,
    system_prompt: Optional[str] = None,
    tier: Optional[str] = None,
) -> List[ChatMessage]:
    """Helper to build pruned context with user query."""
    return context_manager.build_context(
        query=query,
        history=history,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        tier=tier,
    )