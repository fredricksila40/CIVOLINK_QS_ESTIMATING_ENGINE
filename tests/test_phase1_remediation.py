"""Phase 1 remediation tests (Tasks 1.1-1.6).

Covers the audited fixes end to end: rebar mass provenance (no
fabricated D^2/162 auto-fill, explicit override vs density formula),
provenance population on every take-off view-model plus the status
line renderer, all-domain verification counting, atomic .clk project
writes, blank-wastage fail-closed semantics, API sidecar guards
(bearer auth, origin, payload cap), bounded .clk decoding, and
per-operation rate-library connections.
"""

import inspect
import json
import zlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from qs_engine.cli import _aggregate_verification
from qs_engine.core.errors import (
    UnverifiedMasterDataError,
    ValidationError,
)
from qs_engine.licensing.storage import atomic_write_bytes
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.persistence.project_file import (
    MAX_DECODED_BYTES,
    MAX_ENCODED_BYTES,
    ProjectFileAdapter,
    SessionState,
)
from qs_engine.persistence.rate_library import RateLibrary
from qs_engine.rates.engine import material_component
from qs_engine.reinforcement.engine import (
    MASS_SOURCE_FORMULA,
    RebarBarOverride,
    resolve_rebar_bar,
)
from qs_engine.ui import views
from qs_engine.ui.controllers import (
    earthworks_controller,
    labour_controller,
    logistics_plan_controller,
    merged_master_version,
    merged_overrides,
    parse_optional_decimal,
    plant_controller,
    rate_builder_controller,
    rebar_controller,
)
from qs_engine.ui.viewmodels import ErrorView


def repo():
    return MasterDataRepository()


def _display_root():
    tk = pytest.importorskip("tkinter")
    try:
        return tk.Tk()
    except tk.TclError:
        pytest.skip("no display")


# --- Task 1.1: rebar mass provenance (no fabricated auto-fill) -----------------

def test_rebar_mass_override_carries_override_provenance():
    view = rebar_controller(
        [{"bar_key": "Y12", "count": "10", "length_per_bar_m": "6",
          "mass_kg_per_m": "0.889"}],
        "0", None, repo())
    assert not isinstance(view, ErrorView)
    # Explicit estimator mass is the "override" source — never reported
    # as a table value the master record never provided (E-01).
    assert view.overrides_used == ("mass_kg_per_m",)
    assert view.master_version == "4.0-skeleton"
    # 60 m x 0.889 kg/m = 53.34 kg (wastage 0).
    assert Decimal(view.total_mass_kg) == Decimal("53.340")


def test_rebar_page_density_feeds_formula_path():
    view = rebar_controller(
        [{"bar_key": "Y12", "count": "10", "length_per_bar_m": "6"}],
        "0", None, repo(), steel_density_kg_per_m3="7850")
    assert not isinstance(view, ErrorView)
    assert view.overrides_used == ("steel_density_kg_per_m3",)
    assert view.master_version == "4.0-skeleton"
    resolved = resolve_rebar_bar(
        "Y12", repo(), RebarBarOverride(steel_density_kg_per_m3="7850"))
    assert resolved.mass_source == MASS_SOURCE_FORMULA
    expected = Decimal("60") * resolved.mass_kg_per_m
    # 28-digit engine totals may differ by one ulp from the raw product.
    assert abs(Decimal(view.total_mass_kg) - expected) < Decimal("1e-25")


def test_rebar_line_density_wins_over_page_density():
    page_level = rebar_controller(
        [{"bar_key": "Y12", "count": "10", "length_per_bar_m": "6"}],
        "0", None, repo(), steel_density_kg_per_m3="7850")
    line_level = rebar_controller(
        [{"bar_key": "Y12", "count": "10", "length_per_bar_m": "6",
          "steel_density_kg_per_m3": "8000"}],
        "0", None, repo(), steel_density_kg_per_m3="7850")
    assert not isinstance(line_level, ErrorView)
    assert line_level.overrides_used == ("steel_density_kg_per_m3",)
    assert (Decimal(line_level.total_mass_kg)
            > Decimal(page_level.total_mass_kg))


def test_rebar_blank_mass_without_density_fails_closed():
    view = rebar_controller(
        [{"bar_key": "Y12", "count": "10", "length_per_bar_m": "6"}],
        "0", None, repo())
    assert isinstance(view, ErrorView)
    assert "no usable unit mass" in view.message


# --- Task 1.2: provenance population on every take-off view -------------------

