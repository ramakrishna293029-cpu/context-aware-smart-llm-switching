"""Comprehensive unit tests and benchmarks for Disjoint LinUCB Contextual Bandit Router."""

from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
import sqlite3
import time
from typing import List

import numpy as np
import pytest

from app.linucb import (
    BanditDecision,
    BanditScore,
    CORE_TIERS,
    MAX_REWARD_MAGNITUDE,
    LinUCBArm,
    LinUCBRouter,
    linucb_router,
)
from app.registry import ModelSpec, registry


@pytest.fixture
def six_models() -> List[ModelSpec]:
    """Retrieve the standard 6 architecture tiers from the registry."""
    return [registry.get_by_tier(f"tier_{i}") for i in range(1, 7)]


@pytest.fixture
def random_context() -> np.ndarray:
    """Generates a random 16-dimensional unit context vector."""
    np.random.seed(42)
    vec = np.random.randn(16).astype(np.float64)
    return vec / np.linalg.norm(vec)


class TestLinUCBArm:
    """Test suite for LinUCBArm mathematical operations, Sherman-Morrison updates, and shrinkage."""

    def test_arm_initialization(self):
        """Verifies initial identity covariance, zero bias, and default values."""
        arm = LinUCBArm(model_id="test-arm", d=16, alpha=1.2)
        assert arm.model_id == "test-arm"
        assert arm.d == 16
        assert arm.alpha == 1.2
        assert arm.pull_count == 0
        assert arm.total_reward == 0.0
        assert arm.A.shape == (16, 16)
        assert arm.b.shape == (16,)
        assert arm.V.shape == (16, 16)
        assert np.array_equal(arm.A, np.eye(16, dtype=np.float64))
        assert np.array_equal(arm.b, np.zeros(16, dtype=np.float64))
        assert np.array_equal(arm.V, np.eye(16, dtype=np.float64))

    def test_mathematical_validity(self, random_context: np.ndarray):
        """Validates UCB calculation against explicit manual vector/matrix mathematics."""
        d = 16
        alpha = 1.5
        arm = LinUCBArm(model_id="math-arm", d=d, alpha=alpha)

        # Set known non-trivial state
        np.random.seed(123)
        known_A = np.eye(d, dtype=np.float64) + np.random.randn(d, d) * 0.1
        known_A = 0.5 * (known_A + known_A.T) + np.eye(d)  # Ensure positive-definite
        known_V = np.linalg.inv(known_A)
        known_b = np.random.randn(d).astype(np.float64)

        arm.A = known_A.copy()
        arm.V = known_V.copy()
        arm.b = known_b.copy()

        # Compute using LinUCBArm
        ucb_score, exp_reward, uncertainty = arm.compute_ucb(random_context, alpha=alpha)

        # Compute manually with independent numpy operations
        theta_hat = known_V @ known_b
        expected_manual_reward = float(np.dot(theta_hat, random_context))
        quad_form = float(np.dot(random_context, known_V @ random_context))
        expected_manual_uncertainty = float(alpha * math.sqrt(max(0.0, quad_form)))
        expected_manual_ucb = expected_manual_reward + expected_manual_uncertainty

        assert np.isclose(exp_reward, expected_manual_reward, atol=1e-9)
        assert np.isclose(uncertainty, expected_manual_uncertainty, atol=1e-9)
        assert np.isclose(ucb_score, expected_manual_ucb, atol=1e-9)

    def test_sherman_morrison_exactness(self):
        """Verifies Sherman-Morrison rank-1 inverse matches np.linalg.inv(A) over 100 updates.

        Requirement: atol=1e-4 tolerance after 100 sequential updates.
        """
        np.random.seed(999)
        d = 16
        arm = LinUCBArm(model_id="sm-arm", d=d, alpha=1.0)

        for _ in range(100):
            x = np.random.randn(d).astype(np.float64)
            x /= np.linalg.norm(x)
            r = float(np.random.uniform(0.0, 1.0))
            arm.update(x, reward=r)

        # Compare Sherman-Morrison online V with full matrix inversion np.linalg.inv(A)
        V_exact = np.linalg.inv(arm.A)
        max_diff = np.max(np.abs(arm.V - V_exact))

        assert max_diff < 1e-4, f"Sherman-Morrison drifted: max diff {max_diff} exceeds 1e-4"
        assert np.allclose(arm.V, V_exact, atol=1e-7), "Sherman-Morrison matches direct inverse"

    def test_exploration_bonus_shrinkage(self, random_context: np.ndarray):
        """Verifies uncertainty decreases monotonically as arm receives more observations along context."""
        arm = LinUCBArm(model_id="shrinkage-arm", d=16, alpha=1.0)
        uncertainties: List[float] = []

        # Record initial uncertainty
        _, _, init_unc = arm.compute_ucb(random_context)
        uncertainties.append(init_unc)

        # Observe updates along this context direction
        for _ in range(25):
            arm.update(random_context, reward=1.0)
            _, _, unc = arm.compute_ucb(random_context)
            uncertainties.append(unc)

        # Assert strict monotonic decrease: u_{t} < u_{t-1} for all t
        for i in range(len(uncertainties) - 1):
            assert uncertainties[i + 1] < uncertainties[i], (
                f"Uncertainty did not strictly decrease: {uncertainties[i]} -> {uncertainties[i+1]}"
            )

    def test_reconditioning_every_500_pulls(self):
        """Verifies re-conditioning to np.linalg.inv(A) executes on exactly 500 pulls."""
        np.random.seed(42)
        arm = LinUCBArm(model_id="recond-arm", d=16, alpha=1.0)
        for _ in range(500):
            x = np.random.randn(16).astype(np.float64)
            x /= np.linalg.norm(x)
            arm.update(x, reward=0.5)

        assert arm.pull_count == 500
        # After 500 pulls, arm.V has been re-conditioned via np.linalg.inv(arm.A)
        V_inv = np.linalg.inv(arm.A)
        assert np.allclose(arm.V, V_inv, atol=1e-9)

    def test_dimension_mismatch_raises_error(self):
        """compute_ucb and update must raise ValueError if vector dimension != d."""
        arm = LinUCBArm(model_id="dim-arm", d=16)
        bad_x = np.ones(15, dtype=np.float64)

        with pytest.raises(ValueError, match="Feature vector dimension mismatch"):
            arm.compute_ucb(bad_x)

        with pytest.raises(ValueError, match="Feature vector dimension mismatch"):
            arm.update(bad_x, reward=1.0)

    def test_non_finite_reward_raises_error(self, random_context: np.ndarray):
        """update must reject NaN and Inf rewards."""
        arm = LinUCBArm(model_id="nan-arm", d=16)

        with pytest.raises(ValueError, match="Invalid reward value"):
            arm.update(random_context, reward=float("nan"))

        with pytest.raises(ValueError, match="Invalid reward value"):
            arm.update(random_context, reward=float("inf"))

        with pytest.raises(ValueError, match="Invalid reward value"):
            arm.update(random_context, reward=float("-inf"))

    def test_nan_inf_context_rejected(self):
        """Non-finite values (NaN / Inf) in x_t must raise ValueError and NOT poison matrices."""
        arm = LinUCBArm(model_id="poison-arm", d=16)
        nan_vec = np.ones(16, dtype=np.float64)
        nan_vec[5] = float("nan")

        inf_vec = np.ones(16, dtype=np.float64)
        inf_vec[2] = float("inf")

        neg_inf_vec = np.ones(16, dtype=np.float64)
        neg_inf_vec[8] = float("-inf")

        for bad_vec in [nan_vec, inf_vec, neg_inf_vec]:
            with pytest.raises(ValueError, match="non-finite values"):
                arm.compute_ucb(bad_vec)

            with pytest.raises(ValueError, match="non-finite values"):
                arm.get_score(bad_vec)

            with pytest.raises(ValueError, match="non-finite values"):
                arm.update(bad_vec, reward=1.0)

        # Confirm arm matrices remain unpoisoned
        assert np.array_equal(arm.A, np.eye(16, dtype=np.float64))
        assert np.array_equal(arm.b, np.zeros(16, dtype=np.float64))
        assert np.array_equal(arm.V, np.eye(16, dtype=np.float64))
        assert arm.pull_count == 0

    def test_alpha_domain_validation(self, random_context: np.ndarray):
        """Negative alpha raises ValueError; alpha=0 allows pure exploitation."""
        # Negative alpha in arm init
        with pytest.raises(ValueError, match="alpha must be non-negative"):
            LinUCBArm(model_id="neg-arm", d=16, alpha=-0.1)

        arm = LinUCBArm(model_id="zero-arm", d=16, alpha=1.0)

        # Negative alpha override
        with pytest.raises(ValueError, match="alpha must be non-negative"):
            arm.compute_ucb(random_context, alpha=-0.5)

        with pytest.raises(ValueError, match="alpha must be non-negative"):
            arm.get_score(random_context, alpha=-0.01)

        # Alpha = 0.0 pure exploitation
        arm.update(random_context, reward=2.0)
        ucb, exp_r, unc = arm.compute_ucb(random_context, alpha=0.0)
        assert unc == 0.0
        assert ucb == exp_r
        assert ucb > 0.0

    def test_extreme_reward_rejection(self, random_context: np.ndarray):
        """Rewards exceeding numerical safety boundary (> 1e6) raise ValueError."""
        arm = LinUCBArm(model_id="bound-arm", d=16)

        with pytest.raises(ValueError, match="magnitude exceeds numerical stability"):
            arm.update(random_context, reward=1e7)

        with pytest.raises(ValueError, match="magnitude exceeds numerical stability"):
            arm.update(random_context, reward=-1e7)

        # Rewards within threshold pass
        arm.update(random_context, reward=MAX_REWARD_MAGNITUDE)
        assert arm.pull_count == 1
        assert arm.total_reward == MAX_REWARD_MAGNITUDE

    def test_orthogonal_and_parallel_updates(self):
        """Verifies rank-1 updates on orthogonal and parallel vectors preserve positive-definiteness."""
        d = 16
        arm = LinUCBArm(model_id="ortho-arm", d=d, alpha=1.0)

        e1 = np.zeros(d, dtype=np.float64)
        e1[0] = 1.0

        e2 = np.zeros(d, dtype=np.float64)
        e2[1] = 1.0

        # Orthogonal updates
        arm.update(e1, reward=1.0)
        arm.update(e2, reward=2.0)

        # Parallel update along e1
        arm.update(e1, reward=1.5)

        # Positive-definiteness check
        eigvals_A = np.linalg.eigvalsh(arm.A)
        eigvals_V = np.linalg.eigvalsh(arm.V)
        assert np.all(eigvals_A >= 1.0)
        assert np.all(eigvals_V > 0.0)

        # V matches direct inversion
        assert np.allclose(arm.V, np.linalg.inv(arm.A), atol=1e-8)

    def test_zero_vector_context(self):
        """Zero vector context computes 0 uncertainty and expected reward gracefully."""
        d = 16
        arm = LinUCBArm(model_id="zero-vec-arm", d=d, alpha=1.0)
        zero_vec = np.zeros(d, dtype=np.float64)

        ucb, exp_r, unc = arm.compute_ucb(zero_vec)
        assert ucb == 0.0
        assert exp_r == 0.0
        assert unc == 0.0

        # Update with zero vector
        arm.update(zero_vec, reward=1.0)
        assert arm.pull_count == 1
        assert arm.total_reward == 1.0
        assert np.array_equal(arm.A, np.eye(d))
        assert np.array_equal(arm.V, np.eye(d))


