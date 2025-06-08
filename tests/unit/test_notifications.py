from server_monitor.notifications import NotificationEvent


def test_notification_event_enum():
    assert NotificationEvent.FAILURE == "failure"
    assert NotificationEvent.RECOVERY == "recovery"
    assert NotificationEvent.BOTH == "both"


def test_notification_event_str():
    # Test string representation
    assert NotificationEvent.FAILURE.value == "failure"
    assert NotificationEvent.RECOVERY.value == "recovery"
    assert NotificationEvent.BOTH.value == "both"


def test_notification_event_membership():
    # Test membership
    assert "failure" in NotificationEvent._value2member_map_
    assert "recovery" in NotificationEvent._value2member_map_
    assert "both" in NotificationEvent._value2member_map_
