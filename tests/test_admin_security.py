"""Phase 6: Admin Security & RBAC tests.

Covers PIN hashing, Super-Admin recovery key resets,
failure lockout limits, and route guarding enforcement.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.core.security import (
    MASTER_ADMIN_LIC_PATH,
    SessionContext,
    UserRole,
    hash_pin,
    verify_pin,
)


@pytest.fixture(autouse=True)
def _isolated_user_config(monkeypatch, tmp_path):
    """Point SessionContext persistence at a per-test temp file.

    SessionContext reads/writes ``data/user_config.json`` (PIN hash,
    failed attempts, lockout_until, recovery key). Left on the real
    path, each test leaks lockout/recovery state into the next one and
    the suite becomes order-dependent — plus it dirties the developer's
    config with test secrets. Same swap pattern the category-registry
    tests already use, but automatic for every test here.
    """
    from qs_engine.core import security
    monkeypatch.setattr(security, "USER_CONFIG_PATH",
                        tmp_path / "user_config.json")


# ------------------------------------------------------------------ #
# PIN Hashing & Verification
# ------------------------------------------------------------------ #

def test_hash_pin_returns_tuple():
    result = hash_pin("123456")
    assert len(result) == 3
    pin_hash, salt, iterations = result
    assert len(pin_hash) == 64
    assert len(salt) == 32
    assert iterations == 100_000


def test_verify_pin_correct():
    pin_hash, salt, _ = hash_pin("123456")
    assert verify_pin("123456", pin_hash, salt)


def test_verify_pin_incorrect():
    pin_hash, salt, _ = hash_pin("123456")
    assert not verify_pin("wrong", pin_hash, salt)


def test_different_salt_different_hash():
    _, salt1, _ = hash_pin("123456")
    _, salt2, _ = hash_pin("123456")
    assert salt1 != salt2


# ------------------------------------------------------------------ #
# SessionContext: Role & Access
# ------------------------------------------------------------------ #

def test_session_default_is_site_clerk():
    ctx = SessionContext()
    assert ctx.role == UserRole.SITE_CLERK


def test_super_admin_role_opens_every_admin_view():
    ctx = SessionContext()
    ctx.set_role(UserRole.SUPER_ADMIN)
    assert ctx.is_admin()
    assert ctx.is_super_admin()

    # Least privilege: a default session is blocked from admin views
    ctx2 = SessionContext()
    with pytest.raises(ValidationError):
        ctx2.check_access("admin_setup")


def test_operational_admin_cannot_open_security_policy():
    ctx = SessionContext()
    ctx.set_role(UserRole.OPERATIONAL_ADMIN)
    assert ctx.is_admin()
    assert not ctx.is_super_admin()
    # Tier 1 runs daily administration...
    assert ctx.check_access("admin_setup") is True
    # ...but never the System Owner's security policy view.
    with pytest.raises(ValidationError) as exc:
        ctx.check_access("security_policy")
    assert "SUPER_ADMIN" in str(exc.value)


def test_public_views_allowed_for_all():
    ctx = SessionContext()
    assert ctx.check_access("overview") is True
    assert ctx.check_access("project") is True


# ------------------------------------------------------------------ #
# Operational PIN Management
# ------------------------------------------------------------------ #

def test_set_operational_pin():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    assert ctx._operational_pin_hash is not None


def test_set_operational_pin_too_short():
    ctx = SessionContext()
    with pytest.raises(ValidationError):
        ctx.set_operational_pin("123")


def test_set_operational_pin_invalid_chars():
    ctx = SessionContext()
    with pytest.raises(ValidationError):
        ctx.set_operational_pin("abcdef")


def test_verify_operational_pin():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    assert ctx.verify_operational_pin("123456")


def test_verify_operational_pin_wrong():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    with pytest.raises(ValidationError):
        ctx.verify_operational_pin("wrong")


# ------------------------------------------------------------------ #
# Lockout Throttling
# ------------------------------------------------------------------ #

def test_pin_lockout_after_five_failures(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH, PIN_LOCKOUT_THRESHOLD, PIN_LOCKOUT_SECONDS
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        for _ in range(PIN_LOCKOUT_THRESHOLD):
            try:
                ctx.verify_operational_pin("wrong")
            except ValidationError:
                pass
        with pytest.raises(ValidationError) as exc:
            ctx.verify_operational_pin("wrong")
        assert "locked out" in str(exc.value).lower()
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_pin_lockout_resets_after_success(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        try:
            ctx.verify_operational_pin("wrong")
        except ValidationError:
            pass
        assert ctx.verify_operational_pin("123456")
        assert ctx._failed_pin_attempts == 0
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_pin_lockout_expires(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH, PIN_LOCKOUT_SECONDS
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        ctx._lockout_until = 0.0
        assert ctx.verify_operational_pin("123456")
    finally:
        sec.USER_CONFIG_PATH = orig_path


# ------------------------------------------------------------------ #
# Master Recovery Key
# ------------------------------------------------------------------ #

def test_session_context_no_master_key_initially(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        assert ctx._master_recovery_key is None
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_reset_pin_with_recovery(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        ctx._master_recovery_key = "CVLK-7Q4M-2XKD-9B3T"
        ctx.reset_pin_with_recovery("CVLK-7Q4M-2XKD-9B3T", "654321")
        assert ctx.verify_operational_pin("654321")
        # Tier 2 reset promotes the owner tier.
        assert ctx.is_super_admin()
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_reset_pin_with_wrong_recovery_key(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        ctx._master_recovery_key = "CVLK-AAAA-BBBB-CCCC"
        with pytest.raises(ValidationError):
            ctx.reset_pin_with_recovery("CVLK-ZZZZ-ZZZZ-ZZZZ", "999999")
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_reset_pin_no_recovery_key(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        with pytest.raises(ValidationError):
            ctx.reset_pin_with_recovery("any-key", "999999")
    finally:
        sec.USER_CONFIG_PATH = orig_path


# ------------------------------------------------------------------ #
# Admin Status
# ------------------------------------------------------------------ #

def test_admin_status(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        status = ctx.get_admin_status()
        assert status["role"] == UserRole.SITE_CLERK.value
        assert status["failed_attempts"] >= 0
        assert "lockout_remaining_seconds" in status
        assert "pin_configured" in status
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_admin_status_after_pin_set(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        status = ctx.get_admin_status()
        assert status["pin_configured"] is True
    finally:
        sec.USER_CONFIG_PATH = orig_path


# ------------------------------------------------------------------ #
# ADMIN_ONLY_VIEWS
# ------------------------------------------------------------------ #

def test_admin_only_views_frozenset():
    from qs_engine.core.security import ADMIN_ONLY_VIEWS
    assert isinstance(ADMIN_ONLY_VIEWS, frozenset)
    assert "admin_setup" in ADMIN_ONLY_VIEWS
    assert "global_policy_editor" in ADMIN_ONLY_VIEWS
    assert len(ADMIN_ONLY_VIEWS) >= 2


# ------------------------------------------------------------------ #
# SessionContext Config Persistence
# ------------------------------------------------------------------ #

def test_operational_pin_persists(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        assert ctx._operational_pin_hash is not None
        assert ctx._operational_pin_salt is not None
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_session_context_role_change(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_role(UserRole.SUPER_ADMIN)
        assert ctx.role == UserRole.SUPER_ADMIN
        ctx.set_role(UserRole.SITE_CLERK)
        assert ctx.role == UserRole.SITE_CLERK
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_session_context_check_access_allowed(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        assert ctx.check_access("overview") is True
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_session_context_check_access_denied(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        with pytest.raises(ValidationError) as exc:
            ctx.check_access("admin_setup")
        assert "ADMIN" in str(exc.value)
    finally:
        sec.USER_CONFIG_PATH = orig_path


# ------------------------------------------------------------------ #
# Locked security parameters
#
# The product decision is explicit: operational PIN = 6-12 digits,
# lockout after exactly 5 consecutive failures, lockout window of
# 5 minutes. These tests pin the constants AND the observable
# behaviour, so any change to them fails loudly here first.
# ------------------------------------------------------------------ #

def test_security_parameters_locked_to_policy_values():
    from qs_engine.core import security
    # PIN length: 6-12 digits
    assert security.PIN_MIN_LEN == 6
    assert security.PIN_MAX_LEN == 12
    # Lockout: 5 consecutive failures -> 300 s (5 minutes)
    assert security.PIN_LOCKOUT_THRESHOLD == 5
    assert security.PIN_LOCKOUT_SECONDS == 300
    # Hashing cost stays put too (PBKDF2-HMAC-SHA256)
    assert security.PBKDF2_ITERATIONS == 100_000
    assert security.PBKDF2_SALT_LEN == 16


def test_pin_regex_accepts_exactly_6_to_12_digits():
    from qs_engine.core.security import PIN_RE
    assert PIN_RE.match("123456")            # minimum length accepted
    assert PIN_RE.match("123456789012")      # maximum length accepted
    assert not PIN_RE.match("12345")         # 5 digits: too short
    assert not PIN_RE.match("1234567890123")  # 13 digits: too long
    assert not PIN_RE.match("")              # empty
    assert not PIN_RE.match("abcdef")        # non-numeric
    assert not PIN_RE.match("12345a")        # mixed


def test_pin_bounds_accepted_and_rejected_end_to_end():
    ctx = SessionContext()
    with pytest.raises(ValidationError) as exc:
        ctx.set_operational_pin("12345")           # 5 digits
    assert "6-12 digits" in str(exc.value)
    with pytest.raises(ValidationError):
        ctx.set_operational_pin("1234567890123")   # 13 digits
    ctx.set_operational_pin("123456")              # 6 digits sets
    assert ctx.verify_operational_pin("123456")
    # A second set is a rotation: Tier 1 is refused without the owner key.
    with pytest.raises(ValidationError) as rotation:
        ctx.set_operational_pin("123456789012")
    assert "Master Recovery Key" in str(rotation.value)
    # The owner key rotates it, and 12 digits verify afterwards.
    ctx._master_recovery_key = "CVLK-AAAA-BBBB-CCCC"
    ctx.reset_pin_with_recovery("CVLK-AAAA-BBBB-CCCC", "123456789012")
    assert ctx.verify_operational_pin("123456789012")


def test_lockout_threshold_is_five_failures():
    from qs_engine.core.security import PIN_LOCKOUT_THRESHOLD
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    # Four wrong attempts (one short of the threshold): no lockout yet.
    for _ in range(PIN_LOCKOUT_THRESHOLD - 1):
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("000000")
    assert ctx._lockout_until is None
    assert ctx.get_admin_status()["lockout_remaining_seconds"] == 0
    # The fifth consecutive failure triggers the lockout.
    with pytest.raises(ValidationError):
        ctx.verify_operational_pin("000000")
    assert ctx._lockout_until is not None


def test_lockout_duration_is_five_minutes():
    import time
    from qs_engine.core.security import PIN_LOCKOUT_SECONDS
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    started = time.time()
    for _ in range(5):
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("000000")
    finished = time.time()
    assert PIN_LOCKOUT_SECONDS == 300
    # The window is exactly five minutes from the locking failure.
    assert started + PIN_LOCKOUT_SECONDS <= ctx._lockout_until
    assert ctx._lockout_until <= finished + PIN_LOCKOUT_SECONDS


def test_lockout_blocks_even_the_correct_pin():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    for _ in range(5):
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("000000")
    with pytest.raises(ValidationError) as exc:
        ctx.verify_operational_pin("123456")
    assert "locked out" in str(exc.value).lower()


def test_lockout_message_names_the_threshold():
    from qs_engine.core.security import PIN_LOCKOUT_THRESHOLD
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    for _ in range(PIN_LOCKOUT_THRESHOLD):
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("000000")
    with pytest.raises(ValidationError) as exc:
        ctx.verify_operational_pin("000000")
    message = str(exc.value)
    assert "locked out" in message.lower()
    assert f"{PIN_LOCKOUT_THRESHOLD} consecutive failed attempts" in message


def test_lockout_reported_remaining_stays_within_five_minutes():
    import re
    from qs_engine.core.security import PIN_LOCKOUT_THRESHOLD
    from qs_engine.core.security import PIN_LOCKOUT_SECONDS
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    for _ in range(PIN_LOCKOUT_THRESHOLD):
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("000000")
    # While locked, the status path surfaces the lockout error carrying
    # the remaining window; it must never exceed the five-minute cap.
    with pytest.raises(ValidationError) as exc:
        ctx.get_admin_status()
    message = str(exc.value)
    assert "locked out" in message.lower()
    match = re.search(r"locked out for (\d+) seconds", message)
    assert match, message
    remaining = int(match.group(1))
    assert 0 < remaining <= PIN_LOCKOUT_SECONDS


def test_malformed_pin_counts_toward_lockout():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    with pytest.raises(ValidationError) as exc:
        ctx.verify_operational_pin("12")   # too short: format error
    assert "Invalid PIN format" in str(exc.value)
    # A rejected format still consumes one throttled attempt.
    assert ctx._failed_pin_attempts == 1


def test_successful_verify_clears_attempt_counter_before_threshold():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    for _ in range(3):
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("000000")
    assert ctx._failed_pin_attempts == 3
    assert ctx.verify_operational_pin("123456") is True
    assert ctx._failed_pin_attempts == 0
    assert ctx._lockout_until is None


# ------------------------------------------------------------------ #
# Owner tiers: PIN unlock and master-key-only rotation
# ------------------------------------------------------------------ #

def test_unlock_with_pin_promotes_to_operational_admin():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    assert ctx.role == UserRole.SITE_CLERK
    assert ctx.unlock_with_pin("123456") == UserRole.OPERATIONAL_ADMIN
    assert ctx.is_admin()
    assert not ctx.is_super_admin()


def test_unlock_with_pin_is_throttled_like_verification():
    from qs_engine.core.security import PIN_LOCKOUT_THRESHOLD
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    for _ in range(PIN_LOCKOUT_THRESHOLD):
        with pytest.raises(ValidationError):
            ctx.unlock_with_pin("000000")
    with pytest.raises(ValidationError) as exc:
        ctx.unlock_with_pin("123456")
    assert "locked out" in str(exc.value).lower()
    assert ctx.role == UserRole.SITE_CLERK      # never promoted


def test_pin_rotation_requires_master_key_even_after_unlock():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    ctx.unlock_with_pin("123456")
    with pytest.raises(ValidationError) as exc:
        ctx.set_operational_pin("654321")
    assert "Master Recovery Key" in str(exc.value)
    # Tier 1 stays Tier 1: an unlock never grants security policy.
    assert ctx.role == UserRole.OPERATIONAL_ADMIN
    assert not ctx.is_super_admin()
    assert ctx.verify_operational_pin("123456")   # old PIN still the live one


def test_master_key_format_is_enforced():
    ctx = SessionContext()
    ctx._master_recovery_key = "CVLK-AAAA-BBBB-CCCC"
    for bad in ("secret", "CVLK-123", "cvlk-aaaa-bbbb-cccc",
                "CVLK-AAAA-BBBB", "CVLK-AAAA-BBBB-CCCC-DD"):
        with pytest.raises(ValidationError) as exc:
            ctx.reset_pin_with_recovery(bad, "123456")
        assert "CVLK" in str(exc.value)


# ------------------------------------------------------------------ #
# Signed master_admin.lic (Ed25519) and owner lockout recovery
# ------------------------------------------------------------------ #

def _write_signed_lic(path, *, master_key="CVLK-AAAA-BBBB-CCCC",
                      tamper=False):
    """Write a master_admin.lic signed by a throwaway owner key."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    from qs_engine.core.security import _canonical_license_body
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    payload = {"master_key": master_key,
               "public_key": base64.b64encode(public_raw).decode()}
    payload["signature"] = base64.b64encode(
        private.sign(_canonical_license_body(payload))).decode()
    if tamper:
        payload["master_key"] = "CVLK-ZZZZ-ZZZZ-ZZZZ"   # body no longer signed
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_master_admin_lic_signature_verified(tmp_path):
    ctx = SessionContext()
    lic = tmp_path / "master_admin.lic"
    _write_signed_lic(lic)
    assert ctx.load_master_recovery_key(lic) is True
    assert ctx._master_recovery_key == "CVLK-AAAA-BBBB-CCCC"
    assert ctx.get_admin_status()["master_key_configured"] is True


