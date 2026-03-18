from __future__ import annotations

from collections import defaultdict
from threading import Lock


class MetricsRegistry:
    """Tiny in-process metrics registry for health and diagnostics."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}
        self._timers: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "total": 0.0, "max": 0.0})

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += int(amount)

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = float(value)

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            timer = self._timers[name]
            timer["count"] += 1
            timer["total"] += float(seconds)
            timer["max"] = max(timer["max"], float(seconds))

    def snapshot(self) -> dict:
        with self._lock:
            timers = {
                name: {
                    "count": int(values["count"]),
                    "avg_seconds": round(values["total"] / values["count"], 4) if values["count"] else 0.0,
                    "max_seconds": round(values["max"], 4),
                }
                for name, values in self._timers.items()
            }
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timers": timers,
            }
