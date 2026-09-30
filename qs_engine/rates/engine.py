"""Unit-rate build-up pipeline (Phase 9).

    component builders (material / labour / plant / logistics /
      subcontractor — each with explicit prices, rates, wastage)
      -> composite_rate() (direct sum + markup stack, sequential or
         parallel compounding, policy recorded)
      -> net vs gross rates (+ total_for quantity helper)

Prices arrive per call (no verified price library exists yet); material
keys are validated to exist (unknown keys fail closed via the
repository). Labour/plant/logistics builders consume Phase 7/8 result
objects directly, so verified resolutions flow through unchanged.
"""

from decimal import Decimal
from typing import Iterable, Mapping, Optional, Union

from ..core.assumptions import VerificationStatus
from ..core.decimal_policy import to_decimal
from ..core.errors import UnverifiedMasterDataError, ValidationError
from ..core.units import SUPPORTED_UNITS
from ..core.validation import (
    validate_percentage,
    validate_quantity,
    validate_rate,
)
from ..core.wastage import apply_wastage
from ..master_data import CrossDomainReference
from ..master_data.schemas import COMPONENT_KIND_DOMAINS, MATERIALS
from .results import (
    COMPONENT_KINDS,
    KIND_LABOUR,
    KIND_LOGISTICS,
    KIND_MATERIAL,
    KIND_OTHER,
    KIND_PLANT,
    KIND_SUBCONTRACT,
    POLICY_PARALLEL,
    POLICY_SEQUENTIAL,
    CompositeRate,
    MarkupApplied,
    MarkupSpec,
    RateComponent,
    RateTemplate,
    TemplateLine,
)

Numeric = Union[Decimal, int, str]

#: Markup percentages accept 0-1000 (profit can exceed 100; >1000 is a typo).
MARKUP_MAX_PCT = Decimal("1000")


def _markup_pct(value: Numeric, label: str) -> Decimal:
    pct = validate_percentage(value, f"markup[{label}]",
                              minimum=0, maximum=MARKUP_MAX_PCT)
    return pct


def material_component(
    *,
    material_key: str,
    qty_per_unit: Numeric,
    unit_price: Numeric,
    wastage_pct: Optional[Numeric] = 0,
    repository,
    description: str = "",
) -> RateComponent:
    """Material cost per work unit with explicit wastage.

    The material key must exist (unknown keys fail closed). Prices are
    explicit per call — no verified price library exists yet.

    wastage_pct semantics: an explicit number (including 0) is used as
    given; None means UNSPECIFIED and falls back to the master record's
    default_wastage_pct when that record is VERIFIED/PROVISIONAL, else
    raises UnverifiedMasterDataError — a blank input is never turned
    into a silent zero-wastage assumption. The parameter default of 0
    remains for direct engine callers that deliberately assert 0%.
    """
    record = CrossDomainReference.parse(
        material_key, domain=MATERIALS).lookup(repository)
    qty = validate_quantity(qty_per_unit, "qty_per_unit")
    price = validate_rate(unit_price, "unit_price")
    if wastage_pct is None:
        default = record.get("default_wastage_pct")
        if (record.get("verification_status")
                not in (VerificationStatus.VERIFIED,
                        VerificationStatus.PROVISIONAL)
                or default is None):
            raise UnverifiedMasterDataError(
                f"Material {material_key!r}: wastage_pct was not "
                f"supplied and the master record has no verified "
                f"default_wastage_pct; enter an explicit wastage_pct "
                f"or verify the material record.")
        wastage_pct = to_decimal(default, "default_wastage_pct")
    wasted = apply_wastage(
        qty * price, validate_percentage(wastage_pct, "wastage_pct"))
    return RateComponent(
        kind=KIND_MATERIAL,
        description=description or f"{material_key} @ {price}/unit",
        cost_per_unit=wasted.quantity_after_wastage,
    )


