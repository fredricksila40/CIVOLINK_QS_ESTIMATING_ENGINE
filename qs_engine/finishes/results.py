"""Finishes result contracts (Phase 6).

Frozen dataclasses. Geometry takeoffs embed a contracts.TakeoffResult for
the primary quantity plus auditable stage detail. Material resolution
returns either computed bundles or an explicit UnresolvedRequirement —
never a silent typical value.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from ..concrete.results import CementBags
from ..contracts.models import MaterialRequirement, Quantity, TakeoffResult
from ..core.wastage import WastageResult


@dataclass(frozen=True)
class Opening:
    """One deducted opening type: dimensions plus identical count.

    Dimensions coerce to Decimal on construction; area_m2 converts via
    the core unit service. count must be an integer >= 1.
    """
    width: Decimal
    height: Decimal
    count: int = 1
    unit: str = "m"

    def __post_init__(self):
        from ..core.decimal_policy import to_decimal
        from ..core.errors import ValidationError
        from ..core.units import convert
        from ..core.validation import validate_dimension
        object.__setattr__(self, "width",
                           convert(validate_dimension(self.width, "width"),
                                   self.unit, "m"))
        object.__setattr__(self, "height",
                           convert(validate_dimension(self.height, "height"),
                                   self.unit, "m"))
        object.__setattr__(self, "unit", "m")
        if (isinstance(self.count, bool)
                or not isinstance(self.count, int) or self.count < 1):
            raise ValidationError(
                f"Opening count must be an integer >= 1; got {self.count!r}")

    @property
    def area_m2(self) -> Decimal:
        """Total deducted area for this opening type."""
        return self.width * self.height * self.count


@dataclass(frozen=True)
class PlasterTakeoff:
    """Plaster geometry: areas per face treatment plus volume."""
    takeoff: TakeoffResult  # net area, m2
    gross_m2: Decimal
    openings_m2: Decimal
    net_m2: Decimal
    faces: int
    thickness_m: Decimal
    volume_m3: Decimal


@dataclass(frozen=True)
class ScreedTakeoff:
    """Screed geometry: floor area plus volume."""
    takeoff: TakeoffResult  # volume, m3
    area_m2: Decimal
    thickness_m: Decimal
    volume_m3: Decimal


@dataclass(frozen=True)
class TileTakeoff:
    """Tile count geometry. wastage/order exist only when an explicit
    wastage_pct was supplied; otherwise unresolved names the gap."""
    takeoff: TakeoffResult  # theoretical count, piece
    net_area_m2: Decimal
    tile_area_m2: Decimal
    theoretical_count: Decimal
    wastage: Optional[WastageResult]
    order_quantity: Optional[int]
    unresolved: Tuple[str, ...]


@dataclass(frozen=True)
class PaintTakeoff:
    """Painting geometry: area per coat plus total coated area."""
    takeoff: TakeoffResult  # net area per coat, m2
    gross_m2: Decimal
    openings_m2: Decimal
    net_m2: Decimal
    faces: int
    coats: int
    total_coated_m2: Decimal


@dataclass(frozen=True)
class UnresolvedRequirement:
    """An explicitly unresolved material requirement.

    requested names WHAT is wanted (e.g. "plaster mortar materials");
    missing lists the exact absent inputs (master keys, fields, or
    override parameters); context states WHY (e.g. no verified domain).
    """
    requested: str
    missing: Tuple[str, ...]
    context: str = ""


@dataclass(frozen=True)
class MortarMaterials:
    """Resolved mortar constituents, post-waste, with audit trail."""
    cement: MaterialRequirement  # kg, post-waste
    sand: MaterialRequirement  # kg, post-waste
    sand_m3: Decimal
    cement_waste: WastageResult
    sand_waste: WastageResult
    bags: CementBags
    overrides_used: bool = True


@dataclass(frozen=True)
class PaintMaterials:
    """Resolved paint quantity, post-waste, with audit trail."""
    theoretical_litres: Decimal
    paint: MaterialRequirement  # litres, post-waste
    paint_waste: WastageResult
    coats: int
    coverage_m2_per_L: Decimal
    overrides_used: bool = True


@dataclass(frozen=True)
class TileConsumables:
    """Resolved tile adhesive/grout quantities, post-waste."""
    adhesive: MaterialRequirement  # kg, post-waste
    grout: MaterialRequirement  # kg, post-waste
    adhesive_waste: WastageResult
    grout_waste: WastageResult
    overrides_used: bool = True
