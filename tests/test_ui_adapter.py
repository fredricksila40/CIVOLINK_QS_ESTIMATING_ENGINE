"""UI adapter tests (Phase 13): controller contracts, headless.

Controllers take strings and return view-models or ErrorView — never
raise engine errors, never compute. Widget instantiation is never
attempted here (views.py needs a display); panel wiring is pinned by
spec-to-controller mapping instead.
"""

from decimal import Decimal

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.ui import controllers, viewmodels, views
from qs_engine.ui.controllers import (
    boq_view_controller,
    concrete_controller,
    document_payload_controller,
    earthworks_controller,
    excel_export_controller,
    finishes_controller,
    labour_controller,
    logistics_plan_controller,
    masonry_controller,
    parse_decimal,
    parse_int,
    parse_optional_decimal,
    plant_controller,
    project_setup_controller,
    rate_builder_controller,
    rebar_controller,
)
from qs_engine.ui.viewmodels import ErrorView


def repo():
    return MasterDataRepository()


def concrete_overrides():
    return {"dry_factor": "2", "cement_ratio": "1", "sand_ratio": "1",
            "aggregate_ratio": "2", "wc_ratio": "0.5",
            "cement_density_kg_per_m3": "1000",
            "sand_density_kg_per_m3": "1000",
            "aggregate_density_kg_per_m3": "1000",
            "water_density_kg_per_L": "1", "bag_mass_kg": "50"}


# --- parsing ---------------------------------------------------------------

def test_parse_decimal_valid_and_strict():
    assert parse_decimal("12.5", "x") == Decimal("12.5")
    assert parse_decimal(" 3 ", "x") == Decimal("3")
    assert parse_decimal(5, "x") == Decimal("5")
    assert parse_decimal(Decimal("1.1"), "x") == Decimal("1.1")
    with pytest.raises(ValidationError):
        parse_decimal("", "x")
    with pytest.raises(ValidationError):
        parse_decimal(1.5, "x")
    with pytest.raises(ValidationError):
        parse_decimal(True, "x")
    with pytest.raises(ValidationError):
        parse_decimal("1,000", "x")
    with pytest.raises(ValidationError):
        parse_decimal("abc", "x")


def test_parse_int_and_optional():
    assert parse_int("3", "x") == 3
    assert parse_int(3, "x") == 3
    with pytest.raises(ValidationError):
        parse_int("3.0", "x")
    with pytest.raises(ValidationError):
        parse_int(2.0, "x")
    assert parse_optional_decimal("", "x") is None
    assert parse_optional_decimal(None, "x") is None
    assert parse_optional_decimal("2.5", "x") == Decimal("2.5")


# --- project setup ----------------------------------------------------------

def test_project_setup_known_and_custom():
    setup = project_setup_controller(standard="SMM")
    assert setup.known is True
    assert setup.edition == ""
    custom = project_setup_controller(standard="POMI", edition="2021")
    assert custom.known is False
    with pytest.raises(ValidationError):
        project_setup_controller(standard="  ")


# --- concrete ---------------------------------------------------------------

def test_concrete_happy_path_exact():
    # 1x1x1 m, K=2, 1:1:2, densities 1000 -> bags exactly 10, water 250.
    view = concrete_controller(
        {"length": "1", "width": "1", "thickness": "1",
         "class_key": "class_c20", "element": "slab"},
        repo(), concrete_overrides())
    assert view.wet_m3 == "1"
    assert view.bags_exact == "10.0"
    assert view.bags_order == "10"
    assert view.water_litres == "250.00"
    assert view.element == "slab"
    assert view.overrides_used is True


def test_concrete_error_paths_become_views():
    bad = concrete_controller(
        {"length": "abc", "width": "1", "thickness": "1",
         "class_key": "class_c20"}, repo(), concrete_overrides())
    assert isinstance(bad, ErrorView)
    unverified = concrete_controller(
        {"length": "1", "width": "1", "thickness": "1",
         "class_key": "class_c20"}, repo())
    assert isinstance(unverified, ErrorView)
    assert "NEEDS_VERIFICATION" in unverified.message


# --- masonry ----------------------------------------------------------------

def test_masonry_happy_path_exact():
    view = masonry_controller(
        {"wall_length": "4", "wall_height": "2",
         "unit_key": "concrete_block_200mm", "element": "wall"},
        repo(),
        {"unit_length_mm": "390", "unit_height_mm": "190",
         "unit_thickness_mm": "200", "bed_joint_mm": "10",
         "perp_joint_mm": "10", "wastage_pct": "5",
         "mortar_cement_ratio": "1", "mortar_sand_ratio": "3",
         "mortar_dry_factor": "1.5",
         "mortar_sand_density_kg_per_m3": "1000",
         "cement_density_kg_per_m3": "1000", "bag_mass_kg": "50"},
        openings=[{"width": "1", "height": "1", "count": 1}])
    assert view.net_m2 == "7"
    assert view.units_order == "92"
    assert view.wet_mortar_m3 == "0.036560000"


