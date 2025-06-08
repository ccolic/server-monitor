"""Tests for health endpoints and metrics."""

import pytest

from server_monitor.health import HealthCheckServer
from server_monitor.metrics import metrics


@pytest.mark.asyncio
async def test_health_check_endpoint():
    """Test the health check endpoint."""
    server = HealthCheckServer(8081)

    class MockRequest:
        def __init__(self):
            pass

    response = await server.health_check(MockRequest())
    assert response.status == 200
    assert response.content_type == "application/json"


@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint():
    """Test the Prometheus metrics endpoint."""
    # Add some test data
    metrics.record_check_time("test_endpoint", 0.5, True)
    metrics.record_error("test_endpoint")

    server = HealthCheckServer(8081)

    class MockRequest:
        def __init__(self):
            pass

    response = await server.get_prometheus_metrics(MockRequest())
    assert response.status == 200
    assert response.content_type == "text/plain"

    # The response should be text containing Prometheus metrics
    assert hasattr(response, "text")


@pytest.mark.asyncio
async def test_json_metrics_endpoint():
    """Test the JSON metrics endpoint."""
    # Add some test data
    metrics.record_check_time("test_endpoint", 0.5, True)
    metrics.record_error("test_endpoint")

    server = HealthCheckServer(8081)

    class MockRequest:
        def __init__(self):
            pass

    response = await server.get_json_metrics(MockRequest())
    assert response.status == 200
    assert response.content_type == "application/json"


@pytest.mark.asyncio
async def test_status_endpoint():
    """Test the status endpoint."""
    server = HealthCheckServer(8081)

    class MockRequest:
        def __init__(self):
            pass

    response = await server.get_status(MockRequest())
    assert response.status == 200
    assert response.content_type == "application/json"


def test_prometheus_metrics_format():
    """Test that Prometheus metrics are correctly formatted."""
    # Reset metrics and add test data
    metrics.reset_metrics()
    metrics.record_check_time("http_example", 0.5, True)
    metrics.record_check_time("http_example", 1.2, True)
    metrics.record_error("api_service")

    prometheus_output = metrics.get_prometheus_metrics()

    # Check that it contains expected Prometheus format elements
    assert "# HELP" in prometheus_output
    assert "# TYPE" in prometheus_output
    assert "server_monitor_checks_total" in prometheus_output
    assert "server_monitor_response_time_seconds" in prometheus_output
    assert "server_monitor_endpoint_up" in prometheus_output
    assert "server_monitor_uptime_seconds" in prometheus_output

    # Check for specific endpoint labels
    assert 'endpoint="http_example"' in prometheus_output
    assert 'endpoint="api_service"' in prometheus_output
    assert 'status="success"' in prometheus_output
    assert 'status="failure"' in prometheus_output


def test_prometheus_content_type():
    """Test that the Prometheus content type is correct."""
    content_type = metrics.get_prometheus_content_type()
    assert content_type.startswith("text/plain")
    assert "version=0.0.4" in content_type
    assert "charset=utf-8" in content_type
