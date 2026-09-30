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


def test_admin_role_blocks_non_admin():
    ctx = SessionContext()
    ctx.set_role(UserRole.ADMIN)
    assert ctx.is_admin()

    # Non-admin should be blocked from admin views
    ctx2 = SessionContext()
    with pytest.raises(ValidationError):
        ctx2.check_access("admin_setup")


def test_estimator_role_blocks_admin():
    ctx = SessionContext()
    ctx.set_role(UserRole.ESTIMATOR)
    assert not ctx.is_admin()
    with pytest.raises(ValidationError):
        ctx.check_access("global_policy_editor")


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
        ctx._master_recovery_key = "super-secret-recovery-key"
        ctx.reset_pin_with_recovery("super-secret-recovery-key", "654321")
        assert ctx.verify_operational_pin("654321")
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
        ctx._master_recovery_key = "correct-key"
        with pytest.raises(ValidationError):
            ctx.reset_pin_with_recovery("wrong-key", "999999")
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
        ctx.set_role(UserRole.ADMIN)
        assert ctx.role == UserRole.ADMIN
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
    ctx.set_operational_pin("123456789012")        # 12 digits sets
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