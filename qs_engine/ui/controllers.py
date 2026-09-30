"""MVP controllers (Phase 13): string in, view-model out, engine decides.

Contract: controllers NEVER raise QSEngineError (including
ValidationError). Every engine/validation failure becomes an ErrorView
carrying the message — views display it without crashing. Only genuine
programming errors (wrong Python types, missing arguments) raise.

Each controller collects string inputs (as widgets provide), converts
via parse_decimal/parse_int, delegates ALL arithmetic to qs_engine, and
returns a render-ready view-model. No float arithmetic exists in this
module; no widget toolkit is imported here (see views.py).
"""

from decimal import Decimal
from typing import List, Mapping, Optional, Tuple, Union

from qs_engine.boq.measurement import KNOWN_STANDARDS
from qs_engine.boq.models import Boq
from qs_engine.core.decimal_policy import to_decimal
from qs_engine.core.errors import QSEngineError, ValidationError
from .viewmodels import (
    BoqItemView,
    BoqSectionView,
    BoqView,
    ConcreteView,
    EarthworksView,
    ErrorView,
    ExportView,
    FinishesView,
    FormworkView,
    KV,
    LabourView,
    LogisticsView,
    MasonryView,
    PlantView,
    ProjectSetupView,
    RateBuildupView,
    RebarView,
)

__all__ = [
    "parse_decimal", "parse_int", "parse_optional_decimal",
    "parse_deductions", "FORMWORK_ELEMENT_TYPES",
    "project_setup_controller",
    "concrete_controller", "masonry_controller", "rebar_controller",
    "formwork_controller", "FormworkController",
    "earthworks_controller", "finishes_controller",
    "labour_controller", "plant_controller", "logistics_plan_controller",
    "rate_builder_controller", "boq_view_controller",
    "excel_export_controller", "tender_export_controller",
    "tender_reconciliation_controller", "document_payload_controller",
    "branded_document_controller", "ipc_valuation_controller",
    "boq_pdf_controller", "ipc_pdf_controller",
]


def _s(value: Optional[Decimal]) -> str:
    """Exact Decimal rendering; None becomes an em-dash placeholder."""
    return str(value) if value is not None else "—"


def parse_decimal(text, field: str) -> Decimal:
    """Strict string -> Decimal for widget input.

    Rejects empty input, floats, bools, and comma-grouped strings
    (locale-ambiguous) with a field-attributed ValidationError.
    """
    if isinstance(text, bool):
        raise ValidationError(f"{field} must be numeric; got {text!r}")
    if isinstance(text, float):
        raise ValidationError(
            f"{field} must be entered as text, not float; got {text!r}")
    if text is None or (isinstance(text, str) and not text.strip()):
        raise ValidationError(f"{field} is required")
    if isinstance(text, Decimal):
        return text
    if isinstance(text, int):
        return Decimal(text)
    if isinstance(text, str) and "," in text:
        raise ValidationError(
            f"{field} must not contain commas; got {text!r}")
    try:
        return to_decimal(text, field)
    except TypeError as exc:
        raise ValidationError(f"{field} must be numeric; got {text!r}") from exc


def parse_int(text, field: str) -> int:
    """Strict string -> int for counts/coats/faces."""
    if isinstance(text, bool) or isinstance(text, float):
        raise ValidationError(
            f"{field} must be a whole number; got {text!r}")
    if isinstance(text, int):
        return text
    if isinstance(text, str) and text.strip().lstrip("+-").isdigit():
        return int(text.strip())
    raise ValidationError(
        f"{field} must be a whole number; got {text!r}")


def parse_optional_decimal(text, field: str) -> Optional[Decimal]:
    """Decimal for optional inputs; empty/None stays None."""
    if text is None or (isinstance(text, str) and not text.strip()):
        return None
    return parse_decimal(text, field)


def _required(inputs: Mapping, key: str) -> str:
    """Fetch a required string input (blank counts as missing)."""
    value = inputs.get(key, "")
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{key} is required")
    return value


def _parsed_overrides(raw: Optional[Mapping], fields) -> dict:
    """Convert supplied string override fields; absent stays absent."""
    raw = raw or {}
    return {name: parse_decimal(raw[name], name)
            for name in fields
            if name in raw and raw[name] not in (None, "")}


def merged_overrides(resolved_records) -> Tuple[str, ...]:
    """Union of overridden_fields across resolved master-data records.

    Provenance for view-models that aggregate several resolutions (e.g.
    one rebar bar per schedule line): every explicit estimator override
    surfaces, in first-seen order, de-duplicated.
    """
    seen: List[str] = []
    for record in resolved_records:
        for field in getattr(record, "overridden_fields", ()) or ():
            if field not in seen:
                seen.append(field)
    return tuple(seen)


def merged_master_version(resolved_records) -> Optional[str]:
    """Master-table version shared by the resolved records (None if none)."""
    for record in resolved_records:
        version = getattr(record, "master_version", None)
        if version:
            return str(version)
    return None


def project_setup_controller(*, standard: str,
                             edition: str = "") -> ProjectSetupView:
    """Validate a measurement-standard selection (unknown names flagged)."""
    if not standard or not str(standard).strip():
        raise ValidationError("Measurement standard is required")
    name = str(standard).strip()
    return ProjectSetupView(
        standard=name, edition=str(edition or "").strip(),
        known=name.upper() in KNOWN_STANDARDS)