def test_master_admin_lic_tampered_or_unsigned_is_refused(tmp_path):
    ctx = SessionContext()
    tampered = tmp_path / "tampered.lic"
    _write_signed_lic(tampered, tamper=True)
    assert ctx.load_master_recovery_key(tampered) is False
    unsigned = tmp_path / "unsigned.lic"
    unsigned.write_text(json.dumps({"master_key": "CVLK-AAAA-BBBB-CCCC"}),
                        encoding="utf-8")
    assert ctx.load_master_recovery_key(unsigned) is False
    assert ctx.load_master_recovery_key(tmp_path / "missing.lic") is False
    assert ctx._master_recovery_key is None


def test_owner_license_clears_pin_lockout(tmp_path):
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    for _ in range(5):
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("000000")
    assert ctx._lockout_until is not None
    lic = tmp_path / "master_admin.lic"
    _write_signed_lic(lic)
    assert ctx.load_master_recovery_key(lic) is True
    assert ctx._failed_pin_attempts == 0
    assert ctx._lockout_until is None
    # The owner can now rotate the PIN, and the new one verifies.
    ctx.reset_pin_with_recovery("CVLK-AAAA-BBBB-CCCC", "654321")
    assert ctx.verify_operational_pin("654321")
    assert ctx.is_super_admin()


