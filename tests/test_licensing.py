"""Licensing foundation tests (Phase 22): states, service, storage,
provider abstraction, and UI activation state.

All provider behavior runs through the scripted FakeLicensingProvider
(no network, no licensing account). Display tests are guarded and
drive only inline (non-blocking) dialog paths.
"""

import inspect
from pathlib import Path

import pytest

from qs_engine.licensing.models import (
    LicenseInfo,
    LicenseState,
    ProviderResult,
    connection_display,
    expiration_display,
    license_display,
)
from qs_engine.licensing.provider import (
    FakeLicensingProvider,
    LicensingProvider,
    NullProvider,
)
from qs_engine.licensing.service import LicensingService
from qs_engine.licensing.storage import LicenseStore


def _service(fake=None, tmp_path=None, **kwargs):
    store = LicenseStore(path=tmp_path / "license.json"
                         if tmp_path is not None else None)
    return LicensingService(provider=fake or FakeLicensingProvider(),
                            store=store, **kwargs)


def _ok_result(**kwargs):
    params = {"ok": True, "state": LicenseState.ACTIVE,
              "organization": "Demo Builders Ltd",
              "expires": "2030-06-30", "device_activated": True,
              "device_label": "SITE-PC-01", "message": "Activated."}
    params.update(kwargs)
    return ProviderResult(**params)


# --- states ------------------------------------------------------------------

def test_license_states_exact():
    assert {state.value for state in LicenseState} == {
        "UNLICENSED", "ACTIVATION_REQUIRED", "ACTIVATING", "ACTIVE",
        "OFFLINE_GRACE", "EXPIRED", "REVOKED", "SUSPENDED",
        "ACTIVATION_LIMIT_REACHED", "NETWORK_ERROR", "VALIDATION_ERROR",
    }


def test_state_display_wording():
    assert license_display(LicenseState.ACTIVE) == "Active"
    assert license_display(LicenseState.UNLICENSED) == "Not Activated"
    assert license_display(LicenseState.EXPIRED) == "Expired"
    assert license_display(LicenseState.REVOKED) == "Revoked"
    assert license_display(LicenseState.SUSPENDED) == "Suspended"
    assert license_display(LicenseState.ACTIVATION_LIMIT_REACHED) == (
        "Activation Limit Reached")
    assert license_display(LicenseState.NETWORK_ERROR) == (
        "Connection Error")
    assert license_display(LicenseState.OFFLINE_GRACE) == (
        "Active (Offline Grace)")
    assert expiration_display(None) == "Perpetual"
    assert expiration_display("2030-01-15") == "2030-01-15"
    assert connection_display(True, LicenseState.OFFLINE_GRACE) == (
        "Offline Grace")
    assert connection_display(False, LicenseState.ACTIVE) == "Online"


# --- provider abstraction ----------------------------------------------------

def test_provider_contract_is_abstract():
    with pytest.raises(TypeError):
        LicensingProvider()  # noqa: abstract direct construction
    for name in ("activate", "validate", "deactivate", "get_status",
                 "get_license_info"):
        assert callable(getattr(LicensingProvider, name, None)), name


def test_null_provider_needs_no_credentials_or_network():
    provider = NullProvider()  # constructs with no arguments
    assert provider.supports_deactivation is False
    result = provider.activate("ANY-KEY")
    assert result.ok is False
    assert result.state == LicenseState.ACTIVATION_REQUIRED


def test_fake_provider_is_clearly_marked():
    assert "NOT a real" in FakeLicensingProvider.__doc__
    assert FakeLicensingProvider.provider_name == "fake"


# --- service states ----------------------------------------------------------

def test_unlicensed_by_default(tmp_path):
    info = _service(tmp_path=tmp_path).snapshot()
    assert info.state == LicenseState.UNLICENSED
    assert info.product == "CIVOLINK QS"


def test_activation_success_persists(tmp_path):
    fake = FakeLicensingProvider(
        responses={"VALID-KEY": _ok_result()})
    service = _service(fake=fake, tmp_path=tmp_path)
    info = service.activate("VALID-KEY")
    assert info.state == LicenseState.ACTIVE
    assert info.organization == "Demo Builders Ltd"
    assert (tmp_path / "license.json").is_file()
    assert service.snapshot().state == LicenseState.ACTIVE