def concrete_controller(inputs: Mapping[str, str], repository,
                        overrides: Mapping[str, str] = None):
    """Concrete take-off panel: strings in, ConcreteView/ErrorView out."""
    from qs_engine.concrete.engine import (
        ConcreteMixOverride,
        calculate_concrete_requirement,
    )
    try:
        get = inputs.get
        req = calculate_concrete_requirement(
            length=parse_decimal(get("length"), "length"),
            width=parse_decimal(get("width"), "width"),
            thickness=parse_decimal(get("thickness"), "thickness"),
            unit=(get("unit") or "m"),
            class_key=_required(inputs, "class_key"),
            repository=repository,
            overrides=ConcreteMixOverride(**_parsed_overrides(overrides, (
                "dry_factor", "cement_ratio", "sand_ratio",
                "aggregate_ratio", "wc_ratio",
                "cement_density_kg_per_m3", "sand_density_kg_per_m3",
                "aggregate_density_kg_per_m3", "water_density_kg_per_L",
                "bag_mass_kg"))),
            element=get("element", ""))
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return ConcreteView(
        element=req.element,
        wet_m3=_s(req.wet_volume.value),
        dry_m3=_s(req.constituents.dry_volume_m3),
        cement_m3=_s(req.constituents.cement_m3),
        sand_m3=_s(req.constituents.sand_m3),
        aggregate_m3=_s(req.constituents.aggregate_m3),
        cement_kg=_s(req.masses.cement_kg),
        sand_kg=_s(req.masses.sand_kg),
        aggregate_kg=_s(req.masses.aggregate_kg),
        bags_exact=_s(req.bags.calculated_bags),
        bags_order=_s(req.bags.ordering_bags),
        water_litres=_s(req.water.water_litres),
        class_key=req.resolved_mix.class_key,
        master_version=req.resolved_mix.master_version,
        overrides_used=req.resolved_mix.overrides_used,
    )


def masonry_controller(inputs: Mapping[str, str], repository,
                       overrides: Mapping[str, str] = None,
                       openings: list = ()):
    """Masonry take-off panel: strings in, MasonryView/ErrorView out."""
    from qs_engine.masonry.engine import (
        MasonryUnitOverride,
        calculate_masonry_requirement,
    )
    try:
        get = inputs.get
        norm_openings = []
        for index, opening in enumerate(openings or ()):
            if isinstance(opening, Mapping):
                count_raw = opening.get("count", 1)
                count = (parse_int(count_raw, f"openings[{index}].count")
                         if count_raw not in (None, "") else 1)
                norm_openings.extend(
                    [(opening.get("width"), opening.get("height"))]
                    * count)
            else:
                norm_openings.append(opening)
        req = calculate_masonry_requirement(
            element=get("element", ""),
            wall_length=parse_decimal(get("wall_length"), "wall_length"),
            wall_height=parse_decimal(get("wall_height"), "wall_height"),
            unit=(get("unit") or "m"),
            openings=tuple(norm_openings),
            unit_key=_required(inputs, "unit_key"),
            repository=repository,
            overrides=MasonryUnitOverride(**_parsed_overrides(overrides, (
                "unit_length_mm", "unit_height_mm", "unit_thickness_mm",
                "bed_joint_mm", "perp_joint_mm", "wastage_pct",
                "mortar_cement_ratio", "mortar_sand_ratio",
                "mortar_dry_factor", "mortar_sand_density_kg_per_m3",
                "cement_density_kg_per_m3", "bag_mass_kg"))))
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return MasonryView(
        element=req.element,
        gross_m2=_s(req.wall.gross_m2),
        net_m2=_s(req.wall.net_m2),
        units_exact=_s(req.takeoff.units_exact),
        units_order=_s(req.takeoff.units_order),
        wet_mortar_m3=_s(req.mortar_volumes.wet_mortar_m3),
        dry_mortar_m3=_s(req.mortar_volumes.dry_mortar_m3),
        cement_kg=_s(req.mortar_constituents.cement_kg),
        sand_kg=_s(req.mortar_constituents.sand_kg),
        bags_order=_s(req.bags.ordering_bags),
        unit_key=req.resolved_unit.unit_key,
        master_version=req.resolved_unit.master_version,
        overrides_used=req.resolved_unit.overrides_used,
    )


