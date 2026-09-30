"""Provider-neutral licensing interface + built-in doubles + Keygen.

LicensingProvider is the only contract the application depends on.
NullProvider (shipped default) honestly reports ACTIVATION_REQUIRED
without network I/O. FakeLicensingProvider is a clearly marked
test/dev double — never a real service. KeygenProvider connects to
Keygen.sh with runtime-supplied account materials only (no embedded
secrets); see docs/LICENSING.md for configuration.
"""

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Dict, Optional

from qs_engine.licensing.models import LicenseState, ProviderResult

#: Keygen API base (overridable per provider instance).
KEYGEN_API_BASE = "https://api.keygen.sh"

#: Transport timeout, integer seconds (float ban covers this package).
KEYGEN_TIMEOUT = 15

#: Response codes treated as activation-limit conditions (best-effort
#: mapping of Keygen validation/activation error codes).
_LIMIT_CODES = frozenset({
    "TOO_MANY_MACHINES", "NO_MACHINES", "FINGERPRINT_TAKEN",
    "MACHINE_LIMIT_EXCEEDED",
})

#: Response codes treated as suspension/revocation.
_REVOKED_CODES = frozenset({"BANNED"})
_SUSPENDED_CODES = frozenset({"SUSPENDED"})


class LicensingProvider(ABC):
    """Application-facing provider contract."""

    provider_name: str = "unconfigured"
    supports_deactivation: bool = False

    @abstractmethod
    def activate(self, key: str,
                 device_label: str = "") -> ProviderResult:
        """Activate a license key for this device."""
        raise NotImplementedError

    @abstractmethod
    def validate(self, record: Dict) -> ProviderResult:
        """Re-validate a stored activation record."""
        raise NotImplementedError

    @abstractmethod
    def deactivate(self, record: Dict) -> ProviderResult:
        """Release this device activation (if supported)."""
        raise NotImplementedError

    def get_status(self, record: Optional[Dict]) -> ProviderResult:
        """Local status read without network (default implementation)."""
        if not record:
            return ProviderResult(
                ok=False, state=LicenseState.UNLICENSED,
                message="No license on file.")
        return ProviderResult(
            ok=True, state=LicenseState.ACTIVE,
            organization=str(record.get("organization", "")),
            expires=record.get("expires"),
            device_activated=bool(record.get("device_activated", False)),
            device_label=str(record.get("device_label", "")),
            message="License on file (unverified).")

    def get_license_info(self, record: Optional[Dict]) -> Dict:
        """Customer-safe info mapping for UI rendering."""
        result = self.get_status(record)
        return {
            "organization": result.organization,
            "expires": result.expires,
            "device_activated": result.device_activated,
            "device_label": result.device_label,
            "state": result.state.value,
        }


class NullProvider(LicensingProvider):
    """Shipped default: no provider configured, no network I/O.

    Every operation reports that activation is required. This is an
    honest unlicensed state, not a mock of a real service.
    """

    provider_name = "none"
    supports_deactivation = False

    def activate(self, key: str,
                 device_label: str = "") -> ProviderResult:
        _ = key, device_label
        return ProviderResult(
            ok=False, state=LicenseState.ACTIVATION_REQUIRED,
            message="No licensing provider is configured in this "
                    "build. Contact your CIVOLINK administrator for "
                    "a license key.")

    def validate(self, record: Dict) -> ProviderResult:
        _ = record
        return ProviderResult(
            ok=False, state=LicenseState.UNLICENSED,
            message="No license on file.")

    def deactivate(self, record: Dict) -> ProviderResult:
        _ = record
        return ProviderResult(
            ok=False, state=LicenseState.VALIDATION_ERROR,
            message="Deactivation is not supported by this provider.")


