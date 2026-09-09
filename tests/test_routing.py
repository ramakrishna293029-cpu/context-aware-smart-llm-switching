"""Unit tests for Analyzer-First Smart Routing, Context Management, and Fallback Ordering."""

import asyncio
import pytest

from app.analyzer import analyzer, _fallback_heuristics, _check_greeting, _try_solve_simple_arithmetic
from app.analyzer_llm import run_analyzer, analyze_and_route, AnalyzerDecision
from app.context import ContextManager, context_manager, build_context, build_messages, estimate_tokens
from app.registry import ModelRegistry, ModelSpec
from app.router import SmartRouter, router, route_decision
from app.schemas import ChatMessage, CandidateInfo
from app.security import resolve_credentials_from_headers


class TestAnalyzerDeterministic:
    def test_greeting_detection(self):
        is_g, ans = _check_greeting("Hi")
        assert is_g is True
        assert ans is not None
        assert "Hello" in ans or "help" in ans

        is_g2, ans2 = _check_greeting("good morning!")
        assert is_g2 is True

        is_g3, _ = _check_greeting("Write python code for binary search")
        assert is_g3 is False

    def test_arithmetic_detection(self):
        ans = _try_solve_simple_arithmetic("5 + 7")
        assert ans is not None
        assert "12" in ans

        ans2 = _try_solve_simple_arithmetic("what is 10 * 20?")
        assert ans2 is not None
        assert "200" in ans2

    def test_fallback_heuristics_self_mode(self):
        res = _fallback_heuristics("Hello there")
        # Heuristic engine never self-answers greetings (no canned text):
        # it classifies and routes to fast tier for a real provider response.
        assert res["answer_mode"] == "switch"
        assert res["answer"] is None
        assert res["target_tier"] == "fast"

        res_math = _fallback_heuristics("calculate 15 + 25")
        assert res_math["answer_mode"] == "self"
        assert "40" in res_math["answer"]

    def test_fallback_heuristics_switch_mode(self):
        res_code = _fallback_heuristics("Implement Dijkstra algorithm in Python")
        assert res_code["answer_mode"] == "switch"
        assert res_code["target_tier"] == "coding"
        assert res_code["coding_required"] is True

        res_arch = _fallback_heuristics("Design a distributed fault-tolerant database architecture with raft")
        assert res_arch["answer_mode"] == "switch"
        assert res_arch["target_tier"] == "reasoning"
        assert res_arch["reasoning_required"] is True

    def test_context_analyzer_signal_engine(self):
        analysis = analyzer.analyze("hi")
        # No canned answers: greetings classify to switch-mode fast tier.
        assert analysis.answer_mode == "switch"
        assert analysis.answer is None
        assert analysis.complexity <= 0.20

        analysis_code = analyzer.analyze("Write a python quicksort function with unit tests")
        assert analysis_code.answer_mode == "switch"
        assert analysis_code.task_type == "coding"
        assert analysis_code.complexity >= 0.50
        assert len(analysis_code.signals) > 0


# Offline demo registry: unit tests must never depend on live provider APIs,
# even when a developer's real .env is present.
from app.registry import ModelRegistry, _build_demo_models
DEMO_REGISTRY = ModelRegistry(_build_demo_models())


