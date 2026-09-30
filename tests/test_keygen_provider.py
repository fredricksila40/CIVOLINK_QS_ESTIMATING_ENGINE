"""Keygen adapter tests (Phase 23): HTTP-mocked, fully offline.

Transport is faked at urllib.request.urlopen; Ed25519 keypairs are
generated at test runtime (never committed). No Keygen account, no
network, no secrets anywhere in this file.
"""

import base64
import io
import json
import urllib.error
from pathlib import Path
from unittest import mock

from qs_engine.licensing.models import LicenseState
from qs_engine.licensing.provider import (
    KeygenProvider,
    verify_signature,
)
from qs_engine.licensing.service import LicensingService
from qs_engine.licensing.storage import LicenseStore

ACCOUNT = "test-account-1"


def _keypair():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    from cryptography.hazmat.primitives import serialization
    raw = public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    return private, base64.b64encode(raw).decode("ascii")


def _signed(private, body: bytes):
    signature = private.sign(body)
    return (base64.b64encode(body).decode("ascii"),
            base64.b64encode(signature).decode("ascii"))


class _Resp:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(code, keygen_code, detail):
    payload = {"errors": [{"code": keygen_code, "detail": detail}]}
    return urllib.error.HTTPError(
        "https://api.keygen.sh/x", code, "Error", {}, io.BytesIO(
            json.dumps(payload).encode("utf-8")))


def _validate_doc(valid=True, code="VALID", license_id="lic-1",
                  expiry="2030-06-30T00:00:00.000Z",
                  detail=""):
    return {
        "data": {"id": license_id, "type": "licenses",
                 "attributes": {
                     "expiry": expiry,
                     "email": "ops@demo.tld",
                     "metadata": {"organization": "Demo Builders"}}},
        "meta": {"valid": valid, "code": code, "detail": detail},
    }


def _machine_doc(machine_id="mac-9"):
    return {"data": {"id": machine_id, "type": "machines"}}


def _provider(**kwargs):
    params = {"account_id": ACCOUNT, "fingerprint": "test-fp"}
    params.update(kwargs)
    return KeygenProvider(**params)


def _service(provider, tmp_path):
    return LicensingService(
        provider=provider,
        store=LicenseStore(path=tmp_path / "license.json"))


# --- configuration safety ----------------------------------------------------

def test_unconfigured_provider_sends_no_network():
    provider = KeygenProvider(account_id=None)
    with mock.patch("urllib.request.urlopen") as urlopen:
        result = provider.activate("SOME-KEY")
    urlopen.assert_not_called()
    assert result.ok is False
    assert result.state == LicenseState.VALIDATION_ERROR


def test_provider_defaults_carry_no_credentials():
    provider = KeygenProvider(account_id=None)
    assert provider.account_id is None
    assert provider.public_key is None
    assert provider.supports_deactivation is True


def test_no_admin_tokens_or_secrets_in_adapter():
    source = Path(__file__).parent.parent.joinpath(
        "qs_engine", "licensing", "provider.py").read_text(
            encoding="utf-8")
    for token in ("sk_live_", "sk_test_", "Bearer ", "admin_token",
                  "private_key", "webhook_secret"):
        assert token not in source, token
    assert "Authorization" in source  # license-key scheme only


# --- activation ---------------------------------------------------------------

def test_activate_success_persists_artifact(tmp_path):
    provider = _provider()
    bodies = []

    def fake_urlopen(request, timeout=None):
        bodies.append(json.loads(request.data.decode("utf-8")))
        if "/machines" in request.full_url:
            return _Resp(_machine_doc())
        return _Resp(_validate_doc())

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.activate("KEY-123")
    assert result.ok is True and result.state == LicenseState.ACTIVE
    assert result.organization == "Demo Builders"
    assert result.expires == "2030-06-30"  # date part normalized
    assert result.device_activated is True
    assert result.artifact["license_id"] == "lic-1"
    assert result.artifact["machine_id"] == "mac-9"
    assert result.artifact["key"] == "KEY-123"
    assert bodies[0]["meta"]["key"] == "KEY-123"
    assert bodies[0]["meta"]["scope"] == {"fingerprint": "test-fp"}


def test_activate_uses_license_key_auth_not_admin_token():
    provider = _provider()
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["auth"] = request.get_header("Authorization")
        if "/machines" in request.full_url:
            return _Resp(_machine_doc())
        return _Resp(_validate_doc())

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.activate("KEY-123")
    assert seen["auth"] == "License KEY-123"


