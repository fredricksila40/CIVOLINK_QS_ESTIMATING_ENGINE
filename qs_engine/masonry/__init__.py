"""Masonry calculation engine (Phase 3).

Take-off with joint-inclusive faces, conservative wet-mortar identity
(gross wall volume minus waste-inclusive ceiled net unit volume), dry
expansion, cement:sand split, bagging, and sand mass/volume. Fail-closed
on unverified master data unless complete explicit overrides supplied.
"""

from .engine import (
    MASONRY_FIELDS,
    RECORD_KEYS,
    MasonryUnitOverride,
    calculate_masonry_requirement,
    gross_wall_volume,
    net_unit_volume,
    resolve_masonry_unit,
    split_mortar,
    mortar_constituents,
    unit_takeoff,
    wall_areas,
    wet_mortar_volume,
)
from .results import (
    MasonryRequirement,
    MasonryTakeoff,
    MortarConstituents,
    MortarVolumes,
    ResolvedMasonryUnit,
    WallAreas,
)

__all__ = [
    "MASONRY_FIELDS", "RECORD_KEYS", "MasonryUnitOverride",
    "calculate_masonry_requirement", "gross_wall_volume", "net_unit_volume",
    "resolve_masonry_unit", "split_mortar", "mortar_constituents",
    "unit_takeoff", "wall_areas", "wet_mortar_volume",
    "MasonryRequirement", "MasonryTakeoff", "MortarConstituents",
    "MortarVolumes", "ResolvedMasonryUnit", "WallAreas",
]
