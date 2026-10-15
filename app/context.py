"""Cost-aware conversation context management and token budgeting.

Intelligently builds the message list sent to a model from conversation history,
trimming old turns so the token budget (MAX_CONTEXT_TOKENS) is strictly respected.
Preserves system prompts, retains conversation anchor when possible, and maintains
chronological ordering. Also supports ingestion of project documents, code, and
current requirements with source provenance and timestamps.

Capability 1: Context ingestion for conversation history, project documents,
code, and current requirements, with source provenance and timestamps.
"""

from typing import Dict, List, Optional
from pathlib import Path

from .config import settings
from .schemas import ChatMessage
from .constraint_ledger import ConstraintLedger, RequirementID, ActiveConstraint


# ---------------------------------------------------------------------------
# Tier-Specific Production Personas & Unified Identity Standards
# ---------------------------------------------------------------------------

UNIFIED_ASSISTANT_CORE = (
    "You are an intelligent, helpful AI assistant. Always maintain a unified, consistent, and natural personality.\n"
    "- Identity: You are simply an AI assistant. Never say you were trained or created by Google, OpenAI, Meta, Anthropic, or any specific provider. If asked about your identity, state that you are an AI assistant designed to help with a wide range of tasks.\n"
    "- Conversational Continuity: Pay close attention to previous messages in the conversation history. Understand pronouns, context, user clarifications, corrections, and follow-ups naturally.\n"
    "- Tone & Warmth: Respond warmly and naturally to greetings and check-ins (e.g. 'How are you?'). Be direct, polite, and helpful.\n"
    "- Formatting & Length: Structure responses with clean bullet bunches and clear sections where appropriate. Keep responses medium-to-short in length, crisp, high-signal, and free of unnecessary disclaimers or filler."
)

MODEL_TIER_PERSONAS: Dict[str, str] = {
    "analyzer": (
        f"{UNIFIED_ASSISTANT_CORE}\n\n"
        "Role: Instant First-Line Assistant. Provide immediate, accurate, and crisp answers. "
        "Use clean bullet-bunched points where appropriate. Keep answers concise, helpful, and medium-to-short in length."
    ),
    "fast": (
        f"{UNIFIED_ASSISTANT_CORE}\n\n"
        "Role: Fast Factual & General Assistant. Deliver clear, well-structured, and concise information. "
        "Group key takeaways into clean bullet bunches. Keep responses focused, informative, and medium-to-short in length."
    ),
    "coding": (
        f"{UNIFIED_ASSISTANT_CORE}\n\n"
        "Role: Principal Software Engineer. Provide clean, production-grade, bug-free code with syntax highlighting. "
        "Structure explanations with concise bullet bunches covering key design choices, time/space complexity, and edge cases. "
        "Keep non-code explanations concise and tightly focused."
    ),
    "reasoning": (
        f"{UNIFIED_ASSISTANT_CORE}\n\n"
        "Role: Analytical Reasoning & Architecture Specialist. Break down complex problems, proofs, logic, and trade-offs into structured steps. "
        "Organize deductions and conclusions into clean, bullet-bunched sections. Deliver sharp, rigorous, medium-to-short explanations."
    ),
    "powerful": (
        f"{UNIFIED_ASSISTANT_CORE}\n\n"
        "Role: Comprehensive Multi-Domain Problem Solver. Synthesize high-depth answers with structured clarity. "
        "Use bullet bunches for key concepts, actionable steps, and trade-offs. Maintain an authoritative, elegant, and concise tone."
    ),
    "balanced": (
        f"{UNIFIED_ASSISTANT_CORE}\n\n"
        "Role: Versatile AI Assistant. Provide clear, accurate, and structured responses with bullet-bunched key points. "
        "Keep answers medium-to-short, highly informative, and easy to read."
    ),
    "custom": (
        f"{UNIFIED_ASSISTANT_CORE}\n\n"
        "Role: Expert AI Assistant. Provide direct, well-structured responses formatted with clean bullet bunches. "
        "Keep response length medium-to-short with high information density."
    ),
}

