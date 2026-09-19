from rbac import has_permission


def test_role_permissions_follow_least_privilege():
    assert has_permission("Admin", "users:write")
    assert has_permission("Supervisor", "watchlist:write")
    assert has_permission("Operator", "scan:read")
    assert not has_permission("Operator", "watchlist:write")
    assert not has_permission("Auditor", "users:write")