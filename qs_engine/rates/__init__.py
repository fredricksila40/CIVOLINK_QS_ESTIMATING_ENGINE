"""Unit-rate build-up engine (Phase 9).

Explicit component builders (material/labour/plant/logistics/
subcontractor) feed composite_rate(), which applies an ordered markup
stack under a recorded compounding policy. Structural rate templates
live in master data for the BOQ phase to bind prices to.
"""

from .engine import (
    COMPONENT_KINDS,
    KIND_LABOUR,
    KIND_LOGISTICS,
    KIND_MATERIAL,
    KIND_OTHER,
    KIND_PLANT,
    KIND_SUBCONTRACT,
    MARKUP_MAX_PCT,
    POLICY_PARALLEL,
    POLICY_SEQUENTIAL,
    composite_rate,
    get_rate_template,
    labour_component_direct,
    labour_component_from_requirement,
    logistics_component,
    material_component,
    other_component,
    plant_component_from_requirement,
    subcontract_component,
    template_is_priced,
)
from .results import (
    CompositeRate,
    MarkupApplied,
    MarkupSpec,
    RateComponent,
    RateTemplate,
    TemplateLine,
)

__all__ = [
    "COMPONENT_KINDS", "KIND_LABOUR", "KIND_LOGISTICS", "KIND_MATERIAL",
    "KIND_OTHER", "KIND_PLANT", "KIND_SUBCONTRACT",
    "MARKUP_MAX_PCT", "POLICY_PARALLEL", "POLICY_SEQUENTIAL",
    "composite_rate", "get_rate_template", "labour_component_direct",
    "labour_component_from_requirement", "logistics_component",
    "material_component", "other_component",
    "plant_component_from_requirement", "subcontract_component",
    "template_is_priced",
    "CompositeRate", "MarkupApplied", "MarkupSpec", "RateComponent",
    "RateTemplate", "TemplateLine",
]
