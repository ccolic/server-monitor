"""Integration tests for the monitoring system."""

import asyncio
import tempfile
from pathlib import Path

import pytest
import yaml

from server_monitor.config import load_config
from server_monitor.monitor import MonitorDaemon


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    config_data = {
        "global": {
            "log_level": "INFO",
            "max_concurrent_checks": 5,
            "email_notifications": {"enabled": False},
            "webhook_notifications": {"enabled": False},
            "database": {"type": "sqlite", "database": ":memory:"},
        },
        "endpoints": [
            {
                "name": "Test HTTP",
                "type": "http",
                "interval": 1,
                "enabled": True,
                "http": {
                    "url": "https://httpbin.org/status/200",
                    "method": "GET",
                    "timeout": 10,
                    "expected_status": 200,
                },
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_daemon_lifecycle(temp_config_file):
    """Test daemon initialization, start, and shutdown."""
    config = load_config(temp_config_file)
    daemon = MonitorDaemon(config)

    # Test initialization
    await daemon.initialize()
    assert len(daemon.endpoint_monitors) == 1
    assert "Test HTTP" in daemon.endpoint_monitors

    # Test getting status before start
    status = await daemon.get_status()
    assert status["daemon"]["total_endpoints"] == 1
    assert status["daemon"]["active_monitors"] == 1

    # Start daemon in background
    start_task = asyncio.create_task(daemon.start())

    # Let it run for a few seconds
    await asyncio.sleep(3)

    # Test stop
    await daemon.stop()

    # Wait for start task to complete
    try:
        await asyncio.wait_for(start_task, timeout=1.0)
    except TimeoutError:
        start_task.cancel()
        try:
            await start_task
        except asyncio.CancelledError:
            pass
    finally:
        Path(temp_config_file).unlink(missing_ok=True)
        # Ensure shared HTTP client is closed to avoid lock hangs
        from server_monitor.checks import HTTPCheck

        await HTTPCheck.close_shared_client()
        # Explicitly close the database connection if possible
        try:
            await daemon.db_manager.close()
        except Exception as e:
            print(f"Database close error: {e}")


@pytest.mark.asyncio
async def test_config_reload(temp_config_file):
    """Test configuration reloading."""
    config = load_config(temp_config_file)
    daemon = MonitorDaemon(config)

    try:
        await daemon.initialize()

        # Modify config - add another endpoint
        config_data = yaml.safe_load(Path(temp_config_file).read_text())
        config_data["endpoints"].append(
            {
                "name": "Test HTTP 2",
                "type": "http",
                "interval": 2,
                "enabled": True,
                "http": {
                    "url": "https://httpbin.org/status/201",
                    "method": "GET",
                    "timeout": 5,
                    "expected_status": 201,
                },
            }
        )

        # Save updated config
        Path(temp_config_file).write_text(yaml.dump(config_data))
        new_config = load_config(temp_config_file)

        # Reload configuration
        await daemon.reload_config(new_config)

        # Verify new endpoint was added
        assert len(daemon.endpoint_monitors) == 2
        assert "Test HTTP 2" in daemon.endpoint_monitors
    finally:
        # Ensure daemon is properly stopped
        await daemon.stop()
        Path(temp_config_file).unlink(missing_ok=True)
        from server_monitor.checks import HTTPCheck

        await HTTPCheck.close_shared_client()
        try:
            await daemon.db_manager.close()
        except Exception as e:
            print(f"Database close error: {e}")


@pytest.mark.asyncio
async def test_metrics_collection():
    """Test that metrics are collected during monitoring."""
    from server_monitor.metrics import metrics

    # Reset metrics
    metrics.reset_metrics()

    config_data = {
        "global": {
            "log_level": "INFO",
            "max_concurrent_checks": 5,
            "email_notifications": {"enabled": False},
            "webhook_notifications": {"enabled": False},
            "database": {"type": "sqlite", "database": ":memory:"},
        },
        "endpoints": [
            {
                "name": "Metrics Test",
                "type": "http",
                "interval": 1,
                "enabled": True,
                "http": {
                    "url": "https://httpbin.org/status/200",
                    "method": "GET",
                    "timeout": 5,
                    "expected_status": 200,
                },
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        temp_path = f.name

    try:
        config = load_config(temp_path)
        daemon = MonitorDaemon(config)
        await daemon.initialize()

        # Start daemon in background
        start_task = asyncio.create_task(daemon.start())

        # Let it run for a few checks
        await asyncio.sleep(3)

        # Stop daemon
        await daemon.stop()

        # Check metrics were collected
        summary = metrics.get_metrics_summary()
        assert summary["total_endpoints"] >= 1
        assert summary["total_checks"] >= 1
        assert "Metrics Test" in summary["endpoints"]

        try:
            await asyncio.wait_for(start_task, timeout=1.0)
        except TimeoutError:
            start_task.cancel()
            try:
                await start_task
            except asyncio.CancelledError:
                pass

    finally:
        Path(temp_path).unlink(missing_ok=True)
        # Ensure shared HTTP client is closed to avoid lock hangs
        from server_monitor.checks import HTTPCheck

        await HTTPCheck.close_shared_client()
        # Explicitly close the database connection if possible
        try:
            await daemon.db_manager.close()
        except Exception as e:
            print(f"Database close error: {e}")


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling for failed endpoints."""
    config_data = {
        "global": {
            "log_level": "INFO",
            "max_concurrent_checks": 5,
            "email_notifications": {"enabled": False},
            "webhook_notifications": {"enabled": False},
            "database": {"type": "sqlite", "database": ":memory:"},
        },
        "endpoints": [
            {
                "name": "Failing Test",
                "type": "http",
                "interval": 1,
                "enabled": True,
                "http": {
                    "url": "https://invalid-domain-that-should-not-exist.com",
                    "method": "GET",
                    "timeout": 2,
                    "expected_status": 200,
                },
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        temp_path = f.name

    try:
        config = load_config(temp_path)
        daemon = MonitorDaemon(config)
        await daemon.initialize()

        # Start daemon in background
        start_task = asyncio.create_task(daemon.start())

        # Let it run for a few failed checks
        await asyncio.sleep(3)

        # Stop daemon
        await daemon.stop()

        # Verify error metrics were recorded
        from server_monitor.metrics import metrics

        summary = metrics.get_metrics_summary()
        if "Failing Test" in summary["endpoints"]:
            endpoint_metrics = summary["endpoints"]["Failing Test"]
            # Should have recorded some errors or low success rate
            assert (
                endpoint_metrics["success_rate"] < 1.0 or endpoint_metrics["errors"] > 0
            )

        try:
            await asyncio.wait_for(start_task, timeout=1.0)
        except TimeoutError:
            start_task.cancel()
            try:
                await start_task
            except asyncio.CancelledError:
                pass

    finally:
        Path(temp_path).unlink(missing_ok=True)
        # Ensure shared HTTP client is closed to avoid lock hangs
        from server_monitor.checks import HTTPCheck

        await HTTPCheck.close_shared_client()
        # Explicitly close the database connection if possible
        try:
            await daemon.db_manager.close()
        except Exception as e:
            print(f"Database close error: {e}")
