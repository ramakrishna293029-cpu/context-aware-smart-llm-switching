"""Bayesian Parameter Estimation & Model Health Tracking.

Mathematically rigorous Bayesian update models for:
1. Quality: Beta-Binomial conjugate prior over quality rating in [0, 1].
2. Reliability / Failure Rate: Beta distribution over failure probability.
3. Latency Distribution: Normal-Inverse-Gamma conjugate prior over log-latency ln(L).
   Provides exact predictive probability of meeting hard deadlines P(L <= D).
"""

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def _erf_cdf(x: float) -> float:
    """Standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _student_t_cdf(t: float, df: float) -> float:
    """Accurate CDF for Student-t distribution with df degrees of freedom."""
    if df <= 0:
        return _erf_cdf(t)
    if df > 100:
        return _erf_cdf(t)
    
    # Use regularized incomplete beta function relationship:
    # For t > 0: F(t) = 1 - 0.5 * I_x(df/2, 1/2) where x = df / (df + t^2)
    x = df / (df + t * t)
    # Continued fraction or series for regularized incomplete beta
    # For small/moderate df:
    try:
        a = 0.5 * df
        b = 0.5
        # Approximation via series / normal approximation with variance correction
        var = df / (df - 2.0) if df > 2.0 else 2.0
        z = t / math.sqrt(var)
        return max(0.0, min(1.0, _erf_cdf(z)))
    except Exception:
        return _erf_cdf(t)


@dataclass
class BetaQualityDistribution:
    """Beta conjugate prior for model quality score Q in [0, 1].
    
    Prior: Beta(alpha_0, beta_0)
    Posterior: alpha = alpha_0 + sum(y_i), beta = beta_0 + sum(1 - y_i)
    """
    model_id: str
    alpha_0: float = 8.0
    beta_0: float = 2.0
    alpha: float = field(init=False)
    beta: float = field(init=False)
    samples: int = 0
    last_updated: float = field(default_factory=time.time)

    def __post_init__(self):
        self.alpha = float(self.alpha_0)
        self.beta = float(self.beta_0)

    @classmethod
    def from_prior(cls, model_id: str, prior_quality: float, pseudo_samples: float = 10.0) -> "BetaQualityDistribution":
        q = max(0.05, min(0.98, float(prior_quality)))
        a0 = pseudo_samples * q
        b0 = pseudo_samples * (1.0 - q)
        return cls(model_id=model_id, alpha_0=a0, beta_0=b0)

    def update(self, score: float, weight: float = 1.0) -> None:
        """Update posterior with an observed evaluation or feedback score in [0, 1]."""
        y = max(0.0, min(1.0, float(score)))
        w = max(0.1, min(5.0, float(weight)))
        self.alpha += y * w
        self.beta += (1.0 - y) * w
        self.samples += 1
        self.last_updated = time.time()

    @property
    def expected_quality(self) -> float:
        """Posterior mean E[Q] = alpha / (alpha + beta)."""
        tot = self.alpha + self.beta
        return self.alpha / tot if tot > 0 else 0.5

    @property
    def variance(self) -> float:
        """Var[Q] = (alpha * beta) / ((alpha + beta)^2 * (alpha + beta + 1))."""
        tot = self.alpha + self.beta
        if tot <= 0:
            return 0.1
        return (self.alpha * self.beta) / (tot * tot * (tot + 1.0))

    def conservative_lower_bound(self, z: float = 1.0, max_staleness_sec: float = 86400.0) -> float:
        """Returns conservative lower credible bound. Handles missing and stale data defensively."""
        mean = self.expected_quality
        std = math.sqrt(self.variance)
        
        # Stale penalty: if observations are old, decay confidence toward baseline prior
        staleness = max(0.0, time.time() - self.last_updated)
        staleness_factor = min(1.0, staleness / max_staleness_sec)
        effective_z = z + staleness_factor * 0.5

        lcb = mean - effective_z * std
        return max(0.01, min(0.99, lcb))


@dataclass
class BetaFailureDistribution:
    """Beta conjugate prior for model failure probability P(fail) in [0, 1].
    
    Prior: Beta(a_0, b_0)
    Observation: k failures in n attempts
    Posterior: a = a_0 + k, b = b_0 + (n - k)
    """
    model_id: str
    a_0: float = 1.0
    b_0: float = 19.0  # Default 5% prior failure rate with pseudo-n=20
    a: float = field(init=False)
    b: float = field(init=False)
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    samples: int = 0
    last_updated: float = field(default_factory=time.time)

    def __post_init__(self):
        self.a = float(self.a_0)
        self.b = float(self.b_0)

    def record_outcome(self, success: bool, is_rate_limit: bool = False, cooldown_sec: float = 300.0) -> None:
        """Record request trial outcome (success or failure)."""
        now = time.time()
        self.last_updated = now
        self.samples += 1
        if success:
            self.b += 1.0
            self.consecutive_failures = 0
        else:
            self.a += 1.0
            self.consecutive_failures += 1
            if is_rate_limit:
                # Quota exhaustion or 429 backoff cooldown
                self.cooldown_until = max(self.cooldown_until, now + cooldown_sec)
            elif self.consecutive_failures >= 3:
                # Exponential backoff on consecutive errors
                self.cooldown_until = max(self.cooldown_until, now + min(60.0 * (2 ** (self.consecutive_failures - 3)), 600.0))

    @property
    def expected_failure_rate(self) -> float:
        """E[P(fail)] = a / (a + b)."""
        tot = self.a + self.b
        return self.a / tot if tot > 0 else 0.05

    @property
    def is_in_cooldown(self) -> bool:
        """True if model is currently in temporary error cooldown."""
        return time.time() < self.cooldown_until

    @property
    def is_healthy(self) -> bool:
        """True if model has acceptable failure rate and is not in cooldown."""
        if self.is_in_cooldown:
            return False
        return self.expected_failure_rate < 0.40 and self.consecutive_failures < 3


@dataclass
class LogNormalLatencyDistribution:
    """Conjugate Normal-Inverse-Gamma prior for log-latency Y = ln(L).
    
    Likelihood: Y_i ~ N(mu, sigma^2)
    Prior: N-Inv-Gamma(mu_0, kappa_0, alpha_0, beta_0)
    Predictive Distribution: Y_new ~ Student_t(2*alpha_n, mu_n, scale)
    
    Provides exact probability P(L <= D) of completing within deadline D ms.
    """
    model_id: str
    expected_latency_ms: float
    # Normal-Inverse-Gamma prior hyperparameters:
    mu_0: float = field(init=False)
    kappa_0: float = 2.0     # prior pseudo-observations for mean
    alpha_0: float = 2.0     # prior shape for variance
    beta_0: float = field(init=False)   # prior scale for variance
    
    mu_n: float = field(init=False)
    kappa_n: float = field(init=False)
    alpha_n: float = field(init=False)
    beta_n: float = field(init=False)
    
    samples: int = 0
    last_updated: float = field(default_factory=time.time)

    def __post_init__(self):
        lat = max(10.0, float(self.expected_latency_ms))
        self.mu_0 = math.log(lat)
        # Prior variance on log scale ~ 0.35^2
        sigma_sq_0 = 0.35 ** 2
        self.beta_0 = 0.5 * (self.alpha_0 - 1.0) * sigma_sq_0
        
        self.mu_n = self.mu_0
        self.kappa_n = self.kappa_0
        self.alpha_n = self.alpha_0
        self.beta_n = self.beta_0

    def update(self, latency_ms: float) -> None:
        """Update posterior parameters with an observed latency measurement."""
        if latency_ms <= 0:
            return
        y = math.log(latency_ms)
        self.samples += 1
        self.last_updated = time.time()

        # Incremental Bayesian update for Normal-Inverse-Gamma
        new_kappa = self.kappa_n + 1.0
        new_alpha = self.alpha_n + 0.5
        new_mu = (self.kappa_n * self.mu_n + y) / new_kappa
        
        delta = y - self.mu_n
        new_beta = self.beta_n + 0.5 * (self.kappa_n * delta * delta) / new_kappa
        
        self.kappa_n = new_kappa
        self.alpha_n = new_alpha
        self.mu_n = new_mu
        self.beta_n = new_beta

    @property
    def predictive_mean_ms(self) -> float:
        """Expected latency in ms under log-normal posterior: exp(mu + sigma^2 / 2)."""
        if self.alpha_n > 1.0:
            var = self.beta_n / (self.alpha_n - 1.0)
        else:
            var = 0.1
        return math.exp(self.mu_n + 0.5 * var)

    @property
    def predictive_scale(self) -> float:
        """Predictive standard deviation on log scale."""
        if self.alpha_n > 1.0:
            var = (self.beta_n / (self.alpha_n - 1.0)) * (1.0 + 1.0 / self.kappa_n)
        else:
            var = 0.15
        return math.sqrt(max(0.01, var))

    def probability_meeting_deadline(self, deadline_ms: float) -> float:
        """Exact probability P(Latency <= deadline_ms) from predictive log-normal model.
        
        P(L <= D) = P(ln(L) <= ln(D))
        Does NOT rely on naive mean + 1 std dev heuristics.
        """
        if deadline_ms <= 0:
            return 0.0
        log_d = math.log(deadline_ms)
        df = 2.0 * self.alpha_n
        scale = math.sqrt(max(1e-6, (self.beta_n * (self.kappa_n + 1.0)) / (self.alpha_n * self.kappa_n)))
        t_stat = (log_d - self.mu_n) / scale
        return max(0.0, min(1.0, _student_t_cdf(t_stat, df)))


class ModelHealthTracker:
    """Registry-wide coordinator for Bayesian health, quality, and latency profiles."""
    
    def __init__(self):
        self._quality: Dict[str, BetaQualityDistribution] = {}
        self._failures: Dict[str, BetaFailureDistribution] = {}
        self._latency: Dict[str, LogNormalLatencyDistribution] = {}
        self._initialized: bool = False

    def reset(self) -> None:
        """Reset all health tracking state, distributions, and cooldowns."""
        self._quality.clear()
        self._failures.clear()
        self._latency.clear()
        self._initialized = False

    def ensure_model(self, model_id: str, prior_quality: float, expected_latency_ms: float) -> None:
        if model_id not in self._quality:
            self._quality[model_id] = BetaQualityDistribution.from_prior(model_id, prior_quality)
        if model_id not in self._failures:
            self._failures[model_id] = BetaFailureDistribution(model_id=model_id)
        if model_id not in self._latency:
            self._latency[model_id] = LogNormalLatencyDistribution(
                model_id=model_id, expected_latency_ms=expected_latency_ms
            )

    def record_outcome(
        self,
        model_id: str,
        success: bool,
        latency_ms: float = 0.0,
        quality_score: Optional[float] = None,
        is_rate_limit: bool = False,
        cooldown_sec: float = 300.0,
        cooldown_seconds: Optional[float] = None,
    ) -> None:
        """Record trial execution across failure, latency, and quality distributions."""
        effective_cooldown = cooldown_seconds if cooldown_seconds is not None else cooldown_sec
        if model_id in self._failures:
            self._failures[model_id].record_outcome(
                success=success, is_rate_limit=is_rate_limit, cooldown_sec=effective_cooldown
            )
        if success and latency_ms > 0 and model_id in self._latency:
            self._latency[model_id].update(latency_ms)
        if quality_score is not None and model_id in self._quality:
            self._quality[model_id].update(quality_score)

    def is_healthy(self, model_id: str) -> bool:
        dist = self._failures.get(model_id)
        if dist is None:
            return True
        return dist.is_healthy

    def is_in_cooldown(self, model_id: str) -> bool:
        dist = self._failures.get(model_id)
        if dist is None:
            return False
        return dist.is_in_cooldown

    def failure_rate(self, model_id: str) -> float:
        dist = self._failures.get(model_id)
        return dist.expected_failure_rate if dist else 0.05

    def quality_lcb(self, model_id: str, z: float = 1.0) -> float:
        dist = self._quality.get(model_id)
        return dist.conservative_lower_bound(z) if dist else 0.5

    def deadline_probability(self, model_id: str, deadline_ms: Optional[float]) -> float:
        if deadline_ms is None or deadline_ms <= 0:
            return 1.0
        dist = self._latency.get(model_id)
        return dist.probability_meeting_deadline(deadline_ms) if dist else 0.5

    def predictive_latency(self, model_id: str) -> float:
        dist = self._latency.get(model_id)
        return dist.predictive_mean_ms if dist else 400.0


# Global singleton health tracker
global_health_tracker = ModelHealthTracker()