def test_masonry_error_path():
    view = masonry_controller(
        {"wall_length": "4", "wall_height": "2",
         "unit_key": "concrete_block_200mm"}, repo())
    assert isinstance(view, ErrorView)


# --- rebar ------------------------------------------------------------------

def test_rebar_happy_and_empty():
    view = rebar_controller(
        [{"bar_key": "Y12", "count": "10", "length_per_bar_m": "6",
          "laps_per_bar": "2", "lap_length_m": "1.0",
          "hook_extra_per_bar_m": "0.3",
          "mass_kg_per_m": "2"}],
        wastage_pct="5", tying_wire_kg_per_tonne="2", repository=repo())
    assert view.total_mass_kg == "166.0"
    assert view.total_mass_tonnes == "0.1660"
    assert view.tying_wire_kg == "0.3320"
    empty = rebar_controller([], wastage_pct="5", repository=repo())
    assert isinstance(empty, ErrorView)


# --- earthworks ---------------------------------------------------------------

def test_earthworks_happy_and_error():
    view = earthworks_controller(
        {"length": "10", "width": "1", "depth": "1.5",
         "soil_key": "clay_soil", "displaced_substructure_m3": "3",
         "element": "trench"},
        repo(),
        {"swell_factor": "1.25", "compact_factor": "1.1",
         "density_kg_per_m3": "1000"})
    assert view.excavation_bank_m3 == "15.0"
    assert view.dispose_loose_m3 == "5.550"
    bad = earthworks_controller(
        {"length": "10", "width": "1", "depth": "1.5",
         "soil_key": "clay_soil"}, repo())
    assert isinstance(bad, ErrorView)


# --- finishes -----------------------------------------------------------------

def test_finishes_kinds_and_unresolved():
    plaster = finishes_controller("plaster", {
        "length": "4", "height": "3", "thickness": "12",
        "element": "wall"})
    assert ("Volume (m³)", "0.288") in [
        (line.label, line.value) for line in plaster.lines]
    tiles = finishes_controller("tiles", {
        "length": "5", "width": "2", "tile_length_mm": "500",
        "tile_width_mm": "500", "joint_mm": "0"})
    assert tiles.unresolved != ()
    assert tiles.lines[-1].value == "—"
    paint = finishes_controller("paint", {
        "length": "4", "height": "3", "coats": "3"})
    assert ("Total coated (m²)", "36") in [
        (line.label, line.value) for line in paint.lines]
    screed = finishes_controller("screed", {
        "length": "5", "width": "4", "thickness": "50"})
    assert ("Volume (m³)", "1.000") in [
        (line.label, line.value) for line in screed.lines]
    unknown = finishes_controller("roofing", {})
    assert isinstance(unknown, ErrorView)


# --- labour / plant -------------------------------------------------------------

def test_labour_happy_and_missing_hours():
    view = labour_controller(
        {"work_quantity": "100", "trade_key": "mason"}, repo(),
        {"output_per_day": "25", "gang_skilled": "2", "gang_unskilled": "4",
         "skilled_rate": "1500", "unskilled_rate": "800"})
    assert view.total_cost == "24800"
    assert view.skilled_person_hours == "—"
    assert labour_controller(
        {"work_quantity": "-5", "trade_key": "mason"}, repo(),
        {"output_per_day": "25", "gang_skilled": "2", "gang_unskilled": "4",
         "skilled_rate": "1500", "unskilled_rate": "800"}).__class__ is ErrorView


def test_plant_happy_and_error():
    view = plant_controller(
        {"work_quantity": "100", "equipment_key": "backhoe_excavator"},
        repo(),
        {"output_per_unit": "20", "rate": "24000"},
        hours_per_day="8")
    assert view.total_cost == "15000.000"
    assert view.duration_basis == "hour"
    bad = plant_controller(
        {"work_quantity": "100", "equipment_key": "backhoe_excavator"},
        repo(),
        {"output_per_unit": "20", "rate": "24000"})
    assert isinstance(bad, ErrorView)


# --- logistics ------------------------------------------------------------------