def test_earthworks_controller_populates_provenance():
    view = earthworks_controller(
        {"length": "10", "width": "1", "depth": "1.5",
         "soil_key": "clay_soil", "displaced_substructure_m3": "3",
         "element": "trench"},
        repo(),
        {"swell_factor": "1.25", "compact_factor": "1.1",
         "density_kg_per_m3": "1000"})
    assert not isinstance(view, ErrorView)
    assert view.overrides_used == (
        "swell_factor", "compact_factor", "density_kg_per_m3")
    assert view.master_version == "5.0-skeleton"


def test_labour_controller_populates_provenance():
    view = labour_controller(
        {"work_quantity": "100", "trade_key": "mason"}, repo(),
        {"output_per_day": "25", "gang_skilled": "2",
         "gang_unskilled": "4", "skilled_rate": "1500",
         "unskilled_rate": "800"})
    assert not isinstance(view, ErrorView)
    assert view.overrides_used == (
        "output_per_day", "gang_skilled", "gang_unskilled",
        "skilled_rate", "unskilled_rate")
    assert view.master_version == "7.0-skeleton"


def test_plant_controller_populates_provenance():
    view = plant_controller(
        {"work_quantity": "100", "equipment_key": "backhoe_excavator"},
        repo(), {"output_per_unit": "20", "rate": "24000"},
        hours_per_day="8")
    assert not isinstance(view, ErrorView)
    assert view.overrides_used == ("output_per_unit", "rate")
    assert view.master_version == "7.0-skeleton"


def test_logistics_controller_populates_provenance():
    view = logistics_plan_controller(
        {"total_loose_m3": "200", "loose_density_t_per_m3": "2",
         "truck_key": "tipper_truck", "distance_km": "10",
         "available_minutes_per_day": "480", "target_per_day": "100",
         "target_unit": "tonne"},
        repo(),
        {"body_length_m": "4", "body_width_m": "2",
         "body_height_m": "1.5", "payload_limit_tonnes": "12",
         "payload_tonnes": "10", "load_time_min": "10",
         "unload_time_min": "5", "speed_loaded_kmh": "20",
         "speed_empty_kmh": "40"})
    assert not isinstance(view, ErrorView)
    assert view.overrides_used == (
        "body_length_m", "body_width_m", "body_height_m",
        "payload_limit_tonnes", "payload_tonnes", "load_time_min",
        "unload_time_min", "speed_loaded_kmh", "speed_empty_kmh")
    assert view.master_version == "8.0-skeleton"


def test_merged_helpers_deduplicate_in_first_seen_order():
    records = [
        SimpleNamespace(overridden_fields=("a", "b"),
                        master_version="1.0"),
        SimpleNamespace(overridden_fields=("b", "c"), master_version=None),
    ]
    assert merged_overrides(records) == ("a", "b", "c")
    assert merged_master_version(records) == "1.0"
    assert merged_overrides([]) == ()
    assert merged_master_version([]) is None


def test_provenance_status_text_covers_every_branch():
    from qs_engine.ui.views import provenance_status_text
    assert provenance_status_text(None) == ""
    assert provenance_status_text(ErrorView(message="boom")) == ""
    assert provenance_status_text(object()) == ""
    assert provenance_status_text(
        SimpleNamespace(overrides_used=True,
                        master_version="2.0-skeleton")) == (
        "Provenance: manual overrides applied \u00b7 master 2.0-skeleton")
    assert provenance_status_text(
        SimpleNamespace(overrides_used=("mass_kg_per_m", "diameter_mm"),
                        master_version="4.0-skeleton")) == (
        "Provenance: manual overrides: mass_kg_per_m, diameter_mm"
        " \u00b7 master 4.0-skeleton")
    assert provenance_status_text(
        SimpleNamespace(overrides_used=False, master_version=None)) == (
        "Provenance: master data only")
    assert provenance_status_text(
        SimpleNamespace(overrides_used=(), master_version=None)) == (
        "Provenance: master data only")


# --- Task 1.3: verification counting covers every domain ----------------------

def test_aggregate_verification_counts_every_domain():
    master = repo()
    counts = _aggregate_verification(master)
    total = sum(len(master.list(domain)) for domain in master.domains())
    assert set(counts) == {
        "VERIFIED", "NEEDS_VERIFICATION", "PROVISIONAL"}
    # Every record of every domain is counted — the pre-fix code only
    # walked a hard-coded subset of tables and under-reported.
    assert sum(counts.values()) == total
    assert total >= 62
    assert {"materials", "rebar_bars", "soils",
            "rate_templates"} <= set(master.domains())


