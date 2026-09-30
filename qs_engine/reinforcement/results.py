"""Reinforcement result contracts (Phase 4).

Frozen dataclasses. Lengths stay exact until reported; mass in kg and
tonnes carried side by side; wastage and tying wire recorded explicitly.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from ..core.wastage import WastageResult


@dataclass(frozen=True)
class ResolvedRebarBar:
    """One bar designation resolved to a usable unit mass.

    mass_source records which resolution path was taken:
    "override"  — estimator-specified unit mass (explicit input);
    "table"     — verified/provisional master-table value;
    "formula"   — nominal-mass formula with an explicitly supplied
                  steel density — never a baked-in 7850/162.2.
    """
    bar_key: str
    diameter_mm: Decimal
    mass_kg_per_m: Decimal
    mass_source: str
    wastage_pct: Optional[Decimal]
    master_version: str = ""
    overrides_used: bool = False
    overridden_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class BarLineResult:
    """One schedule line: per-bar build-up, totals, mass."""
    bar_key: str
    count: int
    length_per_bar_m: Decimal
    laps_per_bar: int
    lap_length_m: Decimal
    hook_extra_per_bar_m: Decimal
    total_length_m: Decimal
    total_mass_kg: Decimal
    mass_kg_per_m: Decimal


@dataclass(frozen=True)
class RebarSchedule:
    """Whole-schedule totals with explicit wastage and optional wire."""
    lines: Tuple[BarLineResult, ...]
    total_length_m: Decimal
    total_mass_kg: Decimal
    total_mass_tonnes: Decimal
    wastage: WastageResult
    tying_wire_kg: Optional[Decimal]
    tying_wire_kg_per_tonne: Optional[Decimal]
