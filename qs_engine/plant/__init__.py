"""Plant & equipment calculation engine (Phase 7).

Duty durations from output rates, hire costs with explicit hour/day
conversion, and optional operating allowances. Fail-closed on unverified
master data unless complete overrides are supplied.
"""

from .engine import (
    BASIS_DAY,
    BASIS_HOUR,
    PLANT_FIELDS,
    RECORD_KEYS,
    PlantOverride,
    calculate_plant_requirement,
    plant_duration,
    resolve_plant_equipment,
)
from .results import PlantRequirement, ResolvedPlant

__all__ = [
    "BASIS_DAY", "BASIS_HOUR", "PLANT_FIELDS", "RECORD_KEYS",
    "PlantOverride", "calculate_plant_requirement", "plant_duration",
    "resolve_plant_equipment",
    "PlantRequirement", "ResolvedPlant",
]
