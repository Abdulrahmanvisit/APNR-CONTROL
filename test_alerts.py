from alerts import create_alert


def test_blocked_and_unknown_plates_require_audible_alerts():
    assert create_alert("Blocked", "ABC123").audible is True
    assert create_alert("Unauthorized", "ABC123").level == "danger"


def test_unreadable_plate_requires_manual_review():
    alert = create_alert("Unreadable", "UNREADABLE")
    assert alert.audible is False
    assert alert.level == "warning"