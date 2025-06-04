"""Tests for check implementations."""

from server_monitor.checks import create_check
from server_monitor.config import CheckType, EndpointConfig, HTTPCheckConfig, TCPCheckConfig, TLSCheckConfig

def test_create_check():
    # HTTP check
    http_config = EndpointConfig(
        name="Test HTTP",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(url="https://example.com", method="GET", timeout=30, expected_status=200),
    )
    http_check = create_check(http_config)
    assert http_check.__class__.__name__ == "HTTPCheck"

    # TCP check
    tcp_config = EndpointConfig(
        name="Test TCP",
        type=CheckType.TCP,
        interval=120,
        tcp=TCPCheckConfig(host="example.com", port=80, timeout=10),
    )
    tcp_check = create_check(tcp_config)
    assert tcp_check.__class__.__name__ == "TCPCheck"

    # TLS check
    tls_config = EndpointConfig(
        name="Test TLS",
        type=CheckType.TLS,
        interval=86400,
        tls=TLSCheckConfig(host="example.com", port=443, timeout=30, cert_expiry_warning_days=14),
    )
    tls_check = create_check(tls_config)
    assert tls_check.__class__.__name__ == "TLSCheck"

# This file now only contains the factory overview test. All other tests are split into their own files.
