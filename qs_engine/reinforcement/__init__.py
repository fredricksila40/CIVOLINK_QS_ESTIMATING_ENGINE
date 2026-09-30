"""Reinforcement calculation engine (Phase 4).

Bar lookup by designation, unit mass from verified tables or the
nominal-mass formula with explicitly supplied steel density, bar-line
expansion (laps/hooks), schedule totals in kg and tonnes, explicit
wastage, and optional tying-wire estimation.
"""

from .engine import (
    PI,
    MASS_SOURCE_FORMULA,
    MASS_SOURCE_TABLE,
    BarLineInput,
    RebarBarOverride,
    calculate_bar_line,
    calculate_rebar_schedule,
    nominal_bar_mass,
    resolve_rebar_bar,
)
from .results import BarLineResult, RebarSchedule, ResolvedRebarBar

__all__ = [
    "PI", "MASS_SOURCE_FORMULA", "MASS_SOURCE_TABLE",
    "BarLineInput", "RebarBarOverride",
    "calculate_bar_line", "calculate_rebar_schedule",
    "nominal_bar_mass", "resolve_rebar_bar",
    "BarLineResult", "RebarSchedule", "ResolvedRebarBar",
]
