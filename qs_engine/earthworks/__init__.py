"""Earthworks, excavation, hardcore, and membrane engine (Phase 5).

Clearance/strip, bank excavation with working-space allowance, swell and
compaction factors, cart-away/backfill balance with displaced substructure,
hardcore/blinding beds, and lapped membrane areas. Fail-closed on
unverified soil data unless complete explicit overrides are supplied.
"""

from .engine import (
    RECORD_KEYS,
    SOIL_FIELDS,
    SoilOverride,
    backfill_loose_requirement,
    backfill_volume,
    blinding_volume,
    calculate_foundation_earthworks,
    cartaway_volume,
    clearance_area,
    compacted_yield,
    excavation_volume,
    hardcore_bed_volume,
    layer_volume,
    loose_for_compacted_target,
    membrane_area_with_laps,
    resolve_soil,
    swell_volume,
    topsoil_strip_volume,
)
from .results import EarthworksBalance, ResolvedSoil

__all__ = [
    "RECORD_KEYS", "SOIL_FIELDS", "SoilOverride",
    "backfill_loose_requirement", "backfill_volume", "blinding_volume",
    "calculate_foundation_earthworks", "cartaway_volume", "clearance_area",
    "compacted_yield", "excavation_volume", "hardcore_bed_volume",
    "layer_volume", "loose_for_compacted_target", "membrane_area_with_laps",
    "resolve_soil", "swell_volume", "topsoil_strip_volume",
    "EarthworksBalance", "ResolvedSoil",
]
