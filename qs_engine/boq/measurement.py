"""Measurement-standard abstraction (Phase 10).

Supports SMM, CESMM, and future standards WITHOUT encoding any of their
rules: a rule is provenance metadata (standard, edition, reference,
source, dates, verification status). Unverified rules stay explicitly
unresolved; nothing from general practice is substituted.

Reference material itself lives in standards/ outside qs_engine and is
never auto-converted into code: source -> extracted rule ->
verification -> structured rule -> test -> implementation.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from ..core.assumptions import VerificationStatus
from ..core.errors import UnknownMasterDataKeyError, ValidationError

#: Standards the engine recognises by name. Other names are accepted for
#: future standards (is_known == False) — never silently, always visible.
KNOWN_STANDARDS = ("SMM", "CESMM")


@dataclass(frozen=True)
class MeasurementStandard:
    """A measurement standard identity (SMM, CESMM, or a future one)."""
    name: str
    edition: str = ""

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValidationError("Measurement standard name must be non-empty")

    @property
    def is_known(self) -> bool:
        """True for SMM/CESMM; future standards report False, visibly."""
        return self.name.strip().upper() in KNOWN_STANDARDS


@dataclass(frozen=True)
class MeasurementRule:
    """One measurement rule reference with full provenance.

    Carries NO measurement logic — only the citation a compiled item was
    measured under. verification_status governs compilation: rules that
    are not VERIFIED fail closed wherever the compiler requires them.
    """
    standard: MeasurementStandard
    rule_ref: str
    source: str = ""
    edition: str = ""
    effective_date: str = ""
    verification_status: str = VerificationStatus.NEEDS_VERIFICATION
    notes: str = ""

    def __post_init__(self):
        if not isinstance(self.standard, MeasurementStandard):
            raise ValidationError(
                f"MeasurementRule standard must be a MeasurementStandard; "
                f"got {type(self.standard).__name__}")
        if not self.rule_ref or not self.rule_ref.strip():
            raise ValidationError(
                "MeasurementRule rule_ref must be non-empty")
        if self.verification_status not in VerificationStatus.ALL:
            raise ValidationError(
                f"Unknown verification_status "
                f"{self.verification_status!r}")

    @property
    def is_verified(self) -> bool:
        """True only for VERIFIED rules."""
        return self.verification_status == VerificationStatus.VERIFIED

    @property
    def citation(self) -> str:
        """Stable human reference, e.g. 'CESMM 4: 3.4' or 'SMM: E.2.1'."""
        edition = (self.edition or self.standard.edition or "").strip()
        base = self.standard.name.strip()
        if edition:
            base = f"{base} {edition}"
        return f"{base}: {self.rule_ref.strip()}"


class Rulebook:
    """A named registry of measurement rules keyed by citation string.

    Duplicate registration fails closed; unknown lookups raise the
    standard typed master-data error. Normal reuse (many items citing
    one rule) is unaffected — only double REGISTRATION is rejected.
    """

    def __init__(self):
        self._rules: Dict[str, MeasurementRule] = {}

    def add(self, rule: MeasurementRule) -> MeasurementRule:
        """Register a rule; duplicate citations fail closed."""
        if not isinstance(rule, MeasurementRule):
            raise ValidationError(
                f"Rulebook accepts MeasurementRule only; "
                f"got {type(rule).__name__}")
        if rule.citation in self._rules:
            raise ValidationError(
                f"Duplicate measurement rule registration: "
                f"{rule.citation!r}")
        self._rules[rule.citation] = rule
        return rule

    def get(self, citation: str) -> MeasurementRule:
        """Fetch a rule by citation; unknown citations fail closed."""
        try:
            return self._rules[citation]
        except KeyError:
            raise UnknownMasterDataKeyError(
                f"Unknown measurement rule {citation!r} in rulebook"
            ) from None

    def citations(self) -> List[str]:
        """Registered citations in registration order."""
        return list(self._rules.keys())
