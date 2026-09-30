"""Mix design constituent calculator (Phase 6).

Computes cement bags, water, sand, coarse aggregate from a
BS EN 206 / BS 8500 mix class using mass-based targets and
maximum water-cement ratios. Every quantity is derived through
``core/decimal_policy``; no float may enter the chain.

The calculation follows the mass-balance invariants mandated by
BS 8500: gross volume includes wastage; cement mass derives from
the minimum cement content target; water derives from the
maximum w/c ratio; the residual mass to the target density is
the combined aggregate, split by fine/coarse ratio.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from qs_engine.core.decimal_policy import (
    apply_percentage,
    quantize_money,
    to_decimal,
)
from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository


@dataclass(frozen=True)
class ConstituentResult:
    """Full constituent breakdown for one mix design period."""
    designation: str
    bs_8500_designation: str
    net_volume: Decimal
    gross_volume: Decimal
    cement_mass: Decimal
    cement_bags: int
    water_liters: Decimal
    aggregate_mass: Decimal
    sand_mass: Decimal
    coarse_agg_mass: Decimal
    sand_volume: Decimal
    coarse_agg_volume: Decimal
    cement_code: str
    fine_agg_code: str
    coarse_agg_code: str


class ConstituentCalculator:
    """Mass-based mix design engine.

    Computes BS EN 206 / BS 8500 constituent quantities from a
    designated mix class and a target net volume, applying
    site wastage to derive gross volume and resolving the
    fine/coarse aggregate split against the master density.
    """

    def __init__(self, repository: MasterDataRepository):
        self._repo = repository

    def _is_mortar(self, design: Mapping) -> bool:
        return bool(design.get("is_mortar"))

    def _compute_mortar(self, design: Mapping,
                         net: Decimal,
                         waste: Decimal) -> ConstituentResult:
        """Compute mortar constituents using mix ratio and k_dry."""
        k_dry = to_decimal(design["k_dry"], "k_dry")
        ratio = str(design["mix_ratio_cement_to_sand"])
        parts = ratio.split(":")
        cement_part = Decimal(parts[0])
        sand_part = Decimal(parts[1])
        total_parts = cement_part + sand_part
        gross = net * k_dry * (Decimal("1") + waste)
        cement_mass = gross * (cement_part / total_parts) * Decimal("1500")
        sand_mass = gross * (sand_part / total_parts) * Decimal("1600")
        cement_bags = int(
            (cement_mass + Decimal("49")) // Decimal("50"))
        water_liters = cement_mass * Decimal("0.5")
        return ConstituentResult(
            designation=design["designation"],
            bs_8500_designation=design["bs_8500_designation"],
            net_volume=net,
            gross_volume=gross,
            cement_mass=quantize_money(cement_mass),
            cement_bags=cement_bags,
            water_liters=quantize_money(water_liters),
            aggregate_mass=quantize_money(sand_mass),
            sand_mass=quantize_money(sand_mass),
            coarse_agg_mass=Decimal("0"),
            sand_volume=quantize_money(sand_mass / Decimal("1600")),
            coarse_agg_volume=Decimal("0"),
            cement_code=design["cement_code"],
            fine_agg_code=design["fine_agg_code"],
            coarse_agg_code=design["coarse_agg_code"],
        )

    def compute(self, designation: str, net_volume: Decimal,
                wastage_pct: Decimal = Decimal("0.05")
                ) -> ConstituentResult:
        """Value one mix design.

        ``designation`` is the Eurocode class code (e.g. ``C20/25``).
        ``net_volume`` is the target net volume in m³.
        ``wastage_pct`` defaults to the mix's default wastage
        factor (5%). All inputs are coerced through ``to_decimal``.
        """
        design = self._lookup(designation)
        net = to_decimal(net_volume, "net_volume")
        if net < 0:
            raise ValidationError(
                f"net_volume must be >= 0; got {net_volume}")
        waste = to_decimal(wastage_pct, "wastage_pct")
        if waste < 0:
            raise ValidationError(
                f"wastage_pct must be >= 0; got {wastage_pct}")
        if self._is_mortar(design):
            return self._compute_mortar(design, net, waste)
        # ---- gross volume ----
        gross = net * (Decimal("1") + waste)
        # ---- cement ----
        min_cement = to_decimal(
            design["min_cement_content_kg_per_m3"],
            "min_cement_content_kg_per_m3")
        cement_mass = gross * min_cement
        cement_bags = int(
            (cement_mass + Decimal("49")) // Decimal("50"))
        # ---- water ----
        max_wc = to_decimal(design["max_wc_ratio"], "max_wc_ratio")
        water_liters = cement_mass * max_wc
        # ---- combined aggregate ----
        target_density = to_decimal(
            design["target_density"], "target_density")
        aggregate_mass = (gross * target_density) - cement_mass - water_liters
        # ---- fine / coarse split ----
        fine_ratio = to_decimal(design["fine_agg_ratio"], "fine_agg_ratio")
        coarse_ratio = to_decimal(
            design["coarse_agg_ratio"], "coarse_agg_ratio")
        sand_mass = aggregate_mass * fine_ratio
        coarse_mass = aggregate_mass * coarse_ratio
        # ---- volumes ----
        sand_vol = sand_mass / target_density
        coarse_vol = coarse_mass / target_density
        return ConstituentResult(
            designation=design["designation"],
            bs_8500_designation=design["bs_8500_designation"],
            net_volume=net,
            gross_volume=gross,
            cement_mass=quantize_money(cement_mass),
            cement_bags=cement_bags,
            water_liters=quantize_money(water_liters),
            aggregate_mass=quantize_money(aggregate_mass),
            sand_mass=quantize_money(sand_mass),
            coarse_agg_mass=quantize_money(coarse_mass),
            sand_volume=quantize_money(sand_vol),
            coarse_agg_volume=quantize_money(coarse_vol),
            cement_code=design["cement_code"],
            fine_agg_code=design["fine_agg_code"],
            coarse_agg_code=design["coarse_agg_code"],
        )

    def _lookup(self, designation: str) -> Mapping:
        """Resolve a Eurocode designation to a mix master record."""
        try:
            for rec in self._repo.list("mix_designs"):
                if rec.get("designation") == designation:
                    return rec
        except Exception:
            pass
        all_designations = []
        try:
            for rec in self._repo.list("mix_designs"):
                all_designations.append(rec.get("designation", ""))
        except Exception:
            pass
        raise ValidationError(
            f"Unknown mix designation {designation!r}; "
            f"expected one of {', '.join(all_designations)}")
