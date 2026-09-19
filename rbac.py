"""Small, centralized permission policy for the APNR application."""

ROLE_PERMISSIONS = {
    "Admin": {
        "scan:read",
        "watchlist:read",
        "watchlist:write",
        "users:write",
        "audit:read",
    },
    "Supervisor": {
        "scan:read",
        "watchlist:read",
        "watchlist:write",
        "audit:read",
    },
    "Operator": {"scan:read", "watchlist:read", "audit:read"},
    "Auditor": {"audit:read", "watchlist:read"},
}


def has_permission(role, permission):
    """Return whether a role is allowed to perform a named operation."""
    return permission in ROLE_PERMISSIONS.get(role, set())