"""Concrete result contracts (Phase 2).

Frozen dataclasses carrying every pipeline stage. Calculated (exact)
and ordering (rounded) quantities are never merged.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Tuple

from ..contracts.models import Quantity


@dataclass(frozen=True)
class ResolvedMix:
    """A concrete class fully resolved to usable numerics.

    Values come from a VERIFIED/PROVISIONAL master-data record, from
    complete explicit overrides, or per-field from both. overrides_used
    and overridden_fields record exactly which path was taken.
    """
    class_key: str
    dry_factor: Decimal
    cement_ratio: Decimal
    sand_ratio: Decimal
    aggregate_ratio: Decimal
    wc_ratio: Decimal
    cement_density_kg_per_m3: Decimal
    sand_density_kg_per_m3: Decimal
    aggregate_density_kg_per_m3: Decimal
    water_density_kg_per_L: Decimal
    bag_mass_kg: Decimal
    master_version: str = ""
    overrides_used: bool = False
    overridden_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ConstituentVolumes:
    """Dry-volume split: parts sum exactly to dry_volume_m3."""
    dry_volume_m3: Decimal
    cement_m3: Decimal
    sand_m3: Decimal
    aggregate_m3: Decimal
    cement_ratio: Decimal
    sand_ratio: Decimal
    aggregate_ratio: Decimal
    dry_factor: Decimal


@dataclass(frozen=True)
class ConstituentMasses:
    """Constituent masses in kg (volume x density, unrounded)."""
    cement_kg: Decimal
    sand_kg: Decimal
    aggregate_kg: Decimal


@dataclass(frozen=True)
class CementBags:
    """Cement in bags. calculated_bags is exact; ordering_bags exists
    only when the caller explicitly requested ceiling."""
    calculated_bags: Decimal
    ordering_bags: Optional[int]
    bag_mass_kg: Decimal
    ceiling_applied: bool


@dataclass(frozen=True)
class WaterRequirement:
    """Mixing water in litres from the W/C ratio."""
    water_litres: Decimal
    wc_ratio: Decimal
    cement_mass_kg: Decimal
    water_density_kg_per_L: Decimal


@dataclass(frozen=True)
class ConcreteRequirement:
    """Full pipeline bundle for one element pour."""
    element: str
    wet_volume: Quantity
    constituents: ConstituentVolumes
    masses: ConstituentMasses
    bags: CementBags
    water: WaterRequirement
    resolved_mix: ResolvedMix
