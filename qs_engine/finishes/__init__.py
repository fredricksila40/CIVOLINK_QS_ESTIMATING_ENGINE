"""Finishes calculation engine (Phase 6): plaster, screed, tiles, painting.

takeoff.py is pure geometry (no master data, no rates). resolution.py
maps geometry to materials and returns either computed bundles or an
explicit UnresolvedRequirement — typical values are never substituted.
"""

from .resolution import (
    MortarOverride,
    PaintOverride,
    TileConsumablesOverride,
    resolve_mortar_materials,
    resolve_paint_materials,
    resolve_tile_consumables,
)
from .results import (
    MortarMaterials,
    Opening,
    PaintMaterials,
    PaintTakeoff,
    PlasterTakeoff,
    ScreedTakeoff,
    TileConsumables,
    TileTakeoff,
    UnresolvedRequirement,
)
from .takeoff import (
    normalize_openings,
    paint_takeoff,
    plaster_takeoff,
    screed_takeoff,
    tile_takeoff,
)

__all__ = [
    "MortarOverride", "PaintOverride", "TileConsumablesOverride",
    "resolve_mortar_materials", "resolve_paint_materials",
    "resolve_tile_consumables",
    "MortarMaterials", "Opening", "PaintMaterials", "PaintTakeoff",
    "PlasterTakeoff", "ScreedTakeoff", "TileConsumables", "TileTakeoff",
    "UnresolvedRequirement",
    "normalize_openings", "paint_takeoff", "plaster_takeoff",
    "screed_takeoff", "tile_takeoff",
]
