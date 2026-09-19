"""Alert policy for Main Gate access decisions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Alert:
    """A transport-neutral alert for the UI, buzzer, or future GPIO adapter."""

    level: str
    message: str
    audible: bool


def create_alert(status, plate_number):
    """Build the alert that corresponds to an access-control status."""
    if status in {"Blocked", "Unauthorized"}:
        return Alert("danger", f"Access attention required for plate {plate_number}.", True)
    if status == "Unreadable":
        return Alert("warning", "Plate could not be read. Manual verification is required.", False)
    return Alert("success", f"Plate {plate_number} is cleared for entry.", False)