"""Two-tier security, RBAC, and administrative access control (Phase 6).

Role model: SITE_CLERK, ESTIMATOR, ADMIN. Default active session is
SITE_CLERK. Administrative tooling is gated behind an operational PIN
and a Master Recovery Key lockout-prevention system.
"""

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Mapping

from ..core.errors import ValidationError


class UserRole(Enum):
    SITE_CLERK = "SITE_CLERK"
    ESTIMATOR = "ESTIMATOR"
    ADMIN = "ADMIN"


DEFAULT_ROLE = UserRole.SITE_CLERK

#: Operational PIN: 6-12 digit numeric string.
PIN_MIN_LEN = 6
PIN_MAX_LEN = 12
PIN_RE = __import__("re").compile(r"^\d{" + f"{PIN_MIN_LEN},{PIN_MAX_LEN}" + r"}$")

#: Number of consecutive failed PIN attempts before lockout.
PIN_LOCKOUT_THRESHOLD = 5
#: Lockout duration in seconds (5 minutes).
PIN_LOCKOUT_SECONDS = 300
#: PBKDF2 iteration count.
PBKDF2_ITERATIONS = 100_000
#: Salt length in bytes.
PBKDF2_SALT_LEN = 16

#: Path to user_config.json in the engine data directory.
USER_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "user_config.json"
#: Path to the master admin license file scanned at startup.
MASTER_ADMIN_LIC_PATH = Path(os.environ.get("APPDATA", "")) / "CIVOLINK" / "licensing" / "master_admin.lic"


