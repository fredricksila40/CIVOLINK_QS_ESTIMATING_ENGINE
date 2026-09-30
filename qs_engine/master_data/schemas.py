"""Master-data record schemas (Phase 0: structure only, no values).

Every record in every domain must carry provenance metadata
(key/source/version/effective_date/verification_status). Domain tables
start EMPTY; values are populated only after engineering verification
(see docs/QS_ASSUMPTION_REGISTER.md).
"""

from typing import Any, Mapping

from ..core.assumptions import VerificationStatus
from ..core.errors import (
    MissingFieldError,
    UnknownMasterDataDomainError,
    ValidationError,
)

SCHEMA_VERSION = "0.1"

MATERIALS = "materials"
CONCRETE_CLASSES = "concrete_classes"
MIX_DESIGNS = "mix_designs"
MASONRY_UNITS = "masonry_units"
REBAR_BARS = "rebar_bars"
COVERAGES = "coverages"
LABOUR = "labour"
PLANT = "plant"
TRUCKS = "trucks"
SOILS = "soils"
RATE_TEMPLATES = "rate_templates"

DOMAINS = (
    MATERIALS,
    CONCRETE_CLASSES,
    MIX_DESIGNS,
    MASONRY_UNITS,
    REBAR_BARS,
    COVERAGES,
    LABOUR,
    PLANT,
    TRUCKS,
    SOILS,
    RATE_TEMPLATES,
)

# Provenance fields required on EVERY record in EVERY domain.
PROVENANCE_FIELDS = (
    "key",
    "source",
    "version",
    "effective_date",
    "verification_status",
)

# Numeric fields that may be null while a record is NEEDS_VERIFICATION
# (Phase 1: catalog identifiers exist before verified figures do).
# PROVISIONAL and VERIFIED records must carry complete numerics.
NULLABLE_NUMERIC_FIELDS = {
    MATERIALS: ("density", "default_wastage_pct"),
    CONCRETE_CLASSES: ("cement_ratio", "sand_ratio", "aggregate_ratio",
                        "dry_volume_factor", "wc_ratio",
                        "cement_density_kg_per_m3", "sand_density_kg_per_m3",
                        "aggregate_density_kg_per_m3", "water_density_kg_per_L",
                        "bag_mass_kg", "default_wastage_pct"),
    MIX_DESIGNS: ("min_cement_content_kg_per_m3", "max_wc_ratio",
                    "fine_agg_ratio", "coarse_agg_ratio",
                    "target_density", "default_wastage_pct"),
    MASONRY_UNITS: ("length_mm", "height_mm", "thickness_mm",
                    "bed_joint_mm", "perp_joint_mm",
                    "mortar_cement_ratio", "mortar_sand_ratio",
                    "mortar_dry_factor", "mortar_sand_density_kg_per_m3",
                    "cement_density_kg_per_m3", "bag_mass_kg",
                    "default_wastage_pct"),
    REBAR_BARS: ("diameter_mm", "mass_kg_per_m", "default_wastage_pct"),
    COVERAGES: ("coverage_per_unit",),
    LABOUR: ("output_per_day", "gang_skilled", "gang_unskilled",
             "skilled_rate", "unskilled_rate"),
    PLANT: ("output_per_unit", "rate"),
    # NOTE: operating_cost_per_hour is intentionally NOT a required field:
    # absent means operating cost is explicitly not estimated, never zero.
    TRUCKS: ("body_length_m", "body_width_m", "body_height_m",
             "payload_limit_tonnes", "payload_tonnes",
             "load_time_min", "unload_time_min",
             "speed_loaded_kmh", "speed_empty_kmh", "hire_rate"),
    # NOTE: fuel_burn_L_per_hr is intentionally NOT required (absent means
    # fuel cost explicitly not estimated, never zero — same rule as plant
    # operating cost). hire_rate resolves to a value or None; costing
    # functions always take explicit rate parameters regardless.
    SOILS: ("swell_factor", "compact_factor", "density_kg_per_m3"),
    # Rate templates carry structure (component refs, markup labels), not
    # values: lists must be present but leaves may be null until verified.
    RATE_TEMPLATES: (),
}