class TestLinUCBRouter:
    """Test suite for LinUCBRouter routing decisions, ranking, fallback chains, and persistence."""

    def test_singleton_instance(self):
        """Verifies the global singleton linucb_router is properly pre-configured."""
        assert isinstance(linucb_router, LinUCBRouter)
        assert len(linucb_router.arms) >= 6
        for tier in CORE_TIERS:
            assert tier in linucb_router.arms

    def test_router_alpha_validation(self, six_models: List[ModelSpec], random_context: np.ndarray):
        """Negative alpha in router initialization or route() call raises ValueError."""
        with pytest.raises(ValueError, match="alpha must be non-negative"):
            LinUCBRouter(d=16, alpha=-1.0)

        router = LinUCBRouter(d=16, alpha=1.0)
        with pytest.raises(ValueError, match="alpha must be non-negative"):
            router.route(random_context, six_models, alpha=-0.5)

    def test_routing_selection_and_ordering(
        self, six_models: List[ModelSpec], random_context: np.ndarray
    ):
        """Arm with highest UCB score must be selected; fallback chain strictly ordered descending."""
        router = LinUCBRouter(d=16, alpha=1.0)

        # Give gemini-tier_3 strong positive reward on this context
        for _ in range(5):
            router.update("gemini-tier_3", random_context, reward=10.0)

        # Give groq-tier_5 moderate positive reward
        for _ in range(3):
            router.update("groq-tier_5", random_context, reward=5.0)

        # Give gemini-tier_1 zero reward
        for _ in range(5):
            router.update("gemini-tier_1", random_context, reward=0.0)

        decision: BanditDecision = router.route(random_context, six_models)

        assert isinstance(decision, BanditDecision)
        assert decision.selected_model.model_id == "gemini-tier_3"
        assert len(decision.fallback_chain) == 5
        assert len(decision.scores) == 6

        # Verify selected model has maximal UCB score
        selected_score = decision.scores[decision.selected_model.model_id].ucb_score
        for model in six_models:
            assert selected_score >= decision.scores[model.model_id].ucb_score

        # Verify fallback chain is strictly non-increasing in UCB score
        chain_scores = [decision.scores[m.model_id].ucb_score for m in decision.fallback_chain]
        for i in range(len(chain_scores) - 1):
            assert chain_scores[i] >= chain_scores[i + 1], (
                f"Fallback chain not sorted descending: {chain_scores[i]} < {chain_scores[i+1]}"
            )

        # Verify x_t is preserved
        assert np.array_equal(decision.x_t, random_context)

    def test_empty_eligible_set_raises_error(self, random_context: np.ndarray):
        """Routing with empty eligible models list must raise ValueError."""
        router = LinUCBRouter(d=16)
        with pytest.raises(ValueError, match="No eligible models provided for routing"):
            router.route(random_context, [])

    def test_nan_inf_in_route_raises_error(self, six_models: List[ModelSpec]):
        """Passing NaN or Inf feature vector to route() raises ValueError immediately."""
        router = LinUCBRouter(d=16)
        bad_x = np.ones(16, dtype=np.float64)
        bad_x[3] = float("nan")

        with pytest.raises(ValueError, match="non-finite values"):
            router.route(bad_x, six_models)

    def test_context_view_mutation_defense(
        self, six_models: List[ModelSpec], random_context: np.ndarray
    ):
        """Mutating the context array after route() does NOT alter decision.x_t."""
        router = LinUCBRouter(d=16)
        x_input = random_context.copy()
        decision = router.route(x_input, six_models)

        # Mutate external context input
        x_input[0] = 9999.0
        assert decision.x_t[0] != 9999.0
        assert np.array_equal(decision.x_t, random_context)

    def test_single_eligible_model(
        self, six_models: List[ModelSpec], random_context: np.ndarray
    ):
        """Routing with exactly 1 eligible model returns empty fallback chain."""
        router = LinUCBRouter(d=16)
        single_model = [six_models[0]]
        decision = router.route(random_context, single_model)
        assert decision.selected_model.model_id == single_model[0].model_id
        assert decision.fallback_chain == []
        assert len(decision.scores) == 1

    def test_dynamic_arm_creation(self, random_context: np.ndarray):
        """Models not in default CORE_TIERS are dynamically instantiated without error."""
        router = LinUCBRouter(d=16)
        custom_spec = ModelSpec(
            model_id="custom-fine-tuned-tier",
            name="Custom Model",
            provider="custom",
            endpoint_model="custom-1",
            api_key="k",
            base_url="https://api.custom.com",
            input_price_per_mtok=0.1,
            output_price_per_mtok=0.2,
            expected_latency_ms=250.0,
            quality=0.85,
            reasoning=0.80,
            coding=0.80,
            context_window=32768,
            tier="custom",
        )
        assert "custom-fine-tuned-tier" not in router.arms
        decision = router.route(random_context, [custom_spec])
        assert decision.selected_model.model_id == "custom-fine-tuned-tier"
        assert "custom-fine-tuned-tier" in router.arms

    def test_thread_safety_and_concurrency(self):
        """Parallel updates across threads maintain matrix symmetry and positive-definiteness."""
        d = 16
        arm = LinUCBArm(model_id="concurrent-arm", d=d, alpha=1.0)
        num_threads = 8
        updates_per_thread = 50
        total_updates = num_threads * updates_per_thread

        def worker_task(thread_idx: int):
            local_rng = np.random.RandomState(42 + thread_idx)
            for _ in range(updates_per_thread):
                vec = local_rng.randn(d).astype(np.float64)
                vec /= np.linalg.norm(vec)
                r = float(local_rng.uniform(0.0, 1.0))
                arm.update(vec, r)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_task, i) for i in range(num_threads)]
            for f in futures:
                f.result()

        # Check total updates received
        assert arm.pull_count == total_updates

        # Check exact matrix symmetry: A == A.T and V == V.T
        assert np.allclose(arm.A, arm.A.T, atol=1e-8), "Matrix A lost symmetry during concurrency"
        assert np.allclose(arm.V, arm.V.T, atol=1e-8), "Matrix V lost symmetry during concurrency"

        # Check positive-definiteness: all eigenvalues > 0
        eigvals_A = np.linalg.eigvalsh(arm.A)
        eigvals_V = np.linalg.eigvalsh(arm.V)
        assert np.all(eigvals_A > 0.0), f"A is not positive-definite: min eigenvalue {np.min(eigvals_A)}"
        assert np.all(eigvals_V > 0.0), f"V is not positive-definite: min eigenvalue {np.min(eigvals_V)}"

        # Sherman-Morrison V must match true inverse after all concurrent updates
        V_inv = np.linalg.inv(arm.A)
        assert np.allclose(arm.V, V_inv, atol=1e-4), "Concurrent V drifted from inv(A)"

    def test_concurrent_route_and_update(
        self, six_models: List[ModelSpec], random_context: np.ndarray
    ):
        """Concurrent reader threads calling route() while writer threads call update()."""
        router = LinUCBRouter(d=16, alpha=1.0)
        num_readers = 4
        num_writers = 4
        iterations = 50

        def reader_task(idx: int):
            for _ in range(iterations):
                dec = router.route(random_context, six_models)
                assert dec.selected_model is not None
                assert len(dec.fallback_chain) == 5

        def writer_task(idx: int):
            local_rng = np.random.RandomState(100 + idx)
            for _ in range(iterations):
                target_tier = CORE_TIERS[local_rng.randint(0, len(CORE_TIERS))]
                vec = local_rng.randn(16).astype(np.float64)
                vec /= np.linalg.norm(vec)
                router.update(target_tier, vec, reward=1.0)

        with ThreadPoolExecutor(max_workers=num_readers + num_writers) as executor:
            reader_futures = [executor.submit(reader_task, i) for i in range(num_readers)]
            writer_futures = [executor.submit(writer_task, i) for i in range(num_writers)]
            for f in reader_futures + writer_futures:
                f.result()

    def test_persistence_sqlite_bit_for_bit(
        self, tmp_path: Path, six_models: List[ModelSpec], random_context: np.ndarray
    ):
        """Save state to SQLite, load into fresh router, verify bit-for-bit exactness."""
        db_file = tmp_path / "bandit_test.db"
        router1 = LinUCBRouter(d=16, alpha=1.0)

        # Train router1 with distinct updates across arms
        np.random.seed(777)
        for i, tier in enumerate(CORE_TIERS):
            for _ in range(15):
                ctx = np.random.randn(16).astype(np.float64)
                ctx /= np.linalg.norm(ctx)
                router1.update(tier, ctx, reward=float(i + 1) * 0.5)

        # Persist to SQLite
        router1.save_state(db_file)
        assert db_file.exists()

        # Instantiate brand-new router and load state
        router2 = LinUCBRouter(d=16, alpha=1.0)
        router2.load_state(db_file)

        # Verify bit-for-bit identity across all arms
        for tier in CORE_TIERS:
            arm1 = router1.arms[tier]
            arm2 = router2.arms[tier]

            assert arm1.pull_count == arm2.pull_count
            assert np.isclose(arm1.total_reward, arm2.total_reward)
            assert np.array_equal(arm1.A, arm2.A), f"Arm {tier} matrix A bit mismatch!"
            assert np.array_equal(arm1.b, arm2.b), f"Arm {tier} vector b bit mismatch!"
            assert np.array_equal(arm1.V, arm2.V), f"Arm {tier} matrix V bit mismatch!"

        # Route decision must be 100% identical
        decision1 = router1.route(random_context, six_models)
        decision2 = router2.route(random_context, six_models)

        assert decision1.selected_model.model_id == decision2.selected_model.model_id
        for m in six_models:
            s1 = decision1.scores[m.model_id]
            s2 = decision2.scores[m.model_id]
            assert s1.ucb_score == s2.ucb_score
            assert s1.expected_reward == s2.expected_reward
            assert s1.uncertainty == s2.uncertainty
            assert s1.pull_count == s2.pull_count

    def test_corrupted_blob_detection(self, tmp_path: Path):
        """Loading malformed SQLite BLOBs with invalid byte lengths raises ValueError."""
        db_file = tmp_path / "corrupted_bandit.db"

        # Create table with truncated BLOBs
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute(
                """
                CREATE TABLE bandit_arms (
                    model_id TEXT PRIMARY KEY,
                    d INTEGER NOT NULL,
                    alpha REAL NOT NULL,
                    pull_count INTEGER NOT NULL,
                    total_reward REAL NOT NULL,
                    A BLOB NOT NULL,
                    b BLOB NOT NULL,
                    V BLOB NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Valid matrix is 16*16*8 = 2048 bytes; insert 100 bytes (corrupted)
            corrupted_blob = b"X" * 100
            conn.execute(
                """
                INSERT INTO bandit_arms (model_id, d, alpha, pull_count, total_reward, A, b, V)
                VALUES ('gemini-tier_1', 16, 1.0, 5, 2.5, ?, ?, ?)
                """,
                (corrupted_blob, corrupted_blob, corrupted_blob),
            )
            conn.commit()

        router = LinUCBRouter(d=16)
        with pytest.raises(ValueError, match="Corrupted BLOB byte length"):
            router.load_state(db_file)

    def test_persistence_json_fallback(
        self, tmp_path: Path, six_models: List[ModelSpec], random_context: np.ndarray
    ):
        """Save state to JSON fallback, load into fresh router, verify equivalence."""
        json_file = tmp_path / "bandit_state.json"
        router1 = LinUCBRouter(d=16, alpha=1.0)

        for tier in CORE_TIERS[:3]:
            router1.update(tier, random_context, reward=2.5)

        router1.save_state(json_file)
        assert json_file.exists()

        router2 = LinUCBRouter(d=16, alpha=1.0)
        router2.load_state(json_file)

        for tier in CORE_TIERS[:3]:
            arm1 = router1.arms[tier]
            arm2 = router2.arms[tier]
            assert arm1.pull_count == arm2.pull_count
            assert np.allclose(arm1.A, arm2.A)
            assert np.allclose(arm1.b, arm2.b)
            assert np.allclose(arm1.V, arm2.V)

    def test_performance_benchmarks(
        self, six_models: List[ModelSpec], random_context: np.ndarray
    ):
        """Performance benchmarks:

        1,000 route calls complete in < 3.0 ms average per call.
        1,000 update calls complete in < 0.1 ms average per call.
        """
        router = LinUCBRouter(d=16, alpha=1.0)

        # 1. Benchmark 1,000 route calls across all 6 core model tiers
        t0 = time.perf_counter()
        for _ in range(1000):
            _ = router.route(random_context, six_models)
        t1 = time.perf_counter()

        avg_route_ms = (t1 - t0) / 1000.0 * 1000.0
        print(f"\n[LinUCB Benchmark] 1,000 route calls avg latency: {avg_route_ms:.4f} ms per call")
        assert avg_route_ms < 3.0, f"Route latency {avg_route_ms:.4f} ms exceeded 3.0 ms cap"

        # 2. Benchmark 1,000 update calls
        t2 = time.perf_counter()
        for _ in range(1000):
            router.update("gemini-tier_3", random_context, reward=0.85)
        t3 = time.perf_counter()

        avg_update_ms = (t3 - t2) / 1000.0 * 1000.0
        print(f"[LinUCB Benchmark] 1,000 update calls avg latency: {avg_update_ms:.4f} ms per call")
        assert avg_update_ms < 0.1, f"Update latency {avg_update_ms:.4f} ms exceeded 0.1 ms cap"