class FakeLicensingProvider(LicensingProvider):
    """Scripted test/dev double. NOT a real licensing service.

    Maps exact key strings to canned ProviderResults so the suite can
    exercise every application state without network access or a
    licensing account. Must never ship as a genuine provider.
    """

    provider_name = "fake"
    supports_deactivation = True

    def __init__(self, responses=None, network_down: bool = False):
        """responses: {key_string: ProviderResult}; unknown keys are
        invalid. network_down: every operation reports a retryable
        network failure instead."""
        self._responses = dict(responses or {})
        self.network_down = network_down

    def _offline(self) -> ProviderResult:
        return ProviderResult(
            ok=False, state=LicenseState.NETWORK_ERROR,
            message="Could not reach the licensing service.",
            retryable=True)

    def activate(self, key: str,
                 device_label: str = "") -> ProviderResult:
        if self.network_down:
            return self._offline()
        result = self._responses.get(str(key or "").strip())
        if result is None:
            return ProviderResult(
                ok=False, state=LicenseState.VALIDATION_ERROR,
                message="That license key was not recognized.")
        return result

    def validate(self, record: Dict) -> ProviderResult:
        if self.network_down:
            return self._offline()
        hint = str((record or {}).get("key_hint", ""))
        for key, result in self._responses.items():
            if hint and (key == hint or key.endswith(hint)):
                return result
        return ProviderResult(
            ok=False, state=LicenseState.REVOKED,
            message="This activation is no longer recognized.")

    def deactivate(self, record: Dict) -> ProviderResult:
        _ = record
        if self.network_down:
            return self._offline()
        return ProviderResult(
            ok=True, state=LicenseState.UNLICENSED,
            message="This device was deactivated.")


def _b64_decode(text: str) -> bytes:
    """Base64 (standard or urlsafe) to bytes; raises ValueError."""
    import base64
    raw = str(text or "").strip()
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.b64decode(padded, validate=False)
    except Exception:
        return base64.urlsafe_b64decode(padded)


def _public_key_bytes(public_key) -> bytes:
    """Normalize an Ed25519 public key to 32 raw bytes.

    Accepts base64 (standard/urlsafe) of the raw key, or a PEM
    SubjectPublicKeyInfo document (trailing 32 bytes). Anything else
    raises ValueError — never guess at key material.
    """
    if isinstance(public_key, (bytes, bytearray)):
        raw = bytes(public_key)
    else:
        text = str(public_key or "").strip()
        if "BEGIN PUBLIC KEY" in text:
            import base64
            body = "".join(
                line.strip() for line in text.splitlines()
                if "BEGIN" not in line and "END" not in line)
            raw = base64.b64decode(body)
            raw = raw[-32:]
        else:
            raw = _b64_decode(text)
    if len(raw) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes.")
    return raw


def verify_signature(public_key, body, signature) -> bool:
    """Ed25519 verify (body, signature) against a public key.

    Inputs accept base64 text or bytes. Returns False for any
    mismatch, malformed material, or missing cryptography backend —
    unverifiable means invalid (fail closed, never an exception).
    """
    try:
        key_bytes = _public_key_bytes(public_key)
        body_bytes = (_b64_decode(body) if isinstance(body, str)
                      else bytes(body))
        sig_bytes = (_b64_decode(signature) if isinstance(signature, str)
                     else bytes(signature))
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(
            sig_bytes, body_bytes)
        return True
    except Exception:
        return False


class _KeygenTransportError(Exception):
    """Retryable transport failure (DNS, refused, timeout, bad JSON)."""


class _KeygenApiError(Exception):
    """Keygen API rejection (parsed error code + detail)."""

    def __init__(self, status, code="", detail=""):
        super().__init__(detail or f"Keygen error {status}")
        self.status = status
        self.code = code
        self.detail = detail


def _api_error_from(exc: urllib.error.HTTPError) -> _KeygenApiError:
    """Parse a Keygen JSON:API error envelope (fail closed on garbage)."""
    try:
        payload = json.loads(exc.read().decode("utf-8") or "{}")
    except ValueError:
        payload = {}
    errors = payload.get("errors") if isinstance(payload, dict) else []
    first = errors[0] if isinstance(errors, list) and errors else {}
    if not isinstance(first, dict):
        first = {}
    code = str(first.get("code", "") or "")
    detail = str(first.get("detail", "") or f"HTTP {exc.code}")
    return _KeygenApiError(exc.code, code, detail)


