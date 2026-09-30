"""Labour calculation pipeline (Phase 7).

    trade lookup -> gang daily/hourly cost
      -> duration (quantity / output per gang-day)
      -> person-day split (skilled : unskilled)
      -> cost (duration x gang cost, converted through explicit
         hours_per_day on hourly rate bases only)

There is no assumed working day in this module: hourly rates REQUIRE an
explicit hours_per_day call parameter, and a contradictory
hours_per_day-with-daily-rates call fails closed. Gang-days stay
fractional; whole-day hiring is procurement, not calculation.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Union

from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.validation import validate_quantity, validate_rate
from ..master_data import resolve as resolve_master
from .results import LabourRequirement, ResolvedLabourTrade

Numeric = Union[Decimal, int, str]

#: Labour numerics the engine consumes.
LABOUR_FIELDS = (
    "output_per_day",
    "gang_skilled",
    "gang_unskilled",
    "skilled_rate",
    "unskilled_rate",
)

#: Record keys backing each labour field.
RECORD_KEYS = {
    "output_per_day": "output_per_day",
    "gang_skilled": "gang_skilled",
    "gang_unskilled": "gang_unskilled",
    "skilled_rate": "skilled_rate",
    "unskilled_rate": "unskilled_rate",
}

RATE_UNIT_DAY = "day"
RATE_UNIT_HOUR = "hour"


@dataclass(frozen=True)
class LabourTradeOverride:
    """Complete-or-nothing explicit overrides for one calculation call."""
    output_per_day: Optional[Decimal] = None
    gang_skilled: Optional[int] = None
    gang_unskilled: Optional[int] = None
    skilled_rate: Optional[Decimal] = None
    unskilled_rate: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in ("output_per_day", "skilled_rate", "unskilled_rate"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing(self) -> tuple:
        """Names of override fields still None."""
        return tuple(f for f in LABOUR_FIELDS if getattr(self, f) is None)

    def is_complete(self) -> bool:
        """True when every override field is supplied."""
        return not self.missing()


def _validate_gang_count(value, name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(
            f"{name} must be an integer >= 0; got {value!r}")
    if isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise ValidationError(
                f"{name} must be an integer >= 0; got {value!r}")
        value = int(text)
    if not isinstance(value, int) or value < 0:
        raise ValidationError(
            f"{name} must be an integer >= 0; got {value!r}")
    return value


def gang_cost_per_rate_unit(gang_skilled: int, gang_unskilled: int,
                            skilled_rate: Numeric,
                            unskilled_rate: Numeric) -> Decimal:
    """Gang cost per rate unit (day or hour, matching the rate basis)."""
    skilled = _validate_gang_count(gang_skilled, "gang_skilled")
    unskilled = _validate_gang_count(gang_unskilled, "gang_unskilled")
    if skilled + unskilled == 0:
        raise ValidationError("gang must contain at least one worker")
    return (skilled * validate_rate(skilled_rate, "skilled_rate")
            + unskilled * validate_rate(unskilled_rate, "unskilled_rate"))


def labour_duration_days(work_quantity: Numeric,
                         output_per_day: Numeric) -> Decimal:
    """Gang-days for a work quantity at a gang output rate."""
    quantity = validate_quantity(work_quantity, "work_quantity")
    output = to_decimal(output_per_day, "output_per_day")
    if output <= 0:
        raise ValidationError(f"output_per_day must be > 0; got {output}")
    return quantity / output


def resolve_labour_trade(
    trade_key: str, repository, overrides: LabourTradeOverride = None,
) -> ResolvedLabourTrade:
    """Resolve a trade to usable productivity and rates, fail-closed.

    NEEDS_VERIFICATION records require complete explicit overrides;
    anything less raises UnverifiedMasterDataError. Verified or
    provisional records resolve from the table, with per-field overrides
    allowed and recorded. Field merging and the fail-closed precedence
    hierarchy delegate to the unified master-data resolver (Phase 3.1);
    values stay raw here so gang counts keep their integer validation.
    """
    resolved = resolve_master(
        repository, "labour", trade_key, overrides,
        fields=LABOUR_FIELDS, record_keys=RECORD_KEYS,
        coerce=False, noun="Labour trade")
    values = resolved.values
    record = resolved.record

    output = to_decimal(values["output_per_day"], "output_per_day")
    if output <= 0:
        raise ValidationError(f"output_per_day must be > 0; got {output}")
    skilled = _validate_gang_count(values["gang_skilled"], "gang_skilled")
    unskilled = _validate_gang_count(values["gang_unskilled"], "gang_unskilled")
    if skilled + unskilled == 0:
        raise ValidationError(
            f"Trade {trade_key!r} gang must contain at least one worker")
    rate_unit = record.get("rate_unit")
    if rate_unit not in (RATE_UNIT_DAY, RATE_UNIT_HOUR):
        raise ValidationError(
            f"Trade {trade_key!r} has unknown rate_unit {rate_unit!r}; "
            f"expected 'day' or 'hour'")

    return ResolvedLabourTrade(
        trade_key=trade_key,
        work_unit=str(record.get("work_unit", "")),
        output_per_day=output,
        gang_skilled=skilled,
        gang_unskilled=unskilled,
        skilled_rate=validate_rate(values["skilled_rate"], "skilled_rate"),
        unskilled_rate=validate_rate(values["unskilled_rate"], "unskilled_rate"),
        rate_unit=rate_unit,
        master_version=resolved.master_version,
        overrides_used=resolved.overrides_used,
        overridden_fields=resolved.overridden_fields,
    )


def calculate_labour_requirement(
    *,
    element: str = "",
    work_quantity: Numeric,
    trade_key: str,
    repository,
    overrides: LabourTradeOverride = None,
    hours_per_day: Numeric = None,
) -> LabourRequirement:
    """Activity labour requirement (keyword-only inputs).

    On hourly rate bases hours_per_day is REQUIRED (no assumed working
    day); on daily bases a supplied hours_per_day is contradictory and
    fails closed.
    """
    resolved = resolve_labour_trade(trade_key, repository, overrides)
    quantity = validate_quantity(work_quantity, "work_quantity")
    duration = labour_duration_days(quantity, resolved.output_per_day)
    skilled_days = duration * resolved.gang_skilled
    unskilled_days = duration * resolved.gang_unskilled
    gang_rate = gang_cost_per_rate_unit(
        resolved.gang_skilled, resolved.gang_unskilled,
        resolved.skilled_rate, resolved.unskilled_rate)

    hours = None
    skilled_hours = None
    unskilled_hours = None
    if resolved.rate_unit == RATE_UNIT_HOUR:
        if hours_per_day is None:
            raise ValidationError(
                "hours_per_day is required with hourly rates "
                "(no working day is assumed)")
        hours = to_decimal(hours_per_day, "hours_per_day")
        if hours <= 0:
            raise ValidationError(f"hours_per_day must be > 0; got {hours}")
        skilled_hours = skilled_days * hours
        unskilled_hours = unskilled_days * hours
        daily_cost = gang_rate * hours
    else:
        if hours_per_day is not None:
            raise ValidationError(
                "hours_per_day contradicts daily rates; omit it")
        daily_cost = gang_rate

    return LabourRequirement(
        element=element,
        work_quantity=quantity,
        work_unit=resolved.work_unit,
        duration_gang_days=duration,
        skilled_person_days=skilled_days,
        unskilled_person_days=unskilled_days,
        skilled_person_hours=skilled_hours,
        unskilled_person_hours=unskilled_hours,
        gang_cost_per_day=daily_cost,
        total_cost=duration * daily_cost,
        hours_per_day=hours,
        resolved_trade=resolved,
    )
