"""Formwork result contracts (Phase 4).

Frozen dataclasses. Contact areas stay exact; deductions itemised;
material schedules expose exact and ordering figures separately.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple


@dataclass(frozen=True)
class FormworkDeduction:
    """One deducted overlap/intersection with its label."""
    label: str
    area_m2: Decimal


@dataclass(frozen=True)
class FormworkAreas:
    """Contact area after itemised deductions (never negative)."""
    gross_m2: Decimal
    deductions: Tuple[FormworkDeduction, ...]
    total_deducted_m2: Decimal
    net_m2: Decimal


@dataclass(frozen=True)
class BoardingSchedule:
    """Plywood/board ordering with an explicit reuse factor."""
    contact_area_m2: Decimal
    sheet_area_m2: Decimal
    reuses: int
    sheets_exact: Decimal
    sheets_to_buy: int


@dataclass(frozen=True)
class PropSchedule:
    """Props/scaffolding in linear metres (continuous stock, unrounded)."""
    contact_area_m2: Decimal
    linear_m_per_m2: Decimal
    linear_m: Decimal


@dataclass(frozen=True)
class ReleaseAgent:
    """Release agent litres from an explicit litres-per-m2 rate."""
    contact_area_m2: Decimal
    litres_per_m2: Decimal
    litres: Decimal
