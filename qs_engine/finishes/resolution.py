"""Finishes material resolution (Phase 6).

Geometry (takeoff.py) never implies materials. Each resolver EITHER
returns computed quantities from complete explicit overrides (or, where
a record domain exists, verified record values) OR returns an explicit
UnresolvedRequirement naming exactly what is missing. Typical values
are never substituted.

There is deliberately no mortar-mix master-data domain yet: plaster and
screed mortar resolve ONLY from complete MortarOverrides until a mixes
phase unifies them with masonry mortar. Paint and tile consumables
resolve from overrides, falling back to coverages records IF verified.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Optional, Union

from ..concrete.engine import cement_bags, dry_constituent_volume
from ..contracts.models import MaterialRequirement, Quantity
from ..core.assumptions import VerificationStatus
from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.units import KG, LITRE
from ..core.validation import (
    validate_density,
    validate_percentage,
    validate_quantity,
)
from ..core.wastage import apply_wastage
from ..master_data import CrossDomainReference
from ..master_data.schemas import COVERAGES, MATERIALS
from .results import (
    MortarMaterials,
    PaintMaterials,
    TileConsumables,
    UnresolvedRequirement,
)

Numeric = Union[Decimal, int, str]

MORTAR_FIELDS = (
    "cement_ratio",
    "sand_ratio",
    "dry_factor",
    "cement_density_kg_per_m3",
    "sand_density_kg_per_m3",
    "bag_mass_kg",
    "wastage_pct",
)


@dataclass(frozen=True)
class MortarOverride:
    """Complete-or-nothing mortar inputs shared by plaster and screed."""
    cement_ratio: Optional[Decimal] = None
    sand_ratio: Optional[Decimal] = None
    dry_factor: Optional[Decimal] = None
    cement_density_kg_per_m3: Optional[Decimal] = None
    sand_density_kg_per_m3: Optional[Decimal] = None
    bag_mass_kg: Optional[Decimal] = None
    wastage_pct: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in MORTAR_FIELDS:
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing(self) -> tuple:
        """Names of override fields still None."""
        return tuple(f for f in MORTAR_FIELDS if getattr(self, f) is None)

    def is_complete(self) -> bool:
        """True when every override field is supplied."""
        return not self.missing()


@dataclass(frozen=True)
class PaintOverride:
    """Explicit paint inputs. Both fields required for a full resolution;
    coverage may alternatively come from a verified coverages record."""
    coverage_m2_per_L: Optional[Decimal] = None
    wastage_pct: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in ("coverage_m2_per_L", "wastage_pct"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing(self) -> tuple:
        """Names of override fields still None."""
        return tuple(f for f in ("coverage_m2_per_L", "wastage_pct")
                     if getattr(self, f) is None)


@dataclass(frozen=True)
class TileConsumablesOverride:
    """Explicit adhesive/grout consumption rates (kg per m2) + wastage."""
    adhesive_kg_per_m2: Optional[Decimal] = None
    grout_kg_per_m2: Optional[Decimal] = None
    wastage_pct: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in ("adhesive_kg_per_m2", "grout_kg_per_m2",
                           "wastage_pct"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing(self) -> tuple:
        """Names of override fields still None."""
        return tuple(f for f in ("adhesive_kg_per_m2", "grout_kg_per_m2",
                                 "wastage_pct")
                     if getattr(self, f) is None)


def _validated_mortar_inputs(overrides: MortarOverride) -> dict:
    """Coerce + validate a complete mortar override set."""
    cement_part = to_decimal(overrides.cement_ratio, "cement_ratio")
    sand_part = to_decimal(overrides.sand_ratio, "sand_ratio")
    if cement_part <= 0 or sand_part <= 0:
        raise ValidationError(
            f"mortar ratios must be > 0; got {cement_part}:{sand_part}")
    dry_factor = to_decimal(overrides.dry_factor, "dry_factor")
    if dry_factor < 1:
        raise ValidationError(f"dry_factor must be >= 1; got {dry_factor}")
    bag = to_decimal(overrides.bag_mass_kg, "bag_mass_kg")
    if bag <= 0:
        raise ValidationError(f"bag_mass_kg must be > 0; got {bag}")
    return {
        "cement_ratio": cement_part,
        "sand_ratio": sand_part,
        "dry_factor": dry_factor,
        "cement_density": validate_density(
            overrides.cement_density_kg_per_m3, "cement_density"),
        "sand_density": validate_density(
            overrides.sand_density_kg_per_m3, "sand_density"),
        "bag_mass": bag,
        "wastage_pct": validate_percentage(
            overrides.wastage_pct, "wastage_pct"),
    }


def resolve_mortar_materials(
    *,
    mortar_volume_m3: Numeric,
    repository,
    cement_material_key: str = "portland_cement_42_5",
    sand_material_key: str = "river_sand",
    overrides: MortarOverride = None,
) -> Union[MortarMaterials, UnresolvedRequirement]:
    """Plaster/screed mortar constituents from a wet mortar volume.

    Material keys are validated to exist (unknown keys fail closed via
    the repository). Without a complete MortarOverride the requirement
    is returned explicitly unresolved — no verified mix domain exists.
    """
    CrossDomainReference.parse(
        cement_material_key, domain=MATERIALS).lookup(repository)
    CrossDomainReference.parse(
        sand_material_key, domain=MATERIALS).lookup(repository)
    volume = validate_quantity(mortar_volume_m3, "mortar_volume_m3")
    overrides = overrides or MortarOverride()
    if not overrides.is_complete():
        return UnresolvedRequirement(
            requested="mortar materials (cement, sand)",
            missing=overrides.missing(),
            context=("no verified mortar-mix domain; complete "
                     "MortarOverride required"),
        )
    mix = _validated_mortar_inputs(overrides)
    dry = dry_constituent_volume(volume, mix["dry_factor"])
    total_parts = mix["cement_ratio"] + mix["sand_ratio"]
    cement_vol = dry * mix["cement_ratio"] / total_parts
    sand_vol = dry * mix["sand_ratio"] / total_parts
    cement_base = cement_vol * mix["cement_density"]
    sand_base = sand_vol * mix["sand_density"]
    cement_waste = apply_wastage(cement_base, mix["wastage_pct"])
    sand_waste = apply_wastage(sand_base, mix["wastage_pct"])
    cement_kg = cement_waste.quantity_after_wastage
    sand_kg = sand_waste.quantity_after_wastage
    return MortarMaterials(
        cement=MaterialRequirement(
            material_key=cement_material_key,
            quantity=Quantity(cement_kg, KG)),
        sand=MaterialRequirement(
            material_key=sand_material_key,
            quantity=Quantity(sand_kg, KG)),
        sand_m3=sand_vol,
        cement_waste=cement_waste,
        sand_waste=sand_waste,
        bags=cement_bags(cement_kg, mix["bag_mass"], round_up=True),
        overrides_used=True,
    )


def _verified_coverage_rate(repository, coverage_key: str):
    """Coverage rate from a coverages record, or None.

    Returns None for NEEDS_VERIFICATION records or null rates; raises
    for unknown keys (fail closed). Verified/provisional non-null rates
    are returned as Decimal.
    """
    record: Mapping = CrossDomainReference.parse(
        coverage_key, domain=COVERAGES).lookup(repository)
    return _verified_rate_from(record, coverage_key)


def _verified_rate_from(record: Mapping, coverage_key: str):
    """Rate from an already-looked-up coverages record, or None."""
    if (record.get("verification_status")
            in (VerificationStatus.VERIFIED, VerificationStatus.PROVISIONAL)
            and record.get("coverage_per_unit") is not None):
        rate = to_decimal(record["coverage_per_unit"], "coverage_per_unit")
        if rate <= 0:
            raise ValidationError(
                f"Coverage {coverage_key!r} rate must be > 0; got {rate}")
        return rate
    return None


def resolve_paint_materials(
    *,
    area_m2: Numeric,
    coats: int,
    repository,
    coverage_key: str,
    paint_material_key: str,
    overrides: PaintOverride = None,
) -> Union[PaintMaterials, UnresolvedRequirement]:
    """Paint litres from coated area. Coverage from explicit override or
    verified coverages record; wastage from explicit override only.
    Anything less returns an explicit UnresolvedRequirement."""
    CrossDomainReference.parse(
        paint_material_key, domain=MATERIALS).lookup(repository)
    coverage_record: Mapping = CrossDomainReference.parse(
        coverage_key, domain=COVERAGES).lookup(repository)
    area = validate_quantity(area_m2, "area_m2")
    if isinstance(coats, bool) or not isinstance(coats, int) or coats < 1:
        raise ValidationError(
            f"coats must be an integer >= 1; got {coats!r}")
    overrides = overrides or PaintOverride()
    rate = overrides.coverage_m2_per_L
    if rate is not None:
        rate = to_decimal(rate, "coverage_m2_per_L")
        if rate <= 0:
            raise ValidationError(
                f"coverage_m2_per_L must be > 0; got {rate}")
    else:
        rate = _verified_rate_from(coverage_record, coverage_key)
    wastage = overrides.wastage_pct
    if wastage is not None:
        wastage = validate_percentage(wastage, "wastage_pct")
    missing = []
    if rate is None:
        missing.append(
            f"coverage_m2_per_L (override, or verified coverages "
            f"record {coverage_key!r})")
    if wastage is None:
        missing.append("wastage_pct (explicit override; no verified source)")
    if missing:
        return UnresolvedRequirement(
            requested=f"paint materials ({paint_material_key})",
            missing=tuple(missing),
            context="no verified paint coverage/wastage in master data",
        )
    theoretical = area * coats / rate
    wasted = apply_wastage(theoretical, wastage)
    litres = wasted.quantity_after_wastage
    return PaintMaterials(
        theoretical_litres=theoretical,
        paint=MaterialRequirement(
            material_key=paint_material_key,
            quantity=Quantity(litres, LITRE)),
        paint_waste=wasted,
        coats=coats,
        coverage_m2_per_L=rate,
        overrides_used=overrides.coverage_m2_per_L is not None,
    )


def resolve_tile_consumables(
    *,
    net_area_m2: Numeric,
    repository,
    adhesive_coverage_key: str,
    grout_coverage_key: str,
    adhesive_material_key: str = "tile_adhesive",
    grout_material_key: str = "tile_grout",
    overrides: TileConsumablesOverride = None,
) -> Union[TileConsumables, UnresolvedRequirement]:
    """Tile adhesive/grout in kg from net tiled area. Rates from explicit
    overrides or verified coverages records; wastage from override only."""
    CrossDomainReference.parse(
        adhesive_material_key, domain=MATERIALS).lookup(repository)
    CrossDomainReference.parse(
        grout_material_key, domain=MATERIALS).lookup(repository)
    adhesive_record: Mapping = CrossDomainReference.parse(
        adhesive_coverage_key, domain=COVERAGES).lookup(repository)
    grout_record: Mapping = CrossDomainReference.parse(
        grout_coverage_key, domain=COVERAGES).lookup(repository)
    area = validate_quantity(net_area_m2, "net_area_m2")
    overrides = overrides or TileConsumablesOverride()

    def _rate(override_value, record: Mapping, coverage_key: str, name: str):
        if override_value is not None:
            rate = to_decimal(override_value, name)
            if rate < 0:
                raise ValidationError(f"{name} must be >= 0; got {rate}")
            return rate, True
        return _verified_rate_from(record, coverage_key), False

    adhesive_rate, adhesive_over = _rate(
        overrides.adhesive_kg_per_m2, adhesive_record,
        adhesive_coverage_key, "adhesive_kg_per_m2")
    grout_rate, grout_over = _rate(
        overrides.grout_kg_per_m2, grout_record,
        grout_coverage_key, "grout_kg_per_m2")
    wastage = overrides.wastage_pct
    if wastage is not None:
        wastage = validate_percentage(wastage, "wastage_pct")
    missing = []
    if adhesive_rate is None:
        missing.append(
            f"adhesive_kg_per_m2 (override, or verified coverages record "
            f"{adhesive_coverage_key!r})")
    if grout_rate is None:
        missing.append(
            f"grout_kg_per_m2 (override, or verified coverages record "
            f"{grout_coverage_key!r})")
    if wastage is None:
        missing.append("wastage_pct (explicit override; no verified source)")
    if missing:
        return UnresolvedRequirement(
            requested="tile consumables (adhesive, grout)",
            missing=tuple(missing),
            context="no verified adhesive/grout consumption in master data",
        )
    adhesive_waste = apply_wastage(area * adhesive_rate, wastage)
    grout_waste = apply_wastage(area * grout_rate, wastage)
    return TileConsumables(
        adhesive=MaterialRequirement(
            material_key=adhesive_material_key,
            quantity=Quantity(adhesive_waste.quantity_after_wastage, KG)),
        grout=MaterialRequirement(
            material_key=grout_material_key,
            quantity=Quantity(grout_waste.quantity_after_wastage, KG)),
        adhesive_waste=adhesive_waste,
        grout_waste=grout_waste,
        overrides_used=bool(adhesive_over or grout_over),
    )
