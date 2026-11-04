"""Regression test suite for Step 1 (Model Persona Mapping) and Step 2 (HTTP Connection Pooling).

Verifies:
- Accurate mapping of 6 registered model tiers to personas.
- Unknown-tier graceful fallback to DEFAULT_SYSTEM_PERSONA.
- Custom system prompt handling and formatting preservation.
- Reusable AsyncClient connection pooling across both Gemini and OpenAI adapters.
- Safe concurrent request client reuse.
- Clean shutdown lifecycle releasing HTTP connection pools.
"""

import asyncio
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from app.context import (
    MODEL_TIER_PERSONAS,
    DEFAULT_SYSTEM_PERSONA,
    PERSONA_FAST,
    PERSONA_CODING,
    PERSONA_REASONING,
    PERSONA_POWERFUL,
    PERSONA_BALANCED,
    PERSONA_ANALYZER,
    get_tier_persona,
    build_messages,
    ContextManager,
)
from app.schemas import ChatMessage
from app.adapters.gemini import GeminiAdapter
from app.adapters.openai import OpenAICompatibleAdapter
from app.adapters.factory import AdapterFactory
from app.registry import ModelSpec


# ==============================================================================
# STEP 1: PERSONA TIER LOOKUP & FALLBACK TESTS
# ==============================================================================

def test_all_six_tiers_return_specialized_personas():
    """Verify each registered tier (tier_1 to tier_6) retrieves its expected persona."""
    # Tier 1 & 2: Fast
    assert get_tier_persona("tier_1") == PERSONA_FAST
    assert "Fast Factual & General Assistant" in get_tier_persona("tier_1")
    assert get_tier_persona("tier_2") == PERSONA_FAST

    # Tier 3: Balanced
    assert get_tier_persona("tier_3") == PERSONA_BALANCED
    assert "Versatile AI Assistant" in get_tier_persona("tier_3")

    # Tier 4: Coding
    assert get_tier_persona("tier_4") == PERSONA_CODING
    assert "Principal Software Engineer" in get_tier_persona("tier_4")

    # Tier 5: Reasoning
    assert get_tier_persona("tier_5") == PERSONA_REASONING
    assert "Analytical Reasoning & Architecture Specialist" in get_tier_persona("tier_5")

    # Tier 6: High-Capability Multi-Domain
    assert get_tier_persona("tier_6") == PERSONA_POWERFUL
    assert "Comprehensive Multi-Domain Problem Solver" in get_tier_persona("tier_6")

    # Analyzer
    assert get_tier_persona("analyzer") == PERSONA_ANALYZER
    assert "Instant First-Line Assistant" in get_tier_persona("analyzer")


def test_persona_case_and_delimiter_insensitivity():
    """Verify tier normalization handles mixed case and hyphens."""
    assert get_tier_persona("TIER_4") == PERSONA_CODING
    assert get_tier_persona("tier-4") == PERSONA_CODING
    assert get_tier_persona(" Tier_1 ") == PERSONA_FAST
    assert get_tier_persona("TIER-6") == PERSONA_POWERFUL


def test_legacy_semantic_aliases_preserved():
    """Verify legacy keys ('fast', 'coding', 'reasoning', etc.) still work."""
    assert get_tier_persona("fast") == PERSONA_FAST
    assert get_tier_persona("coding") == PERSONA_CODING
    assert get_tier_persona("reasoning") == PERSONA_REASONING
    assert get_tier_persona("powerful") == PERSONA_POWERFUL
    assert get_tier_persona("balanced") == PERSONA_BALANCED


def test_unknown_tier_falls_back_to_default_persona():
    """Verify unmapped or unknown tier names fall back to DEFAULT_SYSTEM_PERSONA."""
    assert get_tier_persona("unknown_tier_99") == DEFAULT_SYSTEM_PERSONA
    assert get_tier_persona("nonexistent") == DEFAULT_SYSTEM_PERSONA
    assert get_tier_persona("") == DEFAULT_SYSTEM_PERSONA
    assert get_tier_persona(None) == DEFAULT_SYSTEM_PERSONA
    assert "Helpful AI Assistant" in DEFAULT_SYSTEM_PERSONA


