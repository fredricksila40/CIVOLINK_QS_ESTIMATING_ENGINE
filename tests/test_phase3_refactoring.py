"""Phase 3 refactoring tests (Tasks 3.1-3.3).

Covers the unified fail-closed master-data resolver (one shared
precedence hierarchy + provenance contract behind every domain engine),
typed cross-domain references (parse / schema validation / runtime
lookup wiring), and the formwork take-off controller end to end
(view-model maths, fail-closed inputs, take-off line, BOQ section, and
the live rebar-page panel).
"""

import inspect
from dataclasses import dataclass
from decimal import Decimal

import pytest

from qs_engine.concrete.engine import ConcreteMixOverride, resolve_mix
from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    MissingFieldError,
    UnknownMasterDataKeyError,
    UnverifiedMasterDataError,
    ValidationError,
)
from qs_engine.earthworks.engine import resolve_soil
from qs_engine.finishes.resolution import resolve_mortar_materials
from qs_engine.finishes.results import UnresolvedRequirement
from qs_engine.labour.engine import resolve_labour_trade
from qs_engine.logistics.engine import TruckOverride, resolve_truck
from qs_engine.masonry.engine import resolve_masonry_unit
from qs_engine.master_data import (
    CrossDomainReference,
    MasterDataRepository,
    resolve,
)
from qs_engine.master_data.schemas import validate_record
from qs_engine.plant.engine import resolve_plant_equipment
from qs_engine.rates.engine import get_rate_template, material_component
from qs_engine.reinforcement.engine import resolve_rebar_bar
from qs_engine.ui import views
from qs_engine.ui.controllers import (
    FORMWORK_ELEMENT_TYPES,
    FormworkController,
    formwork_controller,
    parse_deductions,
)
from qs_engine.ui.session import TRADE_SECTIONS, TakeoffSession
from qs_engine.ui.viewmodels import ErrorView, FormworkView, KV
from qs_engine.ui.views import extract_takeoff_line, provenance_status_text


class _FakeRepository:
    """Static record stand-in: resolver-contract tests only."""

    def __init__(self, record, version="v-fake"):
        self._record = dict(record)
        self._version = version

    def get(self, domain, key):
        record = dict(self._record)
        record.setdefault("key", key)
        return record

    def table_version(self, domain):
        return self._version


@dataclass
class _Override:
    """Generic override model for the shared-resolver contract tests."""
    cement_ratio: Decimal = None
    sand_ratio: Decimal = None


# --- Task 3.1: unified resolver contract ---------------------------------------

def test_generic_resolver_merges_override_then_record():
    repo = _FakeRepository({
        "verification_status": VerificationStatus.PROVISIONAL,
        "cement_ratio": "0.5",
        "sand_ratio": "1.5",
    })
    resolved = resolve(
        repo, "concrete_classes", "cls", _Override(cement_ratio=Decimal("0.7")),
        fields=("cement_ratio", "sand_ratio"), noun="Concrete class")
    assert resolved.values["cement_ratio"] == Decimal("0.7")   # override wins
    assert resolved.values["sand_ratio"] == Decimal("1.5")     # record value
    assert resolved.overridden_fields == ("cement_ratio",)
    assert resolved.overrides_used is True
    assert resolved.verified is True
    assert resolved.unverified is False
    assert resolved.master_version == "v-fake"
    assert resolved.missing_fields == ()


def test_generic_resolver_fails_closed_on_missing_required():
    unverified = _FakeRepository({
        "verification_status": VerificationStatus.NEEDS_VERIFICATION})
    with pytest.raises(UnverifiedMasterDataError) as excinfo:
        resolve(unverified, "concrete_classes", "cls", None,
                fields=("cement_ratio",), noun="Concrete class")
    assert "Concrete class 'cls' is NEEDS_VERIFICATION" in str(excinfo.value)
    assert "cement_ratio" in str(excinfo.value)

    incomplete = _FakeRepository({
        "verification_status": VerificationStatus.VERIFIED,
        "cement_ratio": None,
    })
    with pytest.raises(ValidationError, match="record is incomplete"):
        resolve(incomplete, "concrete_classes", "cls", None,
                fields=("cement_ratio",), noun="Concrete class")


