"""Performance metrics and monitoring utilities."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

import structlog
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

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

        # Create a custom registry to avoid conflicts
        self.registry = CollectorRegistry()
        # Prometheus metrics
        self._setup_prometheus_metrics()

    def _setup_prometheus_metrics(self) -> None:
        """Initialize Prometheus metrics."""
        self.checks_total = Counter(
            "server_monitor_checks_total",
            "Total number of health checks performed",
            ["endpoint", "status"],
            registry=self.registry,
        )

        self.response_time_seconds = Histogram(
            "server_monitor_response_time_seconds",
            "Response time of health checks in seconds",
            ["endpoint"],
            buckets=(
                0.01,
                0.025,
                0.05,
                0.075,
                0.1,
                0.25,
                0.5,
                0.75,
                1.0,
                2.5,
                5.0,
                7.5,
                10.0,
                float("inf"),
            ),
            registry=self.registry,
        )

        self.endpoint_up = Gauge(
            "server_monitor_endpoint_up",
            "Whether the endpoint is up (1) or down (0)",
            ["endpoint"],
            registry=self.registry,
        )

        self.monitor_uptime_seconds = Gauge(
            "server_monitor_uptime_seconds",
            "Monitor uptime in seconds",
            registry=self.registry,
        )

        self.endpoint_success_rate = Gauge(
            "server_monitor_endpoint_success_rate",
            "Success rate of endpoint checks (0-1)",
            ["endpoint"],
            registry=self.registry,
        )

        self.endpoint_avg_response_time = Gauge(
            "server_monitor_endpoint_avg_response_time_seconds",
            "Average response time for endpoint in seconds",
            ["endpoint"],
            registry=self.registry,
        )

    def record_check_time(
        self, endpoint: str, duration: float, success: bool = True
    ) -> None:
        """Record check execution time."""
        self.check_times[endpoint].append(duration)
        self.check_counts[endpoint] += 1

        # If it's a failure, also increment error count
        if not success:
            self.error_counts[endpoint] += 1

        # Update Prometheus metrics
        status = "success" if success else "failure"
        self.checks_total.labels(endpoint=endpoint, status=status).inc()
        self.response_time_seconds.labels(endpoint=endpoint).observe(duration)
        self.endpoint_up.labels(endpoint=endpoint).set(1 if success else 0)

        # Update derived metrics
        self._update_endpoint_metrics(endpoint)

    def record_error(self, endpoint: str) -> None:
        """Record an error for an endpoint."""
        self.error_counts[endpoint] += 1
        self.checks_total.labels(endpoint=endpoint, status="failure").inc()
        self.endpoint_up.labels(endpoint=endpoint).set(0)

        # Update derived metrics
        self._update_endpoint_metrics(endpoint)

    def _update_endpoint_metrics(self, endpoint: str) -> None:
        """Update derived Prometheus metrics for an endpoint."""
        # Update success rate
        success_rate = self.get_success_rate(endpoint)
        self.endpoint_success_rate.labels(endpoint=endpoint).set(success_rate)

        # Update average response time
        avg_time = self.get_avg_response_time(endpoint)
        self.endpoint_avg_response_time.labels(endpoint=endpoint).set(avg_time)

        # Update monitor uptime
        uptime = (datetime.now() - self.last_reset).total_seconds()
        self.monitor_uptime_seconds.set(uptime)

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

    def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        # Ensure all current metrics are up to date
        uptime = (datetime.now() - self.last_reset).total_seconds()
        self.monitor_uptime_seconds.set(uptime)

        # Update all endpoint metrics
        for endpoint in self.check_counts:
            self._update_endpoint_metrics(endpoint)

        return generate_latest(self.registry).decode("utf-8")

    def get_prometheus_content_type(self) -> str:
        """Get the content type for Prometheus metrics."""
        return CONTENT_TYPE_LATEST

    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self.check_times.clear()
        self.check_counts.clear()
        self.error_counts.clear()
        self.last_reset = datetime.now()

        # Reset Prometheus metrics (they'll be recreated on next update)
        self.registry = CollectorRegistry()
        self._setup_prometheus_metrics()

        logger.info("Performance metrics reset")

    @asynccontextmanager
    async def measure_check(self, endpoint: str) -> AsyncIterator[None]:
        """Context manager to measure check execution time."""
        start_time = time.time()
        success = True
        try:
            yield
        except Exception:
            success = False
            raise
        finally:
            duration = time.time() - start_time
            self.record_check_time(endpoint, duration, success)


# Global metrics instance
metrics = PerformanceMetrics()