def test_custom_system_prompt_takes_precedence():
    """Verify user/session custom system prompt is honored with appended formatting."""
    custom = "You are a specialized legal document reviewer."
    res = get_tier_persona("tier_4", custom_system_prompt=custom)
    assert res.startswith(custom)
    assert "Response formatting guidelines:" in res
    assert "Principal Software Engineer" not in res  # Overridden by user custom prompt


def test_build_messages_injects_correct_tier_persona():
    """Verify build_messages correctly sets role='system' with tier persona."""
    messages = build_messages(
        history=[],
        query="How do I reverse a linked list?",
        tier="tier_4",
    )
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert "Principal Software Engineer" in messages[0].content
    assert messages[1].role == "user"
    assert messages[1].content == "How do I reverse a linked list?"


# ==============================================================================
# STEP 2: HTTP CLIENT CONNECTION POOLING TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_gemini_adapter_reuses_http_client():
    """Verify GeminiAdapter reuses the same AsyncClient across repeated calls."""
    adapter = GeminiAdapter()
    client_1 = adapter._get_client()
    assert isinstance(client_1, httpx.AsyncClient)
    assert not client_1.is_closed

    client_2 = adapter._get_client()
    assert client_1 is client_2, "GeminiAdapter must reuse the existing AsyncClient instance"

    # Verify connection limits
    pool = client_1._transport._pool
    assert pool._max_connections == 100
    assert pool._max_keepalive_connections == 20

    # Test clean shutdown
    await adapter.aclose()
    assert client_1.is_closed
    assert adapter._client is None


@pytest.mark.asyncio
async def test_openai_adapter_reuses_http_client():
    """Verify OpenAICompatibleAdapter reuses the same AsyncClient across repeated calls."""
    adapter = OpenAICompatibleAdapter("groq")
    client_1 = adapter._get_client()
    assert isinstance(client_1, httpx.AsyncClient)
    assert not client_1.is_closed

    client_2 = adapter._get_client()
    assert client_1 is client_2, "OpenAICompatibleAdapter must reuse the existing AsyncClient instance"

    # Verify connection limits
    pool = client_1._transport._pool
    assert pool._max_connections == 100
    assert pool._max_keepalive_connections == 20

    await adapter.aclose()
    assert client_1.is_closed
    assert adapter._client is None


@pytest.mark.asyncio
async def test_adapter_factory_aclose_lifecycle():
    """Verify AdapterFactory.aclose() closes all registered adapter connection pools."""
    factory = AdapterFactory()
    gemini = GeminiAdapter()
    openai = OpenAICompatibleAdapter("groq")

    # Initialize clients
    g_client = gemini._get_client()
    o_client = openai._get_client()
    assert not g_client.is_closed
    assert not o_client.is_closed

    factory.register(gemini)
    factory.register(openai)

    await factory.aclose()

    assert g_client.is_closed
    assert o_client.is_closed
    assert gemini._client is None
    assert openai._client is None


@pytest.mark.asyncio
async def test_concurrent_requests_share_client_safely():
    """Verify concurrent async requests can safely dispatch through the pooled client."""
    adapter = OpenAICompatibleAdapter("mock-groq")
    client = adapter._get_client()

    # Mock post to simulate concurrent API traffic
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Concurrent OK"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    model = ModelSpec(
        model_id="test-m",
        name="Test",
        provider="groq",
        endpoint_model="test-m",
        api_key="k",
        base_url="https://api.groq.com",
        input_price_per_mtok=0.1,
        output_price_per_mtok=0.2,
        expected_latency_ms=100,
        quality=0.8,
        reasoning=0.8,
        coding=0.8,
        context_window=8192,
        tier="tier_2",
    )

    with patch.object(client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        # Fire 10 concurrent requests
        tasks = [
            adapter.generate(model, [ChatMessage(role="user", content=f"Query {i}")])
            for i in range(10)
        ]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        assert all(r.content == "Concurrent OK" for r in results)
        assert mock_post.call_count == 10

    await adapter.aclose()
