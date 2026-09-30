"""Earthworks, excavation, hardcore, and membrane pipeline (Phase 5).

    clearance area -> topsoil strip volume
    excavation (bank, with working-space allowance each side)
      -> swell (bank x K_swell = loose cart-away state)
      -> backfill (bank - displaced substructure)
      -> backfill loose (bank x K_compact, or bank uncompacted)
      -> dispose (loose dug - backfill loose; negative = net import)
    hardcore/blinding beds (area x thickness; loose supply x K_compact)
    membranes with lap scaling (area x (1 + lap%))

Bulk excavation and trenching share excavation_volume (rectangular prism
with working space); geometry is identical, only the element differs.
Factors >= 1 are definitional (swell/compaction cannot shrink volume);
anything less fails closed. All arithmetic Decimal, unrounded.
No engineering constants live here.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Union

from ..contracts.models import Quantity
from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.units import M2, M3, convert
from ..core.validation import (
    validate_density,
    validate_dimension,
    validate_percentage,
    validate_quantity,
)
from ..master_data import resolve as resolve_master
from .results import EarthworksBalance, ResolvedSoil

Numeric = Union[Decimal, int, str]

#: Soil numerics the engine consumes.
SOIL_FIELDS = ("swell_factor", "compact_factor", "density_kg_per_m3")

#: Record keys backing each soil field.
RECORD_KEYS = {
    "swell_factor": "swell_factor",
    "compact_factor": "compact_factor",
    "density_kg_per_m3": "density_kg_per_m3",
}


@dataclass(frozen=True)
class SoilOverride:
    """Complete-or-nothing explicit overrides for one calculation call."""
    swell_factor: Optional[Decimal] = None
    compact_factor: Optional[Decimal] = None
    density_kg_per_m3: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in SOIL_FIELDS:
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing(self) -> tuple:
        """Names of override fields still None."""
        return tuple(f for f in SOIL_FIELDS if getattr(self, f) is None)

    def is_complete(self) -> bool:
        """True when every override field is supplied."""
        return not self.missing()


def _factor_at_least_one(value: Numeric, name: str) -> Decimal:
    """Swell/compaction/dry factors scale volume up; < 1 is meaningless."""
    factor = to_decimal(value, name)
    if factor < 1:
        raise ValidationError(f"{name} must be >= 1; got {factor}")
    return factor


def clearance_area(length: Numeric, width: Numeric, unit: str = "m") -> Quantity:
    """Site clearance / topsoil strip area in m2."""
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    return Quantity(length_m * width_m, M2)


def topsoil_strip_volume(area_m2: Numeric, strip_depth: Numeric,
                         unit: str = "m") -> Quantity:
    """Topsoil strip volume in m3 from area and strip depth."""
    area = validate_quantity(area_m2, "area_m2")
    depth_m = convert(validate_dimension(strip_depth, "strip_depth"), unit, "m")
    return Quantity(area * depth_m, M3)


def excavation_volume(length: Numeric, width: Numeric, depth: Numeric,
                      unit: str = "m", working_space_m: Numeric = 0) -> Quantity:
    """Bank (in-situ) excavation volume in m3.

    working_space_m is the formwork-access allowance added to EACH side,
    i.e. plan dimensions grow by twice the allowance. Serves bulk
    excavation and trenching alike (identical geometry).
    """
    space_m = convert(validate_quantity(working_space_m, "working_space_m"),
                      unit, "m")
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    depth_m = convert(validate_dimension(depth, "depth"), unit, "m")
    return Quantity(
        (length_m + Decimal("2") * space_m)
        * (width_m + Decimal("2") * space_m) * depth_m, M3)


def swell_volume(bank_volume_m3: Numeric, swell_factor: Numeric) -> Decimal:
    """Loose cart-away-state volume: bank x K_swell."""
    bank = validate_quantity(bank_volume_m3, "bank_volume_m3")
    return bank * _factor_at_least_one(swell_factor, "swell_factor")


def loose_for_compacted_target(compacted_m3: Numeric,
                               compact_factor: Numeric) -> Decimal:
    """Loose supply needed to achieve a compacted target: target x K."""
    target = validate_quantity(compacted_m3, "compacted_m3")
    return target * _factor_at_least_one(compact_factor, "compact_factor")


def compacted_yield(loose_m3: Numeric, compact_factor: Numeric) -> Decimal:
    """Compacted volume achieved from placed loose volume: loose / K."""
    loose = validate_quantity(loose_m3, "loose_m3")
    return loose / _factor_at_least_one(compact_factor, "compact_factor")


def backfill_volume(excavation_bank_m3: Numeric,
                    displaced_substructure_m3: Numeric) -> Decimal:
    """Backfill (bank): excavation minus displaced substructure/concrete.

    Displaced volume beyond excavation is inconsistent input and fails
    closed — unlike mortar, no ceiling effect can explain it.
    """
    excavation = validate_quantity(excavation_bank_m3, "excavation_bank_m3")
    displaced = validate_quantity(
        displaced_substructure_m3, "displaced_substructure_m3")
    if displaced > excavation:
        raise ValidationError(
            f"Displaced substructure ({displaced} m3) exceeds excavation "
            f"({excavation} m3)")
    return excavation - displaced


def cartaway_volume(loose_dug_m3: Numeric,
                    backfill_loose_reused_m3: Numeric) -> Decimal:
    """Dispose (loose): dug loose minus backfill loose reused.

    Both inputs are loose-state volumes — the bank/loose mixing is
    resolved BEFORE this step (see backfill_loose_requirement). A
    negative result is a net IMPORT requirement, exposed not hidden.
    """
    dug = validate_quantity(loose_dug_m3, "loose_dug_m3")
    reused = validate_quantity(backfill_loose_reused_m3, "backfill_loose_reused_m3")
    return dug - reused


def backfill_loose_requirement(backfill_bank_m3: Numeric,
                               compact_factor: Numeric = None) -> Decimal:
    """Loose volume the backfill consumes.

    Compacted backfill: bank x K_compact. Uncompacted return: pass
    compact_factor=None to reuse the bank volume as-is.
    """
    bank = validate_quantity(backfill_bank_m3, "backfill_bank_m3")
    if compact_factor is None:
        return bank
    return bank * _factor_at_least_one(compact_factor, "compact_factor")


def layer_volume(area_m2: Numeric, thickness: Numeric,
                 unit: str = "m") -> Quantity:
    """Compacted bed volume in m3 for hardcore/blinding layers."""
    area = validate_quantity(area_m2, "area_m2")
    thickness_m = convert(
        validate_dimension(thickness, "thickness"), unit, "m")
    return Quantity(area * thickness_m, M3)


def hardcore_bed_volume(area_m2: Numeric, thickness: Numeric,
                        unit: str = "m") -> Quantity:
    """Hardcore bed (compacted) volume in m3."""
    return layer_volume(area_m2, thickness, unit)


def blinding_volume(area_m2: Numeric, thickness: Numeric,
                    unit: str = "m") -> Quantity:
    """Quarry-dust/sand blinding (compacted) volume in m3."""
    return layer_volume(area_m2, thickness, unit)


def membrane_area_with_laps(area_m2: Numeric, lap_pct: Numeric) -> Decimal:
    """DPM / anti-termite area with lap allowance: area x (1 + lap%)."""
    area = validate_quantity(area_m2, "area_m2")
    lap = validate_percentage(lap_pct, "lap_pct")
    return area * (Decimal("1") + lap / Decimal("100"))


def resolve_soil(soil_key: str, repository,
                 overrides: SoilOverride = None) -> ResolvedSoil:
    """Resolve a soil type to usable factors, fail-closed.

    NEEDS_VERIFICATION records require complete explicit overrides;
    anything less raises UnverifiedMasterDataError. Verified or
    provisional records resolve from the table, with per-field overrides
    allowed and recorded. Field merging and the fail-closed precedence
    hierarchy delegate to the unified master-data resolver (Phase 3.1).
    """
    resolved = resolve_master(
        repository, "soils", soil_key, overrides,
        fields=SOIL_FIELDS, record_keys=RECORD_KEYS, noun="Soil")
    values = resolved.values

    _factor_at_least_one(values["swell_factor"], "swell_factor")
    _factor_at_least_one(values["compact_factor"], "compact_factor")
    validate_density(values["density_kg_per_m3"], "density")

    return ResolvedSoil(
        soil_key=soil_key,
        master_version=resolved.master_version,
        overrides_used=resolved.overrides_used,
        overridden_fields=resolved.overridden_fields,
        **values,
    )


def calculate_foundation_earthworks(
    *,
    element: str = "",
    length: Numeric,
    width: Numeric,
    depth: Numeric,
    unit: str = "m",
    working_space_m: Numeric = 0,
    soil_key: str,
    repository,
    overrides: SoilOverride = None,
    displaced_substructure_m3: Numeric = 0,
    compact_backfill: bool = True,
) -> EarthworksBalance:
    """Foundation excavation cart-away/backfill balance (keyword-only).

    compact_backfill=True applies K_compact to the backfill loose
    requirement; False returns the bank volume uncompacted.
    """
    soil = resolve_soil(soil_key, repository, overrides)
    excavation = excavation_volume(
        length, width, depth, unit, working_space_m).value
    loose_dug = swell_volume(excavation, soil.swell_factor)
    backfill_bank = backfill_volume(
        excavation, validate_quantity(
            displaced_substructure_m3, "displaced_substructure_m3"))
    backfill_loose = backfill_loose_requirement(
        backfill_bank, soil.compact_factor if compact_backfill else None)
    dispose = cartaway_volume(loose_dug, backfill_loose)
    return EarthworksBalance(
        element=element,
        excavation_bank_m3=excavation,
        loose_dug_m3=loose_dug,
        displaced_substructure_m3=to_decimal(
            displaced_substructure_m3, "displaced_substructure_m3"),
        backfill_bank_m3=backfill_bank,
        backfill_loose_m3=backfill_loose,
        dispose_loose_m3=dispose,
        bank_mass_kg=excavation * soil.density_kg_per_m3,
        swell_factor=soil.swell_factor,
        compact_factor_used=soil.compact_factor if compact_backfill else None,
        resolved_soil=soil,
    )
