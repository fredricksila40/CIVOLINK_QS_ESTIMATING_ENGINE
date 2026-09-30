"""Document payload synthesizer (Phase 12).

Maps compiled BOQ structures and composite rates into explicit, strongly
typed, JSON-serializable DTOs for downstream document generators
(Commercial Proposals, BOQ Tender Schedules, Cost Statements).

Design rules:
- Decimals serialize as STRINGS (exact, round-trippable); JSON has no
  Decimal and floats would corrupt money. None stays null.
- Status flags travel verbatim (priced/provisional/unpriced/unresolved);
  unresolved totals are explicit nulls plus flags, so no generator can
  misrepresent an incomplete estimate as a priced tender.
- No rendering, no docx, no frozen-engine contact, no core mutation.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from qs_engine.boq.models import (
    STATUS_PRICED,
    STATUS_PROVISIONAL,
    STATUS_UNPRICED,
    STATUS_UNRESOLVED,
    CompiledBoq,
)
from qs_engine.core.errors import ValidationError
from qs_engine.rates.results import CompositeRate as _RateResult

OWNERSHIP_HEADER = "CIVOLINK Engine Payload"


def _decimal_string(value: Optional[Decimal]):
    """Exact string form for JSON (None stays None)."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise ValidationError(
            f"Payload money must be Decimal; got {type(value).__name__}")
    return str(value)


@dataclass(frozen=True)
class ItemPayload:
    """One BOQ line as document data (amounts are exact strings)."""
    item_no: str
    description: str
    quantity: str
    unit: str
    rate: Optional[str]
    amount: Optional[str]
    status: str
    pricing_kind: str
    rate_ref: str
    takeoff_ref: str
    measurement_ref: Optional[str]
    provenance: Tuple[str, ...]
    notes: str = ""


@dataclass(frozen=True)
class SectionPayload:
    """One bill section with honest totals."""
    code: str
    title: str
    items: Tuple[ItemPayload, ...]
    total: Optional[str]
    resolved_subtotal: str
    has_unresolved: bool


@dataclass(frozen=True)
class SummaryPayload:
    """Document-level roll-up with status counts and flags."""
    grand_total: Optional[str]
    resolved_subtotal: str
    has_unresolved: bool
    unresolved_items: Tuple[str, ...]
    priced_count: int
    provisional_count: int
    unpriced_count: int
    unresolved_count: int


@dataclass(frozen=True)
class DocumentPayload:
    """A complete document DTO: header, governance, sections, summary."""
    document_title: str
    purpose: str
    ownership: str = OWNERSHIP_HEADER
    project_ref: str = ""
    boq_ref: str = ""
    compilation_id: str = ""
    document_date: str = ""
    measurement_standards: Tuple[str, ...] = ()
    sections: Tuple[SectionPayload, ...] = ()
    summary: SummaryPayload = None
    governance: str = (
        "QS Engine = Source of Truth | Document = Presentation Surface")

    def __post_init__(self):
        if not self.document_title or not self.document_title.strip():
            raise ValidationError("DocumentPayload needs a document_title")
        if not self.purpose or not self.purpose.strip():
            raise ValidationError("DocumentPayload needs a purpose")
        if self.summary is None:
            raise ValidationError("DocumentPayload needs a summary")

    def to_dict(self) -> dict:
        """Plain-JSON dict (Decimals already strings; tuples to lists)."""
        import dataclasses
        def convert(value):
            if dataclasses.is_dataclass(value):
                return {f.name: convert(getattr(value, f.name))
                        for f in dataclasses.fields(value)}
            if isinstance(value, (tuple, list)):
                return [convert(v) for v in value]
            return value
        return convert(self)

    def to_json(self) -> str:
        """JSON string (round-trippable; amounts parse back exactly)."""
        return json.dumps(self.to_dict(), indent=2)


@dataclass(frozen=True)
class RateComponentPayload:
    """One build-up line as document data."""
    kind: str
    description: str
    cost_per_unit: str
    provisional: bool = False


@dataclass(frozen=True)
class MarkupPayload:
    """One applied markup with its amount and running total."""
    label: str
    pct: str
    amount: str
    running_total: str


@dataclass(frozen=True)
class RateSheetPayload:
    """A rate build-up sheet DTO (e.g. Detailed Rate Build-Up Summary)."""
    document_title: str
    purpose: str
    ownership: str = OWNERSHIP_HEADER
    element: str = ""
    work_unit: str = ""
    components: Tuple[RateComponentPayload, ...] = ()
    direct_cost_per_unit: str = ""
    markups: Tuple[MarkupPayload, ...] = ()
    markup_policy: str = ""
    net_rate: str = ""
    gross_rate: str = ""

    def __post_init__(self):
        if not self.document_title or not self.document_title.strip():
            raise ValidationError("RateSheetPayload needs a document_title")
        if not self.purpose or not self.purpose.strip():
            raise ValidationError("RateSheetPayload needs a purpose")

    def to_dict(self) -> dict:
        import dataclasses
        def convert(value):
            if dataclasses.is_dataclass(value):
                return {f.name: convert(getattr(value, f.name))
                        for f in dataclasses.fields(value)}
            if isinstance(value, (tuple, list)):
                return [convert(v) for v in value]
            return value
        return convert(self)

    def to_json(self) -> str:
        """JSON string (round-trippable; amounts parse back exactly)."""
        return json.dumps(self.to_dict(), indent=2)


