"""Closed-Loop Reward Engine & Telemetry Adaptation for LinUCB Router.

Evaluates completion quality from heuristic signals, normalizes performance telemetry
(cost, latency, reliability), and calculates multi-objective scalar rewards for
online contextual bandit parameter adaptation.
"""

from dataclasses import dataclass
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


def is_code_fence_balanced(text: str) -> bool:
    """Checks whether markdown code fences are properly balanced using length awareness.

    In CommonMark, an opening code fence of length N (where N >= 3 backticks) can
    only be closed by a closing fence of length M >= N backticks. Inner code blocks
    with fewer backticks do not close outer fences.

    Args:
        text: Markdown string to evaluate.

    Returns:
        True if all code fences are properly closed or none exist; False if truncated.
    """
    if not text:
        return True
    fences = re.findall(r"`{3,}", text)
    if not fences:
        return True
    open_fence_len = 0
    for fence in fences:
        fence_len = len(fence)
        if open_fence_len == 0:
            open_fence_len = fence_len
        elif fence_len >= open_fence_len:
            open_fence_len = 0
    return open_fence_len == 0


def _safe_numeric(val: Any) -> Optional[float]:
    """Safely converts arbitrary input to float, rejecting booleans, non-numerics, and exceptions."""
    if val is None or isinstance(val, bool):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class ResponseQualityEvaluator:
    """Heuristic quality evaluator assessing response fidelity, structure, and completeness.

    Evaluates response strings for code fence balance, code prompt sufficiency,
    refusal detection, Python AST syntax validity, deterministic arithmetic checks,
    and incorporates explicit user feedback.

    Note on semantic correctness:
    Deterministic AST parsing and arithmetic checks provide structural and numerical
    sanity guards, but do NOT establish complete semantic correctness or formal
    verification of arbitrary generative outputs.
    """

    DEFAULT_CODE_KEYWORDS: Tuple[str, ...] = (
        "def ",
        "class ",
        "function",
        "implement",
        "write",
    )

    DEFAULT_REFUSAL_PHRASES: Tuple[str, ...] = (
        "i cannot assist",
        "i am unable to fulfill",
    )

    def __init__(
        self,
        base_quality: float = 1.0,
        code_fence_penalty: float = 0.3,
        code_request_penalty: float = 0.3,
        refusal_penalty: float = 0.4,
        positive_feedback_bonus: float = 0.2,
        negative_feedback_penalty: float = 0.4,
        ast_syntax_penalty: float = 0.35,
        arithmetic_mismatch_penalty: float = 0.50,
        code_keywords: Optional[Tuple[str, ...]] = None,
        refusal_phrases: Optional[Tuple[str, ...]] = None,
        min_code_words: int = 15,
    ) -> None:
        self.base_quality: float = float(base_quality)
        self.code_fence_penalty: float = float(code_fence_penalty)
        self.code_request_penalty: float = float(code_request_penalty)
        self.refusal_penalty: float = float(refusal_penalty)
        self.positive_feedback_bonus: float = float(positive_feedback_bonus)
        self.negative_feedback_penalty: float = float(negative_feedback_penalty)
        self.ast_syntax_penalty: float = float(ast_syntax_penalty)
        self.arithmetic_mismatch_penalty: float = float(arithmetic_mismatch_penalty)
        self.code_keywords: Tuple[str, ...] = (
            code_keywords if code_keywords is not None else self.DEFAULT_CODE_KEYWORDS
        )
        self.refusal_phrases: Tuple[str, ...] = (
            refusal_phrases if refusal_phrases is not None else self.DEFAULT_REFUSAL_PHRASES
        )
        self.min_code_words: int = int(min_code_words)

    def evaluate_quality(
        self,
        query: str,
        response_text: str,
        success: bool = True,
        error: Optional[str] = None,
        explicit_feedback: Optional[Union[int, float]] = None,
    ) -> float:
        """Evaluates heuristic response quality clamped to [0.0, 1.0].

        Rules:
            1. If success == False or error is present -> 0.0.
            2. If response_text is empty or whitespace -> 0.0.
            3. Markdown code fence completeness: if code fences are unbalanced -> deduct 0.3.
            4. Code request sufficiency: if query requests code ("def ", "class ", "function",
               "implement", "write") and response has < 15 words or missing code fence -> deduct 0.3.
            5. Refusal detection: if response contains "I cannot assist" or
               "I am unable to fulfill" -> deduct 0.4.
            6. Explicit user feedback: strictly +1 awards +0.2 bonus, -1 incurs -0.4 deduction.
               Strings, booleans, neutral (0), or out-of-domain numeric values are ignored.
            7. Python AST syntax validation: if Python code block contains SyntaxError -> deduct 0.35.
            8. Deterministic arithmetic verification: if query is a simple two-operand arithmetic
               question and the expected number is missing from response -> deduct 0.50.
            9. Strictly clamped to [0.0, 1.0].

        Args:
            query: User prompt string.
            response_text: Model completion text.
            success: Whether invocation completed successfully.
            error: Error message string if invocation failed.
            explicit_feedback: User rating (+1 positive, -1 negative, None/0 unrated).

        Returns:
            Quality score float bounded in [0.0, 1.0].
        """
        # Rule 1: Failed call or present error -> 0.0
        if not success or (error is not None and bool(str(error).strip())):
            return 0.0

        # Rule 2: Empty or whitespace response -> 0.0
        if response_text is None or not str(response_text).strip():
            return 0.0

        score = self.base_quality
        resp_clean = str(response_text)
        resp_lower = resp_clean.lower()

        # Defensively extract query string
        query_str = query if isinstance(query, str) else str(query) if query is not None else ""
        query_lower = query_str.lower()

        # Rule 3: Length-aware markdown code fence completeness
        if not is_code_fence_balanced(resp_clean):
            score -= self.code_fence_penalty

        # Rule 4: Code request sufficiency
        is_code_request = any(kw in query_lower for kw in self.code_keywords)
        if is_code_request:
            words = resp_clean.strip().split()
            has_code_fence = bool(re.search(r"`{3,}", resp_clean))
            if len(words) < self.min_code_words or not has_code_fence:
                score -= self.code_request_penalty

        # Rule 5: Refusal detection
        if any(phrase in resp_lower for phrase in self.refusal_phrases):
            score -= self.refusal_penalty

        # Rule 6: Explicit user feedback with strict type & domain validation
        if isinstance(explicit_feedback, (int, float)) and not isinstance(explicit_feedback, bool):
            if explicit_feedback == 1:
                score += self.positive_feedback_bonus
            elif explicit_feedback == -1:
                score -= self.negative_feedback_penalty

        # Rule 7: Python AST syntax validation for python code blocks
        py_blocks = re.findall(r"```(?:python|py)\b(.*?)```", resp_clean, re.DOTALL | re.IGNORECASE)
        for block in py_blocks:
            code_text = block.strip()
            if code_text:
                try:
                    import ast
                    ast.parse(code_text)
                except SyntaxError:
                    score -= self.ast_syntax_penalty
                    break

        # Rule 8: Deterministic arithmetic check for supported two-operand arithmetic queries
        arith_match = re.search(
            r"\b(\d+(?:\.\d+)?)\s*([\+\-\*\/]|multiplied by|times|plus|minus|divided by)\s*(\d+(?:\.\d+)?)\b",
            query_str,
            re.IGNORECASE,
        )
        if arith_match:
            try:
                n1 = float(arith_match.group(1))
                op_raw = arith_match.group(2).lower()
                n2 = float(arith_match.group(3))
                expected = None
                if op_raw in ("+", "plus"):
                    expected = n1 + n2
                elif op_raw in ("-", "minus"):
                    expected = n1 - n2
                elif op_raw in ("*", "multiplied by", "times"):
                    expected = n1 * n2
                elif op_raw in ("/", "divided by") and n2 != 0:
                    expected = n1 / n2
                if expected is not None:
                    exp_str = str(int(expected)) if expected.is_integer() else f"{expected:.4f}".rstrip("0").rstrip(".")
                    if not re.search(r"\b" + re.escape(exp_str) + r"\b", resp_clean):
                        score -= self.arithmetic_mismatch_penalty
            except Exception:
                pass

        # Rule 9: Strictly clamped to [0.0, 1.0]
        return float(max(0.0, min(1.0, score)))


