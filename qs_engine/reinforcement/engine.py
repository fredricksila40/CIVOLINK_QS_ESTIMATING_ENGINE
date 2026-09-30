"""Reinforcement calculation pipeline (Phase 4).

    bar lookup (Y-key) -> unit mass (verified table value, or nominal-mass
      formula with explicitly supplied steel density)
      -> bar line (count x (length + laps x lap_len + hooks))
      -> schedule totals (kg + tonnes) -> wastage -> tying wire

The nominal-mass formula is mass = pi x (d/1000)^2 / 4 x density with an
EXACT decimal pi literal and a caller-supplied density. The convenient
d^2/162.2 shortcut is deliberately NOT used: it bakes in an unstated
7850 kg/m3 density. No steel density lives in this module.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Union

from ..core.assumptions import VerificationStatus
from ..core.decimal_policy import to_decimal
from ..core.errors import UnverifiedMasterDataError, ValidationError
from ..core.units import KG, TONNE, convert
from ..core.validation import (
    validate_density,
    validate_percentage,
    validate_quantity,
)
from ..core.wastage import apply_wastage
from ..master_data import resolve as resolve_master
from .results import BarLineResult, RebarSchedule, ResolvedRebarBar

Numeric = Union[Decimal, int, str]

#: Exact decimal pi (mathematical constant, not an engineering assumption).
PI = Decimal("3.141592653589793238462643383279")

MASS_SOURCE_TABLE = "table"
MASS_SOURCE_FORMULA = "formula"
#: Estimator-specified unit mass (explicit override) — never shown as a
#: table value: provenance must not claim master data that wasn't used.
MASS_SOURCE_OVERRIDE = "override"


@dataclass(frozen=True)
class RebarBarOverride:
    """Explicit per-call overrides for one bar designation.

    mass_kg_per_m: estimator-specified unit mass (method "override").
    diameter_mm + steel_density_kg_per_m3: nominal-mass formula path.
    wastage_pct: informational override carried for later phases.
    """
    mass_kg_per_m: Optional[Decimal] = None
    diameter_mm: Optional[Decimal] = None
    steel_density_kg_per_m3: Optional[Decimal] = None
    wastage_pct: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in ("mass_kg_per_m", "diameter_mm",
                           "steel_density_kg_per_m3", "wastage_pct"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))


@dataclass(frozen=True)
class BarLineInput:
    """One cutting/schedule line. All extras are per bar, in metres."""
    bar_key: str
    count: int
    length_per_bar_m: Numeric
    laps_per_bar: int = 0
    lap_length_m: Numeric = 0
    hook_extra_per_bar_m: Numeric = 0

    def __post_init__(self):
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise ValidationError(
                f"count must be an integer number of bars; "
                f"got {self.count!r}")
        if self.count <= 0:
            raise ValidationError(f"count must be > 0; got {self.count}")
        if isinstance(self.laps_per_bar, bool) or not isinstance(
                self.laps_per_bar, int):
            raise ValidationError(
                f"laps_per_bar must be an integer; got {self.laps_per_bar!r}")
        if self.laps_per_bar < 0:
            raise ValidationError(
                f"laps_per_bar must be >= 0; got {self.laps_per_bar}")


def nominal_bar_mass(diameter_mm: Numeric,
                     steel_density_kg_per_m3: Numeric) -> Decimal:
    """Nominal unit mass in kg/m from first principles.

    mass = pi x (d_mm/1000)^2 / 4 x density. Both inputs validated;
    density is caller-supplied (verified master data or explicit
    override), never a constant in this module.
    """
    diameter = to_decimal(diameter_mm, "diameter_mm")
    if diameter <= 0:
        raise ValidationError(f"diameter_mm must be > 0; got {diameter}")
    density = validate_density(steel_density_kg_per_m3, "steel_density")
    diameter_m = diameter / Decimal("1000")
    return PI * diameter_m * diameter_m / Decimal("4") * density


def resolve_rebar_bar(
    bar_key: str, repository, overrides: RebarBarOverride = None,
) -> ResolvedRebarBar:
    """Resolve a bar designation to a usable unit mass, fail-closed.

    Precedence: explicit mass override -> verified/provisional table value
    -> nominal-mass formula with explicit diameter + density overrides.
    Anything less raises UnverifiedMasterDataError. mass_source records
    which path was taken: "override", "table", or "formula". The raw
    field merge runs through the unified master-data resolver (Phase 3.1,
    strict=False); this wrapper owns the three-path mass logic — mass
    never resolves from an unverified record even when it carries one.
    """
    overrides = overrides or RebarBarOverride()
    resolved = resolve_master(
        repository, "rebar_bars", bar_key, overrides,
        fields=("mass_kg_per_m", "diameter_mm", "wastage_pct",
                "steel_density_kg_per_m3"),
        record_keys={"wastage_pct": "default_wastage_pct"},
        required=(), strict=False, noun="Rebar bar")
    status = resolved.verification_status
    master_version = resolved.master_version

    diameter = resolved.values["diameter_mm"]
    if diameter is not None and diameter <= 0:
        raise ValidationError(f"diameter_mm must be > 0; got {diameter}")

    mass = None
    source = None
    overridden = []
    if overrides.mass_kg_per_m is not None:
        mass = resolved.values["mass_kg_per_m"]
        source = MASS_SOURCE_OVERRIDE
        overridden.append("mass_kg_per_m")
    elif (status in (VerificationStatus.VERIFIED, VerificationStatus.PROVISIONAL)
          and resolved.values["mass_kg_per_m"] is not None):
        mass = resolved.values["mass_kg_per_m"]
        source = MASS_SOURCE_TABLE
    elif overrides.steel_density_kg_per_m3 is not None and diameter is not None:
        mass = nominal_bar_mass(diameter, overrides.steel_density_kg_per_m3)
        source = MASS_SOURCE_FORMULA
        overridden.append("steel_density_kg_per_m3")
        if overrides.diameter_mm is not None:
            overridden.append("diameter_mm")
    else:
        raise UnverifiedMasterDataError(
            f"Rebar bar {bar_key!r} is NEEDS_VERIFICATION with no usable "
            f"unit mass; supply an explicit mass_kg_per_m override, or "
            f"diameter_mm + steel_density_kg_per_m3 for the nominal-mass "
            f"formula, or verify the master-data record."
        )
    if mass <= 0:
        raise ValidationError(f"mass_kg_per_m must be > 0; got {mass}")
    # An explicit diameter input is provenance even when the mass came
    # from another path (it shaped the resolution the estimator saw).
    if (overrides.diameter_mm is not None
            and "diameter_mm" not in overridden):
        overridden.append("diameter_mm")

    wastage = resolved.values["wastage_pct"]
    if wastage is not None:
        if "wastage_pct" in resolved.overridden_fields:
            overridden.append("wastage_pct")
            wastage = validate_percentage(wastage, "wastage_pct")
        else:
            wastage = validate_percentage(wastage, "default_wastage_pct")

    return ResolvedRebarBar(
        bar_key=bar_key,
        diameter_mm=diameter,
        mass_kg_per_m=mass,
        mass_source=source,
        wastage_pct=wastage,
        master_version=master_version,
        overrides_used=bool(overridden),
        overridden_fields=tuple(overridden),
    )


def calculate_bar_line(line: BarLineInput, resolved: ResolvedRebarBar) -> BarLineResult:
    """Expand one schedule line to total length and mass."""
    if line.bar_key != resolved.bar_key:
        raise ValidationError(
            f"Bar line key {line.bar_key!r} does not match resolved bar "
            f"{resolved.bar_key!r}")
    length = validate_quantity(line.length_per_bar_m, "length_per_bar_m")
    lap = validate_quantity(line.lap_length_m, "lap_length_m")
    hooks = validate_quantity(line.hook_extra_per_bar_m, "hook_extra_per_bar_m")
    per_bar = length + line.laps_per_bar * lap + hooks
    total_length = per_bar * line.count
    return BarLineResult(
        bar_key=line.bar_key,
        count=line.count,
        length_per_bar_m=length,
        laps_per_bar=line.laps_per_bar,
        lap_length_m=lap,
        hook_extra_per_bar_m=hooks,
        total_length_m=total_length,
        total_mass_kg=total_length * resolved.mass_kg_per_m,
        mass_kg_per_m=resolved.mass_kg_per_m,
    )


def calculate_rebar_schedule(
    line_results: Iterable[BarLineResult],
    wastage_pct: Numeric,
    tying_wire_kg_per_tonne: Numeric = None,
) -> RebarSchedule:
    """Schedule totals with explicit wastage and optional tying wire.

    wastage_pct is REQUIRED on every call (no record default is applied
    here, so schedules never inherit an unseen allowance). tying wire is
    estimated only when an explicit kg-per-tonne ratio is supplied.
    """
    lines = tuple(line_results)
    if not lines:
        raise ValidationError("Rebar schedule requires at least one line")
    total_length = sum((line.total_length_m for line in lines), Decimal("0"))
    total_kg = sum((line.total_mass_kg for line in lines), Decimal("0"))
    total_tonnes = convert(total_kg, KG, TONNE)
    wasted = apply_wastage(
        total_kg, validate_percentage(wastage_pct, "wastage_pct"))
    wire_ratio = None
    wire_kg = None
    if tying_wire_kg_per_tonne is not None:
        wire_ratio = validate_quantity(
            tying_wire_kg_per_tonne, "tying_wire_kg_per_tonne")
        wire_kg = total_tonnes * wire_ratio
    return RebarSchedule(
        lines=lines,
        total_length_m=total_length,
        total_mass_kg=total_kg,
        total_mass_tonnes=total_tonnes,
        wastage=wasted,
        tying_wire_kg=wire_kg,
        tying_wire_kg_per_tonne=wire_ratio,
    )
