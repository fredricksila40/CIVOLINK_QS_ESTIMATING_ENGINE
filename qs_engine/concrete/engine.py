"""Concrete calculation pipeline (Phase 2).

    wet volume (m3)
      -> dry constituent volume (x K_dry)
      -> ratio split (cement : sand : aggregate)
      -> masses (x densities)
      -> cement bags (/ bag mass, explicit ceiling option)
      -> water (cement x W/C / water density)

All arithmetic is Decimal and unrounded until the caller rounds.
No engineering constants live here: every numeric arrives from verified
master data or from explicit per-call overrides.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Union

from ..contracts.models import Quantity
from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.rounding import apply_ceiling
from ..core.units import M3, convert
from ..core.validation import (
    validate_density,
    validate_dimension,
    validate_quantity,
)
from ..master_data import resolve as resolve_master
from .results import (
    CementBags,
    ConcreteRequirement,
    ConstituentMasses,
    ConstituentVolumes,
    ResolvedMix,
    WaterRequirement,
)

Numeric = Union[Decimal, int, str]

#: Mix numerics the engine consumes, in resolution order.
MIX_FIELDS = (
    "dry_factor",
    "cement_ratio",
    "sand_ratio",
    "aggregate_ratio",
    "wc_ratio",
    "cement_density_kg_per_m3",
    "sand_density_kg_per_m3",
    "aggregate_density_kg_per_m3",
    "water_density_kg_per_L",
    "bag_mass_kg",
)

#: Record keys backing each mix field.
RECORD_KEYS = {
    "dry_factor": "dry_volume_factor",
    "cement_ratio": "cement_ratio",
    "sand_ratio": "sand_ratio",
    "aggregate_ratio": "aggregate_ratio",
    "wc_ratio": "wc_ratio",
    "cement_density_kg_per_m3": "cement_density_kg_per_m3",
    "sand_density_kg_per_m3": "sand_density_kg_per_m3",
    "aggregate_density_kg_per_m3": "aggregate_density_kg_per_m3",
    "water_density_kg_per_L": "water_density_kg_per_L",
    "bag_mass_kg": "bag_mass_kg",
}


@dataclass(frozen=True)
class ConcreteMixOverride:
    """Complete-or-nothing explicit overrides for one calculation call.

    Every field defaults to None. A NEEDS_VERIFICATION class record
    requires ALL fields supplied; otherwise resolution fails closed.
    """
    dry_factor: Optional[Decimal] = None
    cement_ratio: Optional[Decimal] = None
    sand_ratio: Optional[Decimal] = None
    aggregate_ratio: Optional[Decimal] = None
    wc_ratio: Optional[Decimal] = None
    cement_density_kg_per_m3: Optional[Decimal] = None
    sand_density_kg_per_m3: Optional[Decimal] = None
    aggregate_density_kg_per_m3: Optional[Decimal] = None
    water_density_kg_per_L: Optional[Decimal] = None
    bag_mass_kg: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in MIX_FIELDS:
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing(self) -> tuple:
        """Names of override fields still None."""
        return tuple(f for f in MIX_FIELDS if getattr(self, f) is None)

    def is_complete(self) -> bool:
        """True when every override field is supplied."""
        return not self.missing()


def wet_concrete_volume(
    length: Numeric, width: Numeric, thickness: Numeric, unit: str = "m",
) -> Quantity:
    """Wet (placed) concrete volume in m3 from element dimensions."""
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    thickness_m = convert(validate_dimension(thickness, "thickness"), unit, "m")
    return Quantity(length_m * width_m * thickness_m, M3)


def dry_constituent_volume(wet_volume_m3: Numeric, dry_factor: Numeric) -> Decimal:
    """Scale wet volume by the dry-volume factor K_dry (>= 1 by definition)."""
    wet = validate_quantity(wet_volume_m3, "wet_volume_m3")
    factor = to_decimal(dry_factor, "dry_factor")
    if factor < 1:
        raise ValidationError(
            f"dry_factor must be >= 1 (dry volume cannot be less than wet); "
            f"got {factor}"
        )
    return wet * factor


def split_constituents(
    dry_volume_m3: Numeric,
    cement_ratio: Numeric,
    sand_ratio: Numeric,
    aggregate_ratio: Numeric,
    dry_factor: Numeric,
) -> ConstituentVolumes:
    """Split dry volume by mix parts; parts sum exactly to dry volume."""
    dry = validate_quantity(dry_volume_m3, "dry_volume_m3")
    parts = {
        "cement_ratio": to_decimal(cement_ratio, "cement_ratio"),
        "sand_ratio": to_decimal(sand_ratio, "sand_ratio"),
        "aggregate_ratio": to_decimal(aggregate_ratio, "aggregate_ratio"),
    }
    for name, part in parts.items():
        if part <= 0:
            raise ValidationError(f"{name} must be > 0; got {part}")
    total = parts["cement_ratio"] + parts["sand_ratio"] + parts["aggregate_ratio"]
    return ConstituentVolumes(
        dry_volume_m3=dry,
        cement_m3=dry * parts["cement_ratio"] / total,
        sand_m3=dry * parts["sand_ratio"] / total,
        aggregate_m3=dry * parts["aggregate_ratio"] / total,
        cement_ratio=parts["cement_ratio"],
        sand_ratio=parts["sand_ratio"],
        aggregate_ratio=parts["aggregate_ratio"],
        dry_factor=to_decimal(dry_factor, "dry_factor"),
    )


def constituent_masses(
    volumes: ConstituentVolumes,
    cement_density_kg_per_m3: Numeric,
    sand_density_kg_per_m3: Numeric,
    aggregate_density_kg_per_m3: Numeric,
) -> ConstituentMasses:
    """Constituent masses in kg (unrounded)."""
    cement_density = validate_density(cement_density_kg_per_m3, "cement_density")
    sand_density = validate_density(sand_density_kg_per_m3, "sand_density")
    aggregate_density = validate_density(
        aggregate_density_kg_per_m3, "aggregate_density")
    return ConstituentMasses(
        cement_kg=volumes.cement_m3 * cement_density,
        sand_kg=volumes.sand_m3 * sand_density,
        aggregate_kg=volumes.aggregate_m3 * aggregate_density,
    )


def cement_bags(
    cement_mass_kg: Numeric, bag_mass_kg: Numeric, round_up: bool = True,
) -> CementBags:
    """Cement bags from cement mass. No default bag mass exists: the caller
    supplies it from verified master data or an explicit override.

    round_up=True ceilings via the central rounding service and keeps the
    exact figure; False returns the exact figure with no ordering quantity.
    """
    mass = validate_quantity(cement_mass_kg, "cement_mass_kg")
    bag = to_decimal(bag_mass_kg, "bag_mass_kg")
    if bag <= 0:
        raise ValidationError(f"bag_mass_kg must be > 0; got {bag}")
    calculated = mass / bag
    if round_up:
        ordered = apply_ceiling(calculated, "bag")
        return CementBags(
            calculated_bags=calculated,
            ordering_bags=ordered.ordering_quantity,
            bag_mass_kg=bag,
            ceiling_applied=True,
        )
    return CementBags(
        calculated_bags=calculated,
        ordering_bags=None,
        bag_mass_kg=bag,
        ceiling_applied=False,
    )


def water_requirement(
    cement_mass_kg: Numeric,
    wc_ratio: Numeric,
    water_density_kg_per_L: Numeric,
) -> WaterRequirement:
    """Mixing water in litres. Water density is an explicit parameter —
    never a hidden 1.0 — so the basis stays auditable."""
    mass = validate_quantity(cement_mass_kg, "cement_mass_kg")
    ratio = to_decimal(wc_ratio, "wc_ratio")
    if ratio <= 0:
        raise ValidationError(f"wc_ratio must be > 0; got {ratio}")
    density = validate_density(water_density_kg_per_L, "water_density")
    return WaterRequirement(
        water_litres=mass * ratio / density,
        wc_ratio=ratio,
        cement_mass_kg=mass,
        water_density_kg_per_L=density,
    )


def resolve_mix(class_key: str, repository, overrides: ConcreteMixOverride = None) -> ResolvedMix:
    """Resolve a concrete class to usable numerics, fail-closed.

    NEEDS_VERIFICATION records (or null numerics) require complete explicit
    overrides; anything less raises UnverifiedMasterDataError. Verified or
    provisional records resolve from the table, with per-field overrides
    allowed and recorded. Field merging and the fail-closed precedence
    hierarchy delegate to the unified master-data resolver (Phase 3.1);
    this wrapper owns use-time validation and the typed result.
    """
    resolved = resolve_master(
        repository, "concrete_classes", class_key, overrides,
        fields=MIX_FIELDS, record_keys=RECORD_KEYS, noun="Concrete class")
    values = resolved.values

    # Use-time validation of every numeric (regardless of source).
    if values["dry_factor"] < 1:
        raise ValidationError(
            f"dry_factor must be >= 1; got {values['dry_factor']}")
    for ratio_name in ("cement_ratio", "sand_ratio", "aggregate_ratio"):
        if values[ratio_name] <= 0:
            raise ValidationError(
                f"{ratio_name} must be > 0; got {values[ratio_name]}")
    validate_density(values["cement_density_kg_per_m3"], "cement_density")
    validate_density(values["sand_density_kg_per_m3"], "sand_density")
    validate_density(values["aggregate_density_kg_per_m3"], "aggregate_density")
    validate_density(values["water_density_kg_per_L"], "water_density")
    if values["bag_mass_kg"] <= 0:
        raise ValidationError(
            f"bag_mass_kg must be > 0; got {values['bag_mass_kg']}")
    if values["wc_ratio"] <= 0:
        raise ValidationError(f"wc_ratio must be > 0; got {values['wc_ratio']}")

    return ResolvedMix(
        class_key=class_key,
        master_version=resolved.master_version,
        overrides_used=resolved.overrides_used,
        overridden_fields=resolved.overridden_fields,
        **values,
    )


def calculate_concrete_requirement(
    *,
    length: Numeric,
    width: Numeric,
    thickness: Numeric,
    unit: str = "m",
    class_key: str,
    repository,
    overrides: ConcreteMixOverride = None,
    round_bags_up: bool = True,
    element: str = "",
) -> ConcreteRequirement:
    """Full concrete pipeline for one element pour (keyword-only inputs)."""
    wet = wet_concrete_volume(length, width, thickness, unit)
    mix = resolve_mix(class_key, repository, overrides)
    dry = dry_constituent_volume(wet.value, mix.dry_factor)
    volumes = split_constituents(
        dry, mix.cement_ratio, mix.sand_ratio, mix.aggregate_ratio,
        mix.dry_factor)
    masses = constituent_masses(
        volumes, mix.cement_density_kg_per_m3, mix.sand_density_kg_per_m3,
        mix.aggregate_density_kg_per_m3)
    bags = cement_bags(masses.cement_kg, mix.bag_mass_kg, round_up=round_bags_up)
    water = water_requirement(
        masses.cement_kg, mix.wc_ratio, mix.water_density_kg_per_L)
    return ConcreteRequirement(
        element=element,
        wet_volume=wet,
        constituents=volumes,
        masses=masses,
        bags=bags,
        water=water,
        resolved_mix=mix,
    )
