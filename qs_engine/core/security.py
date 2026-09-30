"""Two-tier security, RBAC, and owner-controlled access (Phase 6).

Roles, least privilege first:

* ``SITE_CLERK`` - default session: take-off, mix lookups, read-only rates.
* ``OPERATIONAL_ADMIN`` - daily administration (rate updates, GL mapping,
  support desk). Unlocked with the Tier 1 operational PIN.
* ``SUPER_ADMIN`` - the System Owner: master-key recovery, PIN rotation,
  security policy. Reachable only with the Master Recovery Key.

Tier 1 (operational PIN, 6-12 digits) opens the daily administration
views but can NEVER rotate a PIN or change a security parameter.
Tier 2 (Master Recovery Key ``CVLK-XXXX-XXXX-XXXX``, released by the
System Owner through a signed ``master_admin.lic``) is the only path to
PIN rotation and security policy. Five consecutive PIN failures lock the
operational tier out for five minutes; the owner key clears the lockout.
"""

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Mapping

from ..core.errors import ValidationError


class UserRole(Enum):
    """Session roles, ordered by privilege."""

    SITE_CLERK = "SITE_CLERK"
    OPERATIONAL_ADMIN = "OPERATIONAL_ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


DEFAULT_ROLE = UserRole.SITE_CLERK

#: Roles that satisfy ``is_admin()`` - Tier 1 (operational) and above.
ADMIN_ROLES = frozenset({UserRole.OPERATIONAL_ADMIN, UserRole.SUPER_ADMIN})

#: Operational PIN: 6-12 digit numeric string.
PIN_MIN_LEN = 6
PIN_MAX_LEN = 12
PIN_RE = re.compile(r"^\d{" + f"{PIN_MIN_LEN},{PIN_MAX_LEN}" + r"}$")