def test_invalid_license_key(tmp_path):
    info = _service(tmp_path=tmp_path).activate("NOPE")
    assert info.state == LicenseState.VALIDATION_ERROR
    assert not (tmp_path / "license.json").is_file()


def test_blank_key_rejected_without_provider_call(tmp_path):
    calls = []
    fake = FakeLicensingProvider(responses={})
    original = fake.activate
    fake.activate = lambda *a, **k: calls.append(1) or original(*a, **k)
    info = _service(fake=fake, tmp_path=tmp_path).activate("   ")
    assert info.state == LicenseState.VALIDATION_ERROR
    assert calls == []


def test_expired_license(tmp_path):
    fake = FakeLicensingProvider(responses={
        "OLD-KEY": _ok_result(state=LicenseState.EXPIRED, ok=False,
                              expires="2020-01-01",
                              message="License expired.")})
    info = _service(fake=fake, tmp_path=tmp_path).activate("OLD-KEY")
    assert info.state == LicenseState.EXPIRED


def test_revoked_and_suspended(tmp_path):
    for state in (LicenseState.REVOKED, LicenseState.SUSPENDED):
        fake = FakeLicensingProvider(responses={
            "BAD-KEY": _ok_result(state=state, ok=False,
                                  message=str(state))})
        info = _service(fake=fake, tmp_path=tmp_path).activate("BAD-KEY")
        assert info.state == state


def test_activation_limit_failure(tmp_path):
    fake = FakeLicensingProvider(responses={
        "FULL-KEY": _ok_result(
            state=LicenseState.ACTIVATION_LIMIT_REACHED, ok=False,
            device_activated=False,
            message="No seats left.")})
    info = _service(fake=fake, tmp_path=tmp_path).activate("FULL-KEY")
    assert info.state == LicenseState.ACTIVATION_LIMIT_REACHED


def test_network_failure_is_not_invalid(tmp_path):
    fake = FakeLicensingProvider(
        responses={"VALID-KEY": _ok_result()}, network_down=False)
    service = _service(fake=fake, tmp_path=tmp_path)
    assert service.activate("VALID-KEY").state == LicenseState.ACTIVE
    fake.network_down = True  # outage AFTER a good activation
    info = service.refresh()
    assert info.state == LicenseState.OFFLINE_GRACE
    assert info.state != LicenseState.VALIDATION_ERROR
    assert info.state != LicenseState.REVOKED


def test_network_failure_without_cache_is_plain_error(tmp_path):
    fake = FakeLicensingProvider(network_down=True)
    info = _service(fake=fake, tmp_path=tmp_path).refresh()
    assert info.state in (LicenseState.UNLICENSED,
                          LicenseState.NETWORK_ERROR)


def test_offline_grace_state_round_trip(tmp_path):
    fake = FakeLicensingProvider(
        responses={"VALID-KEY": _ok_result()}, network_down=False)
    service = _service(fake=fake, tmp_path=tmp_path)
    service.activate("VALID-KEY")
    fake.network_down = True
    assert service.refresh().state == LicenseState.OFFLINE_GRACE
    fake.network_down = False  # reconnect re-validates cleanly
    assert service.refresh().state == LicenseState.ACTIVE


def test_local_expiry_without_network(tmp_path):
    store = LicenseStore(path=tmp_path / "license.json")
    store.save({"provider": "fake", "key_hint": "KEY1",
                "state": "ACTIVE", "organization": "Acme",
                "expires": "2020-05-01", "device_activated": True})
    service = LicensingService(provider=FakeLicensingProvider(),
                               store=store)
    assert service.snapshot().state == LicenseState.EXPIRED


def test_deactivation_supported_path(tmp_path):
    fake = FakeLicensingProvider(
        responses={"VALID-KEY": _ok_result()})
    service = _service(fake=fake, tmp_path=tmp_path)
    service.activate("VALID-KEY")
    info = service.deactivate()
    assert info.state == LicenseState.UNLICENSED
    assert not (tmp_path / "license.json").is_file()


def test_deactivation_unsupported_provider(tmp_path):
    service = _service(fake=NullProvider(), tmp_path=tmp_path)
    info = service.deactivate()
    assert info.state == LicenseState.VALIDATION_ERROR


