"""Per-provider circuit breaker.

Closed: calls pass. After `threshold` provider-level failures the breaker
opens for `cooldown_s`; one probe call is allowed afterwards and closes the
breaker on success or restarts the cooldown on failure.
"""

from __future__ import annotations

import time


class CircuitBreaker:
    def __init__(
        self,
        threshold: int,
        cooldown_s: float,
        clock=time.monotonic,
    ):
        self.threshold = max(1, threshold)
        self.cooldown_s = max(0.0, cooldown_s)
        self._clock = clock
        self.failures = 0
        self.opened_at: float | None = None
        self.tripped_count = 0

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if self._clock() - self.opened_at >= self.cooldown_s:
            self.opened_at = None
            self.failures = max(0, self.threshold - 1)
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = self._clock()
            self.tripped_count += 1