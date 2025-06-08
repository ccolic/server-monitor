"""Check implementations for different monitoring types."""

from __future__ import annotations

import asyncio
import re
import ssl
import time
from abc import ABC, abstractmethod

# Try to import UTC from datetime (Python 3.11+), else fallback to datetime.UTC
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone

    UTC = timezone.utc  # noqa: UP017
from datetime import datetime
from typing import Any

import httpx
import structlog
from cryptography import x509
from cryptography.hazmat.backends import default_backend

from .config import EndpointConfig, HTTPCheckConfig, TCPCheckConfig, TLSCheckConfig
from .database import CheckResult, CheckStatus

logger = structlog.get_logger(__name__)


class BaseCheck(ABC):
    """Base class for all check types."""

    def __init__(self, config: EndpointConfig) -> None:
        self.config = config
        self.name = config.name

    @abstractmethod
    async def execute(self) -> CheckResult:
        """Execute the check and return result."""
        pass

    def _create_result(
        self,
        status: CheckStatus,
        response_time: float | None = None,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> CheckResult:
        """Create a check result."""
        return CheckResult(
            endpoint_name=self.name,
            check_type=self.config.type.value,
            status=status,
            response_time=response_time,
            error_message=error_message,
            details=details or {},
            timestamp=datetime.now(UTC),
        )


class HTTPCheck(BaseCheck):
    """HTTP/HTTPS check implementation."""

    _shared_client: httpx.AsyncClient | None = None
    _client_lock = asyncio.Lock()

    def __init__(self, config: EndpointConfig) -> None:
        super().__init__(config)
        if not config.http:
            raise ValueError("HTTP configuration is required for HTTP checks")
        self.http_config: HTTPCheckConfig = config.http

    @classmethod
    async def get_shared_client(cls) -> httpx.AsyncClient:
        """Get or create shared HTTP client."""
        if cls._shared_client is None:
            async with cls._client_lock:
                if cls._shared_client is None:
                    cls._shared_client = httpx.AsyncClient(
                        timeout=30.0,  # Default timeout
                        follow_redirects=True,
                        limits=httpx.Limits(
                            max_connections=100, max_keepalive_connections=20
                        ),
                    )
        return cls._shared_client

    @classmethod
    async def close_shared_client(cls) -> None:
        """Close shared HTTP client."""
        if cls._shared_client:
            await cls._shared_client.aclose()
            cls._shared_client = None

    @classmethod
    def reset_shared_client(cls) -> None:
        """Reset shared client - mainly for testing."""
        cls._shared_client = None

    async def execute(self) -> CheckResult:
        """Execute HTTP check."""
        start_time = time.time()

        try:
            # Use async context manager for httpx client to ensure proper mocking in tests
            async with httpx.AsyncClient(
                timeout=self.http_config.timeout,
                verify=self.http_config.verify_ssl,
                follow_redirects=self.http_config.follow_redirects,
            ) as client:
                response = await client.request(
                    method=self.http_config.method,
                    url=self.http_config.url,
                    headers=self.http_config.headers,
                )

            response_time = time.time() - start_time

            # Check status code
            expected_status = self.http_config.expected_status
            if isinstance(expected_status, int):
                expected_status = [expected_status]

            if response.status_code not in expected_status:
                logger.warning(
                    "HTTP status code mismatch",
                    endpoint=self.name,
                    method=self.http_config.method,
                    url=self.http_config.url,
                    status_code=response.status_code,
                    expected_status=self.http_config.expected_status,
                    response_time_ms=round(response_time * 1000, 2),
                )
                return self._create_result(
                    status=CheckStatus.FAILURE,
                    response_time=response_time,
                    error_message=f"HTTP {response.status_code}: Expected {self.http_config.expected_status}",
                    details={
                        "status_code": response.status_code,
                        "expected_status": self.http_config.expected_status,
                        "url": self.http_config.url,
                        "method": self.http_config.method,
                    },
                )

            # Check content if configured
            if self.http_config.content_match:
                try:
                    content = response.text
                    if self.http_config.content_regex:
                        if not re.search(self.http_config.content_match, content):
                            logger.warning(
                                "HTTP content regex mismatch",
                                endpoint=self.name,
                                method=self.http_config.method,
                                url=self.http_config.url,
                                status_code=response.status_code,
                                content_match=self.http_config.content_match,
                                response_time_ms=round(response_time * 1000, 2),
                            )
                            return self._create_result(
                                status=CheckStatus.FAILURE,
                                response_time=response_time,
                                error_message=f"Content regex '{self.http_config.content_match}' not found",
                                details={
                                    "status_code": response.status_code,
                                    "content_match": self.http_config.content_match,
                                    "content_regex": True,
                                    "url": self.http_config.url,
                                },
                            )
                    else:
                        if self.http_config.content_match not in content:
                            logger.warning(
                                "HTTP content mismatch",
                                endpoint=self.name,
                                method=self.http_config.method,
                                url=self.http_config.url,
                                status_code=response.status_code,
                                content_match=self.http_config.content_match,
                                response_time_ms=round(response_time * 1000, 2),
                            )
                            return self._create_result(
                                status=CheckStatus.FAILURE,
                                response_time=response_time,
                                error_message=f"Content '{self.http_config.content_match}' not found",
                                details={
                                    "status_code": response.status_code,
                                    "content_match": self.http_config.content_match,
                                    "content_regex": False,
                                    "url": self.http_config.url,
                                },
                            )
                except re.error as e:
                    response_time = time.time() - start_time
                    logger.error(
                        "HTTP regex pattern error",
                        endpoint=self.name,
                        url=self.http_config.url,
                        content_match=self.http_config.content_match,
                        error=str(e),
                        response_time_ms=round(response_time * 1000, 2),
                    )
                    return self._create_result(
                        status=CheckStatus.ERROR,
                        response_time=response_time,
                        error_message=f"Invalid regex pattern: {str(e)}",
                        details={
                            "url": self.http_config.url,
                            "error_type": "PatternError",
                            "content_match": self.http_config.content_match,
                        },
                    )

            result = self._create_result(
                status=CheckStatus.SUCCESS,
                response_time=response_time,
                details={
                    "status_code": response.status_code,
                    "url": self.http_config.url,
                    "method": self.http_config.method,
                    "content_length": len(response.content),
                },
            )

            # Log successful HTTP request
            logger.info(
                "HTTP check completed",
                endpoint=self.name,
                method=self.http_config.method,
                url=self.http_config.url,
                status_code=response.status_code,
                response_time_ms=round(response_time * 1000, 2),
            )

            return result

        except httpx.TimeoutException as e:
            response_time = time.time() - start_time
            logger.warning(
                "HTTP timeout",
                endpoint=self.name,
                method=self.http_config.method,
                url=self.http_config.url,
                timeout=self.http_config.timeout,
                response_time_ms=round(response_time * 1000, 2),
                error=str(e),
            )
            return self._create_result(
                status=CheckStatus.FAILURE,
                response_time=response_time,
                error_message=f"HTTP request timeout after {self.http_config.timeout}s",
                details={
                    "url": self.http_config.url,
                    "timeout": self.http_config.timeout,
                    "error_type": "TimeoutError",
                },
            )

        except httpx.ConnectError as e:
            response_time = time.time() - start_time
            logger.warning(
                "HTTP connection error",
                endpoint=self.name,
                method=self.http_config.method,
                url=self.http_config.url,
                response_time_ms=round(response_time * 1000, 2),
                error=str(e),
            )
            return self._create_result(
                status=CheckStatus.FAILURE,
                response_time=response_time,
                error_message=f"Connection error: {str(e)}",
                details={
                    "url": self.http_config.url,
                    "error_type": "ConnectionError",
                },
            )

        except httpx.NetworkError as e:
            response_time = time.time() - start_time
            logger.error(
                "HTTP network error",
                endpoint=self.name,
                method=self.http_config.method,
                url=self.http_config.url,
                response_time_ms=round(response_time * 1000, 2),
                error=str(e),
            )
            return self._create_result(
                status=CheckStatus.ERROR,
                response_time=response_time,
                error_message=str(e),
                details={"url": self.http_config.url, "error_type": "NetworkError"},
            )

        except Exception as e:
            response_time = time.time() - start_time
            logger.error(
                "HTTP general error",
                endpoint=self.name,
                method=self.http_config.method,
                url=self.http_config.url,
                response_time_ms=round(response_time * 1000, 2),
                error_type=type(e).__name__,
                error=str(e),
            )
            return self._create_result(
                status=CheckStatus.ERROR,
                response_time=response_time,
                error_message=str(e),
                details={"url": self.http_config.url, "error_type": type(e).__name__},
            )


class TCPCheck(BaseCheck):
    """TCP connection check implementation."""

    def __init__(self, config: EndpointConfig) -> None:
        super().__init__(config)
        if not config.tcp:
            raise ValueError("TCP configuration is required for TCP checks")
        self.tcp_config: TCPCheckConfig = config.tcp

    async def execute(self) -> CheckResult:
        """Execute TCP check."""
        start_time = time.time()

        try:
            # Create connection with timeout
            future = asyncio.open_connection(
                host=self.tcp_config.host, port=self.tcp_config.port
            )

            reader, writer = await asyncio.wait_for(
                future, timeout=self.tcp_config.timeout
            )

            response_time = time.time() - start_time

            # Close connection
            writer.close()
            await writer.wait_closed()

            result = self._create_result(
                status=CheckStatus.SUCCESS,
                response_time=response_time,
                details={"host": self.tcp_config.host, "port": self.tcp_config.port},
            )

            # Log successful TCP connection
            logger.info(
                "TCP check completed",
                endpoint=self.name,
                host=self.tcp_config.host,
                port=self.tcp_config.port,
                response_time_ms=round(response_time * 1000, 2),
            )

            return result

        except TimeoutError:
            response_time = time.time() - start_time
            logger.warning(
                "TCP connection timeout",
                endpoint=self.name,
                host=self.tcp_config.host,
                port=self.tcp_config.port,
                timeout=self.tcp_config.timeout,
                response_time_ms=round(response_time * 1000, 2),
            )
            return self._create_result(
                status=CheckStatus.FAILURE,
                response_time=response_time,
                error_message=f"TCP connection timeout after {self.tcp_config.timeout}s",
                details={
                    "host": self.tcp_config.host,
                    "port": self.tcp_config.port,
                    "timeout": self.tcp_config.timeout,
                },
            )

        except Exception as e:
            response_time = time.time() - start_time
            logger.error(
                "TCP connection error",
                endpoint=self.name,
                host=self.tcp_config.host,
                port=self.tcp_config.port,
                response_time_ms=round(response_time * 1000, 2),
                error_type=type(e).__name__,
                error=str(e),
            )
            return self._create_result(
                status=CheckStatus.ERROR,
                response_time=response_time,
                error_message=str(e),
                details={
                    "host": self.tcp_config.host,
                    "port": self.tcp_config.port,
                    "error_type": type(e).__name__,
                },
            )


class TLSCheck(BaseCheck):
    """TLS/SSL certificate check implementation."""

    def __init__(self, config: EndpointConfig) -> None:
        super().__init__(config)
        if not config.tls:
            raise ValueError("TLS configuration is required for TLS checks")
        self.tls_config: TLSCheckConfig = config.tls

    async def execute(self) -> CheckResult:
        """Execute TLS check."""
        start_time = time.time()

        try:
            # Create SSL context
            context = ssl.create_default_context()

            # Connect and get certificate
            future = asyncio.open_connection(
                host=self.tls_config.host,
                port=self.tls_config.port,
                ssl=context,
                server_hostname=self.tls_config.host,
            )

            reader, writer = await asyncio.wait_for(
                future, timeout=self.tls_config.timeout
            )

            response_time = time.time() - start_time

            # Get certificate from the SSL transport
            transport = writer.transport
            if hasattr(transport, "get_extra_info"):
                peercert_der = transport.get_extra_info("peercert_chain")
                if peercert_der:
                    # Parse the first certificate in the chain
                    cert_der = peercert_der[0]
                    cert = x509.load_der_x509_certificate(cert_der, default_backend())

                    # Check certificate validity
                    now = datetime.now(UTC)
                    not_valid_after = cert.not_valid_after_utc
                    not_valid_before = cert.not_valid_before_utc

                    # Calculate days until expiry
                    days_until_expiry = (not_valid_after - now).days

                    # Close connection
                    writer.close()
                    await writer.wait_closed()

                    # Check if certificate is valid
                    if now < not_valid_before:
                        logger.warning(
                            "TLS certificate not yet valid",
                            endpoint=self.name,
                            host=self.tls_config.host,
                            port=self.tls_config.port,
                            not_valid_before=not_valid_before.isoformat(),
                            not_valid_after=not_valid_after.isoformat(),
                            days_until_expiry=days_until_expiry,
                            response_time_ms=round(response_time * 1000, 2),
                        )
                        return self._create_result(
                            status=CheckStatus.FAILURE,
                            response_time=response_time,
                            error_message="Certificate is not yet valid",
                            details={
                                "host": self.tls_config.host,
                                "port": self.tls_config.port,
                                "not_valid_before": not_valid_before.isoformat(),
                                "not_valid_after": not_valid_after.isoformat(),
                                "days_until_expiry": days_until_expiry,
                            },
                        )

                    if now > not_valid_after:
                        logger.warning(
                            "TLS certificate expired",
                            endpoint=self.name,
                            host=self.tls_config.host,
                            port=self.tls_config.port,
                            not_valid_before=not_valid_before.isoformat(),
                            not_valid_after=not_valid_after.isoformat(),
                            days_until_expiry=days_until_expiry,
                            response_time_ms=round(response_time * 1000, 2),
                        )
                        return self._create_result(
                            status=CheckStatus.FAILURE,
                            response_time=response_time,
                            error_message="Certificate has expired",
                            details={
                                "host": self.tls_config.host,
                                "port": self.tls_config.port,
                                "not_valid_before": not_valid_before.isoformat(),
                                "not_valid_after": not_valid_after.isoformat(),
                                "days_until_expiry": days_until_expiry,
                            },
                        )

                    # Check if certificate expires soon
                    if days_until_expiry <= self.tls_config.cert_expiry_warning_days:
                        logger.warning(
                            "TLS certificate expiring soon",
                            endpoint=self.name,
                            host=self.tls_config.host,
                            port=self.tls_config.port,
                            not_valid_before=not_valid_before.isoformat(),
                            not_valid_after=not_valid_after.isoformat(),
                            days_until_expiry=days_until_expiry,
                            warning_threshold=self.tls_config.cert_expiry_warning_days,
                            response_time_ms=round(response_time * 1000, 2),
                        )
                        return self._create_result(
                            status=CheckStatus.FAILURE,
                            response_time=response_time,
                            error_message=f"Certificate expires in {days_until_expiry} days",
                            details={
                                "host": self.tls_config.host,
                                "port": self.tls_config.port,
                                "not_valid_before": not_valid_before.isoformat(),
                                "not_valid_after": not_valid_after.isoformat(),
                                "days_until_expiry": days_until_expiry,
                                "warning_threshold": self.tls_config.cert_expiry_warning_days,
                            },
                        )

                    # Certificate is valid
                    result = self._create_result(
                        status=CheckStatus.SUCCESS,
                        response_time=response_time,
                        details={
                            "host": self.tls_config.host,
                            "port": self.tls_config.port,
                            "not_valid_before": not_valid_before.isoformat(),
                            "not_valid_after": not_valid_after.isoformat(),
                            "days_until_expiry": days_until_expiry,
                            "subject": cert.subject.rfc4514_string(),
                            "issuer": cert.issuer.rfc4514_string(),
                        },
                    )

                    # Log successful TLS check
                    logger.info(
                        "TLS check completed",
                        endpoint=self.name,
                        host=self.tls_config.host,
                        port=self.tls_config.port,
                        days_until_expiry=days_until_expiry,
                        response_time_ms=round(response_time * 1000, 2),
                    )

                    return result
                else:
                    # Close connection
                    writer.close()
                    await writer.wait_closed()

                    logger.error(
                        "TLS certificate retrieval failed",
                        endpoint=self.name,
                        host=self.tls_config.host,
                        port=self.tls_config.port,
                        response_time_ms=round(response_time * 1000, 2),
                        error="Unable to retrieve certificate from connection",
                    )
                    return self._create_result(
                        status=CheckStatus.ERROR,
                        response_time=response_time,
                        error_message="Unable to retrieve certificate from connection",
                        details={
                            "host": self.tls_config.host,
                            "port": self.tls_config.port,
                        },
                    )
            else:
                # Close connection
                writer.close()
                await writer.wait_closed()

                logger.error(
                    "TLS transport access failed",
                    endpoint=self.name,
                    host=self.tls_config.host,
                    port=self.tls_config.port,
                    response_time_ms=round(response_time * 1000, 2),
                    error="Unable to access SSL transport information",
                )
                return self._create_result(
                    status=CheckStatus.ERROR,
                    response_time=response_time,
                    error_message="Unable to access SSL transport information",
                    details={
                        "host": self.tls_config.host,
                        "port": self.tls_config.port,
                    },
                )

        except TimeoutError:
            response_time = time.time() - start_time
            logger.warning(
                "TLS connection timeout",
                endpoint=self.name,
                host=self.tls_config.host,
                port=self.tls_config.port,
                timeout=self.tls_config.timeout,
                response_time_ms=round(response_time * 1000, 2),
            )
            return self._create_result(
                status=CheckStatus.FAILURE,
                response_time=response_time,
                error_message=f"TLS connection timeout after {self.tls_config.timeout}s",
                details={
                    "host": self.tls_config.host,
                    "port": self.tls_config.port,
                    "timeout": self.tls_config.timeout,
                },
            )

        except ssl.SSLError as e:
            response_time = time.time() - start_time
            logger.warning(
                "TLS SSL error",
                endpoint=self.name,
                host=self.tls_config.host,
                port=self.tls_config.port,
                response_time_ms=round(response_time * 1000, 2),
                error=str(e),
            )
            return self._create_result(
                status=CheckStatus.FAILURE,
                response_time=response_time,
                error_message=f"SSL/TLS error: {str(e)}",
                details={
                    "host": self.tls_config.host,
                    "port": self.tls_config.port,
                    "error_type": "SSLError",
                },
            )

        except Exception as e:
            response_time = time.time() - start_time
            logger.error(
                "TLS general error",
                endpoint=self.name,
                host=self.tls_config.host,
                port=self.tls_config.port,
                response_time_ms=round(response_time * 1000, 2),
                error_type=type(e).__name__,
                error=str(e),
            )
            return self._create_result(
                status=CheckStatus.ERROR,
                response_time=response_time,
                error_message=str(e),
                details={
                    "host": self.tls_config.host,
                    "port": self.tls_config.port,
                    "error_type": type(e).__name__,
                },
            )


def create_check(config: EndpointConfig) -> BaseCheck:
    """Factory function to create appropriate check instance."""
    if config.type.value == "http":
        return HTTPCheck(config)
    elif config.type.value == "tcp":
        return TCPCheck(config)
    elif config.type.value == "tls":
        return TLSCheck(config)
    else:
        raise ValueError(f"Unsupported check type: {config.type}")