def labour_component_from_requirement(
    labour_requirement, work_quantity: Numeric,
    description: str = "",
) -> RateComponent:
    """Labour cost per unit from a Phase 7 LabourRequirement.

    work_quantity is the work the requirement covers (> 0); per-unit
    cost = total labour cost / quantity.
    """
    quantity = validate_quantity(work_quantity, "work_quantity")
    if quantity == 0:
        raise ValidationError(
            "work_quantity must be > 0 to allocate labour cost per unit")
    return RateComponent(
        kind=KIND_LABOUR,
        description=(description
                     or f"labour: {labour_requirement.resolved_trade.trade_key}"),
        cost_per_unit=labour_requirement.total_cost / quantity,
    )


def labour_component_direct(
    *,
    hours_per_unit: Numeric,
    rate_per_hour: Numeric,
    description: str = "",
) -> RateComponent:
    """Labour cost per unit from explicit hours and rate (no lookup)."""
    hours = validate_quantity(hours_per_unit, "hours_per_unit")
    rate = validate_rate(rate_per_hour, "rate_per_hour")
    return RateComponent(
        kind=KIND_LABOUR,
        description=description or f"labour direct @ {rate}/hr",
        cost_per_unit=hours * rate,
    )


def plant_component_from_requirement(
    plant_requirement, work_quantity: Numeric,
    description: str = "",
) -> RateComponent:
    """Plant cost per unit from a Phase 7 PlantRequirement."""
    quantity = validate_quantity(work_quantity, "work_quantity")
    if quantity == 0:
        raise ValidationError(
            "work_quantity must be > 0 to allocate plant cost per unit")
    return RateComponent(
        kind=KIND_PLANT,
        description=(description or
                     f"plant: {plant_requirement.resolved_plant.equipment_key}"),
        cost_per_unit=plant_requirement.total_cost / quantity,
    )


def logistics_component(
    *,
    total_haulage_cost: Numeric,
    work_quantity: Numeric,
    description: str = "",
) -> RateComponent:
    """Haulage allocation per work unit (e.g. cart-away per m3 dug)."""
    total = validate_rate(total_haulage_cost, "total_haulage_cost")
    quantity = validate_quantity(work_quantity, "work_quantity")
    if quantity == 0:
        raise ValidationError(
            "work_quantity must be > 0 to allocate haulage cost per unit")
    return RateComponent(
        kind=KIND_LOGISTICS,
        description=description or "haulage allocation",
        cost_per_unit=total / quantity,
    )


def subcontract_component(
    *,
    amount_per_unit: Numeric,
    description: str,
    provisional: bool = False,
) -> RateComponent:
    """Subcontractor / prime-cost / provisional allowance per unit.

    provisional=True labels PC sums and provisional allowances so they
    stay distinguishable in the build-up (description REQUIRED).
    """
    if not description or not description.strip():
        raise ValidationError(
            "subcontract components require a description "
            "(provisional sums must be labelled)")
    return RateComponent(
        kind=KIND_SUBCONTRACT,
        description=description,
        cost_per_unit=validate_rate(amount_per_unit, "amount_per_unit"),
        provisional=provisional,
    )


def other_component(*, amount_per_unit: Numeric,
                    description: str = "") -> RateComponent:
    """Any other direct cost per unit."""
    return RateComponent(
        kind=KIND_OTHER,
        description=description or "other direct cost",
        cost_per_unit=validate_rate(amount_per_unit, "amount_per_unit"),
    )


def _check_component(component: RateComponent) -> RateComponent:
    if not isinstance(component, RateComponent):
        raise ValidationError(
            f"Expected RateComponent; got {type(component).__name__}")
    if component.kind not in COMPONENT_KINDS:
        raise ValidationError(f"Unknown component kind {component.kind!r}")
    validate_rate(component.cost_per_unit, "component.cost_per_unit")
    return component


