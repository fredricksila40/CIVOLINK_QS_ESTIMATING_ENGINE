"""Corporate document adapter (Phases 12 + 15): compiled QS results to
DTOs, company-profile persistence, and branded Word/PDF export.

Unidirectional payload synthesis only: CompiledBoq / CompositeRate in,
JSON-serializable document payloads out, presentation files into
output/. No rendering inside the calculation core, no frozen-engine
imports, no side effects on take-off state.
"""

from .company_profile import (
    COMPANY_PROFILE_FIELDS,
    DEFAULT_COMPANY_PROFILE,
    load_company_profile,
    resolve_profile_path,
    save_company_profile,
    validate_company_profile,
)
from .payload import (
    OWNERSHIP_HEADER,
    ItemPayload,
    RateSheetPayload,
    SectionPayload,
    DocumentPayload,
    SummaryPayload,
    synthesize_boq_payload,
    synthesize_rate_payload,
)
from .word_export import (
    CORPORATE_TEMPLATES,
    DOCUMENT_KINDS,
    TEMPLATE_DESCRIPTIONS,
    export_branded_document,
    resolve_output_dir,
    resolve_scripts_dir,
    template_label,
)

__all__ = [
    "OWNERSHIP_HEADER",
    "ItemPayload", "RateSheetPayload", "SectionPayload",
    "DocumentPayload", "SummaryPayload",
    "synthesize_boq_payload", "synthesize_rate_payload",
    "COMPANY_PROFILE_FIELDS", "DEFAULT_COMPANY_PROFILE",
    "load_company_profile", "resolve_profile_path",
    "save_company_profile", "validate_company_profile",
    "CORPORATE_TEMPLATES", "DOCUMENT_KINDS", "TEMPLATE_DESCRIPTIONS",
    "export_branded_document", "resolve_output_dir",
    "resolve_scripts_dir", "template_label",
]