# ------------------------------------------------------------------ #
# Support & helpdesk (system.support_email in user_config.json)
# ------------------------------------------------------------------ #

def test_support_email_round_trip():
    ctx = SessionContext()
    assert ctx.support_email == ""
    assert ctx.set_support_email("  support@civolink.co.ke  ") == (
        "support@civolink.co.ke")
    assert SessionContext().support_email == "support@civolink.co.ke"


def test_support_email_validation_and_clearing():
    ctx = SessionContext()
    for bad in ("support", "support@", "@civolink.co.ke", "a b@c.com"):
        with pytest.raises(ValidationError):
            ctx.set_support_email(bad)
    # Clearing is always allowed.
    ctx.set_support_email("support@civolink.co.ke")
    assert ctx.set_support_email("") == ""
    assert SessionContext().support_email == ""


def test_admin_status_reports_tiers_and_support_desk():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    ctx.unlock_with_pin("123456")
    ctx.set_support_email("helpdesk@civolink.co.ke")
    status = ctx.get_admin_status()
    assert status["role"] == UserRole.OPERATIONAL_ADMIN.value
    assert status["is_admin"] is True
    assert status["is_super_admin"] is False
    assert status["support_email"] == "helpdesk@civolink.co.ke"
    assert status["pin_configured"] is True
    ctx.set_role(UserRole.SUPER_ADMIN)
    assert ctx.get_admin_status()["is_super_admin"] is True