# --- storage -----------------------------------------------------------------

def test_storage_round_trip_and_clear(tmp_path):
    store = LicenseStore(path=tmp_path / "license.json")
    assert store.load() is None
    record = {"provider": "fake", "key_hint": "EY-1",
              "state": "ACTIVE"}
    store.save(record)
    assert store.load() == record
    store.clear()
    assert store.load() is None
    store.clear()  # missing file is not an error


def test_storage_corrupt_file_fails_closed(tmp_path):
    path = tmp_path / "license.json"
    path.write_text("{not json", encoding="utf-8")
    assert LicenseStore(path=path).load() is None
    path.write_text("[1, 2]", encoding="utf-8")
    assert LicenseStore(path=path).load() is None


def test_storage_default_dir_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CIVOLINK_LICENSE_DIR", str(tmp_path))
    from qs_engine.licensing.storage import default_license_dir
    assert default_license_dir() == tmp_path


# --- no credentials in client ------------------------------------------------

def test_no_provider_credentials_in_client_code():
    import ast as _ast
    root = Path(__file__).parent.parent / "qs_engine" / "licensing"
    offenders = []
    for path in sorted(root.glob("*.py")):
        tree = _ast.parse(path.read_text(encoding="utf-8"),
                          filename=str(path))
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Constant) and isinstance(
                    node.value, str):
                lowered = node.value.lower()
                if lowered.startswith(("sk_live_", "sk_test_",
                                       "pk_live_", "whsec_")):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"embedded secrets: {offenders}"
    for provider in (NullProvider(), FakeLicensingProvider()):
        for attr in ("api_key", "secret", "token", "private_key",
                     "admin_token", "webhook_secret"):
            assert not hasattr(provider, attr), attr


# --- UI activation state (display-guarded) -----------------------------------

def _requires_display():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    return tk, root


def test_license_dialogs_build_and_show_state(tmp_path):
    _, root = _requires_display()
    from types import SimpleNamespace
    from qs_engine.ui import views
    fake = FakeLicensingProvider(
        responses={"VALID-KEY": _ok_result()})
    service = LicensingService(
        provider=fake,
        store=LicenseStore(path=tmp_path / "license.json"))
    app = SimpleNamespace(license_service=service,
                          refresh_status=lambda: None)
    dialog = views.show_license_status(app)
    assert dialog is not None
    texts = []

    def walk(widget):
        for child in widget.winfo_children():
            try:
                texts.append(child.cget("text"))
            except Exception:
                pass
            walk(child)

    walk(dialog)
    assert any("Not Activated" in str(text) for text in texts)
    dialog.destroy()
    root.destroy()


def test_activation_dialog_success_flow(tmp_path):
    _, root = _requires_display()
    from types import SimpleNamespace
    from qs_engine.ui import views
    fake = FakeLicensingProvider(
        responses={"VALID-KEY": _ok_result()})
    service = LicensingService(
        provider=fake,
        store=LicenseStore(path=tmp_path / "license.json"))
    app = SimpleNamespace(license_service=service,
                          refresh_status=lambda: None)
    dialog = views.show_license_activation(app)
    assert dialog is not None
    entries = []

    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TEntry":
                entries.append(child)
            walk(child)

    walk(dialog)
    assert len(entries) == 1
    entries[0].insert(0, "VALID-KEY")
    buttons = []

    def walk_buttons(widget):
        for child in widget.winfo_children():
            if ("Button" in child.winfo_class()
                    and child.cget("text") == "Activate"):
                buttons.append(child)
            walk_buttons(child)

    walk_buttons(dialog)
    buttons[0].invoke()
    dialog.update_idletasks()
    assert service.snapshot().state == LicenseState.ACTIVE
    dialog.destroy()
    root.destroy()


def test_help_menu_has_license_entries():
    _, root = _requires_display()
    from qs_engine.ui import views
    app = views.QSApp.__new__(views.QSApp)
    assert callable(views.show_license_status)
    assert callable(views.show_license_activation)
    source = inspect.getsource(views.QSApp._build_menu)
    assert "License Status" in source
    assert "Activate License" in source
    root.destroy()