def rebar_controller(lines: list, wastage_pct: str,
                     tying_wire_kg_per_tonne=None, repository=None,
                     steel_density_kg_per_m3=None):
    """Rebar schedule panel: line mappings in, RebarView/ErrorView out.

    Each line mapping holds bar_key/count/length_per_bar_m strings plus
    optional laps_per_bar/lap_length_m/hook_extra_per_bar_m and per-line
    mass/diameter/density overrides. steel_density_kg_per_m3 is a
    page-level estimator entry applied only to lines that do not carry
    their own density — it feeds the engine's nominal-mass formula when
    Unit Mass is blank; it is never a baked-in constant.
    """
    from qs_engine.reinforcement.engine import (
        BarLineInput,
        RebarBarOverride,
        calculate_bar_line,
        calculate_rebar_schedule,
        resolve_rebar_bar,
    )
    try:
        if not lines:
            raise ValidationError("Rebar schedule needs at least one line")
        results = []
        resolved_bars = []
        for index, raw in enumerate(lines):
            if not isinstance(raw, Mapping):
                raise ValidationError(
                    f"Rebar line #{index} must be a mapping")
            resolved = resolve_rebar_bar(
                _required(raw, "bar_key"), repository,
                RebarBarOverride(**_parsed_overrides(
                    _with_page_density(raw, steel_density_kg_per_m3), (
                        "mass_kg_per_m", "diameter_mm",
                        "steel_density_kg_per_m3", "wastage_pct"))))
            resolved_bars.append(resolved)
            results.append(calculate_bar_line(BarLineInput(
                bar_key=raw["bar_key"],
                count=parse_int(raw.get("count"), f"lines[{index}].count"),
                length_per_bar_m=parse_decimal(
                    raw.get("length_per_bar_m"),
                    f"lines[{index}].length_per_bar_m"),
                laps_per_bar=parse_int(raw.get("laps_per_bar", 0),
                                       f"lines[{index}].laps_per_bar"),
                lap_length_m=parse_decimal(
                    raw.get("lap_length_m", 0) or 0,
                    f"lines[{index}].lap_length_m"),
                hook_extra_per_bar_m=parse_decimal(
                    raw.get("hook_extra_per_bar_m", 0) or 0,
                    f"lines[{index}].hook_extra_per_bar_m")), resolved))
        schedule = calculate_rebar_schedule(
            results,
            wastage_pct=parse_decimal(wastage_pct, "wastage_pct"),
            tying_wire_kg_per_tonne=parse_optional_decimal(
                tying_wire_kg_per_tonne, "tying_wire_kg_per_tonne"))
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return RebarView(
        lines=tuple(KV(f"{r.bar_key} x{r.count}",
                       f"{r.total_length_m} m / {r.total_mass_kg} kg")
                    for r in results),
        total_length_m=_s(schedule.total_length_m),
        total_mass_kg=_s(schedule.total_mass_kg),
        total_mass_tonnes=_s(schedule.total_mass_tonnes),
        wastage_pct=_s(schedule.wastage.wastage_pct),
        after_wastage_kg=_s(schedule.wastage.quantity_after_wastage),
        tying_wire_kg=_s(schedule.tying_wire_kg),
        overrides_used=merged_overrides(resolved_bars),
        master_version=merged_master_version(resolved_bars),
    )


#: Formwork contact-area element types the controller understands; each
#: maps 1:1 to a formwork engine take-off function.
FORMWORK_ELEMENT_TYPES = (
    "slab_soffit", "slab_edge", "beam", "column", "footing", "wall",
)


def parse_deductions(text) -> Tuple[Tuple[str, str], ...]:
    """Parse deduction text ``"label:area; label:area"`` into pairs.

    Blank input yields no deductions and blank segments are skipped; a
    segment without a colon, label, or area fails closed so a typo can
    never silently drop a deduction. Areas stay strings here — the
    engine validates and coerces them through the Decimal policy.
    """
    if text is None:
        return ()
    if not isinstance(text, str):
        raise ValidationError(
            f"Deduction text must be a string; got {type(text).__name__}")
    if not text.strip():
        return ()
    pairs = []
    for index, segment in enumerate(text.split(";")):
        segment = segment.strip()
        if not segment:
            continue
        if ":" not in segment:
            raise ValidationError(
                f"Deduction #{index + 1} must be 'label:area'; "
                f"got {segment!r}")
        label, _, area = segment.partition(":")
        label, area = label.strip(), area.strip()
        if not label:
            raise ValidationError(
                f"Deduction #{index + 1} needs a label before ':'")
        if not area:
            raise ValidationError(
                f"Deduction #{index + 1} needs an area after ':'")
        pairs.append((label, area))
    return tuple(pairs)


class FormworkController:
    """Formwork take-off: string inputs in, FormworkView/ErrorView out.

    Contact areas, itemised deductions, and the plywood/props/release-
    agent schedules all come from the formwork engine — this controller
    only parses strings and maps results. Each scheduling block runs
    only when its rate is supplied; an absent rate leaves those strings
    empty instead of inventing a value. Never raises QSEngineError.
    """

    element_types = FORMWORK_ELEMENT_TYPES

    def calculate(self, inputs: Mapping, deductions=()):
        """Resolve one formwork take-off from widget-style string inputs.

        ``deductions`` is either the "label:area; ..." text from the
        panel or an iterable of (label, area) pairs. Scheduling rates
        (sheet_area_m2 + optional reuses, linear_m_per_m2,
        litres_per_m2) are optional; schedules are computed on the net
        contact area after deductions.
        """
        from qs_engine.formwork.engine import (
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
        try:
            if not isinstance(inputs, Mapping):
                raise ValidationError(
                    f"Formwork inputs must be a mapping; "
                    f"got {type(inputs).__name__}")
            element_type = str(
                _required(inputs, "element_type")).strip().lower()
            unit = str(inputs.get("unit") or "m").strip() or "m"
            element = str(inputs.get("element") or "").strip()
            length = parse_decimal(inputs.get("length"), "length")
            if element_type == "slab_soffit":
                area = slab_soffit_area(
                    length,
                    parse_decimal(inputs.get("width"), "width"), unit)
            elif element_type == "slab_edge":
                area = slab_edge_area(
                    length,
                    parse_decimal(inputs.get("width"), "width"),
                    parse_decimal(inputs.get("depth"), "depth"), unit)
            elif element_type == "beam":
                area = beam_formwork_area(
                    length,
                    parse_decimal(inputs.get("width"), "width"),
                    parse_decimal(inputs.get("depth"), "depth"), unit)
            elif element_type == "column":
                area = column_formwork_area(
                    length,
                    parse_decimal(inputs.get("width"), "width"),
                    parse_decimal(inputs.get("height"), "height"), unit)
            elif element_type == "footing":
                area = footing_formwork_area(
                    length,
                    parse_decimal(inputs.get("width"), "width"),
                    parse_decimal(inputs.get("depth"), "depth"), unit)
            elif element_type == "wall":
                faces_raw = inputs.get("faces")
                faces = (2 if faces_raw in (None, "")
                         else parse_int(faces_raw, "faces"))
                area = wall_formwork_area(
                    length,
                    parse_decimal(inputs.get("height"), "height"),
                    faces, unit)
            else:
                raise ValidationError(
                    f"Unknown formwork element_type {element_type!r}; "
                    f"expected one of {list(FORMWORK_ELEMENT_TYPES)}")
            if isinstance(deductions, str):
                deduction_pairs = parse_deductions(deductions)
            else:
                deduction_pairs = tuple(deductions or ())
            areas = apply_deductions(area.value, deduction_pairs)

            sheet_area = parse_optional_decimal(
                inputs.get("sheet_area_m2"), "sheet_area_m2")
            boarding = None
            if sheet_area is not None:
                reuses_raw = inputs.get("reuses")
                reuses = (1 if reuses_raw in (None, "")
                          else parse_int(reuses_raw, "reuses"))
                boarding = schedule_boarding(
                    areas.net_m2, sheet_area, reuses)
            prop_rate = parse_optional_decimal(
                inputs.get("linear_m_per_m2"), "linear_m_per_m2")
            props = (schedule_props(areas.net_m2, prop_rate)
                     if prop_rate is not None else None)
            agent_rate = parse_optional_decimal(
                inputs.get("litres_per_m2"), "litres_per_m2")
            agent = (release_agent_litres(areas.net_m2, agent_rate)
                     if agent_rate is not None else None)
        except QSEngineError as exc:
            return ErrorView(message=str(exc))

        return FormworkView(
            element_type=element_type,
            element=element,
            gross_m2=_s(areas.gross_m2),
            total_deducted_m2=_s(areas.total_deducted_m2),
            net_m2=_s(areas.net_m2),
            deductions=tuple(
                KV(item.label, _s(item.area_m2))
                for item in areas.deductions),
            sheet_area_m2=_s(boarding.sheet_area_m2) if boarding else "",
            reuses=str(boarding.reuses) if boarding else "",
            sheets_exact=_s(boarding.sheets_exact) if boarding else "",
            sheets_to_buy=str(boarding.sheets_to_buy) if boarding else "",
            linear_m_per_m2=_s(props.linear_m_per_m2) if props else "",
            linear_m=_s(props.linear_m) if props else "",
            litres_per_m2=_s(agent.litres_per_m2) if agent else "",
            litres=_s(agent.litres) if agent else "",
        )


def formwork_controller(inputs: Mapping, deductions=()):
    """Formwork panel delegate: ``FormworkController().calculate(...)``."""
    return FormworkController().calculate(inputs, deductions)


def _with_page_density(raw: Mapping, density) -> Mapping:
    """Apply the page-level density only when the line has none of its own."""
    if density in (None, ""):
        return raw
    if str(raw.get("steel_density_kg_per_m3") or "").strip():
        return raw
    merged = dict(raw)
    merged["steel_density_kg_per_m3"] = density
    return merged


def earthworks_controller(inputs: Mapping[str, str], repository,
                          overrides: Mapping[str, str] = None):
    """Earthworks balance panel: strings in, EarthworksView/ErrorView."""
    from qs_engine.earthworks.engine import (
        SoilOverride,
        calculate_foundation_earthworks,
    )
    try:
        get = inputs.get
        compact_raw = get("compact_backfill", True)
        if isinstance(compact_raw, str):
            compacted = compact_raw.strip().lower() not in (
                "false", "no", "0", "")
        else:
            compacted = bool(compact_raw)
        req = calculate_foundation_earthworks(
            element=get("element", ""),
            length=parse_decimal(get("length"), "length"),
            width=parse_decimal(get("width"), "width"),
            depth=parse_decimal(get("depth"), "depth"),
            unit=(get("unit") or "m"),
            working_space_m=parse_decimal(get("working_space_m", 0) or 0,
                                          "working_space_m"),
            soil_key=_required(inputs, "soil_key"),
            repository=repository,
            overrides=SoilOverride(**_parsed_overrides(overrides, (
                "swell_factor", "compact_factor",
                "density_kg_per_m3"))),
            displaced_substructure_m3=parse_decimal(
                get("displaced_substructure_m3", 0) or 0,
                "displaced_substructure_m3"),
            compact_backfill=compacted)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return EarthworksView(
        element=req.element,
        excavation_bank_m3=_s(req.excavation_bank_m3),
        loose_dug_m3=_s(req.loose_dug_m3),
        backfill_bank_m3=_s(req.backfill_bank_m3),
        backfill_loose_m3=_s(req.backfill_loose_m3),
        dispose_loose_m3=_s(req.dispose_loose_m3),
        bank_mass_kg=_s(req.bank_mass_kg),
        soil_key=req.resolved_soil.soil_key,
        overrides_used=tuple(req.resolved_soil.overridden_fields),
        master_version=req.resolved_soil.master_version or None,
    )


def finishes_controller(kind: str, inputs: Mapping[str, str]):
    """Finishes take-off panel: geometry strings in, FinishesView out.

    kind is plaster/screed/tiles/paint. Resolution (mortar, coverage)
    belongs to the rate-builder/BOQ steps; unresolved entries travel
    visibly on the view.
    """
    from qs_engine.finishes.takeoff import (
        Opening,
        paint_takeoff,
        plaster_takeoff,
        screed_takeoff,
        tile_takeoff,
    )
    try:
        get = inputs.get
        if kind not in ("plaster", "screed", "tiles", "paint"):
            raise ValidationError(
                f"Unknown finishes kind {kind!r}; expected plaster, "
                f"screed, tiles, or paint")
        raw_openings = get("openings", ())
        openings = []
        for index, raw in enumerate(raw_openings or ()):
            if isinstance(raw, Mapping):
                openings.append(Opening(
                    width=parse_decimal(raw.get("width"),
                                        f"openings[{index}].width"),
                    height=parse_decimal(raw.get("height"),
                                         f"openings[{index}].height"),
                    count=parse_int(raw.get("count", 1),
                                    f"openings[{index}].count"),
                    unit=get("unit", "m") or "m"))
            else:
                openings.append(raw)
        element = get("element", "")
        if kind == "plaster":
            result = plaster_takeoff(
                length=parse_decimal(get("length"), "length"),
                height=parse_decimal(get("height"), "height"),
                unit=(get("unit") or "m"),
                faces=parse_int(get("faces", 2), "faces"),
                openings=openings,
                thickness=parse_decimal(get("thickness"), "thickness"),
                thickness_unit=(get("thickness_unit") or "mm"),
                element=element)
            lines = (KV("Gross area (m²)", _s(result.gross_m2)),
                     KV("Openings (m²)", _s(result.openings_m2)),
                     KV("Net area (m²)", _s(result.net_m2)),
                     KV("Thickness (m)", _s(result.thickness_m)),
                     KV("Volume (m³)", _s(result.volume_m3)))
            unresolved = ()
        elif kind == "screed":
            result = screed_takeoff(
                length=parse_decimal(get("length"), "length"),
                width=parse_decimal(get("width"), "width"),
                unit=(get("unit") or "m"),
                thickness=parse_decimal(get("thickness"), "thickness"),
                thickness_unit=(get("thickness_unit") or "mm"),
                element=element)
            lines = (KV("Area (m²)", _s(result.area_m2)),
                     KV("Thickness (m)", _s(result.thickness_m)),
                     KV("Volume (m³)", _s(result.volume_m3)))
            unresolved = ()
        elif kind == "tiles":
            result = tile_takeoff(
                length=parse_decimal(get("length"), "length"),
                width=parse_decimal(get("width"), "width"),
                unit=(get("unit") or "m"),
                openings=openings,
                tile_length_mm=parse_decimal(
                    get("tile_length_mm"), "tile_length_mm"),
                tile_width_mm=parse_decimal(
                    get("tile_width_mm"), "tile_width_mm"),
                joint_mm=parse_decimal(get("joint_mm"), "joint_mm"),
                wastage_pct=parse_optional_decimal(
                    get("wastage_pct"), "wastage_pct"),
                element=element)
            lines = (KV("Net area (m²)", _s(result.net_area_m2)),
                     KV("Tile area (m²)", _s(result.tile_area_m2)),
                     KV("Theoretical count", _s(result.theoretical_count)),
                     KV("Order quantity",
                        str(result.order_quantity)
                        if result.order_quantity is not None else "—"),)
            unresolved = result.unresolved
        else:
            result = paint_takeoff(
                length=parse_decimal(get("length"), "length"),
                height=parse_decimal(get("height"), "height"),
                unit=(get("unit") or "m"),
                faces=parse_int(get("faces", 1), "faces"),
                openings=openings,
                coats=parse_int(get("coats"), "coats"),
                element=element)
            lines = (KV("Net area per coat (m²)", _s(result.net_m2)),
                     KV("Coats", _s(result.coats)),
                     KV("Total coated (m²)", _s(result.total_coated_m2)))
            unresolved = ()
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return FinishesView(kind=kind, element=element, lines=lines,
                        unresolved=unresolved)


def labour_controller(inputs: Mapping[str, str], repository,
                      overrides: Mapping[str, str] = None,
                      hours_per_day=None):
    """Labour panel: strings in, LabourView/ErrorView out."""
    from qs_engine.labour.engine import (
        LabourTradeOverride,
        calculate_labour_requirement,
    )
    try:
        get = inputs.get
        hours = (parse_decimal(hours_per_day, "hours_per_day")
                 if hours_per_day not in (None, "") else None)
        req = calculate_labour_requirement(
            element=get("element", ""),
            work_quantity=parse_decimal(get("work_quantity"),
                                        "work_quantity"),
            trade_key=_required(inputs, "trade_key"),
            repository=repository,
            overrides=LabourTradeOverride(**_parsed_overrides(overrides, (
                "output_per_day", "skilled_rate", "unskilled_rate")) |
                {name: _parse_gang_count(overrides, name)
                 for name in ("gang_skilled", "gang_unskilled")}),
            hours_per_day=hours)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return LabourView(
        element=req.element,
        duration_gang_days=_s(req.duration_gang_days),
        skilled_person_days=_s(req.skilled_person_days),
        unskilled_person_days=_s(req.unskilled_person_days),
        skilled_person_hours=_s(req.skilled_person_hours),
        unskilled_person_hours=_s(req.unskilled_person_hours),
        gang_cost_per_day=_s(req.gang_cost_per_day),
        total_cost=_s(req.total_cost),
        trade_key=req.resolved_trade.trade_key,
        overrides_used=tuple(req.resolved_trade.overridden_fields),
        master_version=req.resolved_trade.master_version or None,
    )


def _parse_gang_count(overrides: Mapping[str, str], name: str):
    """Gang counts are integers, not Decimals — parsed separately."""
    raw = (overrides or {}).get(name)
    if raw in (None, ""):
        return None
    return parse_int(raw, name)


def plant_controller(inputs: Mapping[str, str], repository,
                     overrides: Mapping[str, str] = None,
                     hours_per_day=None):
    """Plant panel: strings in, PlantView/ErrorView out."""
    from qs_engine.plant.engine import (
        PlantOverride,
        calculate_plant_requirement,
    )
    try:
        get = inputs.get
        hours = (parse_decimal(hours_per_day, "hours_per_day")
                 if hours_per_day not in (None, "") else None)
        req = calculate_plant_requirement(
            element=get("element", ""),
            work_quantity=parse_decimal(get("work_quantity"),
                                        "work_quantity"),
            equipment_key=_required(inputs, "equipment_key"),
            repository=repository,
            overrides=PlantOverride(**_parsed_overrides(overrides, (
                "output_per_unit", "rate", "operating_cost_per_hour"))),
            hours_per_day=hours)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return PlantView(
        element=req.element,
        duration_value=_s(req.duration_value),
        duration_basis=req.duration_basis,
        hire_cost=_s(req.hire_cost),
        operating_cost=_s(req.operating_cost),
        total_cost=_s(req.total_cost),
        equipment_key=req.resolved_plant.equipment_key,
        overrides_used=tuple(req.resolved_plant.overridden_fields),
        master_version=req.resolved_plant.master_version or None,
    )


def logistics_plan_controller(inputs: Mapping[str, str], repository,
                              overrides: Mapping[str, str] = None):
    """Haulage plan panel: strings in, LogisticsView/ErrorView out."""
    from qs_engine.logistics.engine import TruckOverride, plan_haulage
    try:
        get = inputs.get
        target_unit = (get("target_unit") or "tonne").strip()
        plan = plan_haulage(
            element=get("element", ""),
            total_loose_m3=parse_decimal(get("total_loose_m3"),
                                         "total_loose_m3"),
            loose_density_t_per_m3=parse_decimal(
                get("loose_density_t_per_m3"), "loose_density_t_per_m3"),
            truck_key=_required(inputs, "truck_key"),
            repository=repository,
            overrides=TruckOverride(**_parsed_overrides(overrides, (
                "body_length_m", "body_width_m", "body_height_m",
                "payload_limit_tonnes", "payload_tonnes",
                "load_time_min", "unload_time_min",
                "speed_loaded_kmh", "speed_empty_kmh",
                "hire_rate", "fuel_burn_L_per_hr"))),
            heap_pct=parse_decimal(get("heap_pct", 0) or 0, "heap_pct"),
            distance_km=parse_decimal(get("distance_km"), "distance_km"),
            available_minutes_per_day=parse_decimal(
                get("available_minutes_per_day"),
                "available_minutes_per_day"),
            target_per_day=parse_decimal(get("target_per_day"),
                                         "target_per_day"),
            target_unit=target_unit)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return LogisticsView(
        element=plan.element,
        load_m3=_s(plan.limiting_load.load_m3),
        load_tonnes=_s(plan.limiting_load.load_tonnes),
        limiting=plan.limiting_load.limiting,
        cycle_minutes=_s(plan.cycle_minutes),
        trips_exact=_s(plan.trips_exact),
        trips_ordered=_s(plan.trips_ordered),
        trucks_required=_s(plan.trucks_required),
        daily_capacity=_s(plan.daily_capacity_per_truck),
        overrides_used=tuple(plan.resolved_truck.overridden_fields),
        master_version=plan.resolved_truck.master_version or None,
    )


def _parse_rate_line(raw: Mapping, index: int, repository):
    """Parse one string rate-build-up line, or pass through objects.

    String kinds: material (key/qty/price/waste), labour via explicit
    hours x rate, logistics (total/quantity), subcontract (amount +
    description + provisional flag), other. Plant lines need a resolved
    PlantRequirement object — strings alone cannot price plant, and the
    controller says so instead of guessing.
    """
    from qs_engine.rates.engine import (
        labour_component_direct,
        logistics_component,
        material_component,
        other_component,
        subcontract_component,
    )
    from qs_engine.rates.results import RateComponent
    if isinstance(raw, RateComponent):
        return raw
    if not isinstance(raw, Mapping):
        raise ValidationError(f"Rate line #{index} must be a mapping")
    kind = (raw.get("kind") or "").strip().lower()
    if kind == "material":
        return material_component(
            material_key=_required(raw, "material_key"),
            qty_per_unit=parse_decimal(raw.get("qty_per_unit"),
                                       f"lines[{index}].qty_per_unit"),
            unit_price=parse_decimal(raw.get("unit_price"),
                                     f"lines[{index}].unit_price"),
            # Blank/absent wastage stays None — never coerced to 0. The
            # engine falls back to the master record default or fails
            # closed (E-24: no fabricated zero-wastage assumption).
            wastage_pct=parse_optional_decimal(
                raw.get("wastage_pct"), f"lines[{index}].wastage_pct"),
            repository=repository,
            description=raw.get("description", ""))
    if kind == "labour":
        return labour_component_direct(
            hours_per_unit=parse_decimal(raw.get("hours_per_unit"),
                                         f"lines[{index}].hours_per_unit"),
            rate_per_hour=parse_decimal(raw.get("rate_per_hour"),
                                        f"lines[{index}].rate_per_hour"),
            description=raw.get("description", ""))
    if kind == "logistics":
        return logistics_component(
            total_haulage_cost=parse_decimal(
                raw.get("total_haulage_cost"),
                f"lines[{index}].total_haulage_cost"),
            work_quantity=parse_decimal(raw.get("work_quantity"),
                                        f"lines[{index}].work_quantity"),
            description=raw.get("description", ""))
    if kind == "subcontract":
        flag = raw.get("provisional", False)
        provisional = (str(flag).strip().lower()
                       not in ("false", "no", "0", "")) if isinstance(
            flag, str) else bool(flag)
        return subcontract_component(
            amount_per_unit=parse_decimal(
                raw.get("amount_per_unit"),
                f"lines[{index}].amount_per_unit"),
            description=_required(raw, "description"),
            provisional=provisional)
    if kind == "plant":
        raise ValidationError(
            f"Rate line #{index}: plant lines need a resolved "
            f"PlantRequirement object (strings alone cannot price plant); "
            f"pass a RateComponent through instead")
    raise ValidationError(
        f"Rate line #{index} has unknown kind {kind!r}; expected "
        f"material, labour, logistics, subcontract, or other")


def rate_builder_controller(lines: list, markups: list,
                            markup_policy: str, element: str,
                            work_unit: str, repository):
    """Rate builder panel: line mappings in, RateBuildupView/ErrorView."""
    from qs_engine.rates.engine import composite_rate
    try:
        if not lines:
            raise ValidationError("Rate build-up needs at least one line")
        components = [_parse_rate_line(raw, index, repository)
                      for index, raw in enumerate(lines)]
        parsed_markups = []
        for index, markup in enumerate(markups or ()):
            if isinstance(markup, Mapping):
                label = markup.get("label", "")
                pct = markup.get("pct")
            else:
                try:
                    label, pct = markup
                except (TypeError, ValueError):
                    raise ValidationError(
                        f"Markup #{index} must be a (label, pct) pair"
                    ) from None
            parsed_markups.append(
                (label, parse_decimal(pct, f"markups[{index}].pct")))
        rate = composite_rate(
            components=components, markups=parsed_markups,
            markup_policy=(markup_policy or "sequential"),
            element=element or "", work_unit=work_unit)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return RateBuildupView(
        element=rate.element,
        work_unit=rate.work_unit,
        components=tuple(KV(f"{c.kind}: {c.description or 'line'}",
                            _s(c.cost_per_unit))
                         for c in rate.components),
        direct_cost=_s(rate.direct_cost_per_unit),
        markups=tuple(KV(f"{m.label} ({m.pct}%)", _s(m.amount))
                      for m in rate.markups),
        markup_policy=rate.markup_policy,
        net_rate=_s(rate.net_rate),
        gross_rate=_s(rate.gross_rate),
    )


def boq_view_controller(boq: Boq, require_measurement_rules: bool = False):
    """BOQ view: compiled document in, rendered strings out."""
    from qs_engine.boq.compiler import compile_boq
    try:
        compiled = compile_boq(
            boq, require_measurement_rules=bool(require_measurement_rules))
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    sections = []
    for section in compiled.sections:
        sections.append(BoqSectionView(
            code=section.code,
            title=section.title,
            items=tuple(BoqItemView(
                item_no=item.item_no,
                description=item.description,
                quantity=_s(item.quantity),
                unit=item.unit,
                rate=_s(item.rate),
                amount=_s(item.amount),
                status=item.status,
            ) for item in section.items),
            total=_s(section.total),
            has_unresolved=section.has_unresolved,
        ))
    return BoqView(
        project_ref=compiled.project_ref,
        boq_ref=compiled.boq_ref,
        sections=tuple(sections),
        grand_total=_s(compiled.total),
        resolved_subtotal=_s(compiled.resolved_subtotal),
        has_unresolved=compiled.has_unresolved,
        unresolved_items=tuple(compiled.unresolved_items),
    )


def excel_export_controller(compiled, output_path: str, project_name: str = "",
                            exported_on: str = ""):
    """Excel export trigger: compiled BOQ + path in, ExportView/Error."""
    from qs_engine.adapters.excel.boq_workbook import export_boq_to_excel
    try:
        path = export_boq_to_excel(
            compiled, output_path, project_name=project_name,
            exported_on=exported_on)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return ExportView(path=str(path), detail="Excel workbook exported")


def tender_export_controller(compiled, output_path: str, *,
                             company_name: str = "",
                             project_title: str = "",
                             client: str = "",
                             reference: str = "",
                             measurement_standard: str = "",
                             exported_on: str = "",
                             template_style: str = "standard"):
    """Tender schedule export trigger: compiled BOQ + path in,
    ExportView/Error out."""
    from qs_engine.adapters.excel.tender_workbook import (
        export_tender_to_excel,
    )
    try:
        path = export_tender_to_excel(
            compiled, output_path, company_name=company_name,
            project_title=project_title, client=client,
            reference=reference, measurement_standard=measurement_standard,
            exported_on=exported_on, template_style=template_style)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return ExportView(path=str(path), detail="Tender schedule exported")


def tender_reconciliation_controller(compiled, tender_path: str):
    """Variance analysis trigger: compiled BOQ + tender file in,
    ReconciliationSummary (or ErrorView) out. Session truth is never
    written — the summary is a review DTO for estimator confirmation."""
    from qs_engine.adapters.excel.reconciliation import (
        reconcile_tender_file,
    )
    try:
        return reconcile_tender_file(compiled, tender_path)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))


def document_payload_controller(compiled, document_title: str,
                                 purpose: str, compilation_id: str = "",
                                 document_date: str = ""):
    """Document DTO trigger: compiled BOQ in, payload (or ErrorView) out."""
    from qs_engine.adapters.document.payload import synthesize_boq_payload
    try:
        payload = synthesize_boq_payload(
            compiled, document_title=document_title, purpose=purpose,
            compilation_id=compilation_id, document_date=document_date)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))
    return payload


def branded_document_controller(compiled=None, payload=None, profile=None,
                                template: str = "civolink",
                                document_kind: str = "quotation",
                                output_dir=None, filename: str = "",
                                custom_template_path=None,
                                export_pdf: bool = False, rate=None):
    """Branded Word export trigger: BOQ DTO + profile in, ExportView out.

    Passes the active BOQ/rate DTO data and company-profile metadata
    into the scripts/ Word generators; the .docx (plus optional PDF
    summary) lands in output/. Any engine/validation failure becomes
    an ErrorView — the view displays it without crashing.
    """
    from qs_engine.adapters.document.word_export import (
        export_branded_document,
    )
    try:
        result = export_branded_document(
            compiled=compiled, payload=payload, profile=profile,
            template=template, document_kind=document_kind,
            output_dir=output_dir, filename=filename,
            custom_template_path=custom_template_path,
            export_pdf=export_pdf, rate=rate)
    except (QSEngineError, ImportError, OSError) as exc:
        return ErrorView(message=str(exc))
    detail = f"Branded Word document exported ({template})"
    if result.get("pdf_path"):
        detail += f" + PDF summary {result['pdf_path']}"
    return ExportView(path=str(result["docx_path"]), detail=detail)


