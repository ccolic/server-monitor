"""Tests for configuration module."""

import os
import tempfile

import pytest
import yaml

from server_monitor.config import (
    CheckType,
    DatabaseType,
    EndpointConfig,
    HTTPCheckConfig,
    MonitorConfig,
    TCPCheckConfig,
    TLSCheckConfig,
    load_config,
)


def test_load_config():
    """Test loading configuration from YAML file."""
    # Create a temporary config file
    config_data = {
        "global": {
            "log_level": "INFO",
            "max_concurrent_checks": 5,
            "database": {"type": "sqlite", "database": ":memory:"},
        },
        "endpoints": [
            {
                "name": "Test HTTP",
                "type": "http",
                "interval": 60,
                "enabled": True,
                "http": {
                    "url": "https://example.com",
                    "method": "GET",
                    "timeout": 30,
                    "expected_status": 200,
                },
            }
        ],
    }

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = f.name

    try:
        # Load the config
        config = load_config(config_path)

        # Verify the config was loaded correctly
        assert config.global_config.log_level == "INFO"
        assert config.global_config.max_concurrent_checks == 5
        assert config.global_config.database.type == DatabaseType.SQLITE
        assert len(config.endpoints) == 1
        assert config.endpoints[0].name == "Test HTTP"
        assert config.endpoints[0].type == CheckType.HTTP
        assert config.endpoints[0].http.url == "https://example.com"
    finally:
        # Clean up
        os.unlink(config_path)


def test_http_config_validation():
    """Test HTTP config validation."""
    # Valid config
    http_config = HTTPCheckConfig(
        url="https://example.com", method="GET", timeout=30, expected_status=200
    )
    assert http_config.url == "https://example.com"

    # Valid config with status list
    http_config = HTTPCheckConfig(
        url="https://example.com",
        method="GET",
        timeout=30,
        expected_status=[200, 201, 204],
    )
    assert 200 in http_config.expected_status
    assert 201 in http_config.expected_status
    assert 204 in http_config.expected_status


def test_http_config_invalid_url():
    with pytest.raises(ValueError):
        HTTPCheckConfig(url="", method="GET", timeout=30, expected_status=200)


def test_http_config_invalid_method():
    with pytest.raises(ValueError):
        HTTPCheckConfig(
            url="https://example.com", method="INVALID", timeout=30, expected_status=200
        )


def test_tcp_config_validation():
    """Test TCP config validation."""
    # Valid config
    tcp_config = TCPCheckConfig(host="example.com", port=80, timeout=10)
    assert tcp_config.host == "example.com"
    assert tcp_config.port == 80


def test_tcp_config_invalid_port():
    with pytest.raises(ValueError):
        TCPCheckConfig(host="example.com", port=70000, timeout=10)


def test_tls_config_validation():
    """Test TLS config validation."""
    # Valid config
    tls_config = TLSCheckConfig(
        host="example.com", port=443, timeout=30, cert_expiry_warning_days=14
    )
    assert tls_config.host == "example.com"
    assert tls_config.cert_expiry_warning_days == 14


def test_tls_config_invalid_expiry_days():
    with pytest.raises(ValueError):
        TLSCheckConfig(
            host="example.com", port=443, timeout=30, cert_expiry_warning_days=-1
        )


def test_endpoint_config_validation():
    """Test endpoint config validation."""
    # HTTP endpoint
    http_endpoint = EndpointConfig(
        name="Test HTTP",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(
            url="https://example.com", method="GET", timeout=30, expected_status=200
        ),
    )
    assert http_endpoint.name == "Test HTTP"
    assert http_endpoint.type == CheckType.HTTP

    # TCP endpoint
    tcp_endpoint = EndpointConfig(
        name="Test TCP",
        type=CheckType.TCP,
        interval=120,
        tcp=TCPCheckConfig(host="example.com", port=80, timeout=10),
    )
    assert tcp_endpoint.name == "Test TCP"
    assert tcp_endpoint.type == CheckType.TCP

    # TLS endpoint
    tls_endpoint = EndpointConfig(
        name="Test TLS",
        type=CheckType.TLS,
        interval=86400,
        tls=TLSCheckConfig(
            host="example.com", port=443, timeout=30, cert_expiry_warning_days=14
        ),
    )
    assert tls_endpoint.name == "Test TLS"
    assert tls_endpoint.type == CheckType.TLS


def test_endpoint_config_validation_failure():
    """Test endpoint config validation failure."""
    # Missing HTTP config for HTTP check
    with pytest.raises(ValueError):
        EndpointConfig(
            name="Test HTTP",
            type=CheckType.HTTP,
            interval=60,
        )

    # Missing TCP config for TCP check
    with pytest.raises(ValueError):
        EndpointConfig(
            name="Test TCP",
            type=CheckType.TCP,
            interval=120,
        )

    # Missing TLS config for TLS check
    with pytest.raises(ValueError):
        EndpointConfig(
            name="Test TLS",
            type=CheckType.TLS,
            interval=86400,
        )


def test_monitor_config_missing_endpoints():
    # Should raise ValueError if endpoints is missing or empty
    with pytest.raises(ValueError):
        MonitorConfig(global_config=None, endpoints=None)
    with pytest.raises(ValueError):
        MonitorConfig(global_config=None, endpoints=[])


def test_load_config_invalid_file():
    # Should raise FileNotFoundError or OSError
    with pytest.raises((FileNotFoundError, OSError)):
        load_config("/no/such/file.yaml")