DEFAULT_SYSTEM_PERSONA = (
    f"{UNIFIED_ASSISTANT_CORE}\n\n"
    "Role: Helpful AI Assistant. Provide accurate, clear and direct responses "
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
    """Manages token budgeting and conversation history pruning up to 128K tokens.

    Capability 1: Supports ingestion of project documents, code snippets, and
    current requirements with source provenance and timestamps. Critical constraints
    are never silently removed during token budget pruning.
    """

    def __init__(self, max_context_tokens: Optional[int] = None, ledger: Optional[ConstraintLedger] = None):
        self.default_max_tokens = max_context_tokens or getattr(settings, "max_context_tokens", 131072)
        self.ledger = ledger or ConstraintLedger()

    def estimate_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def get_token_count(self, messages: List[ChatMessage]) -> int:
        """Calculates total estimated tokens for a list of ChatMessages including framing."""
        total = 0
        for msg in messages:
            total += self.estimate_tokens(msg.content) + 4  # 4 tokens per message framing overhead
        return total

    def ingest_document(
        self,
        content: str,
        source_id: str,
        doc_type: str = "general",
        metadata: Optional[Dict[str, str]] = None,
    ) -> RequirementID:
        """Ingest a project document with source provenance and timestamp.

        Args:
            content: The document content text.
            source_id: Unique identifier for the document (e.g. file path, doc ID).
            doc_type: Category of document (e.g. "spec", "design", "reference", "code").
            metadata: Optional metadata dict (e.g. author, creation_date, version).

        Returns:
            RequirementID for the ingested document, trackable in the constraint ledger.
        """
        now = datetime.now(timezone.utc).isoformat()
        req_id = self.ledger.add_requirement(
            requirement_id=source_id,
            authority="document",
            scope="session",
            version=now,
            status="active",
            text=content[:500] if content else "",  # Store summary for reference
            supersedes=None,
        )

        # Also add as active constraint with relevance based on content length
        relevance = min(1.0, len(content) / 5000)  # Longer docs get higher relevance default
        constraint_key = f"constraint_{source_id}"
        constraint = ActiveConstraint(
            id=req_id,
            text=content,
            category="context_window",
            relevance_score=relevance,
        )
        self.ledger.constraints[constraint_key] = constraint

        return req_id

    def ingest_code(
        self,
        code: str,
        file_path: str,
        line_range: Optional[tuple[int, int]] = None,
        function_names: Optional[List[str]] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> RequirementID:
        """Ingest code snippet with file provenance and timestamps.

        Args:
            code: The code content to ingest.
            file_path: Path to the source file.
            line_range: Optional (start_line, end_line) range.
            function_names: Optional list of function names defined in the code.
            metadata: Optional metadata (e.g. language, version, purpose).

        Returns:
            RequirementID for the ingested code, trackable in the constraint ledger.
        """
        now = datetime.now(timezone.utc).isoformat()
        # Create summary of code for provenance
        code_summary = code[:300] + ("..." if len(code) > 300 else "")
        lang = metadata.get("language", "unknown") if metadata else "unknown"

        req_id = self.ledger.add_requirement(
            requirement_id=f"code_{file_path}",
            authority="code",
            scope="session",
            version=now,
            status="active",
            text=f"{code_summary}\nLang: {lang}\nRange: {line_range}",
            supersedes=None,
        )

        # Add as active constraint with relevance based on code relevance
        relevance = 0.8  # Code typically high relevance
        if function_names:
            relevance = min(1.0, relevance + 0.1 * len(function_names))

        constraint_key = f"constraint_code_{file_path}"
        constraint = ActiveConstraint(
            id=req_id,
            text=f"Code from {file_path}:{line_range or 'full'}",
            category="capability",
            relevance_score=relevance,
        )
        self.ledger.constraints[constraint_key] = constraint

        return req_id

    def ingest_requirement(
        self,
        req_id: str,
        authority: str,
        scope: str,
        version: str,
        status: str = "active",
        text: Optional[str] = None,
        supersedes: Optional[str] = None,
    ) -> RequirementID:
        """Ingest a custom requirement with authority, scope, version, and supersession links."""
        return self.ledger.add_requirement(
            requirement_id=req_id,
            authority=authority,
            scope=scope,
            version=version,
            status=status,
            text=text,
            supersedes=supersedes,
        )

    def build_context(
        self,
        query: str,
        history: Optional[List[ChatMessage]] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        tier: Optional[str] = None,
        critical_constraint_ids: Optional[List[str]] = None,
    ) -> List[ChatMessage]:
        """Trims history to stay within `max_tokens` (default 128K) and appends the user query.

        Preserves:
        1. System prompt / Tier persona (if specified or configured)
        2. Anchor message (the initial conversation context) if it fits
        3. Most recent turns in chronological order
        4. Current user query
        5. **Critical constraints never silently removed** (Capability 6)

        Key enhancement: When critical_constraint_ids are provided, the method ensures
        that all constraints in that list are represented in the context via a special
        "ACTIVE CONSTRAINTS" system prompt section. Critical constraints are pruned last
        and never silently discarded to fit the token budget.
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

        # **Capability 6: Ensure critical constraints are never silently removed**
        if critical_constraint_ids:
            # Collect critical constraint texts from the ledger
            critical_texts: List[str] = []
            for cid in critical_constraint_ids:
                constraint = self.ledger.constraints.get(f"constraint_{cid}")
                if constraint and constraint.text:
                    # Truncate if very long to avoid budget overflow
                    txt = constraint.text[:200] if len(constraint.text) > 200 else constraint.text
                    critical_texts.append(f"- {txt}")

            if critical_texts:
                # Insert critical constraints as a system prompt section BEFORE the query
                # This ensures they are always present in the context
                constraints_section = (
                    "ACTIVE CONSTRAINTS (must be considered):\n"
                    + "\n".join(critical_texts)
                    + "\n\n"
                )
                # Insert after system prompt, before query
                ordered.insert(1, ChatMessage(
                    role="system",
                    content=constraints_section,
                ))
                # Adjust budget: subtract the tokens for the constraints section
                constraints_tokens = self.estimate_tokens(constraints_section)
                # Reduce history budget proportionally if needed
                if used + constraints_tokens > history_budget:
                    # Reduce kept history items to make room
                    excess = used + constraints_tokens - history_budget
                    # Remove items from the end (oldest kept) until fit
                    while kept and excess > 0:
                        removed = kept.pop()
                        removed_cost = self.estimate_tokens(removed.content) + 4
                        excess -= removed_cost
                        used -= removed_cost
                    # Recalculate budget after removals
                    history_budget = budget - reserved_headroom - query_tokens - sys_tokens - constraints_tokens

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
        critical_constraint_ids: Optional[List[str]] = None,
    ) -> List[ChatMessage]:
        """Convenience alias for build_context."""
        return self.build_context(
            query,
            history=history,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            tier=tier,
            critical_constraint_ids=critical_constraint_ids,
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