"""Branded Word/PDF export pipeline (Phase 15).

Bridges the pure DTO layer (payload.py) and the company-profile store
(company_profile.py) into the top-level scripts/ Word generators
(scripts/document_base.py, scripts/quotation_word.py,
scripts/invoice_word.py).

Boundary note: qs_engine must never statically import docx or scripts/
(tests/test_import_boundary.py enforces this via AST), so the scripts/
generators are loaded at runtime with importlib from their file
locations. Static imports here are stdlib + qs_engine only.
"""

import importlib
import importlib.util
import re
import sys
import types
from datetime import date
from pathlib import Path

from qs_engine.boq.models import CompiledBoq
from qs_engine.core.errors import ValidationError

from .company_profile import load_company_profile
from .payload import (
    DocumentPayload,
    RateSheetPayload,
    synthesize_boq_payload,
)

#: Template Selection Hub entries: key -> dropdown label.
CORPORATE_TEMPLATES = (
    ("edmolt", "EDMOLT Construction Template"),
    ("civolink", "CIVOLINK Standard BOQ Template"),
    ("custom", "Custom Corporate Template"),
)

TEMPLATE_DESCRIPTIONS = {
    "edmolt": "Pre-styled headers with branded tables in the company "
              "accent colour.",
    "civolink": "Clean tender style: neutral schedule tables, CIVOLINK "
                "identity header.",
    "custom": "Loads a user-defined .docx template and fills its "
              "{{merge tags}} (business_name, project_ref, boq_ref, "
              "grand_total, document_title, document_date).",
}

#: Document kinds: key -> (dropdown label, default title, default purpose).
DOCUMENT_KINDS = (
    ("quotation", "Quotation"),
    ("invoice", "Invoice"),
)

DOCUMENT_DEFAULTS = {
    "quotation": ("Quotation", "Client quotation"),
    "invoice": ("Invoice", "Client invoice"),
}

_GENERATOR_MODULE = {
    "quotation": "quotation_word",
    "invoice": "invoice_word",
}

_BUILDER_FUNCTION = {
    "quotation": "build_quotation_document",
    "invoice": "build_invoice_document",
}

# Synthetic package name under which the top-level scripts/
# generators are loaded at runtime. A real package context (rather
# than a bare file-location load) is required because the generators
# use explicit relative imports (e.g. `from .document_base import`).
_SCRIPTS_PACKAGE = "civolink_corpdoc_scripts"

_loaded = {}


def template_label(key: str) -> str:
    """Dropdown label for a template key (ValidationError on unknown)."""
    for known, label in CORPORATE_TEMPLATES:
        if known == key:
            return label
    raise ValidationError(
        f"Unknown corporate template {key!r}; expected one of "
        f"{[k for k, _ in CORPORATE_TEMPLATES]}")


def _runtime_base() -> Path:
    """Base directory for bundled/file outputs.

    Source runs use the engine root (four levels above this file);
    PyInstaller frozen binaries use the executable's directory so
    outputs persist outside the temporary _MEIPASS bundle.
    """
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent.parent


def resolve_scripts_dir(path=None) -> Path:
    """Absolute path of the top-level scripts/ generator directory.

    Frozen binaries read the generators from the bundled
    sys._MEIPASS/scripts copy (shipped via BUNDLED_DATA); source runs
    use <engine-root>/scripts.
    """
    if path is not None:
        return Path(path)
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "scripts"
    return _runtime_base() / "scripts"


def resolve_output_dir(path=None) -> Path:
    """Absolute path of the output/ directory for .docx/.pdf files."""
    if path is not None:
        return Path(path)
    return _runtime_base() / "output"


def _ensure_scripts_package(scripts_dir: Path):
    """Register the scripts/ directory as a package in sys.modules."""
    package = sys.modules.get(_SCRIPTS_PACKAGE)
    if package is None:
        package = types.ModuleType(_SCRIPTS_PACKAGE)
        package.__path__ = [str(scripts_dir)]
        sys.modules[_SCRIPTS_PACKAGE] = package
    elif str(scripts_dir) not in package.__path__:
        package.__path__.append(str(scripts_dir))
    return package


def _load_module(module_name: str, scripts_dir: Path):
    """Import a scripts/ generator module (cached, package-aware)."""
    full_name = f"{_SCRIPTS_PACKAGE}.{module_name}"
    if full_name not in _loaded:
        _ensure_scripts_package(scripts_dir)
        expected = scripts_dir / f"{module_name}.py"
        if not expected.is_file():
            raise ValidationError(
                f"Corporate document generator not found: {expected}")
        try:
            _loaded[full_name] = importlib.import_module(full_name)
        except ImportError as exc:
            raise ValidationError(
                f"Corporate document generator not found: "
                f"{expected}") from exc
    return _loaded[full_name]


def _sanitize_stem(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip())
    return cleaned.strip("._") or "branded_document"