def test_overview_verification_line_matches_cli_counts():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("overview")
    app.update_idletasks()
    body = app.workspace.interior
    rendered = []

    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "Text":
                rendered.append(child.get("1.0", "end"))
            walk(child)

    walk(body)
    app.destroy()
    root.destroy()
    assert rendered, "overview text widget missing"
    counts = _aggregate_verification(repo())
    expected = (
        f"Verification: {counts['VERIFIED']} verified, "
        f"{counts['NEEDS_VERIFICATION']} needs verification, "
        f"{counts['PROVISIONAL']} provisional")
    assert any(expected in text for text in rendered)


# --- Task 1.4: atomic project-file writes -------------------------------------

def test_atomic_write_bytes_round_trip_leaves_no_tmp(tmp_path):
    target = tmp_path / "data.bin"
    assert atomic_write_bytes(target, b"payload") == target
    assert target.read_bytes() == b"payload"
    assert [path.name for path in tmp_path.iterdir()] == ["data.bin"]


def test_atomic_write_bytes_failure_preserves_previous_file(
        tmp_path, monkeypatch):
    import qs_engine.licensing.storage as storage
    target = tmp_path / "data.bin"
    atomic_write_bytes(target, b"v1")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"v2")
    assert target.read_bytes() == b"v1"
    assert not list(tmp_path.glob("*.tmp"))


def test_save_project_write_failure_is_validation_error(
        tmp_path, monkeypatch):
    import qs_engine.licensing.storage as storage
    target = tmp_path / "project.clk"
    ProjectFileAdapter.save_project(
        target, SessionState(project={"name": "First"}))
    before = target.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(ValidationError) as exc_info:
        ProjectFileAdapter.save_project(
            target, SessionState(project={"name": "Second"}))
    assert "Could not write project file" in str(exc_info.value)
    assert target.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))
    monkeypatch.undo()
    restored = ProjectFileAdapter.load_project(target)
    assert restored.project == {"name": "First"}


# --- Task 1.5: blank wastage stays blank (never a silent zero) ----------------

def test_format_rate_line_blank_waste_never_becomes_zero():
    blank = views.format_rate_line(
        {"kind": "material", "key": "river_sand", "qty": "1",
         "price": "90", "waste": "", "desc": ""})
    assert "waste=" not in blank
    assert views.parse_rate_lines(blank + "\n")[0][
        "wastage_pct"] == ""
    explicit = views.format_rate_line(
        {"kind": "material", "key": "river_sand", "qty": "1",
         "price": "90", "waste": "0", "desc": ""})
    assert "waste=0" in explicit
    assert views.parse_rate_lines(explicit + "\n")[0][
        "wastage_pct"] == "0"
    seven = views.format_rate_line(
        {"kind": "material", "key": "river_sand", "qty": "1",
         "price": "90", "waste": "7.5", "desc": ""})
    assert views.parse_rate_lines(seven + "\n")[0][
        "wastage_pct"] == "7.5"


def test_material_component_blank_wastage_fails_closed_on_unverified():
    # Shipped material records carry no verified default, so an
    # unspecified wastage can never become a fabricated 0 % assumption.
    with pytest.raises(UnverifiedMasterDataError):
        material_component(
            material_key="river_sand", qty_per_unit="1",
            unit_price="90", wastage_pct=None, repository=repo())


def test_material_component_blank_wastage_uses_verified_default():
    class StubRepository:
        def get(self, domain, key):
            return {"key": key, "verification_status": "PROVISIONAL",
                    "default_wastage_pct": "5"}

    component = material_component(
        material_key="sand", qty_per_unit="1", unit_price="90",
        wastage_pct=None, repository=StubRepository())
    assert component.cost_per_unit == Decimal("94.5")


def test_material_component_explicit_zero_stays_zero():
    component = material_component(
        material_key="river_sand", qty_per_unit="1", unit_price="90",
        wastage_pct=0, repository=repo())
    assert component.cost_per_unit == Decimal("90")


def test_rate_builder_blank_wastage_errors_explicit_value_succeeds():
    lines = [{"kind": "material", "material_key": "river_sand",
              "qty_per_unit": "1", "unit_price": "90"}]
    blank = rate_builder_controller(
        list(lines), [], "sequential", "bedding", "m³", repo())
    assert isinstance(blank, ErrorView)
    assert "wastage_pct" in blank.message
    explicit = rate_builder_controller(
        [dict(lines[0], wastage_pct="0")],
        [{"label": "profit", "pct": "10"}],
        "sequential", "bedding", "m³", repo())
    assert not isinstance(explicit, ErrorView)
    assert explicit.gross_rate == "99"


def test_parse_optional_decimal_blank_stays_none():
    assert parse_optional_decimal("", "wastage_pct") is None
    assert parse_optional_decimal(None, "wastage_pct") is None
    assert parse_optional_decimal("   ", "wastage_pct") is None
    assert parse_optional_decimal("2.5", "wastage_pct") == Decimal("2.5")


