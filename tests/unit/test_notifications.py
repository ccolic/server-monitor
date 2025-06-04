import pytest
from server_monitor.notifications import NotificationEvent


def test_notification_event_enum():
    assert NotificationEvent.UP == "up"
    assert NotificationEvent.DOWN == "down"
    assert NotificationEvent.WARN == "warn"
    assert NotificationEvent.ERROR == "error"
    assert NotificationEvent.RECOVERED == "recovered"


def test_notification_event_str():
    # Test string representation
    assert str(NotificationEvent.UP) == "up"
    assert str(NotificationEvent.ERROR) == "error"


def test_notification_event_membership():
    # Test membership
    assert "up" in NotificationEvent._value2member_map_
    assert "down" in NotificationEvent._value2member_map_
    assert "warn" in NotificationEvent._value2member_map_
    assert "error" in NotificationEvent._value2member_map_
    assert "recovered" in NotificationEvent._value2member_map_
