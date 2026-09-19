from access_control import decide_access, normalize_plate_number


def test_normalize_plate_number_removes_formatting():
    assert normalize_plate_number("KAN-123 AB") == "KAN123AB"


def test_decision_states_are_explicit():
    assert decide_access("ABC123", "Allowed", 90).status == "Allowed"
    assert decide_access("ABC123", "Blocked", 90).alert_required is True
    assert decide_access("ABC123", None, 90).status == "Unauthorized"
    assert decide_access("UNREADABLE", None, 0).status == "Unreadable"