class RewardCalculator:
    """Multi-objective scalar reward calculator for LinUCB bandit updates.

    Weights:
        w_q: Quality weight (default: 0.40)
        w_c: Cost penalty weight (default: 0.30)
        w_l: Latency penalty weight (default: 0.20)
        w_r: Reliability / Success bonus weight (default: 0.10)

    Ceilings:
        C_max: Cost normalization ceiling in USD (default: $0.005)
        L_max: Latency normalization ceiling in ms (default: 5000.0 ms)
    """

    def __init__(
        self,
        w_q: float = 0.40,
        w_c: float = 0.30,
        w_l: float = 0.20,
        w_r: float = 0.10,
        c_max: float = 0.005,
        l_max: float = 5000.0,
    ) -> None:
        self.w_q: float = float(w_q)
        self.w_c: float = float(w_c)
        self.w_l: float = float(w_l)
        self.w_r: float = float(w_r)

        if c_max <= 0.0:
            raise ValueError(f"c_max must be positive, got {c_max}")
        if l_max <= 0.0:
            raise ValueError(f"l_max must be positive, got {l_max}")

        self.c_max: float = float(c_max)
        self.l_max: float = float(l_max)

    def compute_reward(
        self,
        cost_usd: Optional[Union[float, int, str]],
        latency_ms: Optional[Union[float, int, str]],
        success: bool,
        quality_score: Union[float, int, str],
    ) -> Tuple[float, Dict[str, float]]:
        """Computes composite scalar reward and breakdown dictionary.

        Formula:
            Q = clamp(quality_score, 0.0, 1.0)
            C_norm = min(1.0, max(0.0, cost_usd / C_max)) if cost_usd > 0 else 0.0
            L_norm = min(1.0, max(0.0, latency_ms / L_max)) if latency_ms > 0 else 0.0
            S = 1.0 if success else 0.0
            R = w_q * Q - w_c * C_norm - w_l * L_norm + w_r * S
            R is bounded in [-1.0, 1.0].

        Args:
            cost_usd: Observed cost in USD, or None.
            latency_ms: Observed latency in milliseconds, or None.
            success: Whether invocation was successful.
            quality_score: Pre-computed quality score in [0.0, 1.0].

        Returns:
            Tuple of:
                - R: Clamped scalar reward float in [-1.0, 1.0].
                - breakdown_dict: Detailed numerical breakdown of all terms.
        """
        # Quality clamped to [0.0, 1.0] with NaN/Inf guards
        q_val = _safe_numeric(quality_score)
        if q_val is None or math.isnan(q_val):
            Q = 0.0
        elif math.isinf(q_val):
            Q = 1.0 if q_val > 0.0 else 0.0
        else:
            Q = min(1.0, max(0.0, q_val))

        # Cost normalized and clamped to [0.0, 1.0] with NaN/Inf guards
        c_val = _safe_numeric(cost_usd)
        if c_val is None or math.isnan(c_val) or c_val <= 0.0:
            C_norm = 0.0
        elif math.isinf(c_val):
            C_norm = 1.0
        else:
            C_norm = min(1.0, max(0.0, c_val / self.c_max))

        # Latency normalized and clamped to [0.0, 1.0] with NaN/Inf guards
        l_val = _safe_numeric(latency_ms)
        if l_val is None or math.isnan(l_val) or l_val <= 0.0:
            L_norm = 0.0
        elif math.isinf(l_val):
            L_norm = 1.0
        else:
            L_norm = min(1.0, max(0.0, l_val / self.l_max))

        # Reliability / Success indicator
        S = 1.0 if bool(success) else 0.0

        # Composite reward calculation
        q_term = self.w_q * Q
        c_term = -self.w_c * C_norm
        l_term = -self.w_l * L_norm
        s_term = self.w_r * S

        raw_r = q_term + c_term + l_term + s_term
        if not success and raw_r >= 0.0:
            raw_r = -0.50
        if math.isnan(raw_r):
            r_clamped = 0.0
        else:
            r_clamped = min(1.0, max(-1.0, raw_r))

        breakdown: Dict[str, float] = {
            "quality": float(Q),
            "cost_norm": float(C_norm),
            "latency_norm": float(L_norm),
            "success": float(S),
            "reliability": float(S),
            "quality_term": float(q_term),
            "cost_term": float(c_term),
            "latency_term": float(l_term),
            "success_term": float(s_term),
            "raw_reward": float(raw_r),
            "reward": float(r_clamped),
        }

        return float(r_clamped), breakdown


