"""Small in-memory rate limiter (sliding window per client IP and bucket).

Good for a single server process. If you scale to several instances, move this
to a shared store such as Redis so limits apply across all of them.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str, int], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def check(self, client: str, bucket: str, limits: list[tuple[int, int]]) -> int | None:
        """limits = [(max_requests, window_seconds), ...]. Returns None if allowed,
        otherwise the number of seconds to wait."""
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            for max_requests, window in limits:
                q = self._hits[(client, bucket, window)]
                while q and q[0] <= now - window:
                    q.popleft()
                if len(q) >= max_requests:
                    return max(1, int(q[0] + window - now) + 1)
            for _, window in limits:
                self._hits[(client, bucket, window)].append(now)
        return None

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < 300:
            return
        self._last_sweep = now
        for key in list(self._hits):
            q = self._hits[key]
            while q and q[0] <= now - key[2]:
                q.popleft()
            if not q:
                del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
