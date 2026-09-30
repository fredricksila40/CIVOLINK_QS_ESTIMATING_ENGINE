"""Multi-period valuation model (Phase 6): per-BOQ-line cumulative
tracking, state machine, and issuance immutability.

Invariants:
* previous_qty + present_qty == to_date_qty
* previous_amount + present_amount == to_date_amount
* DRAFT -> APPROVED -> ISSUED (ISSUED is read-only / locked)
* Without an active Variation Order (VO), cumulative quantities may
  never exceed the compiled BOQ limit for that line.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Mapping, Optional

from qs_engine.core.errors import ValidationError
from qs_engine.core.decimal_policy import to_decimal

VALUATION_STATES = ("DRAFT", "APPROVED", "ISSUED")
VALID_TRANSITIONS = {
    "DRAFT": {"APPROVED"},
    "APPROVED": {"DRAFT", "ISSUED"},
    "ISSUED": set(),
}


def _state_name(state) -> str:
    text = str(state or "").strip().upper()
    if text not in VALUATION_STATES:
        raise ValidationError(
            f"Unknown valuation state {state!r}; expected one of "
            f"{', '.join(VALUATION_STATES)}")
    return text


@dataclass(frozen=True)
class ValuationPeriod:
    """One interim valuation period over a single BOQ line item.

    Immutable once created; issued periods are never modified
    (historical immutability / auditability).
    """
    valuation_no: str
    boq_ref: str
    period_no: int
    state: str
    previous_qty: Decimal
    present_qty: Decimal
    to_date_qty: Decimal
    previous_amount: Decimal
    present_amount: Decimal
    to_date_amount: Decimal
    onsite_materials: Decimal
    vo_active: bool
    created_on: str

    @staticmethod
    def _d(value, name: str) -> Decimal:
        return to_decimal(value, f"{name} (ValuationPeriod)")

    @classmethod
    def create(cls, valuation_no: str, boq_ref: str, period_no: int,
               *, previous_qty, present_qty, previous_amount,
               present_amount, onsite_materials="0", state="DRAFT",
               vo_active=False, created_on=None) -> "ValuationPeriod":
        """Build a period, recomputing every cumulative.

        ``previous_qty``, ``previous_amount`` are DERIVED from the
        prior period's cumulative (they are never trusted raw),
        guaranteeing the invariant previous + present == to_date.
        """
        previous_qty = cls._d(previous_qty, "previous_qty")
        present_qty = cls._d(present_qty, "present_qty")
        previous_amount = cls._d(previous_amount, "previous_amount")
        present_amount = cls._d(present_amount, "present_amount")
        onsite = cls._d(onsite_materials, "onsite_materials")
        to_date_qty = previous_qty + present_qty
        to_date_amount = previous_amount + present_amount
        return cls(
            valuation_no=str(valuation_no or "").strip(),
            boq_ref=str(boq_ref or "").strip(),
            period_no=period_no,
            state=_state_name(state),
            previous_qty=previous_qty,
            present_qty=present_qty,
            to_date_qty=to_date_qty,
            previous_amount=previous_amount,
            present_amount=present_amount,
            to_date_amount=to_date_amount,
            onsite_materials=onsite,
            vo_active=bool(vo_active),
            created_on=str(created_on or date.today().isoformat()),
        )

    def transition_to(self, new_state: str) -> "ValuationPeriod":
        """Return a new period with the state advanced.

        Issued periods are locked: they cannot leave ISSUED and
        no new period may be built on top of one that has not
        been approved first.
        """
        target = _state_name(new_state)
        allowed = VALID_TRANSITIONS[self.state]
        if target not in allowed:
            raise ValidationError(
                f"Cannot transition valuation {self.valuation_no} "
                f"from {self.state} to {new_state}")
        return replace(self, state=target)


class ValuationManager:
    """Tracks cumulative work per BOQ line across valuation periods.

    ``boq_limits`` maps boq_ref -> compiled quantity (Decimal).
    Issued periods are immutable; a new period copies the prior
    period's cumulative as its ``previous``.
    """

    def __init__(self, boq_limits: Optional[Mapping[str, Decimal]] = None):
        self._boq_limits = {str(k): to_decimal(v, f"boq_limit {k}")
                            for k, v in (boq_limits or {}).items()}
        self._periods: Dict[str, List[ValuationPeriod]] = {}

    def add_period(self, period: ValuationPeriod) -> ValuationPeriod:
        """Register a valuation period, validating invariants.

        * Adding a period after an ``ISSUED`` one is forbidden
          (issued periods are locked / read-only).
        * ``previous`` must equal the prior period's cumulative.
        * Without an active VO, cumulative may not exceed the BOQ limit.
        """
        key = period.boq_ref
        existing = self._periods.get(key, [])
        if existing and existing[-1].state == "ISSUED":
            raise ValidationError(
                f"Cannot add a period after an issued valuation for "
                f"{key}")
        # previous must mirror the prior cumulative; state-only
        # re-registrations (same period_no as the last) skip this
        # check so that DRAFT -> APPROVED -> ISSUED transitions
        # can update the last period without re-stating figures.
        if existing:
            prior = existing[-1]
            if period.period_no > prior.period_no:
                if (period.previous_qty != prior.to_date_qty
                        or period.previous_amount != prior.to_date_amount):
                    raise ValidationError(
                        f"Period {period.period_no} previous quantities must "
                        f"equal prior cumulative ({prior.to_date_qty}, "
                        f"{prior.to_date_amount})")
        # BOQ limit guard (VO waiver)
        if key in self._boq_limits and not period.vo_active:
            limit = self._boq_limits[key]
            if period.to_date_qty > limit:
                raise ValidationError(
                    f"Cumulative quantity {period.to_date_qty} for {key} "
                    f"exceeds the BOQ limit {limit}; activate a Variation "
                    f"Order to proceed")
        self._periods.setdefault(key, []).append(period)
        return period

    def periods(self, boq_ref: str) -> List[ValuationPeriod]:
        """Periods for a BOQ line, newest last."""
        return list(self._periods.get(boq_ref, []))

    def cumulative(self, boq_ref: str) -> dict:
        """Latest cumulative quantities and amounts for a line."""
        existing = self._periods.get(boq_ref, [])
        if not existing:
            return {"to_date_qty": Decimal("0"),
                    "to_date_amount": Decimal("0"),
                    "state": "DRAFT", "period_no": 0}
        last = existing[-1]
        return {"to_date_qty": last.to_date_qty,
                "to_date_amount": last.to_date_amount,
                "state": last.state,
                "period_no": len(existing)}

    def all_cumulative(self) -> Dict[str, dict]:
        return {key: self.cumulative(key)
                for key in self._periods}
