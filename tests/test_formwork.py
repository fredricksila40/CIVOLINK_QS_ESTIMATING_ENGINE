"""Formwork engine tests (Phase 4).

All numeric fixtures below are ARBITRARY TEST VALUES to exercise the math —
sheet areas, prop rates, and release rates are explicit per-call parameters
here, not project data, and must never be mistaken for verified values.
"""

from decimal import Decimal

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.formwork.engine import (
    apply_deductions,
    beam_formwork_area,
    column_formwork_area,
    footing_formwork_area,
    release_agent_litres,
    schedule_boarding,
    schedule_props,
    slab_edge_area,
    slab_soffit_area,
    wall_formwork_area,
)


# --- element contact areas -------------------------------------------------

def test_slab_soffit():
    assert slab_soffit_area(Decimal("4"), Decimal("3")).value == Decimal("12")


def test_slab_edge():
    # Perimeter 2x(4+3) x 0.3 depth = 4.2.
    assert slab_edge_area(4, 3, Decimal("0.3")).value == Decimal("4.2")


def test_beam_two_sides_plus_soffit():
    # 5 x (2x0.6 + 0.3) = 7.5.
    qty = beam_formwork_area(Decimal("5"), Decimal("0.3"), Decimal("0.6"))
    assert qty.value == Decimal("7.5")
    assert qty.unit == "m\u00b2"


def test_column_perimeter():
    # 2x(0.4+0.4) x 3 = 4.8.
    assert column_formwork_area(Decimal("0.4"), Decimal("0.4"),
                                Decimal("3")).value == Decimal("4.8")


def test_footing_sides():
    # 2x(2+2) x 0.5 = 4.
    assert footing_formwork_area(2, 2, Decimal("0.5")).value == Decimal("4")


def test_wall_faces_option():
    assert wall_formwork_area(Decimal("4"), Decimal("2.5")).value == Decimal("20")
    assert wall_formwork_area(Decimal("4"), Decimal("2.5"), faces=1).value == Decimal("10")
    with pytest.raises(ValidationError):
        wall_formwork_area(Decimal("4"), Decimal("2.5"), faces=3)


def test_element_bad_dims_rejected():
    with pytest.raises(Exception):
        slab_soffit_area(Decimal("0"), Decimal("3"))
    with pytest.raises(Exception):
        beam_formwork_area(Decimal("5"), Decimal("-0.3"), Decimal("0.6"))


# --- deductions ------------------------------------------------------------

def test_deductions_itemised():
    areas = apply_deductions(Decimal("12"), [("beam intersection", Decimal("2.5"))])
    assert areas.gross_m2 == Decimal("12")
    assert areas.total_deducted_m2 == Decimal("2.5")
    assert areas.net_m2 == Decimal("9.5")
    assert areas.deductions[0].label == "beam intersection"


def test_deductions_default_empty():
    areas = apply_deductions(Decimal("12"))
    assert areas.net_m2 == Decimal("12")
    assert areas.deductions == ()


def test_deductions_excess_fails_closed():
    with pytest.raises(ValidationError):
        apply_deductions(Decimal("12"), [("too big", Decimal("12.01"))])


def test_deductions_reject_bad_items():
    with pytest.raises(ValidationError):
        apply_deductions(Decimal("12"), [(Decimal("2.5"),)])
    with pytest.raises(ValidationError):
        apply_deductions(Decimal("12"), [("", Decimal("1"))])
    with pytest.raises(ValidationError):
        apply_deductions(Decimal("12"), [("x", Decimal("-1"))])


# --- material scheduling ---------------------------------------------------

def test_boarding_exact_and_reuse():
    sched = schedule_boarding(Decimal("12"), Decimal("2.4"), reuses=1)
    assert sched.sheets_exact == Decimal("5")
    assert sched.sheets_to_buy == 5
    reused = schedule_boarding(Decimal("12"), Decimal("2.4"), reuses=3)
    assert reused.sheets_to_buy == 2  # ceiling(5/3)


def test_boarding_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        schedule_boarding(Decimal("12"), Decimal("0"))
    with pytest.raises(ValidationError):
        schedule_boarding(Decimal("12"), Decimal("2.4"), reuses=0)
    with pytest.raises(ValidationError):
        schedule_boarding(Decimal("12"), Decimal("2.4"), reuses="3")
    with pytest.raises(ValidationError):
        schedule_boarding(Decimal("-12"), Decimal("2.4"))


def test_props_linear_metres_unrounded():
    sched = schedule_props(Decimal("12"), Decimal("0.5"))
    assert sched.linear_m == Decimal("6.0")
    with pytest.raises(ValidationError):
        schedule_props(Decimal("12"), Decimal("-0.5"))


def test_release_agent_litres():
    agent = release_agent_litres(Decimal("12"), Decimal("0.1"))
    assert agent.litres == Decimal("1.2")
    with pytest.raises(ValidationError):
        release_agent_litres(Decimal("12"), Decimal("-0.1"))


def test_takeoff_to_schedule_chain():
    # Slab 4x3 soffit, less a 2.5 m2 intersection, boarded on 2.4 m2 sheets.
    gross = slab_soffit_area(Decimal("4"), Decimal("3")).value
    areas = apply_deductions(gross, [("intersection", Decimal("2.5"))])
    sched = schedule_boarding(areas.net_m2, Decimal("2.4"), reuses=1)
    assert areas.net_m2 == Decimal("9.5")
    assert sched.sheets_exact == Decimal("9.5") / Decimal("2.4")
    assert sched.sheets_to_buy == 4  # ceiling(3.9583...)