def _synthesize_item(item) -> tuple:
    """Map one CompiledItem -> (ItemPayload, status)."""
    return (ItemPayload(
        item_no=item.item_no,
        description=item.description,
        quantity=str(item.quantity),
        unit=item.unit,
        rate=_decimal_string(item.rate),
        amount=_decimal_string(item.amount),
        status=item.status,
        pricing_kind=item.pricing_kind,
        rate_ref=item.rate_ref,
        takeoff_ref=item.takeoff_ref,
        measurement_ref=item.measurement_ref,
        provenance=tuple(item.provenance),
        notes=item.notes,
    ), item.status)


def synthesize_boq_payload(
    compiled: CompiledBoq,
    *,
    document_title: str,
    purpose: str,
    compilation_id: str = "",
    document_date: str = "",
) -> DocumentPayload:
    """Synthesize a document DTO from a compiled BOQ (no rendering)."""
    if not isinstance(compiled, CompiledBoq):
        raise ValidationError(
            f"synthesize_boq_payload needs a CompiledBoq; "
            f"got {type(compiled).__name__}")
    if not document_title or not document_title.strip():
        raise ValidationError("document_title must be non-empty")
    if not purpose or not purpose.strip():
        raise ValidationError("purpose must be non-empty")

    sections = []
    counts = {STATUS_PRICED: 0, STATUS_PROVISIONAL: 0,
              STATUS_UNPRICED: 0, STATUS_UNRESOLVED: 0}
    standards = set()
    for section in compiled.sections:
        items = []
        for item in section.items:
            payload, status = _synthesize_item(item)
            items.append(payload)
            counts[status] = counts.get(status, 0) + 1
            if item.measurement_ref:
                standards.add(item.measurement_ref)
        sections.append(SectionPayload(
            code=section.code,
            title=section.title,
            items=tuple(items),
            total=_decimal_string(section.total),
            resolved_subtotal=str(section.resolved_subtotal),
            has_unresolved=section.has_unresolved,
        ))
    summary = SummaryPayload(
        grand_total=_decimal_string(compiled.total),
        resolved_subtotal=str(compiled.resolved_subtotal),
        has_unresolved=compiled.has_unresolved,
        unresolved_items=tuple(compiled.unresolved_items),
        priced_count=counts.get(STATUS_PRICED, 0),
        provisional_count=counts.get(STATUS_PROVISIONAL, 0),
        unpriced_count=counts.get(STATUS_UNPRICED, 0),
        unresolved_count=counts.get(STATUS_UNRESOLVED, 0),
    )
    return DocumentPayload(
        document_title=document_title,
        purpose=purpose,
        project_ref=compiled.project_ref,
        boq_ref=compiled.boq_ref,
        compilation_id=compilation_id,
        document_date=document_date,
        measurement_standards=tuple(sorted(standards)),
        sections=tuple(sections),
        summary=summary,
    )


def synthesize_rate_payload(
    rate,
    *,
    document_title: str,
    purpose: str,
) -> RateSheetPayload:
    """Synthesize a rate-sheet DTO from a Phase 9 CompositeRate."""
    if not isinstance(rate, _RateResult):
        raise ValidationError(
            f"synthesize_rate_payload needs a CompositeRate; "
            f"got {type(rate).__name__}")
    if not document_title or not document_title.strip():
        raise ValidationError("document_title must be non-empty")
    if not purpose or not purpose.strip():
        raise ValidationError("purpose must be non-empty")
    return RateSheetPayload(
        document_title=document_title,
        purpose=purpose,
        element=rate.element,
        work_unit=rate.work_unit,
        components=tuple(
            RateComponentPayload(
                kind=c.kind, description=c.description,
                cost_per_unit=str(c.cost_per_unit),
                provisional=c.provisional)
            for c in rate.components),
        direct_cost_per_unit=str(rate.direct_cost_per_unit),
        markups=tuple(
            MarkupPayload(label=m.label, pct=str(m.pct),
                          amount=str(m.amount),
                          running_total=str(m.running_total))
            for m in rate.markups),
        markup_policy=rate.markup_policy,
        net_rate=str(rate.net_rate),
        gross_rate=str(rate.gross_rate),
    )