def test_logistics_happy_and_error():
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
    assert view.trucks_required == "2"
    assert view.limiting == "weight"
    bad = logistics_plan_controller(
        {"total_loose_m3": "200", "loose_density_t_per_m3": "2",
         "truck_key": "tipper_truck", "distance_km": "10",
         "available_minutes_per_day": "480", "target_per_day": "100",
         "target_unit": "tonne"}, repo())
    assert isinstance(bad, ErrorView)


# --- rate builder ---------------------------------------------------------------

def test_rate_builder_exact_and_plant_guidance():
    view = rate_builder_controller(
        [{"kind": "material", "material_key": "portland_cement_42_5",
          "qty_per_unit": "2", "unit_price": "100",
          "wastage_pct": "10"},
         {"kind": "subcontract", "amount_per_unit": "50",
          "description": "PC", "provisional": "yes"}],
        [("profit", "10")], "sequential", "rate", "m³", repo())
    assert view.direct_cost == "270"
    assert view.gross_rate == "297"
    assert view.markup_policy == "sequential"
    plant_line = rate_builder_controller(
        [{"kind": "plant"}], [], "sequential", "r", "m³", repo())
    assert isinstance(plant_line, ErrorView)
    assert "PlantRequirement" in plant_line.message
    assert isinstance(rate_builder_controller(
        [], [], "sequential", "r", "m³", repo()), ErrorView)


# --- BOQ view + export triggers ---------------------------------------------------

def _two_line_boq():
    from qs_engine.boq.models import (
        Boq, BoqItem, BoqSection, BoqSubsection, explicit_rate,
        provisional_sum,
    )
    return Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("E", "Earthworks", (
            BoqItem(description="Dig", trade="E", unit="m³",
                    quantity=Decimal("10"),
                    pricing=explicit_rate(Decimal("100"), "t")),
            BoqItem(description="PC", trade="E", unit="sum",
                    quantity=Decimal("1"),
                    pricing=provisional_sum(Decimal("50"), "pc")),
        )),
    ))


def test_boq_view_rendering():
    view = boq_view_controller(_two_line_boq())
    assert view.grand_total == "1050"
    assert view.has_unresolved is False
    assert view.sections[0].items[0].status == "priced"
    assert view.sections[0].items[1].status == "provisional"
    assert isinstance(boq_view_controller(None), ErrorView)


def test_excel_export_trigger(tmp_path):
    from qs_engine.boq.compiler import compile_boq
    out = str(tmp_path / "ui.xlsx")
    view = excel_export_controller(
        compile_boq(_two_line_boq()), out, project_name="P")
    assert view.path == out
    import os
    assert os.path.exists(out)
    bad = excel_export_controller("nope", out)
    assert isinstance(bad, ErrorView)


def test_document_payload_trigger():
    from qs_engine.boq.compiler import compile_boq
    payload = document_payload_controller(
        compile_boq(_two_line_boq()), "Tender Schedule", "Tender")
    assert payload.document_title == "Tender Schedule"
    assert payload.summary.resolved_subtotal == "1050"
    bad = document_payload_controller(
        compile_boq(_two_line_boq()), " ", "Tender")
    assert isinstance(bad, ErrorView)


# --- determinism + view wiring ------------------------------------------------------

def test_controllers_deterministic():
    first = concrete_controller(
        {"length": "2", "width": "2", "thickness": "0.1",
         "class_key": "class_c20"}, repo(), {
            "dry_factor": "1.5", "cement_ratio": "1", "sand_ratio": "2",
            "aggregate_ratio": "4", "wc_ratio": "0.5",
            "cement_density_kg_per_m3": "1000",
            "sand_density_kg_per_m3": "1000",
            "aggregate_density_kg_per_m3": "1000",
            "water_density_kg_per_L": "1", "bag_mass_kg": "50"})
    second = concrete_controller(
        {"length": "2", "width": "2", "thickness": "0.1",
         "class_key": "class_c20"}, repo(), {
            "dry_factor": "1.5", "cement_ratio": "1", "sand_ratio": "2",
            "aggregate_ratio": "4", "wc_ratio": "0.5",
            "cement_density_kg_per_m3": "1000",
            "sand_density_kg_per_m3": "1000",
            "aggregate_density_kg_per_m3": "1000",
            "water_density_kg_per_L": "1", "bag_mass_kg": "50"})
    assert first == second


def test_panel_specs_map_to_controllers():
    import qs_engine.ui.controllers as ctrl
    for key, (title, name, fields) in views.PANEL_SPECS.items():
        assert callable(getattr(ctrl, name, None)), key
        assert isinstance(fields, list)


def test_viewmodels_importable():
    assert viewmodels.ErrorView("x").message == "x"
