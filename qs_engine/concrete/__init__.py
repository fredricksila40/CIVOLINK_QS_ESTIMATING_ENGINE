"""Concrete calculation engine (Phase 2).

Ratio-based pipeline: wet volume -> dry volume -> constituent split ->
masses -> bags -> water. Fail-closed on unverified master data unless
complete explicit overrides are supplied.
"""

from .engine import (
    MIX_FIELDS,
    RECORD_KEYS,
    ConcreteMixOverride,
    calculate_concrete_requirement,
    cement_bags,
    constituent_masses,
    dry_constituent_volume,
    resolve_mix,
    split_constituents,
    water_requirement,
    wet_concrete_volume,
)
from .results import (
    CementBags,
    ConcreteRequirement,
    ConstituentMasses,
    ConstituentVolumes,
    ResolvedMix,
    WaterRequirement,
)

__all__ = [
    "MIX_FIELDS", "RECORD_KEYS", "ConcreteMixOverride",
    "calculate_concrete_requirement", "cement_bags", "constituent_masses",
    "dry_constituent_volume", "resolve_mix", "split_constituents",
    "water_requirement", "wet_concrete_volume",
    "CementBags", "ConcreteRequirement", "ConstituentMasses",
    "ConstituentVolumes", "ResolvedMix", "WaterRequirement",
]
