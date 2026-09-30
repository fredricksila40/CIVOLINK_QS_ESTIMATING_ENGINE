"""Licensing domain models: states, info snapshots, provider results.

Pure data contracts — no I/O, no network, no toolkit. Timestamps are
integer epoch seconds (the qs_engine float ban covers this package).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class LicenseState(str, Enum):
    """Application-level license states (fixed set; do not extend
    casually — every state needs a UI mapping below)."""

    UNLICENSED = "UNLICENSED"
    ACTIVATION_REQUIRED = "ACTIVATION_REQUIRED"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    OFFLINE_GRACE = "OFFLINE_GRACE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUSPENDED = "SUSPENDED"
    ACTIVATION_LIMIT_REACHED = "ACTIVATION_LIMIT_REACHED"
    NETWORK_ERROR = "NETWORK_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"


#: Customer-facing wording per state (UI + dialogs share this table).
STATE_DISPLAY = {
    LicenseState.UNLICENSED: "Not Activated",
    LicenseState.ACTIVATION_REQUIRED: "Activation Required",
    LicenseState.ACTIVATING: "Activating…",
    LicenseState.ACTIVE: "Active",
    LicenseState.OFFLINE_GRACE: "Active (Offline Grace)",
    LicenseState.EXPIRED: "Expired",
    LicenseState.REVOKED: "Revoked",
    LicenseState.SUSPENDED: "Suspended",
    LicenseState.ACTIVATION_LIMIT_REACHED: "Activation Limit Reached",
    LicenseState.NETWORK_ERROR: "Connection Error",
    LicenseState.VALIDATION_ERROR: "Validation Error",
}


@dataclass(frozen=True)
class LicenseInfo:
    """Customer-safe license snapshot for UI rendering.

    Contains no credentials, fingerprints, or provider internals —
    only what the License dialog is allowed to display.
    """

    product: str = "CIVOLINK QS"
    state: LicenseState = LicenseState.UNLICENSED
    organization: str = ""
    expires: Optional[str] = None  # ISO date, or None = perpetual
    device_activated: bool = False
    device_label: str = ""
    offline: bool = False
    last_checked: int = 0  # integer epoch seconds
    message: str = ""


@dataclass(frozen=True)
class ProviderResult:
    """Outcome of one provider operation (activation/validation)."""

    ok: bool
    state: LicenseState
    organization: str = ""
    expires: Optional[str] = None
    device_activated: bool = False
    device_label: str = ""
    message: str = ""
    retryable: bool = False  # True only for transient network failure
    artifact: Dict[str, Any] = field(default_factory=dict)


def license_display(state: LicenseState) -> str:
    """Customer-facing license line (headless-testable)."""
    return STATE_DISPLAY.get(state, "Unknown")


def expiration_display(expires: Optional[str]) -> str:
    """Expiry line: date as supplied, or Perpetual when open-ended."""
    text = str(expires or "").strip()
    return text if text else "Perpetual"


def connection_display(offline: bool, state: LicenseState) -> str:
    """Connection line: offline grace is distinct from errors."""
    if state == LicenseState.OFFLINE_GRACE or offline:
        return "Offline Grace"
    if state == LicenseState.NETWORK_ERROR:
        return "Offline (Unverified)"
    return "Online"
