import pytest
from unittest.mock import MagicMock
from server_monitor.checks import create_check
from server_monitor.config import EndpointConfig

def test_create_check_invalid_type():
    class DummyType:
        value = "invalid"
    config = MagicMock()
    config.type = DummyType()
    with pytest.raises(ValueError):
        create_check(config)

def test_create_check_with_minimal_config():
    # Only required fields, no optional
    config = MagicMock()
    config.type = MagicMock()
    config.type.value = "http"
    config.http = MagicMock()
    check = create_check(config)
    assert check is not None

def test_create_check_invalid_type_string():
    class DummyType:
        value = "notarealtype"
    config = MagicMock()
    config.type = DummyType()
    with pytest.raises(ValueError):
        create_check(config)
