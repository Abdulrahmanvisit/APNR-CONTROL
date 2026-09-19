"""Access decision rules for recognized vehicle plates."""

from dataclasses import dataclass


UNREADABLE_VALUES = {"", "UNREADABLE", "OCR_ERROR", "OCRERROR"}
VALID_CATEGORIES = {"Allowed", "Blocked", "Visitor"}


@dataclass(frozen=True)
class AccessDecision:
    """Normalized result used by the UI, alert layer, and audit logger."""

    plate_number: str
    status: str
    alert_required: bool
    reason: str


def normalize_plate_number(value):
    """Normalize a plate for comparison with the central registry."""
    return "".join(character for character in str(value or "").upper() if character.isalnum())


def decide_access(plate_number, category=None, confidence=0.0, minimum_confidence=20.0):
    """Classify a recognition result without performing database or UI work."""
    normalized_plate = normalize_plate_number(plate_number)
    if normalized_plate in UNREADABLE_VALUES or confidence < minimum_confidence:
        return AccessDecision(normalized_plate or "UNREADABLE", "Unreadable", False, "Recognition confidence is insufficient.")
    if category in VALID_CATEGORIES:
        return AccessDecision(normalized_plate, category, category == "Blocked", f"Plate matched the {category} registry.")
    return AccessDecision(normalized_plate, "Unauthorized", True, "Plate was not found in the authorized registry.")