# Module-level singletons
quality_evaluator: ResponseQualityEvaluator = ResponseQualityEvaluator()
reward_calculator: RewardCalculator = RewardCalculator()


def record_and_update_bandit(
    router: Any,
    model_id: str,
    x_t: np.ndarray,
    cost_usd: Optional[float],
    latency_ms: float,
    success: bool,
    response_text: str,
    query: str,
    explicit_feedback: Optional[Union[int, float]] = None,
    tracker: Optional[Any] = None,
    evaluator: Optional[ResponseQualityEvaluator] = None,
    calculator: Optional[RewardCalculator] = None,
) -> float:
    """Computes closed-loop quality, composite reward, and safely updates bandit & tracker.

    Includes defensive fault isolation ensuring telemetry/bandit exceptions never
    crash the active user request.

    Args:
        router: LinUCBRouter instance (or object exposing .update(model_id, x_t, reward)).
        model_id: Identifier string of the model tier.
        x_t: 16-dimensional context feature vector.
        cost_usd: Observed inference cost in USD, or None.
        latency_ms: Measured latency in milliseconds.
        success: Whether the inference request succeeded.
        response_text: Model completion text.
        query: Original user prompt query.
        explicit_feedback: Optional user feedback (+1 bonus, -1 deduction).
        tracker: Optional telemetry tracker instance.
        evaluator: Optional custom ResponseQualityEvaluator. Defaults to singleton.
        calculator: Optional custom RewardCalculator. Defaults to singleton.

    Returns:
        Scalar reward R in [-1.0, 1.0].
    """
    eval_engine = evaluator if evaluator is not None else quality_evaluator
    calc_engine = calculator if calculator is not None else reward_calculator

    error_msg = None if success else "Inference failure"

    q_score = eval_engine.evaluate_quality(
        query=query,
        response_text=response_text,
        success=success,
        error=error_msg,
        explicit_feedback=explicit_feedback,
    )

    reward, _ = calc_engine.compute_reward(
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        success=success,
        quality_score=q_score,
    )

    # Fault-isolated router update
    if router is not None:
        try:
            router.update(model_id, x_t, reward)
            if hasattr(router, "save_state"):
                router.save_state()
        except Exception as exc:
            logger.error(
                "Bandit router update failed for model tier '%s': %s",
                model_id,
                exc,
                exc_info=True,
            )

    # Fault-isolated telemetry tracker update
    if tracker is not None:
        try:
            if hasattr(tracker, "record_update"):
                tracker.record_update(
                    model_id=model_id,
                    reward=reward,
                    latency_ms=latency_ms,
                    cost_usd=cost_usd,
                    success=success,
                )
            elif hasattr(tracker, "log_transaction"):
                tracker.log_transaction(
                    model_id=model_id,
                    reward=reward,
                    latency_ms=latency_ms,
                )
        except Exception as exc:
            logger.error(
                "Telemetry tracker update failed for model tier '%s': %s",
                model_id,
                exc,
                exc_info=True,
            )

    return reward


__all__ = [
    "is_code_fence_balanced",
    "ResponseQualityEvaluator",
    "RewardCalculator",
    "quality_evaluator",
    "reward_calculator",
    "record_and_update_bandit",
]
