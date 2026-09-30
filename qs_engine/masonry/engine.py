"""Masonry calculation pipeline (Phase 3).

    wall areas (gross - openings = net)
      -> unit takeoff (face incl. joints -> exact -> +waste -> ceiling)
      -> conservative mortar: wet = gross wall volume - net unit volume
         (net volume uses waste-inclusive CEILED units; wet floored at 0
         with both inputs exposed on the result for audit)
      -> dry mortar (x K_dry,mortar) -> cement:sand split
      -> cement bags (explicit ceiling) + sand mass/volume

Dry-factor scaling and bagging reuse the tested concrete-engine services;
no logic is duplicated. All arithmetic is Decimal and unrounded until the
caller rounds. No engineering constants live here.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Union

from ..concrete.engine import cement_bags, dry_constituent_volume
from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.rounding import apply_ceiling
from ..core.units import M2, MM2, MM3, M3, convert
from ..core.validation import (
    validate_density,
    validate_dimension,
    validate_percentage,
    validate_quantity,
)
from ..core.wastage import apply_wastage
from ..master_data import resolve as resolve_master
from .results import (
    MasonryRequirement,
    MasonryTakeoff,
    MortarConstituents,
    MortarVolumes,
    ResolvedMasonryUnit,
    WallAreas,
)

Numeric = Union[Decimal, int, str]

#: Masonry numerics the engine consumes, in resolution order.
MASONRY_FIELDS = (
    "unit_length_mm",
    "unit_height_mm",
    "unit_thickness_mm",
    "bed_joint_mm",
    "perp_joint_mm",
    "wastage_pct",
    "mortar_cement_ratio",
    "mortar_sand_ratio",
    "mortar_dry_factor",
    "mortar_sand_density_kg_per_m3",
    "cement_density_kg_per_m3",
    "bag_mass_kg",
)

#: Record keys backing each masonry field.
RECORD_KEYS = {
    "unit_length_mm": "length_mm",
    "unit_height_mm": "height_mm",
    "unit_thickness_mm": "thickness_mm",
    "bed_joint_mm": "bed_joint_mm",
    "perp_joint_mm": "perp_joint_mm",
    "wastage_pct": "default_wastage_pct",
    "mortar_cement_ratio": "mortar_cement_ratio",
    "mortar_sand_ratio": "mortar_sand_ratio",
    "mortar_dry_factor": "mortar_dry_factor",
    "mortar_sand_density_kg_per_m3": "mortar_sand_density_kg_per_m3",
    "cement_density_kg_per_m3": "cement_density_kg_per_m3",
    "bag_mass_kg": "bag_mass_kg",
}


@dataclass(frozen=True)
class MasonryUnitOverride:
    """Complete-or-nothing explicit overrides for one calculation call.

    Every field defaults to None. A NEEDS_VERIFICATION unit record
    requires ALL fields supplied; otherwise resolution fails closed.
    """
    unit_length_mm: Optional[Decimal] = None
    unit_height_mm: Optional[Decimal] = None
    unit_thickness_mm: Optional[Decimal] = None
    bed_joint_mm: Optional[Decimal] = None
    perp_joint_mm: Optional[Decimal] = None
    wastage_pct: Optional[Decimal] = None
    mortar_cement_ratio: Optional[Decimal] = None
    mortar_sand_ratio: Optional[Decimal] = None
    mortar_dry_factor: Optional[Decimal] = None
    mortar_sand_density_kg_per_m3: Optional[Decimal] = None
    cement_density_kg_per_m3: Optional[Decimal] = None
    bag_mass_kg: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in MASONRY_FIELDS:
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing(self) -> tuple:
        """Names of override fields still None."""
        return tuple(f for f in MASONRY_FIELDS if getattr(self, f) is None)

    def is_complete(self) -> bool:
        """True when every override field is supplied."""
        return not self.missing()


def wall_areas(
    length: Numeric,
    height: Numeric,
    unit: str = "m",
    openings: Iterable[tuple] = (),
) -> WallAreas:
    """Gross, deducted, and net wall areas in m2.

    openings is an iterable of (width, height) pairs in the same unit as
    the wall. Net area below zero (openings exceed wall) is inconsistent
    input and fails closed.
    """
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    height_m = convert(validate_dimension(height, "height"), unit, "m")
    gross = length_m * height_m
    deducted = Decimal("0")
    for index, opening in enumerate(openings):
        try:
            width, tall = opening
        except (TypeError, ValueError):
            raise ValidationError(
                f"Opening #{index} must be a (width, height) pair; "
                f"got {opening!r}") from None
        deducted += (convert(validate_dimension(width, f"opening[{index}].width"),
                             unit, "m")
                     * convert(validate_dimension(tall, f"opening[{index}].height"),
                               unit, "m"))
    net = gross - deducted
    if net < 0:
        raise ValidationError(
            f"Openings ({deducted} m2) exceed gross wall area ({gross} m2)")
    return WallAreas(gross_m2=gross, openings_m2=deducted, net_m2=net)


def unit_takeoff(
    net_area_m2: Numeric,
    unit_length_mm: Numeric,
    unit_height_mm: Numeric,
    bed_joint_mm: Numeric,
    perp_joint_mm: Numeric,
    wastage_pct: Numeric,
) -> MasonryTakeoff:
    """Unit count at three visible stages.

    Face area includes one bed joint course and one perp joint per unit.
    Joints may be zero (dry-stack) but never negative. Units are discrete:
    ordering is always ceiled, with exact and waste-inclusive figures kept.
    """
    net = validate_quantity(net_area_m2, "net_area_m2")
    length_mm = validate_dimension(unit_length_mm, "unit_length_mm")
    height_mm = validate_dimension(unit_height_mm, "unit_height_mm")
    bed_mm = validate_quantity(bed_joint_mm, "bed_joint_mm")
    perp_mm = validate_quantity(perp_joint_mm, "perp_joint_mm")
    face_mm2 = (length_mm + perp_mm) * (height_mm + bed_mm)
    face_m2 = convert(face_mm2, MM2, M2)
    exact = net / face_m2 if face_m2 != 0 else Decimal("0")
    wasted = apply_wastage(exact, validate_percentage(wastage_pct, "wastage_pct"))
    ordered = apply_ceiling(wasted.quantity_after_wastage, "piece")
    return MasonryTakeoff(
        units_exact=exact,
        units_with_waste=wasted.quantity_after_wastage,
        units_order=ordered.ordering_quantity,
        wastage=wasted,
        unit_face_area_m2=face_m2,
        net_area_m2=net,
    )


def gross_wall_volume(net_area_m2: Numeric, thickness_mm: Numeric) -> Decimal:
    """Wall solid volume in m3 from net (post-deduction) area x thickness."""
    net = validate_quantity(net_area_m2, "net_area_m2")
    thickness_m = convert(
        validate_dimension(thickness_mm, "thickness_mm"), "mm", "m")
    return net * thickness_m


def net_unit_volume(
    units_order: int, unit_length_mm: Numeric, unit_height_mm: Numeric,
    unit_thickness_mm: Numeric,
) -> Decimal:
    """Total net unit volume in m3 for the (ceiled, waste-inclusive) order."""
    if units_order < 0:
        raise ValidationError(f"units_order must be >= 0; got {units_order}")
    per_unit_m3 = convert(
        validate_dimension(unit_length_mm, "unit_length_mm")
        * validate_dimension(unit_height_mm, "unit_height_mm")
        * validate_dimension(unit_thickness_mm, "unit_thickness_mm"),
        MM3, M3)
    return per_unit_m3 * units_order


def wet_mortar_volume(gross_wall_volume_m3: Numeric,
                      net_unit_volume_m3: Numeric) -> Decimal:
    """Conservative wet mortar identity, floored at zero.

    Wet = gross wall volume - net unit volume (waste-inclusive, ceiled).
    On tiny patches ceiling can push net above gross; mortar cannot be
    negative, so the result floors at 0. Both inputs stay visible on
    MortarVolumes, so the clamp is auditable, never silent.
    """
    gross = validate_quantity(gross_wall_volume_m3, "gross_wall_volume_m3")
    net = validate_quantity(net_unit_volume_m3, "net_unit_volume_m3")
    wet = gross - net
    return wet if wet > 0 else Decimal("0")


def split_mortar(
    wet_mortar_m3: Numeric,
    dry_mortar_m3: Numeric,
    cement_ratio: Numeric,
    sand_ratio: Numeric,
    dry_factor: Numeric,
    gross_wall_volume_m3: Numeric,
    net_unit_volume_m3: Numeric,
) -> MortarVolumes:
    """Split dry mortar by cement:sand parts; parts sum exactly to dry."""
    wet = validate_quantity(wet_mortar_m3, "wet_mortar_m3")
    dry = validate_quantity(dry_mortar_m3, "dry_mortar_m3")
    cement_part = to_decimal(cement_ratio, "cement_ratio")
    sand_part = to_decimal(sand_ratio, "sand_ratio")
    if cement_part <= 0 or sand_part <= 0:
        raise ValidationError(
            f"mortar ratios must be > 0; got {cement_part}:{sand_part}")
    total = cement_part + sand_part
    factor = to_decimal(dry_factor, "dry_factor")
    return MortarVolumes(
        wet_mortar_m3=wet,
        dry_mortar_m3=dry,
        cement_m3=dry * cement_part / total,
        sand_m3=dry * sand_part / total,
        cement_ratio=cement_part,
        sand_ratio=sand_part,
        dry_factor=factor,
        gross_wall_volume_m3=validate_quantity(
            gross_wall_volume_m3, "gross_wall_volume_m3"),
        net_unit_volume_m3=validate_quantity(
            net_unit_volume_m3, "net_unit_volume_m3"),
    )


def mortar_constituents(
    volumes: MortarVolumes,
    cement_density_kg_per_m3: Numeric,
    sand_density_kg_per_m3: Numeric,
) -> MortarConstituents:
    """Mortar constituents: cement mass, sand mass, and sand volume."""
    cement_density = validate_density(
        cement_density_kg_per_m3, "cement_density")
    sand_density = validate_density(sand_density_kg_per_m3, "sand_density")
    return MortarConstituents(
        cement_kg=volumes.cement_m3 * cement_density,
        sand_kg=volumes.sand_m3 * sand_density,
        sand_m3=volumes.sand_m3,
    )


def resolve_masonry_unit(
    unit_key: str, repository, overrides: MasonryUnitOverride = None,
) -> ResolvedMasonryUnit:
    """Resolve a masonry unit to usable numerics, fail-closed.

    NEEDS_VERIFICATION records (or null numerics) require complete explicit
    overrides; anything less raises UnverifiedMasterDataError. Verified or
    provisional records resolve from the table, with per-field overrides
    allowed and recorded. Field merging and the fail-closed precedence
    hierarchy delegate to the unified master-data resolver (Phase 3.1).
    """
    resolved = resolve_master(
        repository, "masonry_units", unit_key, overrides,
        fields=MASONRY_FIELDS, record_keys=RECORD_KEYS, noun="Masonry unit")
    values = resolved.values

    # Use-time validation of every numeric (regardless of source).
    validate_dimension(values["unit_length_mm"], "unit_length_mm")
    validate_dimension(values["unit_height_mm"], "unit_height_mm")
    validate_dimension(values["unit_thickness_mm"], "unit_thickness_mm")
    validate_quantity(values["bed_joint_mm"], "bed_joint_mm")
    validate_quantity(values["perp_joint_mm"], "perp_joint_mm")
    validate_percentage(values["wastage_pct"], "wastage_pct")
    if values["mortar_cement_ratio"] <= 0 or values["mortar_sand_ratio"] <= 0:
        raise ValidationError(
            f"mortar ratios must be > 0; got "
            f"{values['mortar_cement_ratio']}:{values['mortar_sand_ratio']}")
    if values["mortar_dry_factor"] < 1:
        raise ValidationError(
            f"mortar_dry_factor must be >= 1; got {values['mortar_dry_factor']}")
    validate_density(
        values["mortar_sand_density_kg_per_m3"], "mortar_sand_density")
    validate_density(values["cement_density_kg_per_m3"], "cement_density")
    if values["bag_mass_kg"] <= 0:
        raise ValidationError(
            f"bag_mass_kg must be > 0; got {values['bag_mass_kg']}")

    return ResolvedMasonryUnit(
        unit_key=unit_key,
        master_version=resolved.master_version,
        overrides_used=resolved.overrides_used,
        overridden_fields=resolved.overridden_fields,
        **values,
    )


def calculate_masonry_requirement(
    *,
    element: str = "",
    wall_length: Numeric,
    wall_height: Numeric,
    unit: str = "m",
    openings: Iterable[tuple] = (),
    unit_key: str,
    repository,
    overrides: MasonryUnitOverride = None,
) -> MasonryRequirement:
    """Full masonry pipeline for one wall (keyword-only inputs)."""
    wall = wall_areas(wall_length, wall_height, unit, openings)
    resolved = resolve_masonry_unit(unit_key, repository, overrides)
    takeoff = unit_takeoff(
        wall.net_m2, resolved.unit_length_mm, resolved.unit_height_mm,
        resolved.bed_joint_mm, resolved.perp_joint_mm, resolved.wastage_pct)
    gross = gross_wall_volume(wall.net_m2, resolved.unit_thickness_mm)
    net_vol = net_unit_volume(
        takeoff.units_order, resolved.unit_length_mm,
        resolved.unit_height_mm, resolved.unit_thickness_mm)
    wet = wet_mortar_volume(gross, net_vol)
    dry = dry_constituent_volume(wet, resolved.mortar_dry_factor)
    volumes = split_mortar(
        wet, dry, resolved.mortar_cement_ratio, resolved.mortar_sand_ratio,
        resolved.mortar_dry_factor, gross, net_vol)
    constituents = mortar_constituents(
        volumes, resolved.cement_density_kg_per_m3,
        resolved.mortar_sand_density_kg_per_m3)
    bags = cement_bags(
        constituents.cement_kg, resolved.bag_mass_kg, round_up=True)
    return MasonryRequirement(
        element=element,
        wall=wall,
        takeoff=takeoff,
        mortar_volumes=volumes,
        mortar_constituents=constituents,
        bags=bags,
        resolved_unit=resolved,
    )
