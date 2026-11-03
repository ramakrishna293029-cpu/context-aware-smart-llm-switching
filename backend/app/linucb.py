"""Disjoint LinUCB Contextual Bandit Router for LLM Switching.

Implements ridge regression with Sherman-Morrison rank-1 online inverse covariance
updates, upper confidence bound (UCB) action selection, and thread-safe persistence.
"""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

from .config import settings
from .registry import ModelSpec

# Default 6 core architecture model tiers managed by LinUCB
CORE_TIERS: Tuple[str, ...] = (
    "gemini-tier_1",
    "groq-tier_2",
    "gemini-tier_3",
    "groq-tier_4",
    "groq-tier_5",
    "gemini-tier_6",
)

# Maximum safe absolute magnitude for reward feedback
MAX_REWARD_MAGNITUDE: float = 1e6


@dataclass
class BanditScore:
    """Exploration and exploitation evaluation metrics for a single model arm."""
    model_id: str
    ucb_score: float
    expected_reward: float
    uncertainty: float
    pull_count: int


@dataclass
class BanditDecision:
    """Action selection output from the LinUCB contextual bandit."""
    selected_model: ModelSpec
    fallback_chain: List[ModelSpec]
    scores: Dict[str, BanditScore]
    x_t: np.ndarray


class LinUCBArm:
    """Disjoint LinUCB Arm maintaining ridge regression parameters for a single LLM tier.

    Parameters:
        model_id: Identifier string of the model/tier.
        d: Context feature dimensionality (default: 16).
        alpha: Exploration parameter (default: 1.0, must be non-negative).

    Attributes:
        A: (d, d) Covariance matrix initialized to I_d (float64).
        b: (d,) Bias / response vector initialized to 0 (float64).
        V: (d, d) Inverse covariance matrix initialized to I_d (float64).
        pull_count: Total number of updates received.
        total_reward: Cumulative scalar reward received.
    """

    def __init__(self, model_id: str, d: int = 16, alpha: float = 1.0) -> None:
        self.model_id: str = str(model_id)
        self.d: int = int(d)
        effective_alpha = float(alpha)
        if effective_alpha < 0.0:
            raise ValueError(
                f"Exploration parameter alpha must be non-negative, got {effective_alpha}"
            )
        self.alpha: float = effective_alpha
        self.A: np.ndarray = np.eye(self.d, dtype=np.float64)
        self.b: np.ndarray = np.zeros(self.d, dtype=np.float64)
        self.V: np.ndarray = np.eye(self.d, dtype=np.float64)
        self.pull_count: int = 0
        self.total_reward: float = 0.0
        self._lock: threading.Lock = threading.Lock()

    def get_score(
        self, x_t: np.ndarray, alpha: Optional[float] = None
    ) -> BanditScore:
        """Atomically computes and returns a BanditScore under arm lock.

        Formula:
            theta_hat = V @ b
            expected_reward = theta_hat @ x_t
            uncertainty = effective_alpha * sqrt(max(0.0, x_t @ V @ x_t))
            ucb_score = expected_reward + uncertainty

        Returns:
            BanditScore with atomic pull_count and metrics snapshot.
        """
        x_vec = np.asarray(x_t, dtype=np.float64).reshape(-1)
        if x_vec.shape[0] != self.d:
            raise ValueError(
                f"Feature vector dimension mismatch: expected {self.d}, got {x_vec.shape[0]}"
            )
        if not np.all(np.isfinite(x_vec)):
            raise ValueError("Feature vector x_t contains non-finite values (NaN or Inf).")

        effective_alpha = self.alpha if alpha is None else float(alpha)
        if effective_alpha < 0.0:
            raise ValueError(
                f"Exploration parameter alpha must be non-negative, got {effective_alpha}"
            )

        with self._lock:
            # theta_hat = V @ b
            theta_hat = self.V @ self.b
            expected_reward = float(np.dot(theta_hat, x_vec))

            # uncertainty = effective_alpha * sqrt(max(0.0, x_t @ V @ x_t))
            quad_form = float(np.dot(x_vec, self.V @ x_vec))
            uncertainty = float(effective_alpha * math.sqrt(max(0.0, quad_form)))
            ucb_score = expected_reward + uncertainty

            return BanditScore(
                model_id=self.model_id,
                ucb_score=ucb_score,
                expected_reward=expected_reward,
                uncertainty=uncertainty,
                pull_count=self.pull_count,
            )

    def compute_ucb(
        self, x_t: np.ndarray, alpha: Optional[float] = None
    ) -> Tuple[float, float, float]:
        """Computes Upper Confidence Bound score for context vector x_t.

        Returns:
            (ucb_score, expected_reward, uncertainty)
        """
        score = self.get_score(x_t, alpha=alpha)
        return (score.ucb_score, score.expected_reward, score.uncertainty)

    def update(self, x_t: np.ndarray, reward: float) -> None:
        """Online rank-1 Sherman-Morrison update of parameters given context and reward.

        Formula:
            b <- b + reward * x_t
            A <- A + outer(x_t, x_t)
            denom = 1.0 + x_t @ V @ x_t
            V <- V - (V @ outer(x_t, x_t) @ V) / denom
            Re-conditions V = inv(A) every 500 pulls.
        """
        x_vec = np.asarray(x_t, dtype=np.float64).reshape(-1)
        if x_vec.shape[0] != self.d:
            raise ValueError(
                f"Feature vector dimension mismatch: expected {self.d}, got {x_vec.shape[0]}"
            )
        if not np.all(np.isfinite(x_vec)):
            raise ValueError("Feature vector x_t contains non-finite values (NaN or Inf).")

        r = float(reward)
        if math.isnan(r) or math.isinf(r):
            raise ValueError(f"Invalid reward value (NaN or Inf): {reward}")
        if abs(r) > MAX_REWARD_MAGNITUDE:
            raise ValueError(
                f"Reward magnitude exceeds numerical stability threshold (abs(r) <= {MAX_REWARD_MAGNITUDE}): {reward}"
            )

        with self._lock:
            # Update bias vector: b <- b + reward * x_t
            self.b += r * x_vec

            # Update covariance matrix: A <- A + outer(x_t, x_t)
            self.A += np.outer(x_vec, x_vec)

            # Sherman-Morrison rank-1 update:
            # V_{t+1} = V_t - (V_t @ outer(x, x) @ V_t) / (1.0 + x^T @ V_t @ x)
            denom = 1.0 + float(np.dot(x_vec, self.V @ x_vec))
            if denom <= 0.0 or math.isnan(denom) or math.isinf(denom):
                self.V = np.linalg.inv(self.A)
            else:
                vx = self.V @ x_vec
                self.V -= np.outer(vx, vx) / denom

            # Enforce exact numerical symmetry
            self.V = 0.5 * (self.V + self.V.T)
            self.A = 0.5 * (self.A + self.A.T)

            self.pull_count += 1
            self.total_reward += r

            # Re-condition every 500 pulls to prevent floating-point drift
            if self.pull_count % 500 == 0:
                self.V = np.linalg.inv(self.A)
                self.V = 0.5 * (self.V + self.V.T)