def composite_rate(
    *,
    components: Iterable[RateComponent],
    markups: Iterable[tuple] = (),
    markup_policy: str = POLICY_SEQUENTIAL,
    element: str = "",
    work_unit: str,
) -> CompositeRate:
    """Composite unit rate from components plus a markup stack.

    markups is an ordered iterable of (label, pct) pairs. SEQUENTIAL
    compounds each markup onto the running total (cumulative);
    PARALLEL applies each to the direct-cost subtotal. Policy recorded.
    """
    if work_unit not in SUPPORTED_UNITS:
        from ..core.errors import UnknownUnitError
        raise UnknownUnitError(f"Unknown unit: {work_unit!r}")
    if markup_policy not in (POLICY_SEQUENTIAL, POLICY_PARALLEL):
        raise ValidationError(
            f"markup_policy must be '{POLICY_SEQUENTIAL}' or "
            f"'{POLICY_PARALLEL}'; got {markup_policy!r}")
    lines = tuple(_check_component(c) for c in components)
    if not lines:
        raise ValidationError(
            "A composite rate needs at least one cost component")
    direct = sum((c.cost_per_unit for c in lines), Decimal("0"))
    specs = []
    for index, markup in enumerate(markups):
        try:
            label, pct = markup
        except (TypeError, ValueError):
            raise ValidationError(
                f"Markup #{index} must be a (label, pct) pair; "
                f"got {markup!r}") from None
        if not label or not str(label).strip():
            raise ValidationError(f"Markup #{index} must have a label")
        specs.append(MarkupSpec(label=str(label),
                                pct=_markup_pct(pct, str(label))))
    applied = []
    running = direct
    gross_parallel_extra = Decimal("0")
    for spec in specs:
        if markup_policy == POLICY_SEQUENTIAL:
            amount = running * spec.pct / Decimal("100")
            running = running + amount
        else:
            amount = direct * spec.pct / Decimal("100")
            gross_parallel_extra = gross_parallel_extra + amount
            running = direct + gross_parallel_extra
        applied.append(MarkupApplied(
            label=spec.label, pct=spec.pct, amount=amount,
            running_total=running))
    gross = running
    return CompositeRate(
        element=element,
        work_unit=work_unit,
        components=lines,
        direct_cost_per_unit=direct,
        markups=tuple(applied),
        markup_policy=markup_policy,
        net_rate=direct,
        gross_rate=gross,
    )


def get_rate_template(template_key: str, repository) -> RateTemplate:
    """Fetch a build-up structure (no prices bound — BOQ phase binds them).

    Structural lookup only: components/markups carry refs and labels with
    null values. Unknown keys fail closed via the repository.
    """
    record: Mapping = repository.get("rate_templates", template_key)
    lines = []
    for index, line in enumerate(record.get("components", [])):
        if not isinstance(line, Mapping):
            raise ValidationError(
                f"Template {template_key!r} component #{index} malformed")
        if line.get("kind") not in COMPONENT_KINDS:
            raise ValidationError(
                f"Template {template_key!r} component #{index} has "
                f"unknown kind {line.get('kind')!r}")
        ref = str(line.get("ref", ""))
        target = COMPONENT_KIND_DOMAINS.get(line.get("kind"))
        if target is not None and ref.strip():
            # Typed reference: a scoped ref pointing at the wrong domain
            # (or a bogus prefix) fails closed here, not at BOQ binding.
            CrossDomainReference.parse(ref, domain=target, strict_scope=True)
        qty = line.get("qty_per_unit")
        lines.append(TemplateLine(
            kind=line["kind"], ref=ref,
            qty_per_unit=(to_decimal(qty, "qty_per_unit")
                          if qty is not None else None),
            note=str(line.get("note", ""))))
    markups = []
    for index, markup in enumerate(record.get("markups", [])):
        if not isinstance(markup, Mapping):
            raise ValidationError(
                f"Template {template_key!r} markup #{index} malformed")
        pct = markup.get("pct")
        markups.append(MarkupSpec(
            label=str(markup.get("label", "")),
            pct=to_decimal(pct, "pct") if pct is not None else None))
    return RateTemplate(
        template_key=template_key,
        name=str(record.get("name", "")),
        work_unit=str(record.get("work_unit", "")),
        components=tuple(lines),
        markups=tuple(markups),
        master_version=repository.table_version("rate_templates"),
    )


def template_is_priced(template: RateTemplate) -> bool:
    """True only when every component qty and markup pct is non-null."""
    return (all(line.qty_per_unit is not None for line in template.components)
            and all(markup.pct is not None for markup in template.markups))