def test_generic_resolver_non_strict_reports_missing_fields():
    repo = _FakeRepository({
        "verification_status": VerificationStatus.NEEDS_VERIFICATION})
    resolved = resolve(repo, "concrete_classes", "cls", None,
                       fields=("cement_ratio", "sand_ratio"), strict=False)
    assert resolved.missing_fields == ("cement_ratio", "sand_ratio")
    assert resolved.values == {"cement_ratio": None, "sand_ratio": None}
    assert resolved.overridden_fields == ()


def test_generic_resolver_required_subset_keeps_optional_fields_none():
    repo = _FakeRepository({
        "verification_status": VerificationStatus.PROVISIONAL,
        "output_per_unit": "3",
        "rate": None,
    })
    resolved = resolve(
        repo, "plant", "mixer", None,
        fields=("output_per_unit", "rate"),
        required=("output_per_unit",), noun="Plant")
    assert resolved.values["rate"] is None
    assert resolved.missing_fields == ()


def test_generic_resolver_coercion_switch():
    repo = _FakeRepository({
        "verification_status": VerificationStatus.PROVISIONAL,
        "gang_skilled": "3",
    })
    raw = resolve(repo, "labour", "mason", None,
                  fields=("gang_skilled",), coerce=False)
    assert raw.values["gang_skilled"] == "3"          # raw, never Decimal
    coerced = resolve(repo, "labour", "mason", None,
                      fields=("gang_skilled",), coerce=True)
    assert coerced.values["gang_skilled"] == Decimal("3")


def test_repo_method_matches_module_resolve():
    repo = MasterDataRepository()
    override = ConcreteMixOverride(cement_ratio=Decimal("0.4"))
    via_module = resolve(
        repo, "concrete_classes", "class_c20", override, strict=False)
    via_method = repo.resolve(
        "concrete_classes", "class_c20", override, strict=False)
    assert via_method == via_module
    assert via_module.values["cement_ratio"] == Decimal("0.4")
    assert via_module.overridden_fields == ("cement_ratio",)
    # The shipped skeleton stays fail-closed for everything else.
    assert "sand_ratio" in via_module.missing_fields
    plain = repo.resolve(
        "concrete_classes", "class_c20",
        fields=("cement_ratio",), strict=False)
    assert plain.overridden_fields == ()
    record = repo.get("concrete_classes", "class_c20")
    expected = (None if record.get("cement_ratio") is None
                else Decimal(record["cement_ratio"]))
    assert plain.values["cement_ratio"] == expected
    assert plain.verified is False


@pytest.mark.parametrize("resolver,key,noun", [
    (resolve_mix, "ghost_class", "Concrete class"),
    (resolve_soil, "ghost_soil", "Soil"),
    (resolve_labour_trade, "ghost_trade", "Labour trade"),
    (resolve_plant_equipment, "ghost_plant", "Plant"),
    (resolve_truck, "ghost_truck", "Truck"),
    (resolve_masonry_unit, "ghost_unit", "Masonry unit"),
])
def test_unverified_error_carries_domain_noun(resolver, key, noun):
    repo = _FakeRepository({
        "verification_status": VerificationStatus.NEEDS_VERIFICATION})
    with pytest.raises(UnverifiedMasterDataError) as excinfo:
        resolver(key, repo)
    assert f"{noun} {key!r} is NEEDS_VERIFICATION" in str(excinfo.value)


def test_rebar_unverified_without_usable_mass_fails_closed():
    repo = _FakeRepository({
        "verification_status": VerificationStatus.NEEDS_VERIFICATION,
        "diameter_mm": "12",
    })
    with pytest.raises(UnverifiedMasterDataError,
                       match="Rebar bar 'ghost'"):
        resolve_rebar_bar("ghost", repo)


def test_truck_hire_and_fuel_stay_wrapper_owned_extras():
    repo = MasterDataRepository()
    planning = dict(
        body_length_m=Decimal("6"), body_width_m=Decimal("2.4"),
        body_height_m=Decimal("2.5"),
        payload_limit_tonnes=Decimal("10"),
        payload_tonnes=Decimal("8"),
        load_time_min=Decimal("15"), unload_time_min=Decimal("10"),
        speed_loaded_kmh=Decimal("40"), speed_empty_kmh=Decimal("50"))
    resolved = resolve_truck(
        "tipper_truck", repo, TruckOverride(**planning))
    assert resolved.overridden_fields == tuple(planning)   # hire/fuel not in
    with_hire = resolve_truck(
        "tipper_truck", repo,
        TruckOverride(hire_rate=Decimal("500"), **planning))
    assert with_hire.overridden_fields == (*tuple(planning), "hire_rate")
    assert with_hire.hire_rate == Decimal("500")


