"""Application-facing licensing service (no network at import/startup).

LicensingService translates provider outcomes into LicenseInfo
snapshots and owns the offline/grace policy:

- A cached ACTIVE record plus a retryable network failure yields
  OFFLINE_GRACE — a temporary outage is never reported as an
  invalid, expired, or revoked license.
- Non-retryable provider verdicts (expired/revoked/suspended/limit)
  are persisted as-is and reported honestly.
- Local expiry is checked from the cached ISO date without network.
- The offline/grace window is provider/policy data (cached
  ``grace_until`` when supplied), never a hard-coded application
  constant.

Enforcement policy (what unlicensed users may do) is intentionally
absent: that is a future product decision, not an architecture
default. The service only reports state.
"""

import datetime
import time
from typing import Dict, Optional

from qs_engine.licensing.models import LicenseInfo, LicenseState
from qs_engine.licensing.provider import LicensingProvider, NullProvider
from qs_engine.licensing.storage import LicenseStore

PRODUCT_NAME = "CIVOLINK QS"


def _now_epoch() -> int:
    return int(time.time())


def _key_hint(key: str) -> str:
    """Non-sensitive key reference (last 4 chars) for record matching."""
    text = str(key or "").strip()
    return text[-4:] if text else ""


def _locally_expired(expires: Optional[str]) -> bool:
    """True when a cached ISO expiry date has passed (no network)."""
    text = str(expires or "").strip()
    if not text:
        return False
    try:
        return datetime.date.fromisoformat(text) < datetime.date.today()
    except ValueError:
        return False


class LicensingService:
    """License state machine over a provider + local store."""

    def __init__(self, provider: Optional[LicensingProvider] = None,
                 store: Optional[LicenseStore] = None):
        self.provider = provider or NullProvider()
        self.store = store or LicenseStore()

    # -- snapshots ------------------------------------------------------
    def snapshot(self) -> LicenseInfo:
        """Current state without network (startup-safe)."""
        record = self.store.load()
        if not record:
            return LicenseInfo(product=PRODUCT_NAME,
                               state=LicenseState.UNLICENSED,
                               message="This copy is not activated.")
        state = self._record_state(record)
        return self._info_from_record(record, state)

    # -- operations -----------------------------------------------------
    def activate(self, key: str,
                 device_label: str = "") -> LicenseInfo:
        """Activate a key; persists only successful activations."""
        if not str(key or "").strip():
            return LicenseInfo(
                product=PRODUCT_NAME, state=LicenseState.VALIDATION_ERROR,
                message="Enter a license key first.")
        result = self.provider.activate(str(key).strip(),
                                        device_label=device_label)
        if not result.ok:
            return LicenseInfo(
                product=PRODUCT_NAME, state=result.state,
                organization=result.organization,
                expires=result.expires,
                device_activated=result.device_activated,
                device_label=result.device_label,
                last_checked=_now_epoch(), message=result.message)
        record = {
            "provider": self.provider.provider_name,
            "key_hint": _key_hint(key),
            "state": LicenseState.ACTIVE.value,
            "organization": result.organization,
            "expires": result.expires,
            "device_activated": result.device_activated,
            "device_label": result.device_label,
            "artifact": dict(result.artifact or {}),
            "updated_at": _now_epoch(),
        }
        self.store.save(record)
        return self._info_from_record(record, LicenseState.ACTIVE,
                                      message=result.message)

    def refresh(self) -> LicenseInfo:
        """Re-validate the stored record against the provider."""
        record = self.store.load()
        if not record:
            return self.snapshot()
        try:
            result = self.provider.validate(record)
        except Exception as exc:
            return LicenseInfo(
                product=PRODUCT_NAME, state=LicenseState.VALIDATION_ERROR,
                message=f"License check failed: {exc}")
        if result.ok:
            record = dict(record)
            record["state"] = LicenseState.ACTIVE.value
            record["organization"] = result.organization
            record["expires"] = result.expires
            record["device_activated"] = result.device_activated
            record["device_label"] = result.device_label
            if result.artifact:
                merged = dict(record.get("artifact") or {})
                merged.update(result.artifact)
                record["artifact"] = merged
            record["updated_at"] = _now_epoch()
            self.store.save(record)
            return self._info_from_record(record, LicenseState.ACTIVE,
                                          message=result.message)
        if result.retryable:
            # Temporary outage: grace on a cached ACTIVE record, plain
            # network error otherwise — never downgrade to invalid.
            if self._record_state(record) == LicenseState.ACTIVE:
                return self._info_from_record(
                    record, LicenseState.OFFLINE_GRACE, offline=True,
                    message=result.message)
            return LicenseInfo(
                product=PRODUCT_NAME, state=LicenseState.NETWORK_ERROR,
                last_checked=_now_epoch(), message=result.message)
        record = dict(record)
        record["state"] = result.state.value
        record["updated_at"] = _now_epoch()
        self.store.save(record)
        return self._info_from_record(record, result.state,
                                      message=result.message)

    def deactivate(self) -> LicenseInfo:
        """Release this device activation where the provider allows."""
        if not self.provider.supports_deactivation:
            return LicenseInfo(
                product=PRODUCT_NAME,
                state=LicenseState.VALIDATION_ERROR,
                message="Deactivation is not supported by this "
                        "licensing provider.")
        record = self.store.load() or {}
        try:
            result = self.provider.deactivate(record)
        except Exception as exc:
            return LicenseInfo(
                product=PRODUCT_NAME, state=LicenseState.VALIDATION_ERROR,
                message=f"Deactivation failed: {exc}")
        if result.ok:
            self.store.clear()
            return LicenseInfo(
                product=PRODUCT_NAME, state=LicenseState.UNLICENSED,
                message=result.message or
                "This device was deactivated.")
        return LicenseInfo(
            product=PRODUCT_NAME, state=result.state,
            last_checked=_now_epoch(), message=result.message)

    # -- internals ------------------------------------------------------
    def _record_state(self, record: Dict) -> LicenseState:
        try:
            state = LicenseState(str(record.get("state", "UNLICENSED")))
        except ValueError:
            return LicenseState.VALIDATION_ERROR
        if state == LicenseState.ACTIVE and _locally_expired(
                record.get("expires")):
            return LicenseState.EXPIRED
        return state

    def _info_from_record(self, record: Dict, state: LicenseState,
                          offline: bool = False,
                          message: str = "") -> LicenseInfo:
        return LicenseInfo(
            product=PRODUCT_NAME, state=state,
            organization=str(record.get("organization", "")),
            expires=record.get("expires"),
            device_activated=bool(record.get("device_activated", False)),
            device_label=str(record.get("device_label", "")),
            offline=offline, last_checked=_now_epoch(), message=message)
