"""Formwork contact-area takeoff and material scheduling (Phase 4).

Two-step API, mirroring the architecture's take-off/resolution split:

  1. Take-off: element contact-area functions + apply_deductions().
  2. Scheduling: boarding / props / release-agent from EXPLICIT rates.

Sheet areas, prop rates, release rates, and reuse factors are per-call
parameters — never constants in this module — until verified master data
exists (see the release-agent coverage skeleton). All arithmetic Decimal.
"""

from decimal import Decimal
from typing import Iterable, Union

from ..contracts.models import Quantity
from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.rounding import apply_ceiling
from ..core.units import M2, convert
from ..core.validation import validate_dimension, validate_quantity
from .results import (
    BoardingSchedule,
    FormworkAreas,
    FormworkDeduction,
    PropSchedule,
    ReleaseAgent,
)

Numeric = Union[Decimal, int, str]


def _rect(length: Numeric, width: Numeric, unit: str,
          length_name: str, width_name: str) -> Decimal:
    """Length x width in m2 with validated positive dimensions."""
    length_m = convert(validate_dimension(length, length_name), unit, "m")
    width_m = convert(validate_dimension(width, width_name), unit, "m")
    return length_m * width_m


def slab_soffit_area(length: Numeric, width: Numeric, unit: str = "m") -> Quantity:
    """Slab soffit contact area (L x W)."""
    return Quantity(_rect(length, width, unit, "length", "width"), M2)


def slab_edge_area(length: Numeric, width: Numeric, depth: Numeric,
                   unit: str = "m") -> Quantity:
    """Slab edge formwork: perimeter x depth."""
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    depth_m = convert(validate_dimension(depth, "depth"), unit, "m")
    return Quantity(Decimal("2") * (length_m + width_m) * depth_m, M2)


def beam_formwork_area(length: Numeric, width: Numeric, depth: Numeric,
                       unit: str = "m") -> Quantity:
    """Beam: two sides plus soffit, L x (2D + W)."""
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    depth_m = convert(validate_dimension(depth, "depth"), unit, "m")
    return Quantity(length_m * (Decimal("2") * depth_m + width_m), M2)


def column_formwork_area(length: Numeric, width: Numeric, height: Numeric,
                         unit: str = "m") -> Quantity:
    """Rectangular column: full perimeter x height. Circular sections
    belong to a later phase."""
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    height_m = convert(validate_dimension(height, "height"), unit, "m")
    return Quantity(Decimal("2") * (length_m + width_m) * height_m, M2)


def footing_formwork_area(length: Numeric, width: Numeric, depth: Numeric,
                          unit: str = "m") -> Quantity:
    """Pad footing sides: perimeter x depth (base unformed)."""
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    depth_m = convert(validate_dimension(depth, "depth"), unit, "m")
    return Quantity(Decimal("2") * (length_m + width_m) * depth_m, M2)


def wall_formwork_area(length: Numeric, height: Numeric, faces: int = 2,
                       unit: str = "m") -> Quantity:
    """Wall formwork: L x H per face. faces=2 both sides, 1 single-sided
    (e.g. against an existing structure)."""
    if faces not in (1, 2):
        raise ValidationError(f"faces must be 1 or 2; got {faces!r}")
    area = _rect(length, height, unit, "length", "height")
    return Quantity(area * faces, M2)


def apply_deductions(gross_m2: Numeric,
                     deductions: Iterable[tuple] = ()) -> FormworkAreas:
    """Subtract itemised overlaps/intersections from a gross contact area.

    deductions is an iterable of (label, area_m2) pairs. Deductions beyond
    gross are inconsistent input and fail closed.
    """
    gross = validate_quantity(gross_m2, "gross_m2")
    items = []
    total = Decimal("0")
    for index, deduction in enumerate(deductions):
        try:
            label, area = deduction
        except (TypeError, ValueError):
            raise ValidationError(
                f"Deduction #{index} must be a (label, area_m2) pair; "
                f"got {deduction!r}") from None
        if not label or not str(label).strip():
            raise ValidationError(f"Deduction #{index} must have a label")
        area_m2 = validate_quantity(area, f"deductions[{index}].area_m2")
        items.append(FormworkDeduction(label=str(label), area_m2=area_m2))
        total += area_m2
    net = gross - total
    if net < 0:
        raise ValidationError(
            f"Deductions ({total} m2) exceed gross contact area ({gross} m2)")
    return FormworkAreas(
        gross_m2=gross,
        deductions=tuple(items),
        total_deducted_m2=total,
        net_m2=net,
    )


def schedule_boarding(contact_area_m2: Numeric, sheet_area_m2: Numeric,
                      reuses: int = 1) -> BoardingSchedule:
    """Plywood/board ordering. Each sheet covers sheet_area x reuses over
    the project; procurement ceilings the exact figure. reuses >= 1."""
    area = validate_quantity(contact_area_m2, "contact_area_m2")
    sheet = validate_quantity(sheet_area_m2, "sheet_area_m2")
    if sheet <= 0:
        raise ValidationError(f"sheet_area_m2 must be > 0; got {sheet}")
    if isinstance(reuses, bool) or not isinstance(reuses, int) or reuses < 1:
        raise ValidationError(f"reuses must be an integer >= 1; got {reuses!r}")
    exact = area / sheet
    ordered = apply_ceiling(exact / reuses, "sheet")
    return BoardingSchedule(
        contact_area_m2=area,
        sheet_area_m2=sheet,
        reuses=reuses,
        sheets_exact=exact,
        sheets_to_buy=ordered.ordering_quantity,
    )


def schedule_props(contact_area_m2: Numeric,
                   linear_m_per_m2: Numeric) -> PropSchedule:
    """Props/scaffolding in linear metres (continuous stock: unrounded)."""
    area = validate_quantity(contact_area_m2, "contact_area_m2")
    rate = validate_quantity(linear_m_per_m2, "linear_m_per_m2")
    return PropSchedule(
        contact_area_m2=area,
        linear_m_per_m2=rate,
        linear_m=area * rate,
    )


def release_agent_litres(contact_area_m2: Numeric,
                         litres_per_m2: Numeric) -> ReleaseAgent:
    """Release agent litres from an explicit rate (verified coverage
    table supplies this rate in a later phase)."""
    area = validate_quantity(contact_area_m2, "contact_area_m2")
    rate = validate_quantity(litres_per_m2, "litres_per_m2")
    return ReleaseAgent(
        contact_area_m2=area,
        litres_per_m2=rate,
        litres=area * rate,
    )