#: Master Recovery Key issued by the System Owner: CVLK-XXXX-XXXX-XXXX.
MASTER_KEY_PREFIX = "CVLK"
MASTER_KEY_RE = re.compile(r"^CVLK-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

#: Support & helpdesk address configured in the administration views.
SUPPORT_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

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


#: Tier 1 views - daily administration, unlocked by the operational PIN.
ADMIN_ONLY_VIEWS = frozenset({"admin_setup", "global_policy_editor"})
#: Tier 2 views - security policy; the Master Recovery Key is mandatory.
SUPER_ADMIN_ONLY_VIEWS = frozenset({"security_policy"})


def _canonical_license_body(payload: Mapping) -> bytes:
    """Canonical bytes the System Owner signs in master_admin.lic.

    Key order is fixed and the ``signature`` field itself is excluded, so
    re-serialising the file cannot change what was signed.
    """
    body = {key: value for key, value in payload.items()
            if key != "signature"}
    return json.dumps(body, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


class SessionContext:
    """Active session security context (two-tier, least privilege).

    Tracks the active role, failed PIN attempts, lockout state, the
    Master Recovery Key, and the configured support desk. Sessions start
    as SITE_CLERK; the operational PIN promotes to OPERATIONAL_ADMIN and
    the owner key promotes to SUPER_ADMIN.
    """

    def __init__(self, role: UserRole = DEFAULT_ROLE):
        self._role = role
        self._failed_pin_attempts: int = 0
        self._lockout_until: Optional[float] = None
        self._operational_pin_hash: Optional[str] = None
        self._operational_pin_salt: Optional[str] = None
        self._master_recovery_key: Optional[str] = None
        self._support_email: Optional[str] = None
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
        system = payload.get("system")
        if isinstance(system, Mapping):
            email = str(system.get("support_email", "") or "").strip()
            self._support_email = email or None
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
            if self._support_email:
                payload["system"] = {"support_email": self._support_email}
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
        """Set the operational PIN (first-time setup only).

        Rotating an existing PIN is a security-policy change and MUST go
        through :meth:`reset_pin_with_recovery` with the Master Recovery
        Key - Tier 1 can never rewrite its own credential.
        """
        if self._operational_pin_hash is not None:
            raise ValidationError(
                "Operational PIN rotation requires the Master Recovery Key "
                f"({MASTER_KEY_PREFIX}-XXXX-XXXX-XXXX)")
        self._store_pin(pin)

    def _store_pin(self, pin: str) -> None:
        """Validate and persist a PIN hash (first set or owner rotation)."""
        pin = pin.strip()
        if not PIN_RE.match(pin):
            raise ValidationError(
                f"Operational PIN must be {PIN_MIN_LEN}-{PIN_MAX_LEN} digits")
        pin_hash, salt, _iterations = hash_pin(pin)
        self._operational_pin_hash = pin_hash
        self._operational_pin_salt = salt
        self._save_config()

    def unlock_with_pin(self, pin: str) -> UserRole:
        """Tier 1 unlock: verify the PIN and promote to OPERATIONAL_ADMIN.

        Lockout throttling applies exactly as in
        :meth:`verify_operational_pin`. Tier 1 opens the daily
        administration views only - never PIN changes or security policy.
        """
        self.verify_operational_pin(pin)
        self.set_role(UserRole.OPERATIONAL_ADMIN)
        return self._role

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
        """Scan for master_admin.lic at startup and adopt its owner key.

        The System Owner's license carries the Master Recovery Key plus an
        Ed25519 signature over its canonical body. An unsigned, tampered,
        or malformed file is refused (fail closed). On success the failed
        attempt counters and any lockout are cleared, so the owner can
        rotate the PIN.
        """
        if not lic_path.exists():
            return False
        try:
            payload = json.loads(lic_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(payload, Mapping):
            return False
        master_key = payload.get("master_key")
        signature = payload.get("signature")
        public_key = payload.get("public_key")
        if not all(isinstance(value, str) and value.strip()
                   for value in (master_key, signature, public_key)):
            return False
        if not MASTER_KEY_RE.match(master_key.strip()):
            return False
        from qs_engine.licensing.provider import verify_signature
        if not verify_signature(public_key,
                                _canonical_license_body(payload),
                                signature):
            return False
        self._master_recovery_key = master_key.strip()
        self._failed_pin_attempts = 0
        self._lockout_until = None
        self._save_config()
        return True

    def reset_pin_with_recovery(self, master_key: str, new_pin: str) -> None:
        """Tier 2 owner reset: rotate the operational PIN with the key.

        Requires the Master Recovery Key adopted from a signed
        master_admin.lic. A successful reset promotes the session to
        SUPER_ADMIN - Tier 1 alone can never rotate the credential.
        """
        if self._master_recovery_key is None:
            raise ValidationError("No master recovery key configured")
        key = str(master_key or "").strip()
        if not MASTER_KEY_RE.match(key):
            raise ValidationError(
                "Master Recovery Key must look like "
                f"{MASTER_KEY_PREFIX}-XXXX-XXXX-XXXX")
        if key != self._master_recovery_key.strip():
            raise ValidationError("Invalid master recovery key")
        self._store_pin(new_pin)
        self.set_role(UserRole.SUPER_ADMIN)

    # -- role & route guarding ---------------------------------------------

    def set_role(self, role: UserRole) -> None:
        """Set the active session role."""
        self._role = role

    @property
    def role(self) -> UserRole:
        """The active session role."""
        return self._role

    def is_admin(self) -> bool:
        """True for Tier 1 (operational admin) and Tier 2 (owner)."""
        return self._role in ADMIN_ROLES

    def is_super_admin(self) -> bool:
        """True only for the System Owner tier (master-key held)."""
        return self._role == UserRole.SUPER_ADMIN

    def check_access(self, view: str) -> bool:
        """Check whether the active role may access a view.

        Returns True when allowed. Raises ValidationError when blocked.
        """
        if view in SUPER_ADMIN_ONLY_VIEWS and not self.is_super_admin():
            raise ValidationError(
                f"View {view!r} requires the SUPER_ADMIN role "
                f"(Master Recovery Key)")
        if view in ADMIN_ONLY_VIEWS and not self.is_admin():
            raise ValidationError(
                f"View {view!r} requires ADMIN role "
                f"(unlock with the operational PIN)")
        return True

    # -- support & helpdesk --------------------------------------------------

    @property
    def support_email(self) -> str:
        """Configured Support & helpdesk address (empty when unset)."""
        return self._support_email or ""

    def set_support_email(self, email: str) -> str:
        """Persist the Support & helpdesk address in user_config.json."""
        text = str(email or "").strip()
        if text and not SUPPORT_EMAIL_RE.match(text):
            raise ValidationError(
                "Support email must look like support@example.com")
        self._support_email = text or None
        self._save_config()
        return self.support_email

    # -- admin panel ---------------------------------------------------------

    def get_admin_status(self) -> dict:
        """Return admin status for the UI (tier, lockout, support desk)."""
        self._check_lockout()
        remaining = 0
        if self._lockout_until is not None:
            remaining = max(0, int(self._lockout_until - time.time()))
        return {
            "role": self._role.value,
            "is_admin": self.is_admin(),
            "is_super_admin": self.is_super_admin(),
            "failed_attempts": self._failed_pin_attempts,
            "lockout_remaining_seconds": remaining,
            "pin_configured": self._operational_pin_hash is not None,
            "master_key_configured": self._master_recovery_key is not None,
            "support_email": self.support_email,
        }
