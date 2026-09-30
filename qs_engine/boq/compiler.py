"""Deterministic BOQ compiler (Phase 10).

Consumes validated Boq structure plus Phase 9 rate results; computes
nothing itself beyond quantity x rate and honest roll-ups. Ordering and
numbering derive from input list positions (never dict iteration):
explicit item_no values are honoured after duplicate checks, otherwise
numbers are section.subsection.item ordinals.

Totals policy: priced and provisional amounts roll up; any unpriced or
unresolved line forces its section total (and hence the grand total) to
None, while resolved_subtotal always reports what IS priced and
unresolved_items names every line needing follow-up.
"""

from decimal import Decimal
from typing import List, Optional

from ..core.errors import ValidationError
from .models import (
    STATUS_PRICED,
    STATUS_PROVISIONAL,
    STATUS_UNPRICED,
    STATUS_UNRESOLVED,
    PRICING_EXPLICIT,
    PRICING_PRICED,
    PRICING_PROVISIONAL,
    PRICING_UNPRICED,
    Boq,
    CompiledBoq,
    CompiledItem,
    CompiledSection,
    CompiledSubsection,
)


def _compile_item(item, section_code: str, subsection_code: str,
                  number: str, require_measurement_rules: bool,
                  ) -> CompiledItem:
    """Compile one line: money, status, and traceability."""
    measurement_ref = (item.measurement.citation
                       if item.measurement is not None else None)
    rule_ok = (item.measurement is not None
               and item.measurement.is_verified)

    rate: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    if item.pricing.kind in (PRICING_PRICED, PRICING_EXPLICIT):
        rate = item.pricing.rate
        amount = item.quantity * rate
        status = STATUS_PRICED
    elif item.pricing.kind == PRICING_PROVISIONAL:
        amount = item.pricing.amount
        status = STATUS_PROVISIONAL
    else:  # PRICING_UNPRICED
        status = STATUS_UNPRICED

    if require_measurement_rules and not rule_ok:
        # Line arithmetic stands (it never needed the rule); the status
        # excludes the line from every total instead. Information
        # preserved, totals honest.
        status = STATUS_UNRESOLVED

    provenance = tuple(part for part in (
        item.takeoff_ref.strip() or None,
        item.pricing.rate_ref.strip() or None,
        measurement_ref,
    ) if part)

    return CompiledItem(
        item_no=number,
        description=item.description,
        section_code=section_code,
        subsection_code=subsection_code,
        trade=item.trade,
        unit=item.unit,
        quantity=item.quantity,
        rate=rate,
        amount=amount,
        status=status,
        pricing_kind=item.pricing.kind,
        rate_ref=item.pricing.rate_ref,
        takeoff_ref=item.takeoff_ref,
        measurement_ref=measurement_ref,
        provenance=provenance,
        notes=item.notes,
        takeoff=item.takeoff,
        rate_result=item.rate_result,
    )


def compile_boq(boq: Boq,
                require_measurement_rules: bool = False) -> CompiledBoq:
    """Compile a Boq into ordered sections with honest totals.

    require_measurement_rules=True marks items without a VERIFIED
    measurement rule unresolved (amount withheld from totals).
    """
    if not isinstance(boq, Boq):
        raise ValidationError(
            f"compile_boq needs a Boq; got {type(boq).__name__}")

    seen_numbers = set()
    compiled_sections: List[CompiledSection] = []
    unresolved_items: List[str] = []
    grand_resolved = Decimal("0")
    grand_clean = True

    for sec_ord, section in enumerate(boq.sections, start=1):
        compiled_items: List[CompiledItem] = []
        compiled_subs = []
        section_resolved = Decimal("0")
        section_clean = True
        for sub_ord, subsection in enumerate(section.subsections, start=1):
            sub_numbers: List[str] = []
            for item_ord, item in enumerate(subsection.items, start=1):
                number = (item.item_no.strip()
                          if item.item_no and item.item_no.strip()
                          else f"{sec_ord}.{sub_ord}.{item_ord}")
                if number in seen_numbers:
                    raise ValidationError(
                        f"Duplicate BOQ item number {number!r}")
                seen_numbers.add(number)
                sub_numbers.append(number)
                compiled = _compile_item(
                    item, section.code, subsection.code, number,
                    require_measurement_rules)
                compiled_items.append(compiled)
                if compiled.amount is not None and compiled.status in (
                        STATUS_PRICED, STATUS_PROVISIONAL):
                    section_resolved += compiled.amount
                else:
                    section_clean = False
                    unresolved_items.append(number)
            compiled_subs.append(CompiledSubsection(
                code=subsection.code, title=subsection.title,
                item_nos=tuple(sub_numbers)))
        compiled_sections.append(CompiledSection(
            code=section.code,
            title=section.title,
            items=tuple(compiled_items),
            total=section_resolved if section_clean else None,
            resolved_subtotal=section_resolved,
            has_unresolved=not section_clean,
            subsections=tuple(compiled_subs),
        ))
        grand_resolved += section_resolved
        grand_clean = grand_clean and section_clean

    return CompiledBoq(
        project_ref=boq.project_ref,
        boq_ref=boq.boq_ref,
        sections=tuple(compiled_sections),
        total=grand_resolved if grand_clean else None,
        resolved_subtotal=grand_resolved,
        has_unresolved=not grand_clean,
        unresolved_items=tuple(unresolved_items),
    )
