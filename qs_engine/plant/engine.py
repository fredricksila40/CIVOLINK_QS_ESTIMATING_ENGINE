"""Plant & equipment calculation pipeline (Phase 7).

    equipment lookup -> duty duration (quantity / output per basis unit)
      -> hire cost (duration x rate, converted through explicit
         hours_per_day when rate and output bases differ)
      -> operating cost (explicit operating hours x rate, when supplied)

Hour/day conversions REQUIRE an explicit hours_per_day — no working day
is assumed anywhere. Operating cost without a supplied rate is
explicitly absent (None), never zero-filled.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Union

from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.validation import validate_quantity, validate_rate
from ..master_data import resolve as resolve_master
from .results import PlantRequirement, ResolvedPlant

Numeric = Union[Decimal, int, str]

#: Plant numerics the engine consumes.
PLANT_FIELDS = (
    "output_per_unit",
    "rate",
    "operating_cost_per_hour",
)

#: Record keys backing each plant field.
RECORD_KEYS = {
    "output_per_unit": "output_per_unit",
    "rate": "rate",
    "operating_cost_per_hour": "operating_cost_per_hour",
}

BASIS_HOUR = "hour"
BASIS_DAY = "day"


@dataclass(frozen=True)
class PlantOverride:
    """Complete-or-nothing explicit overrides, except operating cost.

    output_per_unit and rate are REQUIRED for any calculation;
    operating_cost_per_hour is OPTIONAL (None = operating cost
    explicitly not estimated).
    """
    output_per_unit: Optional[Decimal] = None
    rate: Optional[Decimal] = None
    operating_cost_per_hour: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in PLANT_FIELDS:
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing_required(self) -> tuple:
        """Required override fields still None (operating excluded)."""
        return tuple(f for f in ("output_per_unit", "rate")
                     if getattr(self, f) is None)

    def is_complete(self) -> bool:
        """True when every required override field is supplied."""
        return not self.missing_required()


def plant_duration(work_quantity: Numeric,
                   output_per_unit: Numeric) -> Decimal:
    """Duty duration in output-basis units (hours or days)."""
    quantity = validate_quantity(work_quantity, "work_quantity")
    output = to_decimal(output_per_unit, "output_per_unit")
    if output <= 0:
        raise ValidationError(f"output_per_unit must be > 0; got {output}")
    return quantity / output


def _basis_checked(value: str, name: str, equipment_key: str) -> str:
    if value not in (BASIS_HOUR, BASIS_DAY):
        raise ValidationError(
            f"Equipment {equipment_key!r} has unknown {name} {value!r}; "
            f"expected 'hour' or 'day'")
    return value


def resolve_plant_equipment(
    equipment_key: str, repository, overrides: PlantOverride = None,
) -> ResolvedPlant:
    """Resolve a machine to usable output and rates, fail-closed.

    NEEDS_VERIFICATION records require complete explicit overrides for
    output and rate (operating cost stays optional); anything less raises
    UnverifiedMasterDataError. Verified or provisional records resolve
    from the table, with per-field overrides allowed and recorded. Field
    merging and the fail-closed precedence hierarchy delegate to the
    unified master-data resolver (Phase 3.1); ``required`` keeps the
    operating cost an optional extra.
    """
    resolved = resolve_master(
        repository, "plant", equipment_key, overrides,
        fields=PLANT_FIELDS, record_keys=RECORD_KEYS,
        required=("output_per_unit", "rate"), noun="Plant")
    values = resolved.values
    record = resolved.record

    output = values["output_per_unit"]
    if output <= 0:
        raise ValidationError(f"output_per_unit must be > 0; got {output}")
    rate = validate_rate(values["rate"], "rate")
    operating = values["operating_cost_per_hour"]
    if operating is not None:
        operating = validate_rate(operating, "operating_cost_per_hour")

    return ResolvedPlant(
        equipment_key=equipment_key,
        work_unit=str(record.get("work_unit", "")),
        output_per_unit=output,
        output_basis=_basis_checked(
            record.get("output_basis"), "output_basis", equipment_key),
        rate=rate,
        rate_unit=_basis_checked(
            record.get("rate_unit"), "rate_unit", equipment_key),
        hire_basis=str(record.get("hire_basis", "")),
        operating_cost_per_hour=operating,
        master_version=resolved.master_version,
        overrides_used=resolved.overrides_used,
        overridden_fields=resolved.overridden_fields,
    )


def calculate_plant_requirement(
    *,
    element: str = "",
    work_quantity: Numeric,
    equipment_key: str,
    repository,
    overrides: PlantOverride = None,
    hours_per_day: Numeric = None,
) -> PlantRequirement:
    """Machine duty requirement (keyword-only inputs).

    hours_per_day is REQUIRED when the hire-rate basis differs from the
    output basis (no working day assumed); contradictory supply with
    matching bases fails closed.
    """
    resolved = resolve_plant_equipment(equipment_key, repository, overrides)
    quantity = validate_quantity(work_quantity, "work_quantity")
    duration = plant_duration(quantity, resolved.output_per_unit)

    hours = None
    if hours_per_day is not None:
        hours = to_decimal(hours_per_day, "hours_per_day")
        if hours <= 0:
            raise ValidationError(f"hours_per_day must be > 0; got {hours}")
    bases_differ = resolved.rate_unit != resolved.output_basis
    if bases_differ and hours is None:
        raise ValidationError(
            f"hours_per_day is required: rate basis "
            f"{resolved.rate_unit!r} differs from output basis "
            f"{resolved.output_basis!r} (no working day is assumed)")
    if bases_differ:
        if resolved.rate_unit == BASIS_DAY:
            hire_cost = duration / hours * resolved.rate
        else:
            hire_cost = duration * hours * resolved.rate
    else:
        hire_cost = duration * resolved.rate

    operating_hours = None
    operating_cost = None
    needs_hours_for_operating = (
        resolved.operating_cost_per_hour is not None
        and resolved.output_basis == BASIS_DAY)
    if resolved.operating_cost_per_hour is not None:
        if resolved.output_basis == BASIS_HOUR:
            operating_hours = duration
        elif hours is None:
            raise ValidationError(
                "Operating cost needs operating hours: output basis is "
                "'day', so supply hours_per_day to derive them")
        else:
            operating_hours = duration * hours
        operating_cost = operating_hours * resolved.operating_cost_per_hour

    if (hours is not None and not bases_differ
            and not needs_hours_for_operating):
        raise ValidationError(
            "hours_per_day is unneeded: rate/output bases match and no "
            "day-basis operating hours are derived; omit it")

    return PlantRequirement(
        element=element,
        work_quantity=quantity,
        work_unit=resolved.work_unit,
        duration_value=duration,
        duration_basis=resolved.output_basis,
        hire_cost=hire_cost,
        operating_hours=operating_hours,
        operating_cost=operating_cost,
        total_cost=hire_cost + (operating_cost or Decimal("0")),
        hours_per_day=hours,
        resolved_plant=resolved,
    )