# --- Task 3.2: typed cross-domain references -----------------------------------

def test_reference_parse_bare_scoped_and_display():
    bare = CrossDomainReference.parse(
        "portland_cement_42_5", domain="materials")
    assert (bare.domain, bare.key) == ("materials", "portland_cement_42_5")
    scoped = CrossDomainReference.parse("materials:portland_cement_42_5")
    assert scoped == bare
    assert str(scoped) == "materials:portland_cement_42_5"


def test_reference_parse_fails_closed():
    with pytest.raises(ValidationError, match="targets domain"):
        CrossDomainReference.parse("coverages:x", domain="materials")
    with pytest.raises(ValidationError, match="ambiguous"):
        CrossDomainReference.parse("portland_cement_42_5")
    with pytest.raises(ValidationError, match="ambiguous"):
        CrossDomainReference.parse("user:abc")
    with pytest.raises(ValidationError, match="unknown domain prefix"):
        CrossDomainReference.parse(
            "user:abc", domain="materials", strict_scope=True)
    with pytest.raises(ValidationError, match="non-empty"):
        CrossDomainReference.parse("   ", domain="materials")
    with pytest.raises(ValidationError, match="empty key"):
        CrossDomainReference.parse("materials:")


def test_reference_lookup_fails_closed_for_user_scope_ids():
    repo = MasterDataRepository()
    ref = CrossDomainReference.parse("user:doesnotexist", domain="materials")
    with pytest.raises(UnknownMasterDataKeyError):
        ref.lookup(repo)
    good = CrossDomainReference.parse("materials:river_sand")
    assert good.lookup(repo)["key"] == "river_sand"


def _coverage_record():
    return {
        "key": "cv_t", "activity": "Test activity",
        "material_key": "portland_cement_42_5",
        "coverage_per_unit": "1.2", "coverage_unit": "m2",
        "consumption_unit": "kg", "source": "test", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }


def test_coverage_material_key_validated_as_typed_reference():
    validate_record("coverages", _coverage_record())   # bare key passes
    with pytest.raises(ValidationError, match="unknown domain prefix"):
        validate_record("coverages", dict(
            _coverage_record(), material_key="user:portland_cement_42_5"))
    with pytest.raises(ValidationError, match="targets domain"):
        validate_record("coverages", dict(
            _coverage_record(), material_key="labour:mason"))


def _template_record():
    return {
        "key": "tpl_t", "name": "Test template", "work_unit": "m2",
        "components": [
            {"kind": "material", "ref": "river_sand", "qty_per_unit": "1"},
            {"kind": "labour", "ref": "mason", "qty_per_unit": "2"},
        ],
        "markups": [], "source": "test", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }


def test_rate_template_component_refs_validated_at_load():
    validate_record("rate_templates", _template_record())
    with pytest.raises(ValidationError, match="targets domain"):
        validate_record("rate_templates", dict(
            _template_record(),
            components=[{"kind": "material", "ref": "labour:mason",
                         "qty_per_unit": "1"}]))
    with pytest.raises(MissingFieldError, match="labour"):
        validate_record("rate_templates", dict(
            _template_record(),
            components=[{"kind": "labour", "ref": "  ",
                         "qty_per_unit": "1"}]))
    # subcontract/other carry free text, never a domain pointer
    validate_record("rate_templates", dict(
        _template_record(),
        components=[{"kind": "subcontract", "ref": "PC sum works",
                     "qty_per_unit": "1"}]))


def test_rate_template_fetch_parses_refs_at_runtime():
    class _TplRepo:
        def get(self, domain, key):
            return {"name": "N", "work_unit": "m2",
                    "components": [
                        {"kind": "material", "ref": "labour:mason",
                         "qty_per_unit": "1"}],
                    "markups": []}

        def table_version(self, domain):
            return "v"

    with pytest.raises(ValidationError, match="targets domain"):
        get_rate_template("t", _TplRepo())
    shipped = get_rate_template(
        "concrete_placed_per_m3", MasterDataRepository())
    assert shipped.components
    assert all(component.ref for component in shipped.components)


