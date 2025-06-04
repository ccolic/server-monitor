from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server_monitor.checks import CheckStatus, HTTPCheck
from server_monitor.config import CheckType, EndpointConfig, HTTPCheckConfig


@pytest.mark.asyncio
async def test_http_check_content_match_plain_text():
    config = EndpointConfig(
        name="Test HTTP Content Plain",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(
            url="https://example.com",
            method="GET",
            timeout=30,
            expected_status=200,
            content_match="Example Domain",
        ),
    )
    check = HTTPCheck(config)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "Example Domain"
    mock_response.content = b"Example Domain"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.request.return_value = mock_response
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await check.execute()
    assert result.status == CheckStatus.SUCCESS


@pytest.mark.asyncio
async def test_http_check_unexpected_status_and_content():
    config = EndpointConfig(
        name="Test HTTP Combo",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(
            url="https://example.com",
            method="GET",
            timeout=30,
            expected_status=404,
            content_match="Not Found",
        ),
    )
    check = HTTPCheck(config)
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Server Error"
    mock_response.content = b"Server Error"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.request.return_value = mock_response
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await check.execute()
    assert result.status == CheckStatus.FAILURE
    assert result.details["status_code"] == 500
    assert "expected_status" in result.details
    # Accept that content_match may not be present if status fails first


@pytest.mark.asyncio
async def test_http_check_invalid_regex():
    config = EndpointConfig(
        name="Test HTTP Invalid Regex",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(
            url="https://example.com",
            method="GET",
            timeout=30,
            expected_status=200,
            content_match="[unclosed",
            content_regex=True,
        ),
    )
    check = HTTPCheck(config)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "Example Domain"
    mock_response.content = b"Example Domain"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value.request.return_value = mock_response
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await check.execute()
    assert result.status == CheckStatus.ERROR
    assert "error_type" in result.details
    assert result.details["error_type"] == "error"


@pytest.mark.asyncio
async def test_http_check_network_error():
    config = EndpointConfig(
        name="Test HTTP Network Error",
        type=CheckType.HTTP,
        interval=60,
        http=HTTPCheckConfig(
            url="https://example.com", method="GET", timeout=30, expected_status=200
        ),
    )
    check = HTTPCheck(config)
    mock_client = AsyncMock()
    mock_client.__aenter__.side_effect = httpx.NetworkError("network down")
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await check.execute()
    assert result.status == CheckStatus.ERROR
    assert result.details["error_type"] == "NetworkError"