class TestAnalyzerLLM:
    def test_run_analyzer_self_mode(self):
        async def run():
            dec = await run_analyzer("Hi", registry_instance=DEMO_REGISTRY)
            assert isinstance(dec, AnalyzerDecision)
            assert dec.answer_mode == "self"
            assert dec.switch_required is False
            assert dec.answer is not None and len(dec.answer) > 0
            assert dec.target_tier == "fast"
            
            info = dec.to_analyzer_info()
            assert info.answer_mode == "self"
            assert info.model_id == dec.analyzer_model.model_id
        asyncio.run(run())

    def test_run_analyzer_switch_mode_coding(self):
        async def run():
            dec = await run_analyzer("Implement Dijkstra shortest path algorithm in Python with adjacency list", registry_instance=DEMO_REGISTRY)
            assert isinstance(dec, AnalyzerDecision)
            assert dec.answer_mode == "switch"
            assert dec.switch_required is True
            assert dec.answer is None
            assert dec.target_tier in ("coding", "reasoning")
            assert dec.coding_required is True
        asyncio.run(run())

    def test_run_analyzer_switch_mode_reasoning(self):
        async def run():
            dec = await run_analyzer("Design a distributed caching architecture with consistent hashing and leader election", registry_instance=DEMO_REGISTRY)
            assert isinstance(dec, AnalyzerDecision)
            assert dec.answer_mode == "switch"
            assert dec.switch_required is True
            assert dec.target_tier in ("reasoning", "coding", "powerful")
            assert dec.reasoning_required is True
        asyncio.run(run())

    def test_analyze_and_route_alias(self):
        async def run():
            dec = await analyze_and_route("Hello!", registry_instance=DEMO_REGISTRY)
            assert dec.answer_mode == "self"
        asyncio.run(run())


class TestContextManagement:
    def test_estimate_tokens(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("hello world") >= 2

    def test_context_manager_pruning(self):
        cm = ContextManager(max_context_tokens=500)
        long_text = "This is a sentence for context testing. " * 20
        history = [
            ChatMessage(role="user", content="Turn 1 anchor: " + long_text),
            ChatMessage(role="assistant", content="Turn 1 reply: " + long_text),
            ChatMessage(role="user", content="Turn 2: " + long_text),
            ChatMessage(role="assistant", content="Turn 2 reply: " + long_text),
            ChatMessage(role="user", content="Turn 3: " + long_text),
            ChatMessage(role="assistant", content="Turn 3 reply: " + long_text),
        ]
        
        pruned = cm.build_context(
            query="What is the final status?",
            history=history,
            max_tokens=400,
            system_prompt="You are a helpful assistant.",
        )
        
        assert len(pruned) >= 2
        assert pruned[0].role == "system"
        assert pruned[-1].role == "user"
        assert pruned[-1].content == "What is the final status?"
        
        token_count = cm.get_token_count(pruned)
        assert token_count <= 400

    def test_build_messages_helper(self):
        history = [ChatMessage(role="user", content="Msg 1"), ChatMessage(role="assistant", content="Msg 2")]
        msgs = build_messages(history, "Msg 3")
        assert msgs[-1].content == "Msg 3"
        assert msgs[-1].role == "user"
        # Includes system prompt if configured
        assert len(msgs) in (3, 4)



class TestSmartRouter:
    def test_routing_strategies(self):
        async def run():
            dec = await run_analyzer("Implement binary search in Python")
            assert dec.answer_mode == "switch"
            
            for strategy in ["balanced", "lowest_cost", "fastest", "highest_quality"]:
                res = router.resolve(dec, strategy=strategy)
                assert res.primary_model is not None
                assert len(res.fallback_chain) >= 1
                assert res.strategy == strategy
                
                cands = res.candidates()
                assert len(cands) >= 1
                selected = [c for c in cands if c["selected"]]
                assert len(selected) == 1
                assert selected[0]["model_id"] == res.primary_model.model_id
                
                cand_infos = res.to_candidate_infos()
                assert len(cand_infos) == len(cands)
                assert all(isinstance(ci, CandidateInfo) for ci in cand_infos)
        asyncio.run(run())

    def test_dynamic_registry_routing(self):
        async def run():
            headers = {
                "X-Groq-Key": "gsk_dynamic_test",
                "X-Gemini-Key": "AIza_dynamic_test",
                "X-OpenAI-Key": "sk-dynamic_test",
            }
            creds = resolve_credentials_from_headers(headers)
            reg = ModelRegistry.from_credentials(creds)
            
            dec = await run_analyzer("Debug React state loop", registry_instance=reg)
            res = route_decision(dec, strategy="balanced", registry=reg)
            assert res.primary_model is not None
            assert len(res.fallback_chain) >= 1
        asyncio.run(run())

