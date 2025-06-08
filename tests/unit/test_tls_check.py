import ssl
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from server_monitor.checks import CheckStatus, TLSCheck
from server_monitor.config import CheckType, EndpointConfig, TLSCheckConfig


@pytest.mark.asyncio
async def test_tls_check_not_yet_valid():
    config = EndpointConfig(
        name="Test TLS Not Yet Valid",
        type=CheckType.TLS,
        interval=86400,
        tls=TLSCheckConfig(
            host="example.com", port=443, timeout=30, cert_expiry_warning_days=14
        ),
    )
    check = TLSCheck(config)
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "example.com")]
    )
    # Create a certificate that is not yet valid (starts tomorrow)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) + timedelta(days=1))  # Future date
        .not_valid_after(datetime.now(UTC) + timedelta(days=90))
        .sign(private_key, hashes.SHA256(), default_backend())
    )
    cert_der = cert.public_bytes(serialization.Encoding.DER)

    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.close = MagicMock()  # close() should not be async
    mock_writer.wait_closed = AsyncMock()  # wait_closed() should be async
    mock_transport = MagicMock()
    mock_transport.get_extra_info.return_value = [cert_der]
    mock_writer.transport = mock_transport

    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("asyncio.wait_for", return_value=(mock_reader, mock_writer)):
            with patch(
                "cryptography.x509.load_der_x509_certificate", return_value=cert
            ):
                result = await check.execute()

    assert result.status == CheckStatus.FAILURE
    assert result.details["host"] == "example.com"
    assert result.details["port"] == 443
    assert "Certificate is not yet valid" in result.error_message


@pytest.mark.asyncio
async def test_tls_check_multiple_certificates():
    config = EndpointConfig(
        name="Test TLS Multi Cert",
        type=CheckType.TLS,
        interval=86400,
        tls=TLSCheckConfig(
            host="example.com", port=443, timeout=30, cert_expiry_warning_days=14
        ),
    )
    check = TLSCheck(config)
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "example.com")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=90))
        .sign(private_key, hashes.SHA256(), default_backend())
    )
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    # Simulate multiple certs in the chain
    mock_reader = AsyncMock()
    mock_writer = AsyncMock()
    mock_writer.close = MagicMock()  # close() should not be async
    mock_writer.wait_closed = AsyncMock()  # wait_closed() should be async
    mock_transport = MagicMock()
    mock_transport.get_extra_info.return_value = [cert_der, cert_der]
    mock_writer.transport = mock_transport
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        with patch("asyncio.wait_for", return_value=(mock_reader, mock_writer)):
            with patch(
                "cryptography.x509.load_der_x509_certificate", return_value=cert
            ):
                result = await check.execute()
    assert result.status == CheckStatus.SUCCESS
    assert result.details["host"] == "example.com"
    assert result.details["port"] == 443


@pytest.mark.asyncio
async def test_tls_check_ssl_handshake_error():
    config = EndpointConfig(
        name="Test TLS Handshake Error",
        type=CheckType.TLS,
        interval=86400,
        tls=TLSCheckConfig(
            host="example.com", port=443, timeout=30, cert_expiry_warning_days=14
        ),
    )
    check = TLSCheck(config)
    with patch("asyncio.open_connection", side_effect=ssl.SSLError("handshake failed")):
        result = await check.execute()
    assert result.status == CheckStatus.FAILURE
    assert result.details["error_type"] == "SSLError"
