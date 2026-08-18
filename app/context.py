"""Cost-aware conversation context management and token budgeting.

Intelligently builds the message list sent to a model from conversation history,
trimming old turns so the token budget (MAX_CONTEXT_TOKENS) is strictly respected.
Preserves system prompts, retains conversation anchor when possible, and maintains
chronological ordering.
"""

from typing import List, Optional

from .config import settings
from .schemas import ChatMessage


def estimate_tokens(text: str) -> int:
    """Estimates token count from text using standard character heuristic (~4 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# Backward-compatibility alias
_estimate_tokens = estimate_tokens


class ContextManager:
    """Manages token budgeting and conversation history pruning."""

    def __init__(self, max_context_tokens: Optional[int] = None):
        self.default_max_tokens = max_context_tokens or getattr(settings, "max_context_tokens", 4096)

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
    ) -> List[ChatMessage]:
        """Trims history to stay within `max_tokens` budget and appends the user query.
        
        Preserves:
        1. System prompt (if specified or configured)
        2. Anchor message (the initial conversation context) if it fits
        3. Most recent turns in chronological order
        4. Current user query
        """
        budget = max(max_tokens or self.default_max_tokens, 256)
        history = list(history or [])
        
        sys_text = (system_prompt if system_prompt is not None else getattr(settings, "system_prompt", "")) or ""
        sys_text = sys_text.strip()
        sys_tokens = self.estimate_tokens(sys_text) + 4 if sys_text else 0
        
        query_tokens = self.estimate_tokens(query) + 4

        # Reserve headroom for query processing & generation buffer (at least 256 tokens or 25% of budget)
        reserved_headroom = max(256, budget // 4)
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
    ) -> List[ChatMessage]:
        """Convenience alias for build_context."""
        return self.build_context(query, history=history, max_tokens=max_tokens, system_prompt=system_prompt)


# Module-level default singleton
context_manager = ContextManager()


def build_messages(
    history: List[ChatMessage],
    query: str,
    max_tokens: Optional[int] = None,
    system_prompt: Optional[str] = None,
) -> List[ChatMessage]:
    """Trim history to `max_tokens` (or settings.max_context_tokens) and append the user query."""
    return context_manager.build_context(
        query=query,
        history=history,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )


def build_context(
    query: str,
    history: Optional[List[ChatMessage]] = None,
    max_tokens: Optional[int] = None,
    system_prompt: Optional[str] = None,
) -> List[ChatMessage]:
    """Helper to build pruned context with user query."""
    return context_manager.build_context(
        query=query,
        history=history,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )