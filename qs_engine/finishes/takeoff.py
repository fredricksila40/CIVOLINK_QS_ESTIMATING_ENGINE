"""Finishes geometry take-off (Phase 6): plaster, screed, tiles, painting.

Pure geometry — no master data, no rates, no wastage defaults. Thickness,
joints, tile sizes, and coats are REQUIRED explicit inputs (there are no
verified defaults to fall back on). Fractional counts stay exact here;
procurement rounding happens only in resolution or via explicit ceiling.
"""

from decimal import Decimal
from typing import Iterable, Union

from ..contracts.models import Quantity, TakeoffResult
from ..core.errors import ValidationError
from ..core.rounding import apply_ceiling
from ..core.units import M2, M3, MM2, PIECE, convert
from ..core.validation import (
    validate_dimension,
    validate_percentage,
    validate_quantity,
)
from ..core.wastage import apply_wastage
from .results import (
    Opening,
    PaintTakeoff,
    PlasterTakeoff,
    ScreedTakeoff,
    TileTakeoff,
)

Numeric = Union[Decimal, int, str]


def normalize_openings(openings: Iterable, unit: str = "m") -> Decimal:
    """Total deducted area in m2 from Opening objects or tuples.

    Accepts Opening instances (which carry their own unit) and
    (width, height) or (width, height, count) tuples in the wall unit.
    An empty iterable means no deductions declared — never an assumption.
    """
    total = Decimal("0")
    for index, item in enumerate(openings):
        if isinstance(item, Opening):
            total += item.area_m2
            continue
        try:
            parts = tuple(item)
        except TypeError:
            raise ValidationError(
                f"Opening #{index} must be an Opening or a "
                f"(width, height[, count]) tuple; got {item!r}") from None
        if len(parts) == 2:
            width, height, count = parts[0], parts[1], 1
        elif len(parts) == 3:
            width, height, count = parts
        else:
            raise ValidationError(
                f"Opening #{index} must be a (width, height[, count]) "
                f"tuple; got {item!r}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValidationError(
                f"Opening #{index} count must be an integer >= 1; "
                f"got {count!r}")
        total += (convert(validate_dimension(width, f"opening[{index}].width"),
                          unit, "m")
                  * convert(validate_dimension(height, f"opening[{index}].height"),
                            unit, "m") * count)
    return total


def _faces_count(faces: int, name: str = "faces") -> int:
    if faces not in (1, 2):
        raise ValidationError(f"{name} must be 1 or 2; got {faces!r}")
    return faces


def plaster_takeoff(
    *,
    length: Numeric,
    height: Numeric,
    unit: str = "m",
    faces: int = 2,
    openings: Iterable = (),
    thickness: Numeric,
    thickness_unit: str = "mm",
    element: str = "",
) -> PlasterTakeoff:
    """Plaster geometry: per-face areas, deductions, net area, volume.

    thickness is REQUIRED (no verified default exists). Volume = net x
    thickness; material resolution is a separate, later step.
    """
    faces = _faces_count(faces)
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    height_m = convert(validate_dimension(height, "height"), unit, "m")
    gross = length_m * height_m * faces
    deducted = normalize_openings(openings, unit) * faces
    net = gross - deducted
    if net < 0:
        raise ValidationError(
            f"Openings ({deducted} m2) exceed gross plaster area ({gross} m2)")
    thickness_m = convert(
        validate_dimension(thickness, "thickness"), thickness_unit, "m")
    volume = net * thickness_m
    return PlasterTakeoff(
        takeoff=TakeoffResult(
            element=element or "plaster",
            quantity=Quantity(net, M2),
            method=f"faces={faces}, openings itemised",
            assumptions=("thickness explicit; no verified defaults",)),
        gross_m2=gross,
        openings_m2=deducted,
        net_m2=net,
        faces=faces,
        thickness_m=thickness_m,
        volume_m3=volume,
    )


