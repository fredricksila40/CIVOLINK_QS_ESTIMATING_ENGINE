"""Earthworks result contracts (Phase 5).

Frozen dataclasses. Bank, loose, and compacted states are carried as
separate named figures — volumes are never mixed across states except
through the explicit, documented balance steps.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple


@dataclass(frozen=True)
class ResolvedSoil:
    """One soil type resolved to usable factors.

    density_kg_per_m3 is the BANK (in-situ) density. Loose-state density
    is deliberately absent: loose mass belongs to the truck/tonnage phase
    with verified loose densities, never to silent derivation here.
    """
    soil_key: str
    swell_factor: Decimal
    compact_factor: Decimal
    density_kg_per_m3: Decimal
    master_version: str = ""
    overrides_used: bool = False
    overridden_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EarthworksBalance:
    """Foundation excavation cart-away/backfill balance (one element).

    excavation_bank_m3: in-situ dig.
    loose_dug_m3: cart-away-state volume (bank x K_swell).
    backfill_bank_m3: excavation minus displaced substructure.
    backfill_loose_m3: loose required (bank x K_compact when compacted,
      else bank for uncompacted return).
    dispose_loose_m3: loose_dug - backfill_loose; NEGATIVE means net
      import requirement, exposed (not hidden or floored).
    bank_mass_kg: in-situ mass (bank x bank density, basis labelled).
    """
    element: str
    excavation_bank_m3: Decimal
    loose_dug_m3: Decimal
    displaced_substructure_m3: Decimal
    backfill_bank_m3: Decimal
    backfill_loose_m3: Decimal
    dispose_loose_m3: Decimal
    bank_mass_kg: Decimal
    swell_factor: Decimal
    compact_factor_used: Optional[Decimal]
    resolved_soil: ResolvedSoil