def test_activate_invalid_key():
    provider = _provider()
    with mock.patch("urllib.request.urlopen",
                    return_value=_Resp(_validate_doc(
                        valid=False, code="NOT_FOUND",
                        detail="not found"))):
        result = provider.activate("NOPE")
    assert result.ok is False
    assert result.state == LicenseState.VALIDATION_ERROR


def test_activate_state_mapping():
    cases = (("EXPIRED", LicenseState.EXPIRED),
             ("SUSPENDED", LicenseState.SUSPENDED),
             ("BANNED", LicenseState.REVOKED),
             ("TOO_MANY_MACHINES",
              LicenseState.ACTIVATION_LIMIT_REACHED),
             ("SOMETHING_ELSE", LicenseState.VALIDATION_ERROR))
    for code, expected in cases:
        provider = _provider()
        with mock.patch("urllib.request.urlopen",
                        return_value=_Resp(_validate_doc(
                            valid=False, code=code))):
            assert provider.activate("K").state is expected, code


def test_activate_network_failure_is_retryable():
    provider = _provider()
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("down")):
        result = provider.activate("KEY-123")
    assert result.state == LicenseState.NETWORK_ERROR
    assert result.retryable is True


def test_activate_machine_taken_maps_to_limit():
    provider = _provider()

    def fake_urlopen(request, timeout=None):
        if "/machines" in request.full_url:
            raise _http_error(422, "FINGERPRINT_TAKEN",
                              "fingerprint is taken")
        return _Resp(_validate_doc())

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.activate("KEY-123")
    assert result.state == LicenseState.ACTIVATION_LIMIT_REACHED


def test_activate_blank_key_never_calls_network():
    provider = _provider()
    with mock.patch("urllib.request.urlopen") as urlopen:
        result = provider.activate("   ")
    urlopen.assert_not_called()
    assert result.state == LicenseState.VALIDATION_ERROR


# --- offline cryptography ------------------------------------------------------

def test_verify_signature_round_trip():
    private, pub_b64 = _keypair()
    body, sig = _signed(private, b"license-body-1")
    assert verify_signature(pub_b64, body, sig) is True
    assert verify_signature(pub_b64, body, sig + "A") is False


def test_verify_signature_wrong_key_and_garbage():
    private, _ = _keypair()
    _, other_pub = _keypair()
    body, sig = _signed(private, b"license-body-1")
    assert verify_signature(other_pub, body, sig) is False
    assert verify_signature("!!!", body, sig) is False
    assert verify_signature(other_pub, body, "!!!") is False


def test_verify_signature_pem_public_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    private = Ed25519PrivateKey.generate()
    pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    body, sig = _signed(private, b"pem-body")
    assert verify_signature(pem, body, sig) is True


# --- validate / grace ------------------------------------------------------------

def test_validate_online_success(tmp_path):
    private, pub_b64 = _keypair()
    body, sig = _signed(private, b"cert-1")
    doc = _validate_doc()
    doc["meta"]["certificate"] = {"body": body, "signature": sig}
    provider = _provider(public_key=pub_b64)
    record = {"artifact": {"key": "KEY-123"}}
    with mock.patch("urllib.request.urlopen",
                    return_value=_Resp(doc)):
        result = provider.validate(record)
    assert result.ok is True and result.state == LicenseState.ACTIVE
    assert result.artifact["certificate_body"] == body


def test_validate_network_failure_with_good_cache_is_retryable(tmp_path):
    private, pub_b64 = _keypair()
    body, sig = _signed(private, b"cert-1")
    provider = _provider(public_key=pub_b64)
    record = {"artifact": {"key": "KEY-123",
                           "certificate_body": body,
                           "certificate_signature": sig}}
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("down")):
        result = provider.validate(record)
    assert result.state == LicenseState.NETWORK_ERROR
    assert result.retryable is True


def test_validate_tampered_cache_fails_closed():
    private, pub_b64 = _keypair()
    body, sig = _signed(private, b"cert-1")
    provider = _provider(public_key=pub_b64)
    record = {"artifact": {"key": "KEY-123",
                           "certificate_body": body,
                           "certificate_signature": sig + "AA"}}
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("down")):
        result = provider.validate(record)
    assert result.ok is False
    assert result.retryable is False
    assert result.state == LicenseState.VALIDATION_ERROR