def screed_takeoff(
    *,
    length: Numeric,
    width: Numeric,
    unit: str = "m",
    thickness: Numeric,
    thickness_unit: str = "mm",
    element: str = "",
) -> ScreedTakeoff:
    """Screed geometry: floor area and volume. Thickness REQUIRED."""
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    area = length_m * width_m
    thickness_m = convert(
        validate_dimension(thickness, "thickness"), thickness_unit, "m")
    volume = area * thickness_m
    return ScreedTakeoff(
        takeoff=TakeoffResult(
            element=element or "screed",
            quantity=Quantity(volume, M3),
            method="area x thickness",
            assumptions=("thickness explicit; no verified defaults",)),
        area_m2=area,
        thickness_m=thickness_m,
        volume_m3=volume,
    )


def tile_takeoff(
    *,
    length: Numeric,
    width: Numeric,
    unit: str = "m",
    openings: Iterable = (),
    tile_length_mm: Numeric,
    tile_width_mm: Numeric,
    joint_mm: Numeric,
    wastage_pct: Numeric = None,
    element: str = "",
) -> TileTakeoff:
    """Tile count geometry. Tile size and joint are REQUIRED; wastage is
    OPTIONAL — when absent the order quantity stays explicitly unresolved
    (no typical percentage is ever applied silently).
    """
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    width_m = convert(validate_dimension(width, "width"), unit, "m")
    gross = length_m * width_m
    deducted = normalize_openings(openings, unit)
    net = gross - deducted
    if net < 0:
        raise ValidationError(
            f"Openings ({deducted} m2) exceed gross tiled area ({gross} m2)")
    tile_length = validate_dimension(tile_length_mm, "tile_length_mm")
    tile_width = validate_dimension(tile_width_mm, "tile_width_mm")
    joint = validate_quantity(joint_mm, "joint_mm")
    tile_m2 = convert(
        (tile_length + joint) * (tile_width + joint), MM2, M2)
    theoretical = net / tile_m2
    if wastage_pct is None:
        return TileTakeoff(
            takeoff=TakeoffResult(
                element=element or "tiles",
                quantity=Quantity(theoretical, PIECE),
                method="net area / joint-inclusive tile area",
                assumptions=("wastage unresolved",)),
            net_area_m2=net,
            tile_area_m2=tile_m2,
            theoretical_count=theoretical,
            wastage=None,
            order_quantity=None,
            unresolved=("wastage_pct: no verified tile wastage; "
                        "theoretical count only",),
        )
    wasted = apply_wastage(
        theoretical, validate_percentage(wastage_pct, "wastage_pct"))
    ordered = apply_ceiling(wasted.quantity_after_wastage, "piece")
    return TileTakeoff(
        takeoff=TakeoffResult(
            element=element or "tiles",
            quantity=Quantity(theoretical, PIECE),
            method="net area / joint-inclusive tile area",
            assumptions=(f"wastage {wasted.wastage_pct}% explicit",)),
        net_area_m2=net,
        tile_area_m2=tile_m2,
        theoretical_count=theoretical,
        wastage=wasted,
        order_quantity=ordered.ordering_quantity,
        unresolved=(),
    )


def paint_takeoff(
    *,
    length: Numeric,
    height: Numeric,
    unit: str = "m",
    faces: int = 1,
    openings: Iterable = (),
    coats: int,
    element: str = "",
) -> PaintTakeoff:
    """Painting geometry: net area per coat and total coated area.

    coats is REQUIRED (no verified coat default exists). Coverage and
    ordering belong to material resolution, not to geometry.
    """
    faces = _faces_count(faces)
    if isinstance(coats, bool) or not isinstance(coats, int) or coats < 1:
        raise ValidationError(
            f"coats must be an integer >= 1; got {coats!r}")
    length_m = convert(validate_dimension(length, "length"), unit, "m")
    height_m = convert(validate_dimension(height, "height"), unit, "m")
    gross = length_m * height_m * faces
    deducted = normalize_openings(openings, unit) * faces
    net = gross - deducted
    if net < 0:
        raise ValidationError(
            f"Openings ({deducted} m2) exceed gross paint area ({gross} m2)")
    return PaintTakeoff(
        takeoff=TakeoffResult(
            element=element or "paint",
            quantity=Quantity(net, M2),
            method=f"faces={faces}, coats={coats}, openings itemised",
            assumptions=("coverage unresolved at take-off stage",)),
        gross_m2=gross,
        openings_m2=deducted,
        net_m2=net,
        faces=faces,
        coats=coats,
        total_coated_m2=net * coats,
    )