def ipc_valuation_controller(contract_sum: str, retention_rate_pct: str,
                             retention_limit: str, previous_valuation: str = "0",
                             items: list = (), onsite_materials: str = "0",
                             advance_repaid: str = "0",
                             advance_balance: str = "0",
                             previous_payments: str = "0",
                             valuation_no: str = ""):
    """IPC valuation trigger: contract + period figures in,
    IPCValuation (or ErrorView) out. Pure valuation math only."""
    from qs_engine.valuation.ipc_engine import compute_ipc
    try:
        return compute_ipc(
            contract_sum, retention_rate_pct, retention_limit,
            previous_valuation=previous_valuation,
            items=[dict(line) for line in items],
            onsite_materials=onsite_materials,
            advance_repaid=advance_repaid,
            advance_balance=advance_balance,
            previous_payments=previous_payments,
            valuation_no=valuation_no)
    except QSEngineError as exc:
        return ErrorView(message=str(exc))


def boq_pdf_controller(compiled, info: dict, output_path: str):
    """BOQ summary PDF trigger: compiled BOQ + info in, ExportView/Error."""
    from qs_engine.export.pdf_exporter import export_boq_summary_pdf
    try:
        path = export_boq_summary_pdf(
            compiled, dict(info or {}), output_path)
    except (QSEngineError, OSError) as exc:
        return ErrorView(message=str(exc))
    return ExportView(path=str(path), detail="BOQ summary PDF exported")


