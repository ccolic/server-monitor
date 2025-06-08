"""Tests for metrics module."""

import pytest

from server_monitor.metrics import PerformanceMetrics


def test_metrics_initialization():
    """Test metrics initialization."""
    metrics = PerformanceMetrics(max_history=100)
    assert metrics.max_history == 100
    assert len(metrics.check_times) == 0
    assert len(metrics.check_counts) == 0
    assert len(metrics.error_counts) == 0


def test_record_check_time():
    """Test recording check times."""
    metrics = PerformanceMetrics()

    metrics.record_check_time("test_endpoint", 1.5)
    metrics.record_check_time("test_endpoint", 2.0)
    metrics.record_check_time("test_endpoint", 1.0)

    assert metrics.check_counts["test_endpoint"] == 3
    assert len(metrics.check_times["test_endpoint"]) == 3
    assert metrics.get_avg_response_time("test_endpoint") == 1.5


def test_record_error():
    """Test recording errors."""
    metrics = PerformanceMetrics()

    metrics.record_error("test_endpoint")
    metrics.record_error("test_endpoint")

    assert metrics.error_counts["test_endpoint"] == 2


def test_success_rate():
    """Test success rate calculation."""
    metrics = PerformanceMetrics()

    # No checks yet - should be 100%
    assert metrics.get_success_rate("test_endpoint") == 1.0

    # 3 checks, 1 error = 66.67% success rate
    metrics.record_check_time("test_endpoint", 1.0)
    metrics.record_check_time("test_endpoint", 1.0)
    metrics.record_check_time("test_endpoint", 1.0)
    metrics.record_error("test_endpoint")

    success_rate = metrics.get_success_rate("test_endpoint")
    assert abs(success_rate - 0.6667) < 0.001


def test_metrics_summary():
    """Test metrics summary generation."""
    metrics = PerformanceMetrics()

    # Add some test data
    metrics.record_check_time("endpoint1", 1.0)
    metrics.record_check_time("endpoint1", 2.0)
    metrics.record_error("endpoint1")

    metrics.record_check_time("endpoint2", 0.5)

    summary = metrics.get_metrics_summary()

    assert summary["total_endpoints"] == 2
    assert summary["total_checks"] == 3
    assert summary["total_errors"] == 1
    assert "endpoint1" in summary["endpoints"]
    assert "endpoint2" in summary["endpoints"]

    endpoint1_data = summary["endpoints"]["endpoint1"]
    assert endpoint1_data["checks"] == 2
    assert endpoint1_data["errors"] == 1
    assert endpoint1_data["avg_response_time"] == 1.5
    assert endpoint1_data["success_rate"] == 0.5


def test_reset_metrics():
    """Test metrics reset."""
    metrics = PerformanceMetrics()

    # Add some data
    metrics.record_check_time("test_endpoint", 1.0)
    metrics.record_error("test_endpoint")

    # Reset
    metrics.reset_metrics()

    assert len(metrics.check_times) == 0
    assert len(metrics.check_counts) == 0
    assert len(metrics.error_counts) == 0


@pytest.mark.asyncio
async def test_measure_check_context_manager():
    """Test the measure_check context manager."""
    metrics = PerformanceMetrics()

    async with metrics.measure_check("test_endpoint"):
        pass  # Simulate some work

    assert metrics.check_counts["test_endpoint"] == 1
    assert len(metrics.check_times["test_endpoint"]) == 1


@pytest.mark.asyncio
async def test_measure_check_with_exception():
    """Test the measure_check context manager with exception."""
    metrics = PerformanceMetrics()

    with pytest.raises(ValueError):
        async with metrics.measure_check("test_endpoint"):
            raise ValueError("Test error")

    # Should still record the check time and error
    assert metrics.check_counts["test_endpoint"] == 1
    assert metrics.error_counts["test_endpoint"] == 1
    assert len(metrics.check_times["test_endpoint"]) == 1