def _compute_candidate_suitability(
    model: ModelSpec,
    strategy: Optional[str] = None,
    task_type: Optional[str] = None,
    complexity: Optional[str] = None,
) -> float:
    """Computes a deterministic context and strategy suitability score for tie-breaking.

    Used when UCB scores are tied (e.g. unpulled arms or equal confidence bounds).
    Ensures cost & performance optimization: low-complexity tasks prefer cheap/fast tiers,
    coding prefers Tier 4, math/reasoning prefers Tier 5, and frontier tasks prefer Tier 6.
    """
    strat = (strategy or "balanced").lower().strip()
    t_type = (task_type or "general").lower().strip()
    comp = (complexity or "medium").lower().strip()

    price = getattr(model, "input_price_per_mtok", 0.1) or 0.1
    cost_factor = 1.0 / (1.0 + price * 3.0)
    lat = getattr(model, "expected_latency_ms", 300.0) or 300.0
    lat_factor = 1.0 / (1.0 + lat / 300.0)
    q_factor = getattr(model, "quality", 0.8) or 0.8
    c_factor = getattr(model, "coding", 0.8) or 0.8
    r_factor = getattr(model, "reasoning", 0.8) or 0.8

    if strat == "lowest_cost":
        return cost_factor * 3.0 + q_factor * 0.5
    if strat == "fastest":
        return lat_factor * 3.0 + cost_factor * 1.0
    if strat == "highest_quality":
        return q_factor * 3.0 + r_factor * 1.5

    # Default: Balanced strategy
    if comp == "low":
        # Low complexity / routine: Tier 1 (Flash-Lite) and Tier 2 (Groq 20B) are optimal
        return cost_factor * 3.5 + lat_factor * 2.0 + q_factor * 0.5
    if t_type == "coding":
        return c_factor * 3.5 + cost_factor * 0.8
    if t_type in ("reasoning", "math"):
        return r_factor * 4.0 + cost_factor * 0.5
    if comp == "high":
        # Frontier synthesis / complex architecture
        return q_factor * 3.0 + r_factor * 2.5 + c_factor * 1.5

    # Medium complexity: balance quality, cost, and latency
    return q_factor * 2.0 + cost_factor * 1.5 + lat_factor * 1.0


