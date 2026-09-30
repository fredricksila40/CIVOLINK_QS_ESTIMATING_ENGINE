"""Phase 2 remediation tests (Task 2.1: unified override channel).

The E-06 gap: QSPanel.run() invoked bindings with two arguments only,
so no panel except concrete (via a private binding) could ever deliver
estimator overrides to its controller. These tests pin the unified
``override_source`` channel end to end — source resolution, the
three-argument binding contract for every default binding, panel-level
passing for Masonry/Earthworks/Labour/Plant/Haulage, the concrete
page's migration onto the generic channel, and trade-scoped session
contexts that can never leak an override into the wrong trade.
"""

import inspect
from types import SimpleNamespace

import pytest

from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.ui import views
from qs_engine.ui.session import TakeoffSession
from qs_engine.ui.viewmodels import ErrorView


def repo():
    return MasterDataRepository()


def _display_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError:
        pytest.skip("no display")


# --- proven inputs + override payloads (engine-verified payloads) -------------

MASONRY_INPUTS = {"wall_length": "4", "wall_height": "2",
                  "unit_key": "concrete_block_200mm", "element": "wall"}
MASONRY_OVERRIDES = {
    "unit_length_mm": "390", "unit_height_mm": "190",
    "unit_thickness_mm": "200", "bed_joint_mm": "10",
    "perp_joint_mm": "10", "wastage_pct": "5",
    "mortar_cement_ratio": "1", "mortar_sand_ratio": "3",
    "mortar_dry_factor": "1.5",
    "mortar_sand_density_kg_per_m3": "1000",
    "cement_density_kg_per_m3": "1000", "bag_mass_kg": "50"}

EARTHWORKS_INPUTS = {"length": "10", "width": "1", "depth": "1.5",
                     "soil_key": "clay_soil",
                     "displaced_substructure_m3": "3", "element": "trench"}
EARTHWORKS_OVERRIDES = {"swell_factor": "1.25", "compact_factor": "1.1",
                        "density_kg_per_m3": "1000"}

LABOUR_INPUTS = {"work_quantity": "100", "trade_key": "mason"}
LABOUR_OVERRIDES = {"output_per_day": "25", "gang_skilled": "2",
                    "gang_unskilled": "4", "skilled_rate": "1500",
                    "unskilled_rate": "800"}

PLANT_INPUTS = {"work_quantity": "100", "equipment_key": "backhoe_excavator",
                "hours_per_day": "8"}
PLANT_OVERRIDES = {"output_per_unit": "20", "rate": "24000"}

LOGISTICS_INPUTS = {"total_loose_m3": "200",
                    "loose_density_t_per_m3": "2",
                    "truck_key": "tipper_truck", "distance_km": "10",
                    "available_minutes_per_day": "480",
                    "target_per_day": "100", "target_unit": "tonne"}
LOGISTICS_OVERRIDES = {
    "body_length_m": "4", "body_width_m": "2", "body_height_m": "1.5",
    "payload_limit_tonnes": "12", "payload_tonnes": "10",
    "load_time_min": "10", "unload_time_min": "5",
    "speed_loaded_kmh": "20", "speed_empty_kmh": "40"}

TRADE_CASES = (
    ("masonry", MASONRY_INPUTS, MASONRY_OVERRIDES),
    ("earthworks", EARTHWORKS_INPUTS, EARTHWORKS_OVERRIDES),
    ("labour", LABOUR_INPUTS, LABOUR_OVERRIDES),
    ("plant", PLANT_INPUTS, PLANT_OVERRIDES),
    ("logistics", LOGISTICS_INPUTS, LOGISTICS_OVERRIDES),
)


# --- override source resolution (headless) ------------------------------------

def test_resolve_override_source_variants():
    assert views.resolve_override_source(None) == {}
    assert views.resolve_override_source({}) == {}
    assert views.resolve_override_source({"a": "1"}) == {"a": "1"}
    assert views.resolve_override_source(lambda: {"b": "2"}) == {"b": "2"}
    assert views.resolve_override_source(lambda: None) == {}
    context = {"k": "v"}
    resolved = views.resolve_override_source(context)
    resolved["k"] = "mutated"
    assert context["k"] == "v", "resolution must hand bindings a copy"


def test_session_override_context_is_trade_scoped():
    project = {"name": "Demo",
               "cement_density_kg_per_m3": "1440",
               "sand_density_kg_per_m3": "1600",
               "aggregate_density_kg_per_m3": "1500"}
    assert views.session_override_context(project, "concrete") == {
        "cement_density_kg_per_m3": "1440",
        "sand_density_kg_per_m3": "1600",
        "aggregate_density_kg_per_m3": "1500"}
    for trade in ("masonry", "earthworks", "labour", "plant",
                  "logistics"):
        assert views.session_override_context(project, trade) == {}, trade
    assert views.session_override_context(None, "concrete") == {}
    assert views.session_override_context(None) == {}


# --- the shared three-argument binding contract (headless) --------------------

def test_default_bindings_accept_the_override_channel():
    for key, binding in views.default_bindings().items():
        parameters = list(inspect.signature(binding).parameters.values())
        assert len(parameters) >= 3, key
        assert parameters[2].default is None, key


def test_panel_and_page_expose_override_source_parameters():
    panel_params = inspect.signature(views.QSPanel.__init__).parameters
    assert panel_params["override_source"].default is None
    assert panel_params["chrome"].default is True
    assert panel_params["action_label"].default == "Calculate"
    assert panel_params["on_result"].default is None
    page_params = inspect.signature(views.build_takeoff_page).parameters
    assert page_params["override_source"].default is None


