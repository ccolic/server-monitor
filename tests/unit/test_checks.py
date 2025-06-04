"""Tests for check implementations."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from server_monitor.checks import (
    BaseCheck,
    CheckStatus,
    HTTPCheck,
    TCPCheck,
    TLSCheck,
    create_check,
)
from server_monitor.config import (
    CheckType,
    EndpointConfig,
    HTTPCheckConfig,
    TCPCheckConfig,
    TLSCheckConfig,
)
from server_monitor.database import CheckResult


def test_create_check():
    """Test check factory function."""
    # HTTP check
    http_config = EndpointConfig(
        name="Test HTTP",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(
            url="https://example.com", method="GET", timeout=30, expected_status=200
        ),
    )
    http_check = create_check(http_config)
    assert isinstance(http_check, HTTPCheck)

    # TCP check
    tcp_config = EndpointConfig(
        name="Test TCP",
        type=CheckType.TCP,
        interval=120,
        tcp=TCPCheckConfig(host="example.com", port=80, timeout=10),
    )
    tcp_check = create_check(tcp_config)
    assert isinstance(tcp_check, TCPCheck)

    # TLS check
    tls_config = EndpointConfig(
        name="Test TLS",
        type=CheckType.TLS,
        interval=86400,
        tls=TLSCheckConfig(
            host="example.com", port=443, timeout=30, cert_expiry_warning_days=14
        ),
    )
    tls_check = create_check(tls_config)
    assert isinstance(tls_check, TLSCheck)


@pytest.mark.asyncio
async def test_http_check_success():
    """Test successful HTTP check."""
    config = EndpointConfig(
        name="Test HTTP",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(
            url="https://example.com", method="GET", timeout=30, expected_status=200
        ),
    )

    check = HTTPCheck(config)

    # Mock the HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "Example Domain"
    mock_response.content = b"Example Domain"

    # Mock the client context manager
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.request.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await check.execute()

    assert result.status == CheckStatus.SUCCESS
    assert result.endpoint_name == "Test HTTP"
    assert result.check_type == "http"
    assert result.details["status_code"] == 200
    assert result.details["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_http_check_failure():
    """Test failed HTTP check due to unexpected status code."""
    config = EndpointConfig(
        name="Test HTTP",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(
            url="https://example.com", method="GET", timeout=30, expected_status=200
        ),
    )

    check = HTTPCheck(config)

    # Mock the HTTP response with a failure status code
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Server Error"
    mock_response.content = b"Server Error"

    # Mock the client context manager
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.request.return_value = mock_response

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await check.execute()

    assert result.status == CheckStatus.FAILURE
    assert result.endpoint_name == "Test HTTP"
    assert result.check_type == "http"
    assert result.details["status_code"] == 500
    assert "expected_status" in result.details


@pytest.mark.asyncio
async def test_tcp_check_success():
    """Test successful TCP check."""
    config = EndpointConfig(
        name="Test TCP",
        type=CheckType.TCP,
        interval=120,
        tcp=TCPCheckConfig(host="example.com", port=80, timeout=10),
    )

    check = TCPCheck(config)

    # Mock successful connection
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("asyncio.wait_for", return_value=(mock_reader, mock_writer)):
            result = await check.execute()

    assert result.status == CheckStatus.SUCCESS
    assert result.endpoint_name == "Test TCP"
    assert result.check_type == "tcp"
    assert result.details["host"] == "example.com"
    assert result.details["port"] == 80


@pytest.mark.asyncio
async def test_tcp_check_timeout():
    """Test TCP check with connection timeout."""
    config = EndpointConfig(
        name="Test TCP",
        type=CheckType.TCP,
        interval=120,
        tcp=TCPCheckConfig(host="example.com", port=80, timeout=10),
    )

    check = TCPCheck(config)

    # Mock connection timeout
    with patch("asyncio.open_connection", return_value=(AsyncMock(), AsyncMock())):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await check.execute()

    assert result.status == CheckStatus.FAILURE
    assert result.endpoint_name == "Test TCP"
    assert result.check_type == "tcp"
    assert "timeout" in result.details


@pytest.mark.asyncio
async def test_tls_check_success():
    """Test successful TLS check."""
    config = EndpointConfig(
        name="Test TLS",
        type=CheckType.TLS,
        interval=86400,
        tls=TLSCheckConfig(
            host="example.com", port=443, timeout=30, cert_expiry_warning_days=14
        ),
    )

    check = TLSCheck(config)

    # Create a mock certificate
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "example.com"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    cert_der = cert.public_bytes(serialization.Encoding.DER)

    # Mock the SSL connection
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_transport = MagicMock()
    mock_transport.get_extra_info.return_value = [cert_der]
    mock_writer.transport = mock_transport

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("asyncio.wait_for", return_value=(mock_reader, mock_writer)):
            with patch("x509.load_der_x509_certificate", return_value=cert):
                result = await check.execute()

    assert result.status == CheckStatus.SUCCESS
    assert result.endpoint_name == "Test TLS"
    assert result.check_type == "tls"
    assert result.details["host"] == "example.com"
    assert result.details["port"] == 443
    assert "days_until_expiry" in result.details