def test_mortar_keys_accept_typed_scope_and_reject_wrong_domain():
    repo = MasterDataRepository()
    result = resolve_mortar_materials(
        mortar_volume_m3=Decimal("1"), repository=repo,
        cement_material_key="materials:portland_cement_42_5")
    # Lookups ran; no MortarOverride means explicitly unresolved.
    assert isinstance(result, UnresolvedRequirement)
    assert result.requested == "mortar materials (cement, sand)"
    with pytest.raises(ValidationError, match="targets domain"):
        resolve_mortar_materials(
            mortar_volume_m3=Decimal("1"), repository=repo,
            cement_material_key="coverages:river_sand")
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_mortar_materials(
            mortar_volume_m3=Decimal("1"), repository=repo,
            cement_material_key="user:doesnotexist")


def test_material_component_accepts_scoped_material_key():
    component = material_component(
        material_key="materials:river_sand", qty_per_unit="1",
        unit_price="90", wastage_pct=0, repository=MasterDataRepository())
    assert component.cost_per_unit == Decimal("90")


# --- Task 3.3: formwork controller ---------------------------------------------

def test_formwork_controller_slab_soffit_full_schedule():
    view = formwork_controller(
        {"element_type": "slab_soffit", "element": "GF Slab S1",
         "length": "8", "width": "5",
         "sheet_area_m2": "2.88", "reuses": "3",
         "linear_m_per_m2": "1.2", "litres_per_m2": "0.15"},
        "opening: 6")
    assert isinstance(view, FormworkView)
    assert view.element_type == "slab_soffit"
    assert view.element == "GF Slab S1"
    assert view.gross_m2 == "40"
    assert view.total_deducted_m2 == "6"
    assert view.net_m2 == "34"
    assert view.deductions == (KV(label="opening", value="6"),)
    assert view.sheets_to_buy == "4"
    assert Decimal(view.sheets_exact) == Decimal("34") / Decimal("2.88")
    assert view.reuses == "3"
    assert Decimal(view.linear_m) == Decimal("34") * Decimal("1.2")
    assert Decimal(view.litres) == Decimal("34") * Decimal("0.15")
    # Formwork consults no master data: no provenance surface at all.
    assert not hasattr(view, "overrides_used")
    assert not hasattr(view, "master_version")
    assert provenance_status_text(view) == ""


@pytest.mark.parametrize("element_type,dims,expected", [
    ("slab_soffit", {"length": "4", "width": "3"}, "12"),
    ("slab_edge", {"length": "4", "width": "3", "depth": "0.5"}, "7"),
    ("beam", {"length": "5", "width": "0.3", "depth": "0.6"}, "7.5"),
    ("column", {"length": "0.4", "width": "0.4", "height": "3"}, "4.8"),
    ("footing", {"length": "2", "width": "2", "depth": "0.5"}, "4"),
    ("wall", {"length": "4", "height": "2.5"}, "20"),
    ("wall", {"length": "4", "height": "2.5", "faces": "1"}, "10"),
])
def test_formwork_element_types_compute_gross_area(
        element_type, dims, expected):
    assert element_type in FORMWORK_ELEMENT_TYPES
    view = formwork_controller({"element_type": element_type, **dims})
    assert isinstance(view, FormworkView), view
    assert Decimal(view.gross_m2) == Decimal(expected)
    assert Decimal(view.net_m2) == Decimal(expected)   # no deductions
    assert view.sheets_exact == ""      # no rates given: no invention
    assert view.linear_m == ""
    assert view.litres == ""


@pytest.mark.parametrize("inputs,deductions", [
    ({}, ""),
    ({"element_type": "pylon", "length": "1"}, ""),
    ({"element_type": "wall", "length": "6", "height": "3"}, "oops"),
    ({"element_type": "wall", "length": "6", "height": "3"}, "x:99"),
    ({"element_type": "wall", "length": "-6", "height": "3"}, ""),
    ({"element_type": "slab_soffit", "length": "abc", "width": "3"}, ""),
    ({"element_type": "wall", "length": "6", "height": "3",
      "faces": "3"}, ""),
    ({"element_type": "wall", "length": "6"}, ""),
    ({"element_type": "wall", "length": "6", "height": "3",
      "sheet_area_m2": "0"}, ""),
    ({"element_type": "wall", "length": "6", "height": "3",
      "sheet_area_m2": "1", "reuses": "0"}, ""),
    ({"element_type": "wall", "length": "6", "height": "3",
      "sheet_area_m2": "abc"}, ""),
])
def test_formwork_controller_never_raises(inputs, deductions):
    result = formwork_controller(inputs, deductions)
    assert isinstance(result, ErrorView), (inputs, deductions, result)