def _assert_overrides_arrived(result, spec_key, overrides):
    """Masonry/Concrete view-models report a bool; the others the
    exact field tuple — either way the engine confirms the flow."""
    used = result.overrides_used
    if spec_key == "masonry":
        assert used is True, spec_key
    else:
        assert set(overrides) <= set(used), spec_key


def test_trade_bindings_forward_overrides_to_engines():
    """The unified channel delivers: binding -> controller -> engine."""
    bindings = views.default_bindings()
    for spec_key, inputs, overrides in TRADE_CASES:
        result = bindings[spec_key](inputs, repo(), overrides)
        assert not isinstance(result, ErrorView), spec_key
        _assert_overrides_arrived(result, spec_key, overrides)
    earthworks = bindings["earthworks"](EARTHWORKS_INPUTS, repo(),
                                        EARTHWORKS_OVERRIDES)
    assert earthworks.overrides_used == (
        "swell_factor", "compact_factor", "density_kg_per_m3")


def test_two_argument_binding_calls_stay_valid_and_fail_closed():
    """Back-compat: without a source the old two-argument call works,
    and an unverified master record still fails closed (no crash, no
    fabricated success)."""
    bindings = views.default_bindings()
    for spec_key, inputs, _overrides in TRADE_CASES:
        result = bindings[spec_key](inputs, repo())
        assert isinstance(result, ErrorView), spec_key


# --- page wiring: generic runner receives a live override source (headless) ---

def test_takeoff_pages_pass_override_source_into_generic_runner(
        monkeypatch):
    captured = {}

    def spy(body, app, trade, spec_key, **kwargs):
        captured[trade] = kwargs
        return {"panel": None}

    monkeypatch.setattr(views, "build_takeoff_page", spy)
    app = SimpleNamespace(session=TakeoffSession())
    for key in ("masonry", "earthworks", "logistics"):
        views.PAGES[key](object(), app)
    for trade in ("masonry", "earthworks", "logistics"):
        source = captured[trade]["override_source"]
        assert callable(source), trade
        assert source() == {}, trade


# --- panel-level passing for every audited trade (display) -------------------

def test_panel_passes_override_source_as_third_argument():
    root = _display_root()
    try:
        captured = []

        def spy(*args):
            captured.append(args)
            return None

        for spec_key, _inputs, overrides in TRADE_CASES:
            captured.clear()
            panel = views.QSPanel(root, spec_key, spy,
                                  override_source=overrides)
            panel.run()
            assert len(captured) == 1, spec_key
            assert len(captured[0]) == 3, spec_key
            assert captured[0][2] == overrides, spec_key
            # mapping source: handed over as a copy, not the original
            assert captured[0][2] is not overrides, spec_key
            panel.destroy()

            captured.clear()
            panel = views.QSPanel(root, spec_key, spy)
            panel.run()
            assert len(captured[0]) == 2, spec_key
            panel.destroy()

            captured.clear()
            context = dict(overrides)
            panel = views.QSPanel(root, spec_key, spy,
                                  override_source=lambda c=context: dict(c))
            context["injected_after_build"] = "1"
            panel.run()
            assert captured[0][2] == context, spec_key
            panel.destroy()
    finally:
        root.destroy()


def test_trade_panels_deliver_overrides_end_to_end():
    """Full E-06 proof: real panel -> real default binding -> real
    controller -> engine provenance showing every supplied override."""
    root = _display_root()
    try:
        bindings = views.default_bindings()
        for spec_key, inputs, overrides in TRADE_CASES:
            panel = views.QSPanel(root, spec_key, bindings[spec_key],
                                  repo(), override_source=overrides)
            for name, value in inputs.items():
                panel._entries[name].insert(0, value)
            result = panel.run()
            assert not isinstance(result, ErrorView), (
                spec_key, getattr(result, "message", None))
            _assert_overrides_arrived(result, spec_key, overrides)
            panel.destroy()
    finally:
        root.destroy()


def test_concrete_page_uses_the_unified_override_channel():
    root = _display_root()
    try:
        import tkinter as tk
        body = tk.Frame(root)
        session = TakeoffSession()
        session.save_project(name="Demo",
                             cement_density_kg_per_m3="1440",
                             sand_density_kg_per_m3="1600",
                             aggregate_density_kg_per_m3="1500")
        app = SimpleNamespace(session=session, repository=repo(),
                              refresh_status=lambda: None)
        refs = views.build_concrete_page(body, app)
        panel = refs["panel"]
        # The private binding is gone: the default controller binding
        # now receives densities through the shared override channel.
        assert getattr(panel._controller, "__name__", "") == (
            "concrete_controller")
        assert views.resolve_override_source(panel._override_source) == {
            "cement_density_kg_per_m3": "1440",
            "sand_density_kg_per_m3": "1600",
            "aggregate_density_kg_per_m3": "1500"}
        body.destroy()
    finally:
        root.destroy()


def test_labour_and_plant_panels_share_the_override_channel():
    root = _display_root()
    try:
        import tkinter as tk
        body = tk.Frame(root)
        app = SimpleNamespace(session=TakeoffSession(), repository=repo(),
                              refresh_status=lambda: None)
        views.build_labour_plant_page(body, app)
        panels = []

        def walk(widget):
            for child in widget.winfo_children():
                if type(child).__name__ == "QSPanel":
                    panels.append(child)
                walk(child)

        walk(body)
        assert {panel._spec_key for panel in panels} == {"labour", "plant"}
        for panel in panels:
            assert callable(panel._override_source)
            assert views.resolve_override_source(panel._override_source) == {}
        body.destroy()
    finally:
        root.destroy()