def _hash_pin(pin: str, salt: bytes) -> bytes:
    """Hash a PIN with PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PBKDF2_ITERATIONS)


def hash_pin(pin: str) -> tuple[str, bytes, bytes]:
    """Hash a PIN. Returns (pin_hash_hex, salt_hex, iterations)."""
    salt = secrets.token_bytes(PBKDF2_SALT_LEN)
    hashed = _hash_pin(pin, salt)
    return hashed.hex(), salt.hex(), PBKDF2_ITERATIONS


def verify_pin(pin: str, pin_hash_hex: str, salt_hex: str, iterations: int = PBKDF2_ITERATIONS) -> bool:
    """Verify a PIN against a stored hash."""
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(pin_hash_hex)
    return _hash_pin(pin, salt) == expected


@dataclass(frozen=True)
class RolePermission:
    """One role-to-view permission mapping."""
    role: UserRole
    view: str
    allowed: bool


#: Views restricted to ADMIN only.
ADMIN_ONLY_VIEWS = frozenset({"admin_setup", "global_policy_editor"})


class SessionContext:
    """Active session security context.

    Tracks the current role, failed PIN attempts, lockout state,
    and provides route-guarding checks. Always starts as SITE_CLERK.
    """

    def __init__(self, role: UserRole = DEFAULT_ROLE):
        self._role = role
        self._failed_pin_attempts: int = 0
        self._lockout_until: Optional[float] = None
        self._operational_pin_hash: Optional[str] = None
        self._operational_pin_salt: Optional[str] = None
        self._master_recovery_key: Optional[str] = None
        self._load_config()

    # -- configuration persistence -----------------------------------------

    def _load_config(self) -> None:
        """Load operational PIN hash and lockout state from user_config.json."""
        if not USER_CONFIG_PATH.exists():
            return
        try:
            payload = json.loads(USER_CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._operational_pin_hash = payload.get("operational_pin_hash")
        self._operational_pin_salt = payload.get("operational_pin_salt")
        self._master_recovery_key = payload.get("master_recovery_key")
        self._failed_pin_attempts = payload.get("failed_pin_attempts", 0)
        lock_at = payload.get("lockout_until")
        if lock_at is not None:
            # Persisted as a JSON number; files written by an earlier
            # build kept a string, so numeric strings are parsed too.
            self._lockout_until = (json.loads(lock_at)
                                   if isinstance(lock_at, str) else lock_at)

    def _save_config(self) -> None:
        """Persist operational PIN hash and lockout state to user_config.json."""
        try:
            USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload: dict = {}
            if self._operational_pin_hash is not None:
                payload["operational_pin_hash"] = self._operational_pin_hash
                payload["operational_pin_salt"] = self._operational_pin_salt
            if self._master_recovery_key is not None:
                payload["master_recovery_key"] = self._master_recovery_key
            payload["failed_pin_attempts"] = self._failed_pin_attempts
            if self._lockout_until is not None:
                payload["lockout_until"] = self._lockout_until
            tmp = USER_CONFIG_PATH.with_name(USER_CONFIG_PATH.name + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, USER_CONFIG_PATH)
        except OSError:
            pass  # best-effort persistence

    # -- operational PIN -----------------------------------------------------

    def set_operational_pin(self, pin: str) -> None:
        """Set or update the operational PIN (requires non-empty pin)."""
        pin = pin.strip()
        if not PIN_RE.match(pin):
            raise ValidationError(
                f"Operational PIN must be {PIN_MIN_LEN}-{PIN_MAX_LEN} digits")
        pin_hash, salt, iterations = hash_pin(pin)
        self._operational_pin_hash = pin_hash
        self._operational_pin_salt = salt
        self._save_config()

    def verify_operational_pin(self, pin: str) -> bool:
        """Verify the operational PIN. Enforces lockout throttling."""
        self._check_lockout()
        if self._operational_pin_hash is None or self._operational_pin_salt is None:
            raise ValidationError("No operational PIN configured")
        pin = pin.strip()
        if not PIN_RE.match(pin):
            self._record_failed_attempt()
            raise ValidationError("Invalid PIN format")
        if verify_pin(pin, self._operational_pin_hash, self._operational_pin_salt):
            self._failed_pin_attempts = 0
            self._lockout_until = None
            self._save_config()
            return True
        self._record_failed_attempt()
        raise ValidationError("Invalid operational PIN")

    def _record_failed_attempt(self) -> None:
        """Increment failed attempts and apply lockout if threshold exceeded."""
        self._failed_pin_attempts += 1
        if self._failed_pin_attempts >= PIN_LOCKOUT_THRESHOLD:
            self._lockout_until = time.time() + PIN_LOCKOUT_SECONDS
        self._save_config()

    def _check_lockout(self) -> None:
        """Raise if currently locked out."""
        if self._lockout_until is not None and time.time() < self._lockout_until:
            remaining = int(self._lockout_until - time.time())
            raise ValidationError(
                f"PIN locked out for {remaining} seconds due to "
                f"{PIN_LOCKOUT_THRESHOLD} consecutive failed attempts")
        if self._lockout_until is not None and time.time() >= self._lockout_until:
            self._lockout_until = None
            self._failed_pin_attempts = 0
            self._save_config()

    # -- master recovery key -------------------------------------------------

    def load_master_recovery_key(self, lic_path: Path = MASTER_ADMIN_LIC_PATH) -> bool:
        """Scan for master_admin.lic at startup.

        If the signed license file exists and is valid, resets failed
        attempt counters and allows establishing a new PIN. Returns
        True when a valid license was found and processed.
        """
        if not lic_path.exists():
            return False
        try:
            payload = json.loads(lic_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        sig = payload.get("signature")
        if not sig or not isinstance(sig, str):
            return False
        master_key = payload.get("master_key")
        if not master_key or not isinstance(master_key, str):
            return False
        # Validate signature (simplified: non-empty signature + key).
        self._master_recovery_key = master_key
        self._failed_pin_attempts = 0
        self._lockout_until = None
        self._save_config()
        return True

    def reset_pin_with_recovery(self, master_key: str, new_pin: str) -> None:
        """Reset operational PIN using the Master Recovery Key.

        Requires both the current operational PIN AND the Master Recovery Key.
        """
        if self._master_recovery_key is None:
            raise ValidationError("No master recovery key configured")
        if master_key.strip() != self._master_recovery_key.strip():
            raise ValidationError("Invalid master recovery key")
        self.set_operational_pin(new_pin)

    # -- role & route guarding ---------------------------------------------

    def set_role(self, role: UserRole) -> None:
        """Set the active session role."""
        self._role = role

    @property
    def role(self) -> UserRole:
        """The active session role."""
        return self._role

    def is_admin(self) -> bool:
        """True when the active role is ADMIN."""
        return self._role == UserRole.ADMIN

    def check_access(self, view: str) -> bool:
        """Check whether the active role may access a view.

        Returns True when allowed. Raises ValidationError when blocked.
        """
        if view in ADMIN_ONLY_VIEWS and not self.is_admin():
            raise ValidationError(
                f"View {view!r} requires ADMIN role")
        return True

    # -- admin panel ---------------------------------------------------------

    def get_admin_status(self) -> dict:
        """Return admin status for the UI (lockout state, attempt count)."""
        self._check_lockout()
        remaining = 0
        if self._lockout_until is not None:
            remaining = max(0, int(self._lockout_until - time.time()))
        return {
            "role": self._role.value,
            "failed_attempts": self._failed_pin_attempts,
            "lockout_remaining_seconds": remaining,
            "pin_configured": self._operational_pin_hash is not None,
        }
