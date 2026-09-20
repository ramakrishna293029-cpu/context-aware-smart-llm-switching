"""Per-model circuit breaker: skip recently failing deployments for a cooldown."""

import time
from collections import defaultdict
from typing import Dict


class ProviderCircuit:
    def __init__(self, fail_threshold: int = 2, cooldown_s: float = 30.0):
        self.fail_threshold = fail_threshold
        self.cooldown_s = cooldown_s
        self._fails: Dict[str, int] = defaultdict(int)
        self._open_until: Dict[str, float] = {}

    def allow(self, model_id: str) -> bool:
        until = self._open_until.get(model_id)
        if until is None:
            return True
        if time.monotonic() < until:
            return False
        self._open_until.pop(model_id, None)
        self._fails[model_id] = 0
        return True

    def success(self, model_id: str) -> None:
        self._fails[model_id] = 0
        self._open_until.pop(model_id, None)

    def failure(self, model_id: str) -> None:
        self._fails[model_id] += 1
        if self._fails[model_id] >= self.fail_threshold:
            self._open_until[model_id] = time.monotonic() + self.cooldown_s

    def reset(self) -> None:
        self._fails.clear()
        self._open_until.clear()


circuits = ProviderCircuit()