class KeygenProvider(LicensingProvider):
    """Keygen.sh adapter. No embedded secrets.

    Configuration is runtime-supplied only (constructor args or
    KEYGEN_ACCOUNT_ID / KEYGEN_PUBLIC_KEY environment variables):
      account_id  – Keygen account slug/ID (public identifier).
      public_key  – Ed25519 public key for offline artifact
                    verification (public verification material).
      api_base    – API root override (default KEYGEN_API_BASE).
      timeout     – integer seconds per API call.
      fingerprint – machine fingerprint supplied by the host. No
                    hardware fingerprinting is implemented here; use
                    the provider-recommended mechanism in production.

    Keygen API v1 endpoints used (JSON:API):
      POST   /v1/accounts/{account}/licenses/actions/validate-key
      POST   /v1/accounts/{account}/machines            (activation)
      DELETE /v1/accounts/{account}/machines/{id}       (deactivation)
    Machine calls authenticate with the license key itself
    (``Authorization: License <key>``), so no admin token is ever
    needed or accepted anywhere in this adapter.
    """

    provider_name = "keygen"
    supports_deactivation = True

    def __init__(self, account_id=None, public_key=None,
                 api_base=None, timeout=KEYGEN_TIMEOUT,
                 fingerprint=""):
        self.account_id = (
            account_id or os.environ.get("KEYGEN_ACCOUNT_ID", "")
            or "").strip() or None
        self.public_key = (
            public_key or os.environ.get("KEYGEN_PUBLIC_KEY", "")
            or "") or None
        self.api_base = (api_base or KEYGEN_API_BASE).rstrip("/")
        self.timeout = timeout
        self.fingerprint = str(fingerprint or "")

    # -- transport ----------------------------------------------------
    def _post(self, path, payload, key=None) -> Dict:
        url = f"{self.api_base}/v1/accounts/{self.account_id}{path}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/vnd.api+json",
                     "Accept": "application/vnd.api+json"})
        if key:
            request.add_header("Authorization",
                               f"License {key.strip()}")
        try:
            with urllib.request.urlopen(
                    request, timeout=self.timeout) as response:
                return json.loads(
                    response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise _api_error_from(exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError,
                ValueError) as exc:
            raise _KeygenTransportError(str(exc)) from exc

    def _delete(self, path, key) -> bool:
        """DELETE a machine; missing-already counts as released."""
        url = f"{self.api_base}/v1/accounts/{self.account_id}{path}"
        request = urllib.request.Request(
            url, method="DELETE",
            headers={"Accept": "application/vnd.api+json",
                     "Authorization": f"License {key.strip()}"})
        try:
            with urllib.request.urlopen(
                    request, timeout=self.timeout):
                return True
        except urllib.error.HTTPError as exc:
            return exc.code == 404
        except (urllib.error.URLError, TimeoutError,
                OSError) as exc:
            raise _KeygenTransportError(str(exc)) from exc

    # -- response mapping ----------------------------------------------
    @staticmethod
    def _normalize_expiry(value) -> Optional[str]:
        """ISO datetime to ISO date (service compares plain dates)."""
        text = str(value or "").strip()
        if not text:
            return None
        return text.split("T")[0]

    @staticmethod
    def _organization_of(attributes: Dict) -> str:
        metadata = attributes.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        for field in ("organization", "company", "customer"):
            value = str(metadata.get(field, "") or "").strip()
            if value:
                return value
        return str(attributes.get("email", "") or "").strip()

    @classmethod
    def _verdict(cls, valid, code,
                 detail) -> ProviderResult:
        """Map a Keygen validate-key meta verdict (fail closed)."""
        code = str(code or "").strip().upper()
        detail = str(detail or "").strip()
        if valid is True or code == "VALID":
            return ProviderResult(ok=True, state=LicenseState.ACTIVE)
        if code == "EXPIRED":
            return ProviderResult(ok=False, state=LicenseState.EXPIRED,
                                  message=detail or "License expired.")
        if code in _SUSPENDED_CODES:
            return ProviderResult(ok=False, state=LicenseState.SUSPENDED,
                                  message=detail or "License suspended.")
        if code in _REVOKED_CODES:
            return ProviderResult(ok=False, state=LicenseState.REVOKED,
                                  message=detail or "License revoked.")
        if code in _LIMIT_CODES:
            return ProviderResult(
                ok=False, state=LicenseState.ACTIVATION_LIMIT_REACHED,
                message=detail or "Activation limit reached.")
        return ProviderResult(
            ok=False, state=LicenseState.VALIDATION_ERROR,
            message=detail or f"License not valid ({code or 'UNKNOWN'}).")

    @staticmethod
    def _certificate_of(document: Dict) -> Dict:
        """Best-effort signed-artifact extraction for offline use.

        Looks for a certificate body/signature pair under documented
        Keygen license-file keys without inventing structure; absent
        keys simply mean offline crypto is unavailable for the record.
        """
        if not isinstance(document, dict):
            return {}
        candidates = []
        data = document.get("data")
        if isinstance(data, dict):
            attributes = data.get("attributes")
            if isinstance(attributes, dict):
                candidates.append(attributes.get("certificate"))
                candidates.append(attributes.get("cert"))
        meta = document.get("meta")
        if isinstance(meta, dict):
            candidates.append(meta.get("certificate"))
            candidates.append(meta.get("cert"))
        for candidate in candidates:
            if isinstance(candidate, dict):
                body = candidate.get("body") or candidate.get("data")
                signature = candidate.get("signature")
                if body and signature:
                    return {"body": body, "signature": signature}
            elif isinstance(candidate, str) and "." in candidate:
                body, _, signature = candidate.partition(".")
                if body and signature:
                    return {"body": body, "signature": signature}
        return {}

    # -- contract -------------------------------------------------------
    def _configured(self) -> Optional[ProviderResult]:
        if not self.account_id:
            return ProviderResult(
                ok=False, state=LicenseState.VALIDATION_ERROR,
                message="Keygen account is not configured "
                        "(KEYGEN_ACCOUNT_ID). No request was sent.")
        return None

    def activate(self, key: str,
                 device_label: str = "") -> ProviderResult:
        key = str(key or "").strip()
        if not key:
            return ProviderResult(
                ok=False, state=LicenseState.VALIDATION_ERROR,
                message="Enter a license key first.")
        missing = self._configured()
        if missing is not None:
            return missing
        scope = {}
        if self.fingerprint:
            scope = {"fingerprint": self.fingerprint}
        try:
            document = self._post(
                "/licenses/actions/validate-key",
                {"meta": {"key": key, "scope": scope}})
        except _KeygenTransportError as exc:
            return ProviderResult(
                ok=False, state=LicenseState.NETWORK_ERROR,
                message=f"Could not reach Keygen: {exc}",
                retryable=True)
        except _KeygenApiError as exc:
            return self._verdict(False, exc.code, exc.detail)
        meta = document.get("meta") if isinstance(document, dict) else {}
        meta = meta if isinstance(meta, dict) else {}
        verdict = self._verdict(meta.get("valid"), meta.get("code"),
                                meta.get("detail"))
        if not verdict.ok:
            return verdict
        data = document.get("data") if isinstance(document, dict) else {}
        data = data if isinstance(data, dict) else {}
        license_id = str(data.get("id", "") or "")
        attributes = data.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        name = (str(device_label or "").strip() or self.fingerprint
                or "civolink-device")
        machine_id = ""
        try:
            machine = self._post(
                "/machines",
                {"data": {"type": "machines",
                          "attributes": {
                              "fingerprint": self.fingerprint,
                              "name": name},
                          "relationships": {
                              "license": {
                                  "data": {"type": "licenses",
                                           "id": license_id}}}}},
                key=key)
            machine_data = machine.get("data") if isinstance(
                machine, dict) else {}
            machine_id = str((machine_data or {}).get("id", "") or "")
        except _KeygenTransportError as exc:
            return ProviderResult(
                ok=False, state=LicenseState.NETWORK_ERROR,
                message=f"Key is valid but the device could not be "
                        f"registered: {exc}",
                retryable=True)
        except _KeygenApiError as exc:
            if (exc.code.upper() in _LIMIT_CODES
                    or "taken" in exc.detail.lower()):
                return ProviderResult(
                    ok=False,
                    state=LicenseState.ACTIVATION_LIMIT_REACHED,
                    message=exc.detail or "Activation limit reached.")
            return ProviderResult(
                ok=False, state=LicenseState.VALIDATION_ERROR,
                message=exc.detail or "Device registration failed.")
        certificate = self._certificate_of(document)
        return ProviderResult(
            ok=True, state=LicenseState.ACTIVE,
            organization=self._organization_of(attributes),
            expires=self._normalize_expiry(attributes.get("expiry")),
            device_activated=True,
            device_label=name or self.fingerprint,
            message="License activated for this device.",
            artifact={"key": key, "license_id": license_id,
                      "machine_id": machine_id,
                      "certificate_body": certificate.get("body"),
                      "certificate_signature": certificate.get(
                          "signature")})

    def validate(self, record: Dict) -> ProviderResult:
        record = record if isinstance(record, dict) else {}
        artifact = record.get("artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        key = str(artifact.get("key", "") or "")
        missing = self._configured()
        if missing is not None:
            if self._offline_backstop(artifact):
                return ProviderResult(
                    ok=False, state=LicenseState.NETWORK_ERROR,
                    message="Keygen account is not configured; "
                            "offline artifact applies.",
                    retryable=True)
            return missing
        if not key:
            return ProviderResult(
                ok=False, state=LicenseState.VALIDATION_ERROR,
                message="No license key on file for re-validation.")
        scope = {}
        if self.fingerprint:
            scope = {"fingerprint": self.fingerprint}
        try:
            document = self._post(
                "/licenses/actions/validate-key",
                {"meta": {"key": key, "scope": scope}})
        except _KeygenTransportError as exc:
            return self._grace_or_error(artifact, str(exc))
        except _KeygenApiError as exc:
            return self._verdict(False, exc.code, exc.detail)
        meta = document.get("meta") if isinstance(document, dict) else {}
        meta = meta if isinstance(meta, dict) else {}
        verdict = self._verdict(meta.get("valid"), meta.get("code"),
                                meta.get("detail"))
        if not verdict.ok:
            return verdict
        data = document.get("data") if isinstance(document, dict) else {}
        data = data if isinstance(data, dict) else {}
        attributes = data.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        certificate = self._certificate_of(document)
        if certificate:
            artifact = dict(artifact)
            artifact["certificate_body"] = certificate.get("body")
            artifact["certificate_signature"] = certificate.get(
                "signature")
        return ProviderResult(
            ok=True, state=LicenseState.ACTIVE,
            organization=self._organization_of(attributes),
            expires=self._normalize_expiry(attributes.get("expiry")),
            device_activated=True,
            device_label=str(record.get("device_label", "")),
            message="License re-validated.",
            artifact=artifact)

    def _offline_backstop(self, artifact: Dict) -> bool:
        """Cached signed artifact currently verifies (no network)."""
        body = artifact.get("certificate_body")
        signature = artifact.get("certificate_signature")
        if not (body and signature and self.public_key):
            return False
        return verify_signature(self.public_key, body, signature)

    def _grace_or_error(self, artifact: Dict,
                        detail: str) -> ProviderResult:
        """Network failure: cryptographic backstop decides the verdict.

        A currently-verifying cached artifact (or one inside its
        provider-supplied grace window) degrades to a retryable
        network error so the service holds OFFLINE_GRACE; an expired
        cache or a tampered artifact fails closed instead.
        """
        body = artifact.get("certificate_body")
        signature = artifact.get("certificate_signature")
        if body and signature and self.public_key:
            if verify_signature(self.public_key, body, signature):
                return ProviderResult(
                    ok=False, state=LicenseState.NETWORK_ERROR,
                    message=f"Could not reach Keygen: {detail}",
                    retryable=True)
            return ProviderResult(
                ok=False, state=LicenseState.VALIDATION_ERROR,
                message="Stored license artifact failed verification.")
        grace_until = artifact.get("grace_until")
        try:
            import time as _time
            if grace_until is not None and int(grace_until) >= int(
                    _time.time()):
                return ProviderResult(
                    ok=False, state=LicenseState.NETWORK_ERROR,
                    message=f"Could not reach Keygen: {detail}",
                    retryable=True)
        except (TypeError, ValueError):
            pass
        return ProviderResult(
            ok=False, state=LicenseState.NETWORK_ERROR,
            message=f"Could not reach Keygen: {detail}",
            retryable=True)

    def deactivate(self, record: Dict) -> ProviderResult:
        record = record if isinstance(record, dict) else {}
        artifact = record.get("artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        missing = self._configured()
        if missing is not None:
            return missing
        key = str(artifact.get("key", "") or "")
        machine_id = str(artifact.get("machine_id", "") or "")
        if not key or not machine_id:
            return ProviderResult(
                ok=False, state=LicenseState.VALIDATION_ERROR,
                message="No device activation on file to release.")
        try:
            released = self._delete(f"/machines/{machine_id}", key)
        except _KeygenTransportError as exc:
            return ProviderResult(
                ok=False, state=LicenseState.NETWORK_ERROR,
                message=f"Could not reach Keygen: {exc}",
                retryable=True)
        if released:
            return ProviderResult(
                ok=True, state=LicenseState.UNLICENSED,
                message="This device was deactivated.")
        return ProviderResult(
            ok=False, state=LicenseState.VALIDATION_ERROR,
            message="Deactivation was not accepted.")
