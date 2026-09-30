"""Masonry result contracts (Phase 3).

Frozen dataclasses carrying every pipeline stage. Exact (calculated),
waste-inclusive, and ordering (ceiled) figures are never merged.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from ..concrete.results import CementBags
from ..contracts.models import Quantity
from ..core.wastage import WastageResult


@dataclass(frozen=True)
class ResolvedMasonryUnit:
    """A masonry unit fully resolved to usable numerics.

    Values come from a VERIFIED/PROVISIONAL master-data record, from
    complete explicit overrides, or per-field from both. overrides_used
    and overridden_fields record exactly which path was taken.
    """
    unit_key: str
    unit_length_mm: Decimal
    unit_height_mm: Decimal
    unit_thickness_mm: Decimal
    bed_joint_mm: Decimal
    perp_joint_mm: Decimal
    wastage_pct: Decimal
    mortar_cement_ratio: Decimal
    mortar_sand_ratio: Decimal
    mortar_dry_factor: Decimal
    mortar_sand_density_kg_per_m3: Decimal
    cement_density_kg_per_m3: Decimal
    bag_mass_kg: Decimal
    master_version: str = ""
    overrides_used: bool = False
    overridden_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WallAreas:
    """Wall areas in m2: gross, deducted openings, net."""
    gross_m2: Decimal
    openings_m2: Decimal
    net_m2: Decimal


@dataclass(frozen=True)
class MasonryTakeoff:
    """Unit count at three visible stages: exact, with waste, ordered."""
    units_exact: Decimal
    units_with_waste: Decimal
    units_order: int
    wastage: WastageResult
    unit_face_area_m2: Decimal
    net_area_m2: Decimal


@dataclass(frozen=True)
class MortarVolumes:
    """Mortar split: wet, dry (x K_dry,mortar), cement/sand parts."""
    wet_mortar_m3: Decimal
    dry_mortar_m3: Decimal
    cement_m3: Decimal
    sand_m3: Decimal
    cement_ratio: Decimal
    sand_ratio: Decimal
    dry_factor: Decimal
    gross_wall_volume_m3: Decimal
    net_unit_volume_m3: Decimal


@dataclass(frozen=True)
class MortarConstituents:
    """Mortar constituents: cement mass, sand mass and sand volume."""
    cement_kg: Decimal
    sand_kg: Decimal
    sand_m3: Decimal


@dataclass(frozen=True)
class MasonryRequirement:
    """Full pipeline bundle for one wall."""
    element: str
    wall: WallAreas
    takeoff: MasonryTakeoff
    mortar_volumes: MortarVolumes
    mortar_constituents: MortarConstituents
    bags: CementBags
    resolved_unit: ResolvedMasonryUnit
