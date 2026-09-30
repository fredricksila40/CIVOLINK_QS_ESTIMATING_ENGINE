"""Formwork calculation engine (Phase 4).

Contact-area takeoff per element type, itemised deduction handling, and
material scheduling (boarding with reuse factor, props in linear metres,
release agent litres) from explicit rates.
"""

from .engine import (
    apply_deductions,
    beam_formwork_area,
    column_formwork_area,
    footing_formwork_area,
    release_agent_litres,
    schedule_boarding,
    schedule_props,
    slab_edge_area,
    slab_soffit_area,
    wall_formwork_area,
)
from .results import (
    BoardingSchedule,
    FormworkAreas,
    FormworkDeduction,
    PropSchedule,
    ReleaseAgent,
)

__all__ = [
    "apply_deductions", "beam_formwork_area", "column_formwork_area",
    "footing_formwork_area", "release_agent_litres", "schedule_boarding",
    "schedule_props", "slab_edge_area", "slab_soffit_area",
    "wall_formwork_area",
    "BoardingSchedule", "FormworkAreas", "FormworkDeduction",
    "PropSchedule", "ReleaseAgent",
]
