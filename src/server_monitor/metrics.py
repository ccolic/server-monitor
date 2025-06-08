"""Performance metrics and monitoring utilities."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class PerformanceMetrics:
    """Collect and track performance metrics."""

    def __init__(self, max_history: int = 1000) -> None:
        self.max_history = max_history
        self.check_times: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=max_history)
        )
        self.check_counts: dict[str, int] = defaultdict(int)
        self.error_counts: dict[str, int] = defaultdict(int)
        self.last_reset = datetime.now()

    def record_check_time(self, endpoint: str, duration: float) -> None:
        """Record check execution time."""
        self.check_times[endpoint].append(duration)
        self.check_counts[endpoint] += 1

    def record_error(self, endpoint: str) -> None:
        """Record an error for an endpoint."""
        self.error_counts[endpoint] += 1

    def get_avg_response_time(self, endpoint: str) -> float:
        """Get average response time for an endpoint."""
        times = self.check_times.get(endpoint, deque())
        return sum(times) / len(times) if times else 0.0

    def get_success_rate(self, endpoint: str) -> float:
        """Get success rate for an endpoint."""
        total_checks = self.check_counts.get(endpoint, 0)
        errors = self.error_counts.get(endpoint, 0)
        if total_checks == 0:
            return 1.0
        return (total_checks - errors) / total_checks

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get a summary of all metrics."""
        endpoints: dict[str, dict[str, Any]] = {}

        for endpoint in self.check_counts:
            endpoints[endpoint] = {
                "checks": self.check_counts[endpoint],
                "errors": self.error_counts[endpoint],
                "avg_response_time": self.get_avg_response_time(endpoint),
                "success_rate": self.get_success_rate(endpoint),
            }

        summary = {
            "total_endpoints": len(self.check_counts),
            "total_checks": sum(self.check_counts.values()),
            "total_errors": sum(self.error_counts.values()),
            "uptime": (datetime.now() - self.last_reset).total_seconds(),
            "endpoints": endpoints,
        }

        return summary

    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self.check_times.clear()
        self.check_counts.clear()
        self.error_counts.clear()
        self.last_reset = datetime.now()
        logger.info("Performance metrics reset")

    @asynccontextmanager
    async def measure_check(self, endpoint: str) -> AsyncIterator[None]:
        """Context manager to measure check execution time."""
        start_time = time.time()
        try:
            yield
        except Exception:
            self.record_error(endpoint)
            raise
        finally:
            duration = time.time() - start_time
            self.record_check_time(endpoint, duration)


# Global metrics instance
metrics = PerformanceMetrics()
