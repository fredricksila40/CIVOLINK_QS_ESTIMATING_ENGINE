"""UI view-models (Phase 13): render-ready frozen dataclasses.

Every numeric is a pre-formatted string produced from engine Decimals —
views never compute. Controllers return these on success or ErrorView on
any engine/validation failure (fail-closed feedback, never a crash).
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class KV:
    """One labelled value row for generic panels."""
    label: str
    value: str


@dataclass(frozen=True)
class ErrorView:
    """Fail-closed feedback: what failed, on which field, and why."""
    message: str
    field: str = ""
    kind: str = "validation"


@dataclass(frozen=True)
class ProjectSetupView:
    """Selected measurement standard (unknown names allowed, flagged)."""
    standard: str
    edition: str
    known: bool


@dataclass(frozen=True)
class ConcreteView:
    """Concrete requirement rendered as strings."""
    element: str
    wet_m3: str
    dry_m3: str
    cement_m3: str
    sand_m3: str
    aggregate_m3: str
    cement_kg: str
    sand_kg: str
    aggregate_kg: str
    bags_exact: str
    bags_order: str
    water_litres: str
    class_key: str
    master_version: str
    overrides_used: bool


@dataclass(frozen=True)
class MasonryView:
    """Masonry requirement rendered as strings."""
    element: str
    gross_m2: str
    net_m2: str
    units_exact: str
    units_order: str
    wet_mortar_m3: str
    dry_mortar_m3: str
    cement_kg: str
    sand_kg: str
    bags_order: str
    unit_key: str
    master_version: str
    overrides_used: bool


@dataclass(frozen=True)
class RebarView:
    """Rebar schedule totals rendered as strings."""
    lines: Tuple[KV, ...]
    total_length_m: str
    total_mass_kg: str
    total_mass_tonnes: str
    wastage_pct: str
    after_wastage_kg: str
    tying_wire_kg: str
    overrides_used: Tuple[str, ...] = ()
    master_version: Optional[str] = None


@dataclass(frozen=True)
class FormworkView:
    """Formwork contact area and material schedules as strings.

    Deliberately carries no provenance fields: every input is an
    explicit estimator entry and no master-data lookup happens, so the
    panel's provenance bar stays blank instead of implying a source.
    Scheduling strings stay empty ("") when their rate was not given.
    """
    element_type: str
    element: str
    gross_m2: str
    total_deducted_m2: str
    net_m2: str
    deductions: Tuple[KV, ...] = ()
    sheet_area_m2: str = ""
    reuses: str = ""
    sheets_exact: str = ""
    sheets_to_buy: str = ""
    linear_m_per_m2: str = ""
    linear_m: str = ""
    litres_per_m2: str = ""
    litres: str = ""


@dataclass(frozen=True)
class EarthworksView:
    """Earthworks balance rendered as strings."""
    element: str
    excavation_bank_m3: str
    loose_dug_m3: str
    backfill_bank_m3: str
    backfill_loose_m3: str
    dispose_loose_m3: str
    bank_mass_kg: str
    soil_key: str
    overrides_used: Tuple[str, ...] = ()
    master_version: Optional[str] = None


@dataclass(frozen=True)
class FinishesView:
    """Take-off lines plus explicitly unresolved entries, per trade."""
    kind: str
    element: str
    lines: Tuple[KV, ...] = ()
    unresolved: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LabourView:
    """Labour requirement rendered as strings."""
    element: str
    duration_gang_days: str
    skilled_person_days: str
    unskilled_person_days: str
    skilled_person_hours: str
    unskilled_person_hours: str
    gang_cost_per_day: str
    total_cost: str
    trade_key: str
    overrides_used: Tuple[str, ...] = ()
    master_version: Optional[str] = None


@dataclass(frozen=True)
class PlantView:
    """Plant duty rendered as strings."""
    element: str
    duration_value: str
    duration_basis: str
    hire_cost: str
    operating_cost: str
    total_cost: str
    equipment_key: str
    overrides_used: Tuple[str, ...] = ()
    master_version: Optional[str] = None


@dataclass(frozen=True)
class LogisticsView:
    """Haulage plan rendered as strings (pricing is a rate-builder step)."""
    element: str
    load_m3: str
    load_tonnes: str
    limiting: str
    cycle_minutes: str
    trips_exact: str
    trips_ordered: str
    trucks_required: str
    daily_capacity: str
    overrides_used: Tuple[str, ...] = ()
    master_version: Optional[str] = None


@dataclass(frozen=True)
class RateBuildupView:
    """Composite rate with component and markup tables as strings."""
    element: str
    work_unit: str
    components: Tuple[KV, ...]
    direct_cost: str
    markups: Tuple[KV, ...]
    markup_policy: str
    net_rate: str
    gross_rate: str


@dataclass(frozen=True)
class BoqItemView:
    """One compiled line rendered as strings."""
    item_no: str
    description: str
    quantity: str
    unit: str
    rate: str
    amount: str
    status: str


@dataclass(frozen=True)
class BoqSectionView:
    """One compiled section rendered as strings."""
    code: str
    title: str
    items: Tuple[BoqItemView, ...]
    total: str
    has_unresolved: bool


@dataclass(frozen=True)
class BoqView:
    """Compiled BOQ rendered as strings with unresolved tracking."""
    project_ref: str
    boq_ref: str
    sections: Tuple[BoqSectionView, ...]
    grand_total: str
    resolved_subtotal: str
    has_unresolved: bool
    unresolved_items: Tuple[str, ...]


@dataclass(frozen=True)
class ExportView:
    """Successful export trigger result."""
    path: str
    detail: str = ""
