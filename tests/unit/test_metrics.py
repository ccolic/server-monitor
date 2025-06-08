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


def test_prometheus_metrics_generation():
    """Test Prometheus metrics generation."""
    metrics = PerformanceMetrics()

    # Add some test data
    metrics.record_check_time("test_endpoint", 0.5, True)
    metrics.record_check_time("test_endpoint", 1.2, True)
    metrics.record_error("test_endpoint")

    prometheus_output = metrics.get_prometheus_metrics()

    # Check that it's a string with Prometheus format
    assert isinstance(prometheus_output, str)
    assert "# HELP" in prometheus_output
    assert "# TYPE" in prometheus_output
    assert "server_monitor_checks_total" in prometheus_output
    assert "server_monitor_response_time_seconds" in prometheus_output
    assert "server_monitor_endpoint_up" in prometheus_output


def test_prometheus_content_type():
    """Test Prometheus content type."""
    metrics = PerformanceMetrics()
    content_type = metrics.get_prometheus_content_type()

    assert content_type.startswith("text/plain")
    assert "version=0.0.4" in content_type


def test_prometheus_metrics_labels():
    """Test that Prometheus metrics include correct labels."""
    metrics = PerformanceMetrics()

    # Add different types of checks
    metrics.record_check_time("http_endpoint", 0.5, True)
    metrics.record_check_time("tcp_endpoint", 1.2, True)
    metrics.record_error("api_endpoint")

    prometheus_output = metrics.get_prometheus_metrics()

    # Check for endpoint labels
    assert 'endpoint="http_endpoint"' in prometheus_output
    assert 'endpoint="tcp_endpoint"' in prometheus_output
    assert 'endpoint="api_endpoint"' in prometheus_output

    # Check for status labels
    assert 'status="success"' in prometheus_output
    assert 'status="failure"' in prometheus_output


def test_record_check_time_with_success_parameter():
    """Test recording check times with explicit success parameter."""
    metrics = PerformanceMetrics()

    # Test successful check
    metrics.record_check_time("test_endpoint", 1.5, True)
    assert metrics.check_counts["test_endpoint"] == 1
    assert metrics.error_counts["test_endpoint"] == 0

    # Test failed check
    metrics.record_check_time("test_endpoint", 2.0, False)
    assert metrics.check_counts["test_endpoint"] == 2
    assert metrics.error_counts["test_endpoint"] == 1

    # Test default (should be True)
    metrics.record_check_time("test_endpoint", 1.0)
    assert metrics.check_counts["test_endpoint"] == 3
    assert metrics.error_counts["test_endpoint"] == 1