def test_service_end_to_end_grace_with_keygen(tmp_path):
    provider = _provider()

    def online(request, timeout=None):
        if "/machines" in request.full_url:
            return _Resp(_machine_doc())
        return _Resp(_validate_doc())

    service = _service(provider, tmp_path)
    with mock.patch("urllib.request.urlopen", side_effect=online):
        assert service.activate("KEY-123").state is LicenseState.ACTIVE
    with mock.patch("urllib.request.urlopen",
                    side_effect=urllib.error.URLError("down")):
        assert service.refresh().state is LicenseState.OFFLINE_GRACE


# --- deactivation ------------------------------------------------------------------

def test_deactivate_success_clears():
    provider = _provider()
    record = {"artifact": {"key": "KEY-123", "machine_id": "mac-9"}}
    with mock.patch("urllib.request.urlopen",
                    return_value=_Resp({})):
        result = provider.deactivate(record)
    assert result.ok is True
    assert result.state == LicenseState.UNLICENSED


def test_deactivate_missing_machine_fails_closed():
    provider = _provider()
    with mock.patch("urllib.request.urlopen") as urlopen:
        result = provider.deactivate({"artifact": {}})
    urlopen.assert_not_called()
    assert result.state == LicenseState.VALIDATION_ERROR


def test_deactivate_gone_machine_counts_as_released():
    provider = _provider()
    record = {"artifact": {"key": "KEY-123", "machine_id": "mac-9"}}

    def gone(request, timeout=None):
        raise _http_error(404, "NOT_FOUND", "gone")

    with mock.patch("urllib.request.urlopen", side_effect=gone):
        result = provider.deactivate(record)
    assert result.ok is True


# --- export entitlement gate (headless) -----------------------------------------------

def test_export_gate_allows_active_and_grace(tmp_path):
    from types import SimpleNamespace
    from qs_engine.ui import views
    from qs_engine.licensing.provider import FakeLicensingProvider
    from qs_engine.licensing.service import LicensingService as Svc
    from qs_engine.licensing.storage import LicenseStore as Store
    from qs_engine.licensing.models import ProviderResult as PR
    from qs_engine.licensing.models import LicenseState as LS
    fake = FakeLicensingProvider(responses={
        "K": PR(ok=True, state=LS.ACTIVE, organization="O")})
    service = Svc(provider=fake,
                  store=Store(path=tmp_path / "license.json"))
    service.activate("K")
    assert views._export_entitlement_error(
        SimpleNamespace(license_service=service)) is None


def test_export_gate_blocks_unlicensed_and_expired(tmp_path):
    from types import SimpleNamespace
    from qs_engine.ui import views
    from qs_engine.licensing.provider import FakeLicensingProvider
    from qs_engine.licensing.service import LicensingService as Svc
    from qs_engine.licensing.storage import LicenseStore as Store
    from qs_engine.licensing.models import ProviderResult as PR
    from qs_engine.licensing.models import LicenseState as LS
    service = Svc(provider=FakeLicensingProvider(),
                  store=Store(path=tmp_path / "license.json"))
    message = views._export_entitlement_error(
        SimpleNamespace(license_service=service))
    assert "active license" in message
    expired = FakeLicensingProvider(responses={
        "K": PR(ok=False, state=LS.EXPIRED, message="old")})
    service2 = Svc(provider=expired,
                   store=Store(path=tmp_path / "license2.json"))
    store_record = {"provider": "fake", "key_hint": "K",
                    "state": "EXPIRED", "organization": "",
                    "expires": "2020-01-01",
                    "device_activated": False}
    service2.store.save(store_record)
    message2 = views._export_entitlement_error(
        SimpleNamespace(license_service=service2))
    assert "Expired" in message2
    assert views._export_entitlement_error(SimpleNamespace()) is None


def test_export_button_labels_preserved_in_source():
    import inspect as _inspect
    from qs_engine.ui import views
    excel = _inspect.getsource(views.build_excel_page)
    assert "Export BOQ" in excel
    assert "_export_entitlement_error" in excel
    corpdoc = _inspect.getsource(views.build_corpdoc_page)
    assert "Generate Branded Document" in corpdoc
    assert "_export_entitlement_error" in corpdoc
    rates_source = _inspect.getsource(views.build_valuations_page)
    assert "Export BOQ Summary PDF" in rates_source
    assert "_export_entitlement_error" in rates_source