# Domain-specific required fields (in addition to provenance).
REQUIRED_FIELDS = {
MATERIALS: ("name", "category", "unit", "density", "density_unit",
                "default_wastage_pct"),
    CONCRETE_CLASSES: ("class_name",
                        "cement_ratio", "sand_ratio", "aggregate_ratio",
                        "dry_volume_factor", "wc_ratio",
                        "cement_density_kg_per_m3", "sand_density_kg_per_m3",
                        "aggregate_density_kg_per_m3", "water_density_kg_per_L",
                        "bag_mass_kg", "default_wastage_pct"),
    MIX_DESIGNS: ("designation",
                    "bs_8500_designation",
                    "min_cement_content_kg_per_m3",
                    "max_wc_ratio",
                    "fine_agg_ratio",
                    "coarse_agg_ratio",
                    "target_density",
                    "cement_code",
                    "fine_agg_code",
                    "coarse_agg_code",
                    "default_wastage_pct"),
    MASONRY_UNITS: ("name",
                    "length_mm", "height_mm", "thickness_mm",
                    "bed_joint_mm", "perp_joint_mm",
                    "mortar_cement_ratio", "mortar_sand_ratio",
                    "mortar_dry_factor", "mortar_sand_density_kg_per_m3",
                    "cement_density_kg_per_m3", "bag_mass_kg",
                    "default_wastage_pct"),
    REBAR_BARS: ("diameter_mm", "mass_kg_per_m", "default_wastage_pct"),
    COVERAGES: ("activity", "material_key", "coverage_per_unit",
                "coverage_unit", "consumption_unit"),
    LABOUR: ("trade", "work_unit", "output_per_day",
             "gang_skilled", "gang_unskilled",
             "skilled_rate", "unskilled_rate", "rate_unit",
             "rate_effective_date"),
    PLANT: ("equipment", "work_unit", "output_per_unit", "output_basis",
            "rate", "rate_unit", "hire_basis", "rate_effective_date"),
    TRUCKS: ("size_label", "body_length_m", "body_width_m",
             "body_height_m", "payload_limit_tonnes", "payload_tonnes",
             "load_time_min", "unload_time_min",
             "speed_loaded_kmh", "speed_empty_kmh",
             "hire_rate", "hire_rate_unit", "rate_effective_date"),
    SOILS: ("name", "swell_factor", "compact_factor", "density_kg_per_m3"),
    RATE_TEMPLATES: ("name", "work_unit", "components", "markups"),
}

# Cross-domain reference fields (Phase 3.2): field -> the domain its
# value must point at. Values are typed references (models.py); presence
# stays with REQUIRED_FIELDS above.
CROSS_DOMAIN_FIELDS = {
    COVERAGES: {"material_key": MATERIALS},
}

# rate_templates component 'kind' -> the domain its 'ref' must target.
# Kinds absent here (subcontract, other) carry free-text refs.
COMPONENT_KIND_DOMAINS = {
    "material": MATERIALS,
    "labour": LABOUR,
    "plant": PLANT,
    "logistics": TRUCKS,
}


def validate_record(domain: str, record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate one master-data record against its domain schema.

    Returns the record unchanged when valid. Raises typed errors otherwise.
    Numeric fields are NOT coerced here — calculators coerce via the
    Decimal policy at use time; the loader only checks presence and status.
    """
    if domain not in DOMAINS:
        raise UnknownMasterDataDomainError(
            f"Unknown master-data domain {domain!r}; "
            f"expected one of {list(DOMAINS)}"
        )
    if not isinstance(record, Mapping):
        raise ValidationError(f"Domain {domain!r}: record must be a mapping")
    unverified = record.get("verification_status") == VerificationStatus.NEEDS_VERIFICATION
    nullable = NULLABLE_NUMERIC_FIELDS[domain]
    required = PROVENANCE_FIELDS + REQUIRED_FIELDS[domain]
    for field in required:
        value = record.get(field)
        if value is None and field in nullable and unverified:
            continue  # unverified catalog entry: numeric pending verification
        if field not in record or value is None or (
            isinstance(value, str) and not value.strip()
        ):
            raise MissingFieldError(
                f"Domain {domain!r}: required field {field!r} missing or empty"
            )
    # Provenance block: status must be a known lifecycle value. Value
    # verification itself is the calculators' job at use time (a VERIFIED
    # record must additionally carry value+source, enforced there).
    if record["verification_status"] not in VerificationStatus.ALL:
        raise ValidationError(
            f"Domain {domain!r}: unknown verification_status "
            f"{record['verification_status']!r}; expected one of "
            f"{list(VerificationStatus.ALL)}"
        )
    # Typed cross-domain references (Phase 3.2): every reference must
    # parse against its declared target domain with a strict scope, so
    # unresolvable prefixes ("user:...") or wrong-domain scopes fail at
    # load instead of surfacing at use time. Imported here because
    # models.py imports this module's DOMAINS.
    from .models import CrossDomainReference
    for field_name, target in CROSS_DOMAIN_FIELDS.get(domain, {}).items():
        value = record.get(field_name)
        if value is None:
            continue  # presence enforced by REQUIRED_FIELDS above
        CrossDomainReference.parse(value, domain=target, strict_scope=True)
    if domain == RATE_TEMPLATES:
        for index, line in enumerate(record.get("components") or ()):
            if not isinstance(line, Mapping):
                continue  # malformed lines fail in get_rate_template
            target = COMPONENT_KIND_DOMAINS.get(line.get("kind"))
            if target is None:
                continue  # subcontract/other carry free-text refs
            ref = line.get("ref")
            if ref is None or (isinstance(ref, str) and not ref.strip()):
                raise MissingFieldError(
                    f"Domain {domain!r}: component #{index} of kind "
                    f"{line.get('kind')!r} needs a non-empty {target!r} "
                    f"ref")
            CrossDomainReference.parse(ref, domain=target, strict_scope=True)
    return record