def _pdf_lines(payload_dict: dict, profile: dict, kind: str,
               template_key: str) -> list:
    summary = payload_dict.get("summary", {}) or {}
    grand = summary.get("grand_total")
    lines = [
        f"Template: {template_label(template_key)}",
        f"Project ref: {payload_dict.get('project_ref', '')}",
        f"BOQ ref: {payload_dict.get('boq_ref', '')}",
        f"Date: {date.today().isoformat()}",
        f"Company: {(profile or {}).get('business_name', '')}",
        "",
    ]
    for section in payload_dict.get("sections", ()):
        lines.append(f"{section.get('code', '')} - "
                     f"{section.get('title', '')}")
        for item in section.get("items", ()):
            amount = (item.get("amount") if item.get("amount") is not None
                      else "UNRESOLVED")
            lines.append(f"  {item.get('item_no', '')} "
                         f"{item.get('description', '')} "
                         f"{item.get('quantity', '')} "
                         f"{item.get('unit', '')} : {amount}")
        section_total = section.get("total")
        lines.append("  Section total: "
                     + (str(section_total) if section_total is not None
                        else "UNRESOLVED"))
        lines.append("")
    lines.append(f"Resolved subtotal: {summary.get('resolved_subtotal', '')}")
    lines.append("Grand total: "
                 + (str(grand) if grand is not None else "UNRESOLVED"))
    if summary.get("unresolved_items"):
        lines.append("Unresolved items: "
                     + ", ".join(summary["unresolved_items"]))
    lines.append("QS Engine = Source of Truth | "
                 "Document = Presentation Surface")
    return lines


def export_branded_document(compiled=None, payload=None, profile=None,
                            template: str = "civolink",
                            document_kind: str = "quotation",
                            output_dir=None, filename: str = "",
                            custom_template_path=None,
                            export_pdf: bool = False,
                            rate=None,
                            scripts_dir=None) -> dict:
    """Compile a branded Word document from BOQ/rate DTOs + profile.

    Either `compiled` (CompiledBoq) or `payload` (DocumentPayload) is
    required; the profile defaults to config/company_profile.json. The
    .docx lands in output/ (PDF alongside it when export_pdf is set).

    Returns {"docx_path": ..., "pdf_path": ... or None}.
    """
    if document_kind not in _GENERATOR_MODULE:
        raise ValidationError(
            f"Unknown document kind {document_kind!r}; expected one of "
            f"{sorted(_GENERATOR_MODULE)}")
    template_label(template)  # validates the template key
    if payload is None:
        if not isinstance(compiled, CompiledBoq):
            raise ValidationError(
                "Branded export needs a compiled BOQ (compile it on the "
                "BOQ View first) or a ready DocumentPayload")
        default_title, default_purpose = DOCUMENT_DEFAULTS[document_kind]
        payload = synthesize_boq_payload(
            compiled, document_title=default_title,
            purpose=default_purpose)
    if not isinstance(payload, DocumentPayload):
        raise ValidationError(
            "Branded export needs a DocumentPayload; "
            f"got {type(payload).__name__}")
    if rate is not None and not isinstance(rate, (RateSheetPayload, dict)):
        raise ValidationError(
            "Rate appendix needs a RateSheetPayload (or its dict form); "
            f"got {type(rate).__name__}")
    active_profile = dict(load_company_profile())
    if profile is not None:
        if not isinstance(profile, dict):
            raise ValidationError(
                "Company profile must be a mapping; "
                f"got {type(profile).__name__}")
        active_profile.update(profile)
    if template == "custom":
        if not custom_template_path or not Path(
                custom_template_path).is_file():
            raise ValidationError(
                "Custom Corporate Template needs an existing .docx "
                "template file — pick one with the template browser")

    scripts = resolve_scripts_dir(scripts_dir)
    module_name = _GENERATOR_MODULE[document_kind]
    generator = _load_module(module_name, scripts)
    try:
        builder = getattr(generator, _BUILDER_FUNCTION[document_kind])
    except AttributeError as exc:
        raise ValidationError(
            f"Corporate document generator {module_name} has no "
            f"{_BUILDER_FUNCTION[document_kind]}") from exc

    out_dir = resolve_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_stem(
        filename or f"{payload.boq_ref or 'document'}_{document_kind}")
    docx_path = out_dir / f"{stem}.docx"
    try:
        built = builder(payload, active_profile, template, str(docx_path),
                        custom_template_path=custom_template_path,
                        rate=rate)
    except ImportError as exc:
        raise ValidationError(
            "Branded Word export needs the 'python-docx' package "
            f"(pip install python-docx): {exc}") from exc

    pdf_path = None
    if export_pdf:
        base = _load_module("document_base", scripts)
        pdf_title = (f"{DOCUMENT_DEFAULTS[document_kind][0]} - "
                     f"{active_profile.get('business_name', '')}")
        pdf_path = base.write_summary_pdf(
            pdf_title,
            _pdf_lines(payload.to_dict(), active_profile, document_kind,
                       template),
            out_dir / f"{stem}.pdf")
    return {"docx_path": str(built), "pdf_path": pdf_path}