class LinUCBRouter:
    """Disjoint LinUCB contextual bandit router for model tier action selection."""

    def __init__(self, d: int = 16, alpha: float = 1.0) -> None:
        self.d: int = int(d)
        init_alpha = float(alpha)
        if init_alpha < 0.0:
            raise ValueError(
                f"Exploration parameter alpha must be non-negative, got {init_alpha}"
            )
        self.alpha: float = init_alpha
        self._lock: threading.RLock = threading.RLock()
        self.arms: Dict[str, LinUCBArm] = {
            tier: LinUCBArm(model_id=tier, d=self.d, alpha=self.alpha)
            for tier in CORE_TIERS
        }

    def reset(self) -> None:
        """Resets all arms and clears any dynamically added arms."""
        with self._lock:
            self.arms = {
                tier: LinUCBArm(model_id=tier, d=self.d, alpha=self.alpha)
                for tier in CORE_TIERS
            }

    def get_or_create_arm(
        self, model_id: str, d: Optional[int] = None, alpha: Optional[float] = None
    ) -> LinUCBArm:
        """Retrieves an existing arm for model_id or creates one dynamically."""
        with self._lock:
            if model_id not in self.arms:
                arm_d = self.d if d is None else int(d)
                arm_alpha = self.alpha if alpha is None else float(alpha)
                self.arms[model_id] = LinUCBArm(model_id=model_id, d=arm_d, alpha=arm_alpha)
            return self.arms[model_id]

    def route(
        self,
        x_t: np.ndarray,
        eligible_models: List[ModelSpec],
        alpha: Optional[float] = None,
        strategy: Optional[str] = None,
        task_type: Optional[str] = None,
        complexity: Optional[str] = None,
    ) -> BanditDecision:
        """Routes prompt context across eligible models using Disjoint LinUCB.

        Args:
            x_t: 16-dimensional context feature vector.
            eligible_models: Filtered list of models satisfying hard constraints.
            alpha: Optional exploration multiplier override (must be non-negative).
            strategy: Optional routing strategy ('balanced', 'lowest_cost', 'fastest', 'highest_quality').
            task_type: Optional query task category ('coding', 'reasoning', 'math', 'factual', 'general').
            complexity: Optional query complexity assessment ('low', 'medium', 'high').

        Returns:
            BanditDecision with selected model, ranked fallback chain, and scores.

        Raises:
            ValueError: If eligible_models is empty, x_t is non-finite, or alpha < 0.
        """
        if not eligible_models:
            raise ValueError("No eligible models provided for routing.")

        # Defensive copy to prevent retroactive mutation by external caller
        x_vec = np.array(x_t, dtype=np.float64, copy=True).reshape(-1)
        if x_vec.shape[0] != self.d:
            raise ValueError(
                f"Feature vector dimension mismatch: expected {self.d}, got {x_vec.shape[0]}"
            )
        if not np.all(np.isfinite(x_vec)):
            raise ValueError("Feature vector x_t contains non-finite values (NaN or Inf).")

        effective_alpha = self.alpha if alpha is None else float(alpha)
        if effective_alpha < 0.0:
            raise ValueError(
                f"Exploration parameter alpha must be non-negative, got {effective_alpha}"
            )

        scores: Dict[str, BanditScore] = {}
        scored_pairs: List[Tuple[ModelSpec, float]] = []

        for model in eligible_models:
            arm = self.get_or_create_arm(model.model_id)
            # Atomically retrieve BanditScore under arm lock to avoid race conditions
            score_obj = arm.get_score(x_vec, alpha=effective_alpha)
            scores[model.model_id] = score_obj
            scored_pairs.append((model, score_obj.ucb_score))

        # Sort strictly descending by UCB score; break ties deterministically by suitability
        # Round UCB scores to 5 decimals so infinitesimal floating-point noise doesn't mask true ties
        scored_pairs.sort(
            key=lambda pair: (
                round(pair[1], 5),
                _compute_candidate_suitability(pair[0], strategy, task_type, complexity),
            ),
            reverse=True,
        )

        selected_model = scored_pairs[0][0]
        fallback_chain = [model for model, _ in scored_pairs[1:]]

        return BanditDecision(
            selected_model=selected_model,
            fallback_chain=fallback_chain,
            scores=scores,
            x_t=x_vec,
        )

    def warm_start_defaults(self) -> None:
        """Pre-seeds the 6 core architecture arms with canonical prior representations.

        Ensures that cold start immediately routes appropriately (Tier 1 for routine/low-complexity,
        Tier 4 for coding, Tier 5 for reasoning, Tier 6 for frontier multi-domain) instead of
        blindly defaulting to Tier 6 on unpulled ties.
        """
        try:
            from .features import feature_extractor
        except ImportError:
            return

        canonical_samples = [
            (
                "Hello! How are you doing today?",
                {"tier_1": 0.88, "tier_2": 0.80, "tier_3": 0.65, "tier_4": 0.40, "tier_5": 0.35, "tier_6": 0.40},
            ),
            (
                "What is a simple definition of photosynthesis?",
                {"tier_1": 0.85, "tier_2": 0.82, "tier_3": 0.75, "tier_4": 0.50, "tier_5": 0.45, "tier_6": 0.50},
            ),
            (
                "Tell me a short joke or humorous observation",
                {"tier_1": 0.82, "tier_2": 0.88, "tier_3": 0.70, "tier_4": 0.45, "tier_5": 0.40, "tier_6": 0.45},
            ),
            (
                "Write a Python function to perform quicksort with comprehensive unit tests and type annotations",
                {"tier_4": 0.94, "tier_6": 0.82, "tier_5": 0.70, "tier_3": 0.65, "tier_2": 0.40, "tier_1": 0.30},
            ),
            (
                "Implement a binary search tree in C++ with memory management and insert/search methods",
                {"tier_4": 0.93, "tier_6": 0.85, "tier_5": 0.72, "tier_3": 0.60, "tier_2": 0.35, "tier_1": 0.25},
            ),
            (
                "Prove that the square root of 2 is irrational using proof by contradiction step by step",
                {"tier_5": 0.96, "tier_6": 0.88, "tier_4": 0.65, "tier_3": 0.60, "tier_2": 0.40, "tier_1": 0.25},
            ),
            (
                "Analyze the Byzantine Generals Problem in distributed consensus under asynchronous networks",
                {"tier_5": 0.95, "tier_6": 0.90, "tier_4": 0.70, "tier_3": 0.65, "tier_2": 0.45, "tier_1": 0.30},
            ),
            (
                "Design a global multi-region active-active cloud architecture balancing Paxos consistency, latency, and disaster recovery",
                {"tier_6": 0.96, "tier_5": 0.88, "tier_4": 0.78, "tier_3": 0.65, "tier_2": 0.50, "tier_1": 0.25},
            ),
        ]

        with self._lock:
            for text, tier_rewards in canonical_samples:
                x_vec = feature_extractor.extract(text)
                for arm_id, arm in self.arms.items():
                    for t_name, reward in tier_rewards.items():
                        if t_name in arm_id:
                            arm.update(x_vec, reward)

    def update(self, model_id: str, x_t: np.ndarray, reward: float) -> None:
        """Updates the disjoint bandit arm associated with model_id."""
        arm = self.get_or_create_arm(model_id)
        arm.update(x_t, reward)

    def save_state(self, db_path: Optional[Union[str, os.PathLike]] = None) -> None:
        """Persists all bandit arm matrices and counters to SQLite or JSON.

        Args:
            db_path: Path to database or JSON file. If None, uses settings.database_path.
        """
        target_path = Path(db_path if db_path is not None else settings.database_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        str_path = str(target_path)

        if str_path.endswith(".json"):
            # JSON format serialization
            data = {}
            with self._lock:
                for mid, arm in self.arms.items():
                    with arm._lock:
                        data[mid] = {
                            "model_id": arm.model_id,
                            "d": arm.d,
                            "alpha": arm.alpha,
                            "pull_count": arm.pull_count,
                            "total_reward": arm.total_reward,
                            "A": arm.A.tolist(),
                            "b": arm.b.tolist(),
                            "V": arm.V.tolist(),
                        }
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return

        # SQLite format serialization with explicit IEEE 754 little-endian (<f8) BLOBs
        with self._lock:
            with sqlite3.connect(str_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bandit_arms (
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
                for mid, arm in self.arms.items():
                    with arm._lock:
                        a_blob = arm.A.astype("<f8").tobytes()
                        b_blob = arm.b.astype("<f8").tobytes()
                        v_blob = arm.V.astype("<f8").tobytes()
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO bandit_arms 
                            (model_id, d, alpha, pull_count, total_reward, A, b, V, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                            """,
                            (
                                arm.model_id,
                                arm.d,
                                arm.alpha,
                                arm.pull_count,
                                arm.total_reward,
                                a_blob,
                                b_blob,
                                v_blob,
                            ),
                        )
                conn.commit()

    def load_state(self, db_path: Optional[Union[str, os.PathLike]] = None) -> None:
        """Loads bandit arm matrices and counters from SQLite or JSON.

        Args:
            db_path: Path to database or JSON file. If None, uses settings.database_path.
        """
        target_path = Path(db_path if db_path is not None else settings.database_path)
        if not target_path.exists():
            return

        str_path = str(target_path)
        if str_path.endswith(".json"):
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                for mid, arm_data in data.items():
                    arm = self.get_or_create_arm(
                        mid, d=arm_data["d"], alpha=arm_data["alpha"]
                    )
                    with arm._lock:
                        arm.d = arm_data["d"]
                        arm.alpha = arm_data["alpha"]
                        arm.pull_count = arm_data["pull_count"]
                        arm.total_reward = arm_data["total_reward"]
                        arm.A = np.array(arm_data["A"], dtype=np.float64).reshape((arm.d, arm.d))
                        arm.b = np.array(arm_data["b"], dtype=np.float64).reshape((arm.d,))
                        arm.V = np.array(arm_data["V"], dtype=np.float64).reshape((arm.d, arm.d))
            return

        # SQLite format loading with explicit endianness and BLOB size validation
        with self._lock:
            with sqlite3.connect(str_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='bandit_arms'"
                )
                if not cursor.fetchone():
                    return
                cursor.execute(
                    "SELECT model_id, d, alpha, pull_count, total_reward, A, b, V FROM bandit_arms"
                )
                rows = cursor.fetchall()
                for row in rows:
                    mid, d, alpha, pull_count, total_reward, a_blob, b_blob, v_blob = row

                    expected_mat_bytes = d * d * 8
                    expected_vec_bytes = d * 8
                    if (
                        len(a_blob) != expected_mat_bytes
                        or len(v_blob) != expected_mat_bytes
                        or len(b_blob) != expected_vec_bytes
                    ):
                        raise ValueError(
                            f"Corrupted BLOB byte length for arm {mid}: "
                            f"expected ({expected_mat_bytes}, {expected_vec_bytes}, {expected_mat_bytes}), "
                            f"got ({len(a_blob)}, {len(b_blob)}, {len(v_blob)})"
                        )

                    arm = self.get_or_create_arm(mid, d=d, alpha=alpha)
                    with arm._lock:
                        arm.d = d
                        arm.alpha = alpha
                        arm.pull_count = pull_count
                        arm.total_reward = total_reward
                        arm.A = np.frombuffer(a_blob, dtype="<f8").reshape((d, d)).copy()
                        arm.b = np.frombuffer(b_blob, dtype="<f8").reshape((d,)).copy()
                        arm.V = np.frombuffer(v_blob, dtype="<f8").reshape((d, d)).copy()


# Global singleton instance for production routing
linucb_router: LinUCBRouter = LinUCBRouter()