def test_formwork_controller_class_and_function_agree():
    inputs = {"element_type": "beam", "length": "5",
              "width": "0.3", "depth": "0.6"}
    assert (FormworkController().calculate(inputs)
            == formwork_controller(inputs))


def test_parse_deductions_text():
    assert parse_deductions(None) == ()
    assert parse_deductions("   ") == ()
    assert parse_deductions("soffit hole: 1.5; edge: 2") == (
        ("soffit hole", "1.5"), ("edge", "2"))
    assert parse_deductions("a:1;;b:2") == (("a", "1"), ("b", "2"))
    for bad in ("no-colon", ":1", "a:"):
        with pytest.raises(ValidationError):
            parse_deductions(bad)
    with pytest.raises(ValidationError):
        parse_deductions(["a", "1"])


def test_formwork_takeoff_line_and_boq_section():
    view = formwork_controller(
        {"element_type": "wall", "length": "6", "height": "3",
         "faces": "1"})
    line = extract_takeoff_line("formwork", view, {"element": "Core Wall"})
    assert line.trade == "formwork"
    assert line.unit == "m²"
    assert line.quantity == "18"
    assert line.description == "Core Wall (wall)"
    assert line.takeoff_ref == "Core Wall"
    unnamed = extract_takeoff_line("formwork", view, {})
    assert unnamed.description == "Formwork (wall)"

    session = TakeoffSession()
    session.add_line(line)
    boq = session.to_boq("P", "B")
    section = next(s for s in boq.sections if s.code == "T")
    assert section.title == "Formwork"
    assert TRADE_SECTIONS["formwork"] == ("T", "Formwork", "Temporary works")


def test_formwork_panel_source_pins_stay_intact():
    source = inspect.getsource(views.build_rebar_page)
    assert "REBAR_GRID_COLUMNS" in source
    assert "Advanced Input" in source
    assert "rebar_row_inputs_to_dsl" in source
    assert "Advanced / Raw DSL Input" not in source
    assert "rebar_unit_mass_for_diameter" not in source
    assert "coming soon" not in source


def _display_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    return root


def test_rebar_page_hosts_live_formwork_panel():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rebar")
    app.update_idletasks()

    def walk(widget, panels, buttons):
        for child in widget.winfo_children():
            cls = child.winfo_class()
            if cls == "TLabelframe":
                panels.append(child)
            elif cls == "TButton":
                buttons.append(child)
            walk(child, panels, buttons)

    panels, buttons = [], []
    walk(app.workspace.interior, panels, buttons)
    panel = next((p for p in panels
                  if str(p.cget("text")) == "Formwork Take-off"), None)
    assert panel is not None, "formwork panel missing from the page"

    # Blank calculate fails closed into the panel's own message (the
    # element-type combo carries a default, so length is first to fail).
    calc = next(b for b in buttons
                if str(b.cget("text")) == "Calculate Formwork")
    calc.invoke()
    app.update_idletasks()
    texts = []

    def collect_labels(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TLabel":
                try:
                    texts.append(str(child.cget("text")))
                except Exception:
                    pass
            collect_labels(child)

    collect_labels(app.workspace.interior)
    assert any("length is required" in t for t in texts)

    # Fill a slab soffit and add it: the shared schedule grid lists both
    # the rebar and the formwork trade after the filter change.
    entries = []

    def collect_entries(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TEntry":
                entries.append(child)
            collect_entries(child)

    collect_entries(panel)
    assert len(entries) == 12
    entries[0].insert(0, "GF Slab S1")   # element / mark
    entries[3].insert(0, "8")            # length
    entries[4].insert(0, "5")            # width
    add = next(b for b in buttons
               if str(b.cget("text")) == "Add Formwork to Take-Off")
    add.invoke()
    app.update_idletasks()
    lines = app.session.lines_by_trade("formwork")
    assert len(lines) == 1
    assert lines[0].unit == "m²"
    assert Decimal(lines[0].quantity) == Decimal("40")
    trees = []

    def collect_trees(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "Treeview":
                trees.append(child)
            collect_trees(child)

    collect_trees(app.workspace.interior)
    assert len(trees) == 1
    assert len(trees[0].get_children()) == 1
    app.destroy()
    root.destroy()
