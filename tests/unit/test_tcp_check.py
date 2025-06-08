from unittest.mock import patch

import pytest

from server_monitor.checks import CheckStatus, TCPCheck
from server_monitor.config import CheckType, EndpointConfig, TCPCheckConfig


@pytest.mark.asyncio
async def test_tcp_check_general_exception():
    config = EndpointConfig(
        name="Test TCP Exception",
        type=CheckType.TCP,
        interval=120,
        tcp=TCPCheckConfig(host="example.com", port=80, timeout=10),
    )
    check = TCPCheck(config)
    with patch("asyncio.open_connection", side_effect=OSError("Connection refused")):
        result = await check.execute()
    assert result.status == CheckStatus.ERROR
    assert result.details["error_type"] == "OSError"


@pytest.mark.asyncio
async def test_tcp_check_host_not_found():
    config = EndpointConfig(
        name="Test TCP Host Not Found",
        type=CheckType.TCP,
        interval=120,
        tcp=TCPCheckConfig(host="no.such.host", port=80, timeout=10),
    )
    check = TCPCheck(config)
    with patch(
        "asyncio.open_connection", side_effect=OSError("Name or service not known")
    ):
        result = await check.execute()
    assert result.status == CheckStatus.ERROR
    assert result.details["error_type"] == "OSError"


@pytest.mark.asyncio
async def test_tcp_check_connection_reset():
    config = EndpointConfig(
        name="Test TCP Conn Reset",
        type=CheckType.TCP,
        interval=120,
        tcp=TCPCheckConfig(host="example.com", port=80, timeout=10),
    )
    check = TCPCheck(config)
    with patch(
        "asyncio.open_connection", side_effect=ConnectionResetError("reset by peer")
    ):
        result = await check.execute()
    assert result.status == CheckStatus.ERROR
    assert result.details["error_type"] == "ConnectionResetError"
