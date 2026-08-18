"""Cost-aware conversation context management.

Builds the message list sent to a model from the conversation history,
trimming old turns so the token budget is respected. Only the tail of
the conversation is sent (recent messages), which keeps context cost
low while preserving what the router needs to interpret follow-ups.
"""

from typing import List

from .config import settings
from .schemas import ChatMessage


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def build_messages(history: List[ChatMessage], query: str) -> List[ChatMessage]:
    """Trim history to `MAX_CONTEXT_TOKENS` and append the user query."""
    budget = max(settings.max_context_tokens, 256)
    query_tokens = _estimate_tokens(query)
    system_prompt = (settings.system_prompt or "").strip()
    system_tokens = _estimate_tokens(system_prompt) if system_prompt else 0

    # Reserve at least 30% of the budget for the live query + response room.
    reserved = max(256, budget // 3)
    history_budget = budget - reserved - query_tokens - system_tokens
    if history_budget < 0:
        history_budget = 0

    kept: List[ChatMessage] = []
    used = 0
    for msg in reversed(history):
        cost = _estimate_tokens(msg.content)
        if used + cost > history_budget:
            break
        kept.append(msg)
        used += cost

    # First message stays as the conversation anchor when there is room.
    if kept and history and kept[-1] is not history[0] and used + _estimate_tokens(history[0].content) <= history_budget:
        kept.append(history[0])

    ordered = list(reversed(kept))
    if system_prompt:
        ordered.insert(0, ChatMessage(role="system", content=system_prompt))
    ordered.append(ChatMessage(role="user", content=query))
    return ordered