def ipc_pdf_controller(valuation, info: dict, output_path: str):
    """IPC statement PDF trigger: valuation + info in, ExportView/Error."""
    from qs_engine.export.pdf_exporter import export_ipc_statement_pdf
    try:
        path = export_ipc_statement_pdf(
            valuation, dict(info or {}), output_path)
    except (QSEngineError, OSError) as exc:
        return ErrorView(message=str(exc))
    return ExportView(path=str(path), detail="IPC statement PDF exported")


def mix_design_controller(inputs: Mapping[str, str], repository,
                           overrides=None):
    """Compute BS EN 206 / BS 8500 constituent quantities.

    Inputs: designation (e.g. C20/25), net_volume (m³),
    wastage_pct (default 0.05). Returns a ConstituentResult
    view-model or an ErrorView on failure.
    """
    from qs_engine.core.errors import ValidationError
    from qs_engine.mixes.calculator import (
        ConstituentCalculator,
    )
    from qs_engine.reconciliation import (
        ISSUE, RECEIPT, STOCK_COUNT,
    )
    from qs_engine.master_data.repository import (
        MasterDataRepository,
    )
    try:
        repo = repository if isinstance(
            repository, MasterDataRepository) else None
        if repo is None:
            return ErrorView(message="MasterDataRepository required")
        designation = (inputs.get("designation") or "").strip()
        if not designation:
            return ErrorView(message="Pick a strength class")
        net_volume = inputs.get("net_volume") or "0"
        wastage_pct = inputs.get("wastage_pct") or "0.05"
        calc = ConstituentCalculator(repo)
        result = calc.compute(
            designation, net_volume, wastage_pct)
        return result
    except ValidationError as exc:
        return ErrorView(message=str(exc.message))
    except Exception as exc:
        return ErrorView(message=f"Mix design error: {exc}")
