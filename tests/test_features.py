"""Unit tests and benchmarks for LinUCB feature extraction engine."""

import time
import numpy as np
import pytest

from app.features import ContextFeatureExtractor, feature_extractor
from app.schemas import ChatMessage


class TestContextFeatureExtractor:
    """Test suite verifying shape, unit norm, edge cases, history blending, and latency."""

    @pytest.fixture
    def extractor(self) -> ContextFeatureExtractor:
        return feature_extractor

    def test_singleton_instance(self, extractor: ContextFeatureExtractor):
        """Verifies the global singleton instance is properly instantiated."""
        assert isinstance(extractor, ContextFeatureExtractor)
        assert extractor.fallback_vector.shape == (16,)
        assert np.isclose(np.linalg.norm(extractor.fallback_vector), 1.0)

    @pytest.mark.parametrize(
        "query",
        [
            "How do I optimize a recursive Fibonacci algorithm in Python?",
            "Solve the system of linear differential equations with initial values.",
            "Hello, good morning! How are you doing today?",
            "Design a distributed rate limiter using Redis and sliding window counters.",
            "SELECT * FROM users WHERE status = 'active' ORDER BY created_at DESC;",
            "git rebase -i HEAD~4 and squash commits into one.",
        ],
    )
    def test_shape_and_dtype(self, extractor: ContextFeatureExtractor, query: str):
        """Vector must have shape exactly (16,) and dtype float64."""
        vec = extractor.extract(query)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (16,)
        assert vec.dtype == np.float64

    @pytest.mark.parametrize(
        "query",
        [
            "Python async await coroutines",
            "Proof by contradiction for square root of two",
            "Hi there! Thank you for the quick help",
            "Microservices architecture with Raft consensus and Kafka queues",
        ],
    )
    def test_unit_norm(self, extractor: ContextFeatureExtractor, query: str):
        """Vector norm must be strictly equal to 1.0 within floating point tolerance."""
        vec = extractor.extract(query)
        norm = np.linalg.norm(vec)
        assert np.isclose(norm, 1.0, atol=1e-7), f"Expected norm 1.0, got {norm}"

    def test_edge_case_empty_string(self, extractor: ContextFeatureExtractor):
        """Empty string returns the uniform fallback unit vector."""
        vec = extractor.extract("")
        assert vec.shape == (16,)
        assert np.isclose(np.linalg.norm(vec), 1.0)
        expected = np.ones(16, dtype=np.float64) / np.sqrt(16.0)
        np.testing.assert_allclose(vec, expected)

    def test_edge_case_whitespace_only(self, extractor: ContextFeatureExtractor):
        """Whitespace-only string returns the uniform fallback unit vector."""
        vec = extractor.extract("   \t\n\r   ")
        assert vec.shape == (16,)
        assert np.isclose(np.linalg.norm(vec), 1.0)
        expected = np.ones(16, dtype=np.float64) / np.sqrt(16.0)
        np.testing.assert_allclose(vec, expected)

    def test_edge_case_unseen_tokens(self, extractor: ContextFeatureExtractor):
        """Pure out-of-vocabulary gibberish returns the uniform fallback unit vector."""
        vec = extractor.extract("zzxxqquuvv123987456 aabbccddeeffgghh")
        assert vec.shape == (16,)
        assert np.isclose(np.linalg.norm(vec), 1.0)
        expected = np.ones(16, dtype=np.float64) / np.sqrt(16.0)
        np.testing.assert_allclose(vec, expected)

    def test_edge_case_10k_char_prompt(self, extractor: ContextFeatureExtractor):
        """Very large 10,000 character prompt extracts cleanly with unit norm."""
        large_query = ("def calculate_matrix_multiplication(A, B):\n"
                       "    # Extensive production documentation and numerical operations\n"
                       "    return np.matmul(A, B)\n") * 150
        assert len(large_query) >= 10000

        vec = extractor.extract(large_query)
        assert vec.shape == (16,)
        assert vec.dtype == np.float64
        assert np.isclose(np.linalg.norm(vec), 1.0)

    def test_edge_case_unicode_and_emojis(self, extractor: ContextFeatureExtractor):
        """Handles unicode characters, multi-lingual scripts, and emojis gracefully."""
        unicode_query = "🚀🔥 Testing high-performance vectorizer 🤖 with unicode: 안녕하세요, こんにちは, 世界!"
        vec = extractor.extract(unicode_query)
        assert vec.shape == (16,)
        assert vec.dtype == np.float64
        assert np.isclose(np.linalg.norm(vec), 1.0)

    def test_edge_case_code_blocks(self, extractor: ContextFeatureExtractor):
        """Handles markdown fenced code blocks across multiple languages."""
        code_query = (
            "Here is the implementation:\n"
            "```python\n"
            "import asyncio\n"
            "async def fetch_user(user_id: int):\n"
            "    async with httpx.AsyncClient() as client:\n"
            "        return await client.get(f'/users/{user_id}')\n"
            "```\n"
            "Can you convert this to C++ with std::thread and std::mutex?"
        )
        vec = extractor.extract(code_query)
        assert vec.shape == (16,)
        assert vec.dtype == np.float64
        assert np.isclose(np.linalg.norm(vec), 1.0)

    def test_history_blending(self, extractor: ContextFeatureExtractor):
        """Verifies that conversation history is combined with the query and alters the vector."""
        bare_query = "What do you think?"
        bare_vec = extractor.extract(bare_query)

        # 1. Test blending with ChatMessage objects
        chat_history = [
            ChatMessage(role="user", content="How do I configure Redis distributed caching?"),
            ChatMessage(role="assistant", content="Use cache-aside pattern with TTL eviction and consistent hashing."),
        ]
        history_vec = extractor.extract(bare_query, history=chat_history)

        assert history_vec.shape == (16,)
        assert np.isclose(np.linalg.norm(history_vec), 1.0)
        # History must enrich the context, producing a distinct vector from bare ambiguous query
        assert not np.allclose(history_vec, bare_vec)

        # 2. Test blending with dict history
        dict_history = [
            {"role": "user", "content": "Explain mathematical induction with base case and inductive step."},
        ]
        dict_vec = extractor.extract(bare_query, history=dict_history)
        assert dict_vec.shape == (16,)
        assert np.isclose(np.linalg.norm(dict_vec), 1.0)
        assert not np.allclose(dict_vec, bare_vec)
        assert not np.allclose(dict_vec, history_vec)

        # 3. Test blending with plain string history
        str_history = ["Distributed microservices and Raft consensus"]
        str_vec = extractor.extract(bare_query, history=str_history)
        assert str_vec.shape == (16,)
        assert np.isclose(np.linalg.norm(str_vec), 1.0)

    def test_benchmark_latency(self, extractor: ContextFeatureExtractor):
        """100 extractions must average strictly less than 2.0 ms each."""
        queries = [
            "How do I write unit tests for FastAPI using pytest?",
            "Compute the derivative of f(x) = x^2 * ln(x)",
            "Good morning! What is the weather like in New York?",
            "Design a distributed message queue using Kafka partitions",
            "SELECT id, username FROM users WHERE is_active = true",
        ]
        history = [
            ChatMessage(role="user", content="We are designing a large scale system"),
            ChatMessage(role="assistant", content="Let us explore microservices and caching"),
        ]

        # Warm-up phase
        for q in queries:
            extractor.extract(q, history=history)

        n_iterations = 100
        start_time = time.perf_counter()
        for i in range(n_iterations):
            q = queries[i % len(queries)]
            extractor.extract(q, history=history)
        end_time = time.perf_counter()

        total_elapsed_ms = (end_time - start_time) * 1000.0
        avg_latency_ms = total_elapsed_ms / n_iterations

        print(f"\n[BENCHMARK] {n_iterations} extractions completed in {total_elapsed_ms:.2f} ms ({avg_latency_ms:.3f} ms/call)")
        assert avg_latency_ms < 2.0, f"Extraction too slow: {avg_latency_ms:.3f} ms exceeds 2.0 ms threshold"

    def test_immutability(self, extractor: ContextFeatureExtractor):
        """Mutating returned feature vector must never corrupt internal fallback vector."""
        v1 = extractor.extract("")
        v1[0] = 999.0
        v2 = extractor.extract("")
        assert v2[0] != 999.0
        assert np.isclose(np.linalg.norm(v2), 1.0)

        f1 = extractor.fallback_vector
        f1[0] = 888.0
        f2 = extractor.fallback_vector
        assert f2[0] != 888.0
        assert np.isclose(np.linalg.norm(f2), 1.0)

    @pytest.mark.parametrize(
        "query",
        [
            "Hello\x00World\x00\x00",
            "\x00",
            "\x00\x00\x00",
            "مرحبا بالعالم كيف حالك اليوم؟",
            "שלום עולם מה נשמע",
            "हिन्दी भाषा परीक्षण",
            "\r\n\t\f\v",
            "~!@#$%^&*()_+{}[]|\":;?><,./`'\\",
            12345,
            3.14159,
            True,
            None,
        ],
    )
    def test_extreme_query_inputs(self, extractor: ContextFeatureExtractor, query):
        """Vector extraction must never crash on weird, null-byte, RTL, or non-string queries."""
        vec = extractor.extract(query)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (16,)
        assert vec.dtype == np.float64
        assert np.isclose(np.linalg.norm(vec), 1.0, atol=1e-7)

    def test_extreme_history_inputs(self, extractor: ContextFeatureExtractor):
        """Extraction handles malformed or heterogeneous history lists gracefully."""
        strange_histories = [
            None,
            [],
            [None, None],
            ["", "   ", "\x00"],
            [123, 45.67, True, False],
            [{"role": "user", "content": None}],
            [{"role": "user", "content": ""}],
            [{"role": "user", "content": "valid text"}],
            [{"other_key": "no content key"}],
            [b"byte string", {"nested": {"deep": 1}}],
            [object()],
        ]
        for h in strange_histories:
            vec = extractor.extract("system latency test", history=h)
            assert vec.shape == (16,)
            assert vec.dtype == np.float64
            assert np.isclose(np.linalg.norm(vec), 1.0, atol=1e-7)

    def test_concurrency_thread_safety(self, extractor: ContextFeatureExtractor):
        """Ensures thread safety under heavy concurrent extraction loads."""
        import concurrent.futures

        queries = [
            "How do I implement Dijkstra?",
            "SELECT * FROM users WHERE id = 10",
            "Hello world!",
            "Raft consensus log replication leader election",
            "Differential calculus integration chain rule",
            "",
            "   ",
            "zzqqww123 unknown tokens",
            "def test(): return True",
            "مرحبا بالعالم",
            "🚀🔥🤖",
        ]

        def worker(i: int) -> bool:
            q = queries[i % len(queries)]
            vec = extractor.extract(q)
            assert vec.shape == (16,)
            norm = np.linalg.norm(vec)
            assert np.isclose(norm, 1.0, atol=1e-7)
            return True

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(worker, i) for i in range(500)]
            for f in concurrent.futures.as_completed(futures):
                assert f.result() is True