# --- Task 1.6: API sidecar guards ----------------------------------------------

def test_api_shipped_payload_cap_is_16_mb():
    from qs_engine.web.api import MAX_REQUEST_BYTES
    assert MAX_REQUEST_BYTES == 16 * 1024 * 1024


def test_api_requires_bearer_token_on_every_endpoint():
    from qs_engine.web.api import api_token, app
    anonymous = TestClient(app)
    response = anonymous.get("/health")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    wrong = TestClient(
        app, headers={"Authorization": "Bearer not-the-token"})
    assert wrong.get("/health").status_code == 401
    assert wrong.post("/api/v1/rate/build",
                      json={"lines": []}).status_code == 401
    authorized = TestClient(
        app, headers={"Authorization": f"Bearer {api_token}"})
    assert authorized.get("/health").status_code == 200


def test_api_rejects_foreign_origin_even_with_valid_token():
    from qs_engine.web.api import api_token, app
    foreign = TestClient(app, headers={
        "Authorization": f"Bearer {api_token}",
        "Origin": "https://evil.example"})
    response = foreign.get("/health")
    assert response.status_code == 403
    assert "Cross-origin" in response.json()["detail"]
    local = TestClient(app, headers={
        "Authorization": f"Bearer {api_token}",
        "Origin": "http://localhost:8000"})
    assert local.get("/health").status_code == 200


def test_api_caps_request_body_size(monkeypatch):
    from qs_engine.web import api
    auth = {"Authorization": f"Bearer {api.api_token}"}
    oversized = TestClient(api.app, headers={
        **auth, "Content-Length": str(api.MAX_REQUEST_BYTES + 1)})
    response = oversized.get("/health")
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"]
    monkeypatch.setattr(api, "MAX_REQUEST_BYTES", 64)
    capped = TestClient(api.app, headers={
        **auth, "Content-Length": "128"})
    assert capped.get("/health").status_code == 413


def test_api_invalid_content_length_is_400():
    from qs_engine.web.api import api_token, app
    client = TestClient(app, headers={
        "Authorization": f"Bearer {api_token}",
        "Content-Length": "abc"})
    assert client.get("/health").status_code == 400


# --- Task 1.6: bounded .clk decoding ------------------------------------------

def test_project_decode_rejects_oversized_encoded_payload():
    payload = b"\x00" * (MAX_ENCODED_BYTES + 1)
    with pytest.raises(ValidationError) as exc_info:
        ProjectFileAdapter.decode(payload)
    assert "limit is" in str(exc_info.value)


def test_project_decode_rejects_decompression_bomb():
    bomb = zlib.compress(json.dumps(
        {"pad": "a" * (MAX_DECODED_BYTES + 1)}).encode("utf-8"))
    assert len(bomb) < MAX_ENCODED_BYTES
    with pytest.raises(ValidationError) as exc_info:
        ProjectFileAdapter.decode(bomb)
    assert "decompresses beyond" in str(exc_info.value)


def test_project_decode_round_trip_still_works():
    state = SessionState(project={"name": "Round trip"})
    loaded = ProjectFileAdapter.decode(ProjectFileAdapter.encode(state))
    assert loaded.project == {"name": "Round trip"}


# --- Task 1.6: rate-library per-operation connections -------------------------

def test_rate_library_close_then_reopen_preserves_data(tmp_path):
    path = str(tmp_path / "rates.db")
    first = RateLibrary(path)
    first.upsert_rate("labour", "mason", "Mason", "day", "1500")
    first.close()
    first.close()  # idempotent
    second = RateLibrary(path)
    try:
        assert second.get_rate("labour", "mason")["rate"] == "1500"
        second.upsert_rate("labour", "mason", "Mason", "day", "1600")
        assert second.get_rate("labour", "mason")["rate"] == "1600"
        assert second.count() == 1
    finally:
        second.close()


def test_rate_library_memory_anchor_keeps_state_across_operations():
    library = RateLibrary(":memory:")
    try:
        library.upsert_rate("plant", "crane", "Crane", "hr", "5000")
        # Without the retained anchor connection every operation would
        # reopen a fresh empty :memory: database.
        assert library.count() == 1
        assert library.get_rate("plant", "crane")["rate"] == "5000"
        library.delete_rate("plant", "crane")
        assert library.count() == 0
    finally:
        library.close()


def test_rate_library_source_inspection_documents_connection_policy():
    source = inspect.getsource(RateLibrary)
    assert "def _connection(self):" in source
    assert "self._anchor" in source
    assert "with self._connection() as conn:" in source
    assert "conn.close()